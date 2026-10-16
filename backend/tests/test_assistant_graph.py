import asyncio
import dataclasses
import json
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI
from sqlalchemy import select

from app.assistant.graph import Answer, ContractSection, NO_EVIDENCE_MESSAGE, build_graph, RECURSION_LIMIT
from app.assistant.tools import ToolContext, default_tools
from app.documents import dao as documents_dao
from app.governance.dao import ModelConfig
from app.governance.models import ToolInvocation
from app.retrieval.index import index_version
from app.retrieval.vector_index import InMemoryVectorIndex
from tests.fakes import RecordingEmbeddings, ScriptedChatModel, SlowScriptedChatModel
from scripts.load import mock_openai
from tests.test_retrieval_index import parsed_version

MODEL = ModelConfig(provider="fake", model_id="scripted", prompt_version="test", temperature=0)


def _ctx(db_session, tenant_id, embeddings, index):
    import uuid
    from app import config
    return ToolContext(session=db_session, tenant_id=tenant_id, session_id="s1", turn_id=uuid.uuid4(),
                       embeddings=embeddings, vector_index=index, model=MODEL, hmac_key=config.PII_HMAC_KEY, vault_key=config.PII_VAULT_KEY)


def _search_call(query):
    return AIMessage(content="", tool_calls=[{"name": "search_contracts", "args": {"query": query}, "id": "call-1"}])


def _config(ctx):
    return {"recursion_limit": RECURSION_LIMIT, "configurable": {"ctx": ctx}}


def _run(model, ctx, question):
    graph = build_graph(model, default_tools())
    return asyncio.run(graph.ainvoke({"messages": [HumanMessage(content=question)]}, config=_config(ctx)))


@pytest.fixture()
def indexed(db_session, tenant_id):
    embeddings, index = RecordingEmbeddings(), InMemoryVectorIndex()
    version = parsed_version(db_session, tenant_id, texts=("On the next $1,500,000 the annual rate is 0.85%.",))
    index_version(db_session, version.id, embeddings=embeddings, vector_index=index)
    return embeddings, index


def _element_id(db_session, tenant_id, indexed):
    from app.retrieval.search import search
    embeddings, index = indexed
    return str(search(db_session, tenant_id=tenant_id, query="annual rate", embeddings=embeddings, vector_index=index)[0].element_id)


def test_answer_with_verified_citation(db_session, tenant_id, indexed):
    element_id = _element_id(db_session, tenant_id, indexed)
    model = ScriptedChatModel(replies=[
        _search_call("annual rate"), AIMessage(content="done"),
        Answer(text="The second tier is 0.85% on the next $1,500,000.", citations=[element_id], refused=False),
    ])
    state = _run(model, _ctx(db_session, tenant_id, *indexed), "What is the second tier rate?")
    assert state["answer"].refused is False
    assert state["citations"][element_id]["page"] == 1
    invocations = db_session.scalars(select(ToolInvocation).where(ToolInvocation.tenant_id == tenant_id)).all()
    assert [i.tool_name for i in invocations] == ["search_contracts"]
    assert json.loads(json.dumps(invocations[0].input))["query"] == "annual rate"


def test_uncited_number_is_retried_then_refused(db_session, tenant_id, indexed):
    element_id = _element_id(db_session, tenant_id, indexed)
    bad = Answer(text="The second tier is 0.90%.", citations=[element_id], refused=False)
    model = ScriptedChatModel(replies=[_search_call("rate"), AIMessage(content="done"), bad, bad])
    state = _run(model, _ctx(db_session, tenant_id, *indexed), "What is the second tier rate?")
    assert state["answer"].refused is True
    assert "0.9" in model.prompts[-1]  # the retry was told which number failed


def test_with_no_evidence_only_a_refusal_or_a_clarification_gets_through(db_session, tenant_id):
    stated = Answer(text="It is 30 days.", citations=[], refused=False)
    model = ScriptedChatModel(replies=[_search_call("charitable donations"), AIMessage(content="done"), stated, stated])
    state = _run(model, _ctx(db_session, tenant_id, RecordingEmbeddings(), InMemoryVectorIndex()), "Donations?")
    assert state["answer"] == Answer(text=NO_EVIDENCE_MESSAGE, citations=[], refused=True)  # both attempts failed the check


def test_calculation_question_forces_the_tool_when_registered(db_session, tenant_id, indexed):
    from app.assistant.graph import FORCED_TOOL, route_tool_choice
    assert route_tool_choice("How much would the Tremblay household pay under this contract?", {FORCED_TOOL}) == FORCED_TOOL
    assert route_tool_choice("How much would they pay?", set()) is None  # tool not registered yet (Plan 2 adds it)
    assert route_tool_choice("Who are the parties?", {FORCED_TOOL}) is None


