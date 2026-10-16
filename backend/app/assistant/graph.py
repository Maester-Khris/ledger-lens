import dataclasses
import hashlib
import json
import operator
import re
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import Runnable, RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import config
from app.assistant.citations import compose_sections, verify_answer, verify_sections
from app.assistant.tools import ToolContext, ToolSpec, execute

PROMPTS = Path(__file__).parent / "prompts"
AGENT_PROMPT = (PROMPTS / "agent_v1.md").read_text()
ANSWER_PROMPT = (PROMPTS / "answer_v1.md").read_text()
GRAPH_VERSION = "v4"
# route + up to 4 tool rounds (a per-contract lookup, P4 D12) + 2 answer attempts + the refuse node, with headroom
RECURSION_LIMIT = 16
MAX_ANSWER_ATTEMPTS = 2
FORCED_TOOL = "compare_contract_to_billing"
SEARCH_TOOL = "search_contracts"
LOOKUP_TOOL = "list_documents"  # forced first: the forced tool takes a document_id the model must look up
CALCULATION_PATTERN = re.compile(r"\b(how much would|fee for|compare|leakage|difference|under this contract)\b", re.I)
NO_EVIDENCE_MESSAGE = "I can't find that in the indexed contracts, so I won't guess."
FAILED_VERIFICATION_MESSAGE = "I couldn't produce an answer I can fully back with the contracts' text."
LIST_CLEARED = "[document list shown earlier; call list_documents again if you need it]"
SCOPE_LINE = "This chat is limited to one contract: {title} (document_id {document_id})."


class ContractSection(BaseModel):
    """What one contract says, citing that contract only."""
    text: str
    citations: list[str]


class Answer(BaseModel):
    text: str
    citations: list[str]
    refused: bool
    clarification: bool = False
    # An answer covering several contracts: one entry each, instead of one text. The service adds the headings.
    sections: list[ContractSection] = []


def _merge(left: dict, right: dict) -> dict:
    return {**left, **right}


class TurnState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    sources: Annotated[dict[str, str], _merge]
    citations: Annotated[dict[str, dict], _merge]
    retrieved: Annotated[list[dict], operator.add]
    forced_tools: list[str]
    answer: Answer | None
    violations: list[str]
    answer_attempts: int
    unvalidated: Annotated[list[str], operator.add]  # document ids with fields the agent may not use
    system_notices: Annotated[list[str], operator.add]
    partial: Answer | None  # the sections of a per-contract answer that passed, kept in case the retry ends in a refusal


def prompt_version() -> str:
    return hashlib.sha256((AGENT_PROMPT + ANSWER_PROMPT).encode()).hexdigest()[:12]


def eval_config_hash() -> str:
    """Identifies the chat configuration a golden-set report was produced with (see tests/eval/test_golden.py)."""
    return hashlib.sha256(f"{config.CHAT_MODEL}|{prompt_version()}|{config.EMBEDDING_MODEL}|{config.MIN_DENSE_SIMILARITY}".encode()).hexdigest()[:12]


def route_tool_choice(question: str, registered: set[str]) -> str | None:
    """Tool calls for calculations are forced, not left to model discretion (backlog Epic 2.5)."""
    return FORCED_TOOL if FORCED_TOOL in registered and CALCULATION_PATTERN.search(question) else None


def _turn_inputs(config: RunnableConfig) -> tuple[ToolContext, Callable[[], AbstractContextManager[Session]]]:
    """Per-turn inputs come through the run config, so one compiled graph serves every turn."""
    ctx = config["configurable"]["ctx"]
    open_session = config["configurable"].get("open_session")
    if open_session is None:
        open_session = lambda: nullcontext(ctx.session)
    return ctx, open_session


