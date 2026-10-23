import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import cached_property
from typing import Literal, TypeVar

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import Runnable
from langgraph.errors import GraphRecursionError
from sqlalchemy.orm import Session, sessionmaker

from app import config
from app.assistant import dao
from app.assistant.graph import (FAILED_VERIFICATION_MESSAGE, GRAPH_VERSION, NO_EVIDENCE_MESSAGE, RECURSION_LIMIT, build_graph, prompt_version)
from app.assistant.models import ChatOutcome, ChatTurn
from app.assistant.tools import ToolContext, ToolSpec
from app.contracts import dao as contracts_dao
from app.documents import dao as documents_dao
from app.governance.dao import ModelConfig
from app.retrieval.vector_index import VectorIndex
from app.tracing import get_tracing_handler

logger = logging.getLogger(__name__)
HISTORY_TURNS = 4
PROGRESS = {"agent": "thinking", "tools": "searching", "answer": "writing", "verify": "checking citations"}
SYSTEM_CITATION_ID = "system"
NOT_COMPARABLE_TEXT = "I can't compare this contract with billing: {reason}"
NO_SUPPORT_DETAIL = "No passage in the indexed contracts supports an answer to this question."
CLARIFY_UNSCOPED = ("I need a little more to go on. Which contract do you mean, and what would you like to know "
                    "about it? Indexed contracts: {titles}.")
CLARIFY_SCOPED = "I need a little more to go on. What would you like to know about {title}?"
CLARIFY_NO_DOCUMENTS = "I need a little more to go on. What would you like to know?"
MAX_CLARIFY_TITLES = 4


@dataclass(frozen=True)
class TurnEvent:
    type: Literal["progress", "answer", "refused", "clarify", "error", "unvalidated"]
    data: dict


@dataclass(frozen=True)
class AssistantRuntime:
    chat_model: BaseChatModel
    embeddings: Embeddings
    vector_index: VectorIndex
    tools: list[ToolSpec]

    @cached_property
    def graph(self) -> Runnable:
        """Compiled once per runtime (once per process in the API); each turn's inputs go in its run config."""
        return build_graph(self.chat_model, self.tools)


def _usage(messages: list) -> tuple[int, int]:
    usage = [m.usage_metadata for m in messages if isinstance(m, AIMessage) and m.usage_metadata]
    return sum(u["input_tokens"] for u in usage), sum(u["output_tokens"] for u in usage)


def _unvalidated_events(session: Session, tenant_id: uuid.UUID, document_ids: list[str], overlay_guest: uuid.UUID | None) -> list[TurnEvent]:
    events = []
    for document_id in dict.fromkeys(document_ids):  # once per document, in order
        view = contracts_dao.terms_view(session, tenant_id, uuid.UUID(document_id), date.today(), overlay_guest)
        if view is None:
            continue
        fields = [{"path": f.path, "label": f.label, "reason": f.reason} for f in view.fields if f.status in ("needs_review", "rejected")]
        if fields:
            events.append(TurnEvent("unvalidated", {"document_id": document_id, "title": view.title, "fields": fields}))
    return events


def _clarifying_question(session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID | None) -> str:
    """P4: the model only decides to ask; the wording is fixed (it left the text empty 5 times in 6 in the eval)."""
    titles = sorted(r.title for r in documents_dao.document_titles(session, tenant_id, document_id))[:MAX_CLARIFY_TITLES]
    if not titles:
        return CLARIFY_NO_DOCUMENTS
    if document_id is not None:
        return CLARIFY_SCOPED.format(title=titles[0])
    return CLARIFY_UNSCOPED.format(titles="; ".join(titles))


def _no_support_citation() -> dict:
    return {"id": SYSTEM_CITATION_ID, "kind": "system", "source": "indexed contracts", "detail": NO_SUPPORT_DETAIL}


T = TypeVar("T")


def _with_session(session_factory: sessionmaker, work: Callable[..., T], *args) -> T:
    """One short session around one piece of DB work, so a turn holds no connection while it waits on the model."""
    with session_factory() as session:
        return work(session, *args)