def test_calculation_question_looks_up_the_id_before_the_forced_tool(db_session, tenant_id, indexed):
    from app.assistant.contract_tools import contract_tools
    from app.assistant.graph import FORCED_TOOL, LOOKUP_TOOL
    compare = AIMessage(content="", tool_calls=[{"name": FORCED_TOOL, "args": {"document_id": "tremblay-household"}, "id": "c2"}])
    model = ScriptedChatModel(replies=[
        AIMessage(content="", tool_calls=[{"name": LOOKUP_TOOL, "args": {}, "id": "c1"}]), compare, AIMessage(content="done"),
        Answer(text="I can't find that contract.", citations=[], refused=True),
    ])
    graph = build_graph(model, default_tools() + contract_tools())
    state = asyncio.run(graph.ainvoke({"messages": [HumanMessage("How much would the Tremblay household pay under this contract?")]},
                                      config=_config(_ctx(db_session, tenant_id, *indexed))))
    assert model.tool_choices == [LOOKUP_TOOL, FORCED_TOOL, "auto"]
    assert "document_id" in state["messages"][-2].content  # the invalid id went back to the model, not a crash
    assert state["answer"].refused is True


def test_answer_retry_fits_after_two_tool_rounds(db_session, tenant_id, indexed):
    element_id = _element_id(db_session, tenant_id, indexed)
    model = ScriptedChatModel(replies=[
        _search_call("rate"), _search_call("annual rate"), AIMessage(content="done"),
        Answer(text="The second tier is 0.85%.", citations=["not-retrieved"], refused=False),
        Answer(text="The second tier is 0.85%.", citations=[element_id], refused=False),
    ])
    state = _run(model, _ctx(db_session, tenant_id, *indexed), "What is the second tier rate?")
    assert state["answer"].refused is False


def test_a_refusal_after_three_tool_rounds_fits_in_the_step_budget(db_session, tenant_id, indexed):
    element_id = _element_id(db_session, tenant_id, indexed)
    bad = Answer(text="The second tier is 0.90%.", citations=[element_id], refused=False)
    model = ScriptedChatModel(replies=[
        _search_call("rate"), _search_call("annual rate"), _search_call("tier"), AIMessage(content="done"), bad, bad,
    ])
    state = _run(model, _ctx(db_session, tenant_id, *indexed), "What is the second tier rate?")  # no GraphRecursionError
    assert state["answer"].refused is True


def test_a_per_contract_answer_is_checked_section_by_section_and_rendered_by_the_service(db_session, tenant_id, indexed):
    element_id = _element_id(db_session, tenant_id, indexed)
    numbered = Answer(text="", citations=[], refused=False, sections=[
        ContractSection(text="The second tier is 0.90%.", citations=[element_id])])  # a number the contract doesn't state
    good = Answer(text="", citations=[], refused=False, sections=[
        ContractSection(text="The second tier is 0.85% on the next $1,500,000.", citations=[element_id])])
    model = ScriptedChatModel(replies=[_search_call("annual rate"), AIMessage(content="done"), numbered, good])
    state = _run(model, _ctx(db_session, tenant_id, *indexed), "What is the management fee?")
    assert "section 1: number 0.9" in model.prompts[-1]  # the retry was told which section failed
    answer = state["answer"]
    assert answer.refused is False and answer.citations == [element_id]
    assert answer.text == "**Tremblay IMA**\n\nThe second tier is 0.85% on the next $1,500,000."


def _mixed(element_id):
    return Answer(text="", citations=[], refused=False, sections=[
        ContractSection(text="The second tier is 0.85% on the next $1,500,000.", citations=[element_id]),
        ContractSection(text="The second tier is 0.90%.", citations=[element_id])])  # not what the contract states


def test_when_the_retry_gives_up_the_sections_that_passed_are_still_answered(db_session, tenant_id, indexed):
    element_id = _element_id(db_session, tenant_id, indexed)
    gave_up = Answer(text="", citations=[], refused=True)
    model = ScriptedChatModel(replies=[_search_call("annual rate"), AIMessage(content="done"), _mixed(element_id), gave_up])
    answer = _run(model, _ctx(db_session, tenant_id, *indexed), "What is the management fee?")["answer"]
    assert answer.refused is False and answer.citations == [element_id]
    assert answer.text == "**Tremblay IMA**\n\nThe second tier is 0.85% on the next $1,500,000."  # the 0.90% section is gone


