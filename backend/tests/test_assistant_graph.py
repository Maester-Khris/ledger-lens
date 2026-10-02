import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select

from app.assistant.graph import Answer, ContractSection, NO_EVIDENCE_MESSAGE, build_graph, RECURSION_LIMIT
from app.assistant.tools import ToolContext, default_tools
from app.governance.dao import ModelConfig
from app.governance.models import ToolInvocation
from app.retrieval.index import index_version
from app.retrieval.vector_index import InMemoryVectorIndex
from tests.fakes import RecordingEmbeddings, ScriptedChatModel
from tests.test_retrieval_index import parsed_version

MODEL = ModelConfig(provider="fake", model_id="scripted", prompt_version="test", temperature=0)


def _ctx(db_session, tenant_id, embeddings, index):
    import uuid
    from app import config
    return ToolContext(session=db_session, tenant_id=tenant_id, session_id="s1", turn_id=uuid.uuid4(),
                       embeddings=embeddings, vector_index=index, model=MODEL, hmac_key=config.PII_HMAC_KEY, vault_key=config.PII_VAULT_KEY)


def _search_call(query):
    return AIMessage(content="", tool_calls=[{"name": "search_contracts", "args": {"query": query}, "id": "call-1"}])


def _run(model, ctx, question):
    graph = build_graph(model, default_tools(), ctx)
    return graph.invoke({"messages": [HumanMessage(content=question)]}, config={"recursion_limit": RECURSION_LIMIT})


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
    graph = build_graph(model, default_tools() + contract_tools(), _ctx(db_session, tenant_id, *indexed))
    state = graph.invoke({"messages": [HumanMessage("How much would the Tremblay household pay under this contract?")]},
                         config={"recursion_limit": RECURSION_LIMIT})
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