def _open_turn(
    session: Session,
    tenant_id: uuid.UUID,
    session_id: str,
    message: str,
    hmac_key: str,
    vault_key: str,
    document_id: uuid.UUID | None,
    guest_id: uuid.UUID | None,
) -> tuple[str, list, str | None]:
    question = documents_dao.tokenize_known_values(session, tenant_id, message, hmac_key, vault_key)
    history = []
    for turn in dao.recent_turns(session, tenant_id, session_id, HISTORY_TURNS, guest_id):
        history += [HumanMessage(turn.question_redacted), AIMessage(turn.answer_redacted or "")]
    scoped = documents_dao.find_document(session, tenant_id, document_id) if document_id is not None else None
    title = scoped.title if scoped is not None else None
    # New question tokens must be visible to reveal(), which runs in another session.
    session.commit()
    return question, history, title


def _final(
    turn_id: uuid.UUID,
    kind: Literal["answer", "refused", "clarify"],
    text: str,
    citations: list[dict],
    confidence: float | None = None,
) -> TurnEvent:
    """The event that ends a turn. It names the turn so the client can attach feedback to it (spec P5 D5), and
    carries the answer call's confidence for the chat eval (the frontend ignores it)."""
    return TurnEvent(kind, {"text": text, "citations": citations, "turn_id": str(turn_id), "confidence": confidence})


@dataclass(frozen=True)
class TurnEnd:
    events: list[TurnEvent]
    outcome: ChatOutcome
    record: dict