def test_when_the_retry_fails_again_the_sections_that_passed_are_still_answered(db_session, tenant_id, indexed):
    element_id = _element_id(db_session, tenant_id, indexed)
    model = ScriptedChatModel(replies=[_search_call("annual rate"), AIMessage(content="done"), _mixed(element_id), _mixed(element_id)])
    answer = _run(model, _ctx(db_session, tenant_id, *indexed), "What is the management fee?")["answer"]
    assert answer.refused is False and "0.90" not in answer.text and "0.85%" in answer.text


def test_when_no_section_passes_the_answer_is_refused(db_session, tenant_id, indexed):
    element_id = _element_id(db_session, tenant_id, indexed)
    bad = Answer(text="", citations=[], refused=False, sections=[ContractSection(text="The second tier is 0.90%.", citations=[element_id])])
    model = ScriptedChatModel(replies=[_search_call("annual rate"), AIMessage(content="done"), bad, bad])
    assert _run(model, _ctx(db_session, tenant_id, *indexed), "What is the management fee?")["answer"].refused is True


def test_a_turn_waiting_on_the_model_holds_no_thread(db_session, tenant_id, indexed):
    """With one executor thread, two turns overlap only if waiting on the model does not occupy a thread."""
    def turn_graph():
        model = SlowScriptedChatModel(delay=0.5, replies=[
            AIMessage(content="done"), Answer(text="", citations=[], refused=True)])
        return build_graph(model, default_tools())

    async def two_turns() -> float:
        asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1))
        started = time.perf_counter()
        await asyncio.gather(*(turn_graph().ainvoke({"messages": [HumanMessage("q")]},
                                                    config=_config(_ctx(db_session, tenant_id, *indexed))) for _ in range(2)))
        return time.perf_counter() - started

    # each turn makes two 0.5 s model calls: about 1 s if they overlap, about 2 s if they queue for the thread
    assert asyncio.run(two_turns()) < 1.5


def test_turn_timeout_cancels_the_model_call_and_saves_timed_out(session_factory, tenant_id, monkeypatch):
    from app import config
    from app.assistant import dao
    from app.assistant.models import ChatOutcome
    from app.assistant.service import AssistantRuntime, run_turn

    model = SlowScriptedChatModel(delay=5, replies=[AIMessage(content="done"), Answer(text="", citations=[], refused=True)])
    runtime = AssistantRuntime(chat_model=model, embeddings=RecordingEmbeddings(), vector_index=InMemoryVectorIndex(),
                               tools=default_tools())

    async def ask():
        return [e async for e in run_turn(session_factory=session_factory, runtime=runtime, tenant_id=tenant_id,
                                          session_id="timeout-turn", message="What is the fee?",
                                          hmac_key=config.PII_HMAC_KEY, vault_key=config.PII_VAULT_KEY)]

    monkeypatch.setattr(config, "CHAT_TURN_TIMEOUT_SECONDS", 0.5)
    started = time.perf_counter()
    final = asyncio.run(ask())[-1]  # asyncio.run waits for executor threads, so a blocking call shows in `elapsed`
    elapsed = time.perf_counter() - started
    assert final.type == "refused" and "too long" in final.data["text"]
    assert elapsed < 2  # the 5 s model call was cancelled, not waited out
    with session_factory() as session:
        assert dao.recent_turns(session, tenant_id, "timeout-turn", 1)[0].outcome is ChatOutcome.timed_out


def test_one_compiled_graph_serves_turns_with_different_contexts(db_session, tenant_id):
    embeddings, index = RecordingEmbeddings(), InMemoryVectorIndex()
    scopes = [parsed_version(db_session, tenant_id, key=key).document_id for key in ("graph-a", "graph-b")]
    lookup = AIMessage(content="", tool_calls=[{"name": "list_documents", "args": {}, "id": "c1"}])
    refused = Answer(text="", citations=[], refused=True)
    model = ScriptedChatModel(replies=[lookup, AIMessage(content="done"), refused, lookup, AIMessage(content="done"), refused])
    graph = build_graph(model, default_tools())
    listed = []
    for scope in scopes:
        ctx = dataclasses.replace(_ctx(db_session, tenant_id, embeddings, index), document_id=scope)
        state = asyncio.run(graph.ainvoke({"messages": [HumanMessage("Which contracts?")]}, config=_config(ctx)))
        listed.append([row["document_id"] for row in json.loads(state["messages"][2].content)])
    assert listed == [[str(scopes[0])], [str(scopes[1])]]


