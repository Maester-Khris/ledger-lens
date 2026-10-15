import json
import uuid

from app import config
from app.assistant.service import _clarifying_question
from app.assistant.tools import NoArgs, ToolContext, default_tools
from app.documents import dao as documents_dao
from app.governance.dao import ModelConfig
from app.retrieval.vector_index import InMemoryVectorIndex
from tests.fakes import RecordingEmbeddings
from tests.support import make_tenant, record_statements
from tests.test_retrieval_index import parsed_version

LIST_TOOL = next(spec for spec in default_tools() if spec.name == "list_documents")


def _ctx(db_session, tenant_id, document_id=None):
    return ToolContext(session=db_session, tenant_id=tenant_id, session_id="titles", turn_id=uuid.uuid4(),
                       embeddings=RecordingEmbeddings(), vector_index=InMemoryVectorIndex(),
                       model=ModelConfig("fake", "scripted", "p", 0), hmac_key=config.PII_HMAC_KEY,
                       vault_key=config.PII_VAULT_KEY, document_id=document_id)


def _three_documents(db_session, tenant_id) -> list[uuid.UUID]:
    return [parsed_version(db_session, tenant_id, key=f"titles-{n}").document_id for n in range(3)]


def _old_tool_json(db_session, tenant_id, document_id=None) -> str:
    """The list_documents tool's output before C1, built from the full listing."""
    rows = [r for r in documents_dao.list_documents(db_session, tenant_id) if document_id is None or r.document.id == document_id]
    return json.dumps([{"document_id": str(r.document.id), "document_key": r.document.document_key, "title": r.document.title}
                       for r in rows])


def test_document_titles_match_the_full_listing_in_order(db_session, tenant_id):
    _three_documents(db_session, tenant_id)
    titles = documents_dao.document_titles(db_session, tenant_id)
    assert len(titles) == 3
    assert [(t.id, t.document_key, t.title) for t in titles] == [
        (r.document.id, r.document.document_key, r.document.title) for r in documents_dao.list_documents(db_session, tenant_id)]


def test_document_titles_filter_to_the_scoped_document_and_the_tenant(db_session, tenant_id):
    ids = _three_documents(db_session, tenant_id)
    assert [t.id for t in documents_dao.document_titles(db_session, tenant_id, ids[1])] == [ids[1]]
    assert documents_dao.document_titles(db_session, tenant_id, uuid.uuid4()) == []
    assert documents_dao.document_titles(db_session, make_tenant(db_session)) == []


def test_list_documents_tool_output_is_unchanged(db_session, tenant_id):
    ids = _three_documents(db_session, tenant_id)
    assert LIST_TOOL.run(_ctx(db_session, tenant_id), NoArgs()).content == _old_tool_json(db_session, tenant_id)
    assert LIST_TOOL.run(_ctx(db_session, tenant_id, ids[0]), NoArgs()).content == _old_tool_json(db_session, tenant_id, ids[0])


def test_list_documents_tool_runs_one_statement(db_session, tenant_id):
    _three_documents(db_session, tenant_id)
    _, statements = record_statements(db_session, lambda: LIST_TOOL.run(_ctx(db_session, tenant_id), NoArgs()))
    assert len(statements) == 1


def test_clarifying_question_reads_titles_in_one_statement(db_session, tenant_id):
    ids = _three_documents(db_session, tenant_id)
    _, statements = record_statements(db_session, lambda: _clarifying_question(db_session, tenant_id, None))
    assert len(statements) == 1
    assert _clarifying_question(db_session, tenant_id, ids[0]) == "I need a little more to go on. What would you like to know about Tremblay IMA?"
