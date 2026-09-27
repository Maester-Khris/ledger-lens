import json
import uuid

from langchain_core.messages import AIMessage
from sqlalchemy import select

from app import config
from app.assistant.contract_tools import contract_tools
from app.assistant.models import ChatTurn
from app.assistant.tools import ToolContext, default_tools, execute
from app.governance.dao import ModelConfig
from app.governance.models import ToolInvocation
from app.retrieval.index import index_version
from app.retrieval.vector_index import InMemoryVectorIndex
from tests.fakes import RecordingEmbeddings, ScriptedChatModel
from tests.test_api_chat import _override, _runtime
from tests.test_retrieval_index import parsed_version

TOOLS = {spec.name: spec for spec in default_tools() + contract_tools()}


def _ctx(db_session, tenant_id, embeddings, index, document_id):
    return ToolContext(session=db_session, tenant_id=tenant_id, session_id="scope", turn_id=uuid.uuid4(),
                       embeddings=embeddings, vector_index=index, model=ModelConfig("fake", "scripted", "p", 0),
                       hmac_key=config.PII_HMAC_KEY, vault_key=config.PII_VAULT_KEY, document_id=document_id)


def _two_documents(db_session, tenant_id, embeddings, index):
    a = parsed_version(db_session, tenant_id, key="scope-a", texts=("Fees are billed quarterly.",))
    b = parsed_version(db_session, tenant_id, key="scope-b", texts=("Fees are billed quarterly too.",))
    for version in (a, b):
        index_version(db_session, version.id, embeddings=embeddings, vector_index=index)
    return a.document_id, b.document_id


def test_scoped_search_ignores_other_document_ids(db_session, tenant_id):
    embeddings, index = RecordingEmbeddings(), InMemoryVectorIndex()
    a, b = _two_documents(db_session, tenant_id, embeddings, index)
    outcome = execute(TOOLS["search_contracts"], _ctx(db_session, tenant_id, embeddings, index, a),
                      {"query": "billed quarterly", "document_ids": [str(b)]})
    assert outcome.citations and {c["document_id"] for c in outcome.citations.values()} == {str(a)}


def test_scoped_list_documents_returns_only_the_scope(db_session, tenant_id):
    embeddings, index = RecordingEmbeddings(), InMemoryVectorIndex()
    a, _ = _two_documents(db_session, tenant_id, embeddings, index)
    outcome = execute(TOOLS["list_documents"], _ctx(db_session, tenant_id, embeddings, index, a), {})
    assert [row["document_id"] for row in json.loads(outcome.content)] == [str(a)]


def test_contract_tool_for_another_document_is_refused_and_still_audited(db_session, tenant_id):
    embeddings, index = RecordingEmbeddings(), InMemoryVectorIndex()
    a, b = _two_documents(db_session, tenant_id, embeddings, index)
    outcome = execute(TOOLS["get_contract_fields"], _ctx(db_session, tenant_id, embeddings, index, a), {"document_id": str(b)})
    assert "This chat is scoped to" in json.loads(outcome.content)["error"]
    # Review Focus 5: the blocked call is recorded, so the audit trail shows it
    assert db_session.scalars(select(ToolInvocation).where(ToolInvocation.session_id == "scope")).first() is not None


def test_chat_with_unknown_document_is_404(client, session_factory):
    _override(client, _runtime(ScriptedChatModel(replies=[]), RecordingEmbeddings(), InMemoryVectorIndex()), session_factory)
    response = client.post("/chat", json={"session_id": "s-404", "message": "hi", "document_id": str(uuid.uuid4())})
    assert response.status_code == 404


def test_scoped_chat_records_the_document_on_the_turn(client, session_factory, db_session, tenant_id):
    embeddings, index = RecordingEmbeddings(), InMemoryVectorIndex()
    a, _ = _two_documents(db_session, tenant_id, embeddings, index)
    model = ScriptedChatModel(replies=[
        AIMessage(content="", tool_calls=[{"name": "search_contracts", "args": {"query": "nothing"}, "id": "c1"}]),
        AIMessage(content="done"),
    ])
    _override(client, _runtime(model, embeddings, index), session_factory)
    client.post("/chat", json={"session_id": "s-scoped", "message": "hi", "document_id": str(a)})
    turn = db_session.scalars(select(ChatTurn).where(ChatTurn.session_id == "s-scoped")).one()
    assert turn.document_id == a