def test_concurrent_turns_on_one_compiled_graph_keep_their_own_scope(session_factory, db_session, tenant_id, monkeypatch):
    # Review Focus 3
    monkeypatch.setenv("MOCK_DELAY_SCALE", "0")
    embeddings, index = RecordingEmbeddings(), InMemoryVectorIndex()
    scopes = []
    for key in ("graph-c", "graph-d"):
        version = parsed_version(db_session, tenant_id, key=key)
        index_version(db_session, version.id, embeddings=embeddings, vector_index=index)
        scopes.append(version.document_id)
    model = ChatOpenAI(model="mock", api_key="mock", base_url="http://testserver/v1", max_retries=0,
                       http_async_client=httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_openai.app)))
    graph = build_graph(model, default_tools())

    async def both():
        return await asyncio.gather(*(graph.ainvoke({"messages": [HumanMessage("When are fees billed?")]}, config={
            "recursion_limit": RECURSION_LIMIT,
            "configurable": {"ctx": dataclasses.replace(_ctx(None, tenant_id, embeddings, index), document_id=scope),
                             "open_session": session_factory}}) for scope in scopes))

    for scope, state in zip(scopes, asyncio.run(both())):
        assert state["citations"] and {c["document_id"] for c in state["citations"].values()} == {str(scope)}


def test_the_runtime_compiles_its_graph_once(monkeypatch):
    from app.assistant import service
    built = []
    monkeypatch.setattr(service, "build_graph", lambda *args: built.append(args) or object())
    runtime = service.AssistantRuntime(chat_model=ScriptedChatModel(), embeddings=RecordingEmbeddings(),
                                       vector_index=InMemoryVectorIndex(), tools=default_tools())
    assert runtime.graph is runtime.graph and len(built) == 1


def test_an_answer_citing_a_section_ref_is_retried_and_never_shown(db_session, tenant_id, indexed):
    # Review Focus 2
    element_id = _element_id(db_session, tenant_id, indexed)
    text = "The second tier is 0.85% on the next $1,500,000."
    model = ScriptedChatModel(replies=[_search_call("annual rate"), AIMessage(content="done"),
                                       Answer(text=text, citations=["S1"], refused=False),
                                       Answer(text=text, citations=[element_id], refused=False)])
    state = _run(model, _ctx(db_session, tenant_id, *indexed), "What is the second tier rate?")
    assert state["answer"].citations == [element_id]
    assert "citation S1 was not retrieved" in model.prompts[-1]


def test_a_scoped_calculation_skips_the_lookup_and_names_its_document(db_session, tenant_id, indexed):
    from app.assistant.contract_tools import contract_tools
    from app.assistant.graph import FORCED_TOOL
    scoped = documents_dao.document_titles(db_session, tenant_id)[0]
    ctx = dataclasses.replace(_ctx(db_session, tenant_id, *indexed), document_id=scoped.id, document_title=scoped.title)
    compare = AIMessage(content="", tool_calls=[{"name": FORCED_TOOL, "args": {"document_id": str(scoped.id)}, "id": "c1"}])
    model = ScriptedChatModel(replies=[compare, AIMessage(content="done"), Answer(text="", citations=[], refused=True)])
    graph = build_graph(model, default_tools() + contract_tools())
    asyncio.run(graph.ainvoke({"messages": [HumanMessage("How much would the household pay under this contract?")]},
                              config=_config(ctx)))
    assert model.tool_choices == [FORCED_TOOL, "auto"]
    assert f"system: This chat is limited to one contract: Tremblay IMA (document_id {scoped.id})." in model.prompts[0]


def test_the_answer_call_shares_the_agent_calls_prefix(db_session, tenant_id, indexed):
    from app.assistant.graph import AGENT_PROMPT, ANSWER_PROMPT
    element_id = _element_id(db_session, tenant_id, indexed)
    model = ScriptedChatModel(replies=[_search_call("annual rate"), AIMessage(content="done"),
                                       Answer(text="The second tier is 0.85% on the next $1,500,000.", citations=[element_id], refused=False)])
    _run(model, _ctx(db_session, tenant_id, *indexed), "What is the second tier rate?")
    agent, answer = model.prompts[0], model.prompts[-1]
    assert agent.startswith("system: " + AGENT_PROMPT) and answer.startswith("system: " + AGENT_PROMPT)
    assert answer.rstrip().endswith("system: " + ANSWER_PROMPT.rstrip())
    assert model.structured_kwargs[-1]["tools"] == [spec.schema() for spec in default_tools()]
    assert model.structured_kwargs[-1]["tool_choice"] == "none"
