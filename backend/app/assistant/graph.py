import hashlib
import operator
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel

from app.assistant.citations import verify_answer
from app.assistant.tools import ToolContext, ToolSpec, execute

PROMPTS = Path(__file__).parent / "prompts"
AGENT_PROMPT = (PROMPTS / "agent_v1.md").read_text()
ANSWER_PROMPT = (PROMPTS / "answer_v1.md").read_text()
GRAPH_VERSION = "v2"
# route + 2 tool rounds + 2 answer attempts, with headroom
RECURSION_LIMIT = 12
MAX_ANSWER_ATTEMPTS = 2
FORCED_TOOL = "compare_contract_to_billing"
LOOKUP_TOOL = "list_documents"  # forced first: the forced tool takes a document_id the model must look up
CALCULATION_PATTERN = re.compile(r"\b(how much would|fee for|compare|leakage|difference|under this contract)\b", re.I)
NO_EVIDENCE_MESSAGE = "I can't find that in the indexed contracts, so I won't guess."
FAILED_VERIFICATION_MESSAGE = "I couldn't produce an answer I can fully back with the contracts' text."


class Answer(BaseModel):
    text: str
    citations: list[str]
    refused: bool


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


def prompt_version() -> str:
    return hashlib.sha256((AGENT_PROMPT + ANSWER_PROMPT).encode()).hexdigest()[:12]


def route_tool_choice(question: str, registered: set[str]) -> str | None:
    """Tool calls for calculations are forced, not left to model discretion (backlog Epic 2.5)."""
    return FORCED_TOOL if FORCED_TOOL in registered and CALCULATION_PATTERN.search(question) else None


def build_graph(chat_model: BaseChatModel, tools: Sequence[ToolSpec], ctx: ToolContext):
    by_name = {spec.name: spec for spec in tools}
    schemas = [spec.schema() for spec in tools]

    def route(state: TurnState) -> dict:
        question = next(m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage))
        forced = route_tool_choice(question, set(by_name))
        return {"forced_tools": [LOOKUP_TOOL, forced] if forced else [], "answer_attempts": 0, "violations": []}

    def agent(state: TurnState) -> dict:
        [choice, *rest] = state.get("forced_tools") or ["auto"]
        reply = chat_model.bind_tools(schemas, tool_choice=choice).invoke([SystemMessage(AGENT_PROMPT), *state["messages"]])
        return {"messages": [reply], "forced_tools": rest}

    def run_tools(state: TurnState) -> dict:
        last = state["messages"][-1]
        messages, sources, citations, retrieved = [], {}, {}, []
        for call in last.tool_calls:
            spec = by_name.get(call["name"])
            if spec is None:
                messages.append(ToolMessage(f"Unknown tool {call['name']}", tool_call_id=call["id"]))
                continue
            outcome = execute(spec, ctx, call["args"])
            messages.append(ToolMessage(outcome.content, tool_call_id=call["id"]))
            sources |= outcome.sources
            citations |= outcome.citations
            retrieved += [{"tool": spec.name, "id": source_id} for source_id in outcome.sources]
        return {"messages": messages, "sources": sources, "citations": citations, "retrieved": retrieved}

    def answer(state: TurnState) -> dict:
        if not state.get("sources"):
            return {"answer": Answer(text=NO_EVIDENCE_MESSAGE, citations=[], refused=True), "violations": []}
        feedback = []
        if state.get("violations"):
            feedback = [HumanMessage("Your previous answer failed verification: " + "; ".join(state["violations"])
                                     + ". Fix it using only cited sources, or refuse.")]
        result = chat_model.with_structured_output(Answer, method="json_schema", include_raw=True).invoke(
            [SystemMessage(ANSWER_PROMPT), *state["messages"], *feedback]
        )
        return {"answer": result["parsed"], "answer_attempts": state.get("answer_attempts", 0) + 1}

    def verify(state: TurnState) -> dict:
        reply = state["answer"]
        return {"violations": verify_answer(reply.text, reply.citations, state.get("sources", {}), reply.refused)}

    def refuse(_state: TurnState) -> dict:
        return {"answer": Answer(text=FAILED_VERIFICATION_MESSAGE, citations=[], refused=True)}

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