def _hits_only(content: str) -> str:
    """A search result as an agent call sees it: each hit with its document and section names, no section text.
    The full text goes to the answer call only (spec T2). Anything else (an error) passes unchanged."""
    try:
        payload = json.loads(content)
    except ValueError:
        return content
    if not isinstance(payload, dict) or "hits" not in payload:
        return content
    sections = payload.get("sections", {})
    return json.dumps({"hits": [
        {**{k: v for k, v in hit.items() if k != "section"},
         "document": sections.get(hit.get("section"), {}).get("document"),
         "section": sections.get(hit.get("section"), {}).get("section")}
        for hit in payload["hits"]
    ]})


def model_view(messages: Sequence[AnyMessage], call: Literal["agent", "answer"]) -> list[AnyMessage]:
    """What one model call is sent; the turn's state keeps every message as it was. For agent calls, a document list
    that a later model reply has already used becomes a placeholder (spec T3), and search hits come without their
    section text (spec T2). The answer call sees both in full: with the list cleared there, an unscoped per-contract
    answer came back refused (gate 1, batch-a-r1). Every tool message stays in place, so its tool call keeps a
    result, as OpenAI requires."""
    names = {c["id"]: c["name"] for m in messages if isinstance(m, AIMessage) for c in m.tool_calls}
    last_reply = max((i for i, m in enumerate(messages) if isinstance(m, AIMessage)), default=-1)
    view = []
    for position, message in enumerate(messages):
        name = names.get(message.tool_call_id) if isinstance(message, ToolMessage) else None
        if name == LOOKUP_TOOL and call == "agent" and position < last_reply:
            message = message.model_copy(update={"content": LIST_CLEARED})
        elif name == SEARCH_TOOL and call == "agent":
            message = message.model_copy(update={"content": _hits_only(message.content)})
        view.append(message)
    return view


def scope_line(ctx: ToolContext) -> list[SystemMessage]:
    if ctx.document_id is None:
        return []
    return [SystemMessage(SCOPE_LINE.format(title=ctx.document_title or "this contract", document_id=ctx.document_id))]


