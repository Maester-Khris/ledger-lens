from langchain_core.messages import AIMessage

from app.assistant.contract_tools import contract_tools
from app.assistant.graph import Answer
from app.assistant.service import AssistantRuntime
from app.assistant.tools import default_tools
from app.contracts.types import FieldRouting
from app.retrieval.index import index_version
from app.retrieval.search import search
from app.retrieval.vector_index import InMemoryVectorIndex
from tests.fakes import RecordingEmbeddings, ScriptedChatModel
from tests.test_api_chat import _events, _override
from tests.test_contracts_compare import _contract
from tests.test_retrieval_index import parsed_version


def _runtime(model, embeddings=None, index=None):
    return AssistantRuntime(chat_model=model, embeddings=embeddings or RecordingEmbeddings(),
                            vector_index=index or InMemoryVectorIndex(), tools=default_tools() + contract_tools())


def test_unconfirmed_fields_are_announced_before_the_final_event(client, session_factory, db_session, tenant_id):
    document_id = _contract(db_session, tenant_id, None, tier_routing=FieldRouting.needs_review, key="uv-1")
    model = ScriptedChatModel(replies=[
        AIMessage(content="", tool_calls=[{"name": "get_contract_fields", "args": {"document_id": str(document_id)}, "id": "c1"}]),
        AIMessage(content="done"),
        Answer(text="Not available.", citations=[], refused=True),
    ])
    _override(client, _runtime(model), session_factory)
    events = _events(client.post("/chat", json={"session_id": "uv-1", "message": "What are the fees?"}))
    kinds = [k for k, _ in events]
    assert kinds.count("unvalidated") == 1 and kinds.index("unvalidated") < len(kinds) - 1
    notice = dict(events)["unvalidated"]
    assert notice["document_id"] == str(document_id)
    assert {f["path"] for f in notice["fields"]} >= {"fee_tiers[0]"} and notice["fields"][0]["reason"]


def test_not_comparable_refusal_becomes_a_system_notice(client, session_factory, db_session, tenant_id):
    document_id = _contract(db_session, tenant_id, None, key="uv-fund")
    model = ScriptedChatModel(replies=[
        AIMessage(content="", tool_calls=[{"name": "list_documents", "args": {}, "id": "c0"}]),
        AIMessage(content="", tool_calls=[{"name": "compare_contract_to_billing", "args": {"document_id": str(document_id)}, "id": "c1"}]),
        AIMessage(content="done"),
        Answer(text="Not available.", citations=[], refused=True),
    ])
    _override(client, _runtime(model), session_factory)
    kind, data = _events(client.post("/chat", json={"session_id": "uv-2", "message": "Compare this contract with billing"}))[-1]
    assert kind == "refused"
    assert "not linked to a billing household" in data["text"]
    assert data["citations"] == [{"id": "system", "kind": "system", "source": "billing records",
                                  "detail": "This contract is not linked to a billing household (fund-level agreement)."}]


def test_notice_never_replaces_a_valid_answer(client, session_factory, db_session, tenant_id):
    # Review Focus 2
    fund = _contract(db_session, tenant_id, None, key="uv-fund-2")
    embeddings, index = RecordingEmbeddings(), InMemoryVectorIndex()
    version = parsed_version(db_session, tenant_id, key="uv-text", texts=("Fees are billed quarterly in arrears.",))
    index_version(db_session, version.id, embeddings=embeddings, vector_index=index)
    element_id = str(search(db_session, tenant_id=tenant_id, query="quarterly", embeddings=embeddings, vector_index=index)[0].element_id)
    model = ScriptedChatModel(replies=[
        AIMessage(content="", tool_calls=[
            {"name": "compare_contract_to_billing", "args": {"document_id": str(fund)}, "id": "c1"},
            {"name": "search_contracts", "args": {"query": "quarterly"}, "id": "c2"},
        ]),
        AIMessage(content="done"),
        Answer(text="Fees are billed quarterly in arrears.", citations=[element_id], refused=False),
    ])
    _override(client, _runtime(model, embeddings, index), session_factory)
    kind, data = _events(client.post("/chat", json={"session_id": "uv-3", "message": "How often are fees billed?"}))[-1]
    assert kind == "answer" and data["citations"][0]["kind"] == "element"
