import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from datetime import date
from sqlalchemy.orm import Session
from app.contracts import dao as contracts_dao

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphRecursionError
from sqlalchemy.orm import sessionmaker

from app import config
from app.assistant import dao
from app.assistant.graph import GRAPH_VERSION, RECURSION_LIMIT, build_graph, prompt_version
from app.assistant.models import ChatOutcome, ChatTurn
from app.assistant.tools import ToolContext, ToolSpec
from app.documents import dao as documents_dao
from app.governance.dao import ModelConfig
from app.retrieval.vector_index import VectorIndex
from app.tracing import get_tracing_handler

logger = logging.getLogger(__name__)
HISTORY_TURNS = 4
PROGRESS = {"agent": "thinking", "tools": "searching", "answer": "writing", "verify": "checking citations"}


@dataclass(frozen=True)
class TurnEvent:
    type: Literal["progress", "answer", "refused", "error", "unvalidated"]
    data: dict


@dataclass(frozen=True)
class AssistantRuntime:
    chat_model: BaseChatModel
    embeddings: Embeddings
    vector_index: VectorIndex
    tools: list[ToolSpec]


def _usage(messages: list) -> tuple[int, int]:
    usage = [m.usage_metadata for m in messages if isinstance(m, AIMessage) and m.usage_metadata]
    return sum(u["input_tokens"] for u in usage), sum(u["output_tokens"] for u in usage)


async def run_turn(
    *, session_factory: sessionmaker, runtime: AssistantRuntime, tenant_id: uuid.UUID, session_id: str,
    message: str, hmac_key: str, vault_key: str,
    guest_id: uuid.UUID | None = None, document_id: uuid.UUID | None = None,
) -> AsyncIterator[TurnEvent]:
    started = time.perf_counter()
    model_id = getattr(runtime.chat_model, "model_name", None) or config.CHAT_MODEL
    record = dict(tenant_id=tenant_id, session_id=session_id, citations=[], retrieved=[], answer_redacted=None,
                  model_id=model_id, prompt_version=prompt_version(), graph_version=GRAPH_VERSION,
                  input_tokens=0, output_tokens=0, guest_id=guest_id, document_id=document_id)
    outcome = ChatOutcome.cancelled  # anything that exits early without setting an outcome was a disconnect
    with session_factory() as session:
        question = documents_dao.tokenize_known_values(session, tenant_id, message, hmac_key, vault_key)
        record["question_redacted"] = question
        history = []
        for turn in dao.recent_turns(session, tenant_id, session_id, HISTORY_TURNS):
            history += [HumanMessage(turn.question_redacted), AIMessage(turn.answer_redacted or "")]
        ctx = ToolContext(session=session, tenant_id=tenant_id, session_id=session_id, turn_id=uuid.uuid4(),
                          embeddings=runtime.embeddings, vector_index=runtime.vector_index,
                          model=ModelConfig("openai", model_id, record["prompt_version"], Decimal(0)), hmac_key=hmac_key, vault_key=vault_key,
                          document_id=document_id)
        graph = build_graph(runtime.chat_model, runtime.tools, ctx)
        state: dict = {}
        
        handler = get_tracing_handler()
        
        run_config = {"recursion_limit": RECURSION_LIMIT}
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
                # Nodes are sync (DB + model calls); LangGraph runs them in a thread pool under astream.
                # ponytail: a timed-out node keeps running in its thread until its own call timeout (30 s) ends it
                async for mode, data in graph.astream({"messages": [*history, HumanMessage(question)]},
                                                      config=run_config,
                                                      stream_mode=["updates", "values"]):
                    if mode == "values":
                        state = data
                    else:
                        for node in data:
                            yield TurnEvent("progress", {"step": PROGRESS.get(node, "thinking")})
            answer = state["answer"]
            for event in _unvalidated_events(session, tenant_id, state.get("unvalidated", [])):
                yield event
            notices = state.get("system_notices", [])
            if answer.refused and notices:
                citation = {"id": SYSTEM_CITATION_ID, "kind": "system", "source": "billing records", "detail": notices[-1]}
                record.update(answer_redacted=NOT_COMPARABLE_TEXT.format(reason=notices[-1]), citations=[citation],
                              retrieved=state.get("retrieved", []))
                record["input_tokens"], record["output_tokens"] = _usage(state.get("messages", []))
                outcome = ChatOutcome.refused
                yield TurnEvent("refused", {"text": NOT_COMPARABLE_TEXT.format(reason=notices[-1]), "citations": [citation]})
                return
            cited = [state["citations"][c] | {"id": c} for c in answer.citations if c in state.get("citations", {})]
            record.update(answer_redacted=answer.text, citations=cited, retrieved=state.get("retrieved", []))
            record["input_tokens"], record["output_tokens"] = _usage(state.get("messages", []))
            outcome = ChatOutcome.refused if answer.refused else ChatOutcome.answered
            [text, *quotes] = documents_dao.reveal(session, tenant_id, [answer.text, *(c.get("quote", "") for c in cited)], vault_key)
            shown = [c | ({"quote": q} if "quote" in c else {}) for c, q in zip(cited, quotes)]
            yield TurnEvent("refused" if answer.refused else "answer", {"text": text, "citations": shown})
        except TimeoutError:
            outcome = ChatOutcome.timed_out
            yield TurnEvent("refused", {"text": "That took too long; please try a narrower question.", "citations": []})
        except GraphRecursionError:
            outcome = ChatOutcome.refused
            yield TurnEvent("refused", {"text": "I couldn't settle on an answer within my step limit.", "citations": []})
        except Exception:  # the client gets a generic error; the details stay in the logs and the audit row
            logger.exception("chat turn failed")
            outcome = ChatOutcome.error
            yield TurnEvent("error", {"text": "Something went wrong answering that question."})
        finally:
            if handler and hasattr(handler, "last_trace_id"):
                record["trace_id"] = handler.last_trace_id
            session.rollback()
            record["latency_ms"] = int((time.perf_counter() - started) * 1000)
            dao.save_turn(session, ChatTurn(outcome=outcome, **record))

SYSTEM_CITATION_ID = "system"
NOT_COMPARABLE_TEXT = "I can't compare this contract with billing: {reason}"

def _unvalidated_events(session: Session, tenant_id: uuid.UUID, document_ids: list[str]) -> list[TurnEvent]:
    events = []
    for document_id in dict.fromkeys(document_ids):  # once per document, in order
        view = contracts_dao.terms_view(session, tenant_id, uuid.UUID(document_id), date.today())
        if view is None:
            continue
        fields = [{"path": f.path, "label": f.label, "reason": f.reason} for f in view.fields if f.status in ("needs_review", "rejected")]
        if fields:
            events.append(TurnEvent("unvalidated", {"document_id": document_id, "title": view.title, "fields": fields}))
    return events