def build_graph(chat_model: BaseChatModel, tools: Sequence[ToolSpec]) -> Runnable:
    """The graph is compiled once per runtime; each run passes
    config={"configurable": {"ctx": ToolContext, "open_session": callable | None}};
    open_session opens a short DB session per tool call so no connection is held
    while waiting on the model, and without it tools use ctx.session.
    """
    by_name = {spec.name: spec for spec in tools}
    schemas = [spec.schema() for spec in tools]
    structured = chat_model.with_structured_output(Answer, method="json_schema", include_raw=True)
    tool_models: dict[str, Runnable] = {}

    # ponytail: unsynchronised cache; two turns racing on a new choice bind it twice, harmlessly
    def with_tools(choice: str) -> Runnable:
        if choice not in tool_models:
            tool_models[choice] = chat_model.bind_tools(schemas, tool_choice=choice)
        return tool_models[choice]

    def route(state: TurnState, config: RunnableConfig) -> dict:
        ctx, _ = _turn_inputs(config)
        question = next(m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage))
        forced = route_tool_choice(question, set(by_name))
        lookup = [] if ctx.document_id is not None else [LOOKUP_TOOL]  # scoped, the scope line gives the id
        return {"forced_tools": [*lookup, forced] if forced else [], "answer_attempts": 0, "violations": []}

    async def agent(state: TurnState, config: RunnableConfig) -> dict:
        ctx, _ = _turn_inputs(config)
        [choice, *rest] = state.get("forced_tools") or ["auto"]
        reply = await with_tools(choice).ainvoke(
            [SystemMessage(AGENT_PROMPT), *scope_line(ctx), *model_view(state["messages"], "agent")]
        )
        return {"messages": [reply], "forced_tools": rest}

    def run_tools(state: TurnState, config: RunnableConfig) -> dict:
        ctx, open_session = _turn_inputs(config)
        last = state["messages"][-1]
        messages, sources, citations, retrieved = [], {}, {}, []
        unvalidated, notices = [], []
        for call in last.tool_calls:
            spec = by_name.get(call["name"])
            if spec is None:
                messages.append(ToolMessage(f"Unknown tool {call['name']}", tool_call_id=call["id"]))
                continue
            with open_session() as session:
                outcome = execute(spec, dataclasses.replace(ctx, session=session), call["args"])
            messages.append(ToolMessage(outcome.content, tool_call_id=call["id"]))
            sources |= outcome.sources
            citations |= outcome.citations
            retrieved += [{"tool": spec.name, "id": source_id} for source_id in outcome.sources]
            unvalidated += [str(outcome.unvalidated_document_id)] if outcome.unvalidated_document_id else []
            notices += [outcome.system_notice] if outcome.system_notice else []
        return {"messages": messages, "sources": sources, "citations": citations, "retrieved": retrieved, "unvalidated": unvalidated, "system_notices": notices}

    async def answer(state: TurnState, config: RunnableConfig) -> dict:
        ctx, _ = _turn_inputs(config)
        feedback = []
        if state.get("violations"):
            feedback = [HumanMessage("Your previous answer failed verification: " + "; ".join(state["violations"])
                                     + ". Fix it using only cited sources, or refuse.")]
        result = await structured.ainvoke(
            [SystemMessage(ANSWER_PROMPT), *scope_line(ctx), *model_view(state["messages"], "answer"), *feedback]
        )
        return {"answer": result["parsed"], "answer_attempts": state.get("answer_attempts", 0) + 1}

    def verify(state: TurnState) -> dict:
        reply = state["answer"]
        if reply.refused and state.get("partial") is not None:
            return {"violations": [], "answer": state["partial"]}  # the retry gave up: answer what was verified
        if reply.sections and not reply.refused and not reply.clarification:
            sections = [(section.text, section.citations) for section in reply.sections]
            sources, cited = state.get("sources", {}), state.get("citations", {})
            contracts = {k: v.get("document_id") for k, v in cited.items()}
            violations = verify_sections(sections, sources, contracts)
            if violations:
                # One contract's section failing must not cost the guest the others: only verified sections are kept,
                # so nothing unverified is ever shown. ponytail: the dropped contract is not named to the guest.
                sections = [section for section in sections if not verify_sections([section], sources, contracts)]
            if not sections:
                return {"violations": violations}
            text, ids = compose_sections(sections, {k: v.get("document_title") for k, v in cited.items()})
            composed = Answer(text=text, citations=ids, refused=False)
            return {"violations": violations, "partial": composed} if violations else {"violations": [], "answer": composed}
        return {"violations": verify_answer(reply.text, reply.citations, state.get("sources", {}), reply.refused, reply.clarification)}

    def refuse(state: TurnState) -> dict:
        if state.get("partial") is not None:
            return {"answer": state["partial"]}
        text = FAILED_VERIFICATION_MESSAGE if state.get("sources") else NO_EVIDENCE_MESSAGE
        return {"answer": Answer(text=text, citations=[], refused=True)}

    def after_agent(state: TurnState) -> str:
        last = state["messages"][-1]
        return "tools" if isinstance(last, AIMessage) and last.tool_calls else "answer"

    def after_verify(state: TurnState) -> str:
        if not state["violations"]:
            return END
        return "answer" if state["answer_attempts"] < MAX_ANSWER_ATTEMPTS else "refuse"

    graph = StateGraph(TurnState)
    for name, node in (("route", route), ("agent", agent), ("tools", run_tools), ("answer", answer),
                       ("verify", verify), ("refuse", refuse)):
        graph.add_node(name, node)
    graph.add_edge(START, "route")
    graph.add_edge("route", "agent")
    graph.add_conditional_edges("agent", after_agent, {"tools": "tools", "answer": "answer"})
    graph.add_edge("tools", "agent")
    graph.add_edge("answer", "verify")
    graph.add_conditional_edges("verify", after_verify, {END: END, "answer": "answer", "refuse": "refuse"})
    graph.add_edge("refuse", END)
    return graph.compile()