def _close_turn(
    session: Session,
    tenant_id: uuid.UUID,
    state: dict,
    turn_id: uuid.UUID,
    document_id: uuid.UUID | None,
    overlay_guest: uuid.UUID | None,
    vault_key: str,
) -> TurnEnd:
    """Everything after the graph that reads the database, in one short session: notices, clarification, reveal."""
    answer = state["answer"]
    confidence = state.get("confidence")
    events = list(_unvalidated_events(session, tenant_id, state.get("unvalidated", []), overlay_guest))
    input_tokens, output_tokens = _usage(state.get("messages", []))
    retrieved = state.get("retrieved", [])
    notices = state.get("system_notices", [])

    if answer.refused and notices:
        citation = {"id": SYSTEM_CITATION_ID, "kind": "system", "source": "billing records", "detail": notices[-1]}
        text = NOT_COMPARABLE_TEXT.format(reason=notices[-1])
        record = dict(
            answer_redacted=text,
            citations=[citation],
            retrieved=retrieved,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        return TurnEnd([*events, _final(turn_id, "refused", text, [citation], confidence)], ChatOutcome.refused, record)

    if answer.refused:
        # P4: every refusal but N11 is fixed text plus a system reason; the model's own wording is never shown.
        text = FAILED_VERIFICATION_MESSAGE if answer.text == FAILED_VERIFICATION_MESSAGE else NO_EVIDENCE_MESSAGE
        citation = _no_support_citation()
        record = dict(
            answer_redacted=text,
            citations=[citation],
            retrieved=retrieved,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        return TurnEnd([*events, _final(turn_id, "refused", text, [citation], confidence)], ChatOutcome.refused, record)

    if answer.clarification:
        text = _clarifying_question(session, tenant_id, document_id)
        record = dict(
            answer_redacted=text,
            citations=[],
            retrieved=retrieved,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        return TurnEnd([*events, _final(turn_id, "clarify", text, [], confidence)], ChatOutcome.clarified, record)

    cited = [state["citations"][c] | {"id": c} for c in answer.citations if c in state.get("citations", {})]
    record = dict(
        answer_redacted=answer.text,
        citations=cited,
        retrieved=retrieved,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    [text, *quotes] = documents_dao.reveal(session, tenant_id, [answer.text, *(c.get("quote", "") for c in cited)], vault_key)
    shown = [c | ({"quote": q} if "quote" in c else {}) for c, q in zip(cited, quotes)]
    return TurnEnd([*events, _final(turn_id, "answer", text, shown, confidence)], ChatOutcome.answered, record)


async def run_turn(
    *, session_factory: sessionmaker, runtime: AssistantRuntime, tenant_id: uuid.UUID, session_id: str,
    message: str, hmac_key: str, vault_key: str,
    guest_id: uuid.UUID | None = None, document_id: uuid.UUID | None = None, overlay_guest: uuid.UUID | None = None,
) -> AsyncIterator[TurnEvent]:
    started = time.perf_counter()
    model_id = getattr(runtime.chat_model, "model_name", None) or config.CHAT_MODEL
    turn_id = uuid.uuid4()
    record = dict(id=turn_id, tenant_id=tenant_id, session_id=session_id, citations=[], retrieved=[], answer_redacted=None,
                  model_id=model_id, prompt_version=prompt_version(), graph_version=GRAPH_VERSION,
                  input_tokens=0, output_tokens=0, guest_id=guest_id, document_id=document_id)
    outcome = ChatOutcome.cancelled  # anything that exits early without setting an outcome was a disconnect

    question, history, title = await asyncio.to_thread(
        _with_session, session_factory, _open_turn, tenant_id, session_id, message, hmac_key, vault_key, document_id, guest_id,
    )
    record["question_redacted"] = question

    ctx = ToolContext(session=None, tenant_id=tenant_id, session_id=session_id, turn_id=turn_id,
                      embeddings=runtime.embeddings, vector_index=runtime.vector_index,
                      model=ModelConfig("openai", model_id, record["prompt_version"], Decimal(0)), hmac_key=hmac_key, vault_key=vault_key,
                      document_id=document_id, document_title=title, overlay_guest=overlay_guest, question=question)
    state: dict = {}

    handler = get_tracing_handler()

    run_config = {"recursion_limit": RECURSION_LIMIT, "configurable": {"ctx": ctx, "open_session": session_factory}}
    if handler:
        run_config["callbacks"] = [handler]
        run_config["metadata"] = {
            "langfuse_session_id": session_id,
            "langfuse_tags": ["chat"],
            "prompt_version": record["prompt_version"],
            "graph_version": record["graph_version"],
            "model_id": record["model_id"],
        }

    try:
        async with asyncio.timeout(config.CHAT_TURN_TIMEOUT_SECONDS):
            # Model calls are coroutines, so the turn timeout cancels them; tools and checks stay sync and run in
            # LangGraph's thread pool. ponytail: a timed-out tool call keeps running in its thread until it returns.
            async for mode, data in runtime.graph.astream({"messages": [*history, HumanMessage(question)]},
                                                          config=run_config,
                                                          stream_mode=["updates", "values"]):
                if mode == "values":
                    state = data
                else:
                    for node in data:
                        yield TurnEvent("progress", {"step": PROGRESS.get(node, "thinking")})
        end = await asyncio.to_thread(
            _with_session, session_factory, _close_turn, tenant_id, state, turn_id, document_id, overlay_guest, vault_key,
        )
        record.update(end.record)
        outcome = end.outcome
        for event in end.events:
            yield event
    except TimeoutError:
        outcome = ChatOutcome.timed_out
        record["citations"] = [_no_support_citation()]
        yield _final(turn_id, "refused", "That took too long; please try a narrower question.", record["citations"])
    except GraphRecursionError:
        outcome = ChatOutcome.refused
        record["citations"] = [_no_support_citation()]
        yield _final(turn_id, "refused", "I couldn't settle on an answer within my step limit.", record["citations"])
    except Exception:  # the client gets a generic error; the details stay in the logs and the audit row
        logger.exception("chat turn failed")
        outcome = ChatOutcome.error
        yield TurnEvent("error", {"text": "Something went wrong answering that question."})
    finally:
        if handler and hasattr(handler, "last_trace_id"):
            record["trace_id"] = handler.last_trace_id
        record["latency_ms"] = int((time.perf_counter() - started) * 1000)
        # shield: a client disconnect cancels this task, and the audit row must still be written
        await asyncio.shield(asyncio.to_thread(_with_session, session_factory, dao.save_turn, ChatTurn(outcome=outcome, **record)))


