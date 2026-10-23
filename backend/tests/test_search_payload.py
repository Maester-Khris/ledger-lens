import json
import uuid

from app import config
from app.assistant.tools import SearchArgs, ToolContext, default_tools
from app.governance.dao import ModelConfig
from app.retrieval.index import index_version
from app.retrieval.vector_index import InMemoryVectorIndex
from tests.fakes import RecordingEmbeddings
from tests.test_retrieval_index import parsed_version

SEARCH = next(spec for spec in default_tools() if spec.name == "search_contracts")


def _search(db_session, tenant_id, embeddings, index, query):
    ctx = ToolContext(session=db_session, tenant_id=tenant_id, session_id="t1", turn_id=uuid.uuid4(), embeddings=embeddings,
                      vector_index=index, model=ModelConfig("fake", "scripted", "p", 0), hmac_key=config.PII_HMAC_KEY,
                      vault_key=config.PII_VAULT_KEY)
    return SEARCH.run(ctx, SearchArgs(query=query))


def _indexed(db_session, tenant_id, keys, texts):
    embeddings, index = RecordingEmbeddings(), InMemoryVectorIndex()
    for key in keys:
        version = parsed_version(db_session, tenant_id, key=key, texts=texts)
        index_version(db_session, version.id, embeddings=embeddings, vector_index=index)
    return embeddings, index


def test_hits_in_one_section_share_one_section_entry(db_session, tenant_id):
    embeddings, index = _indexed(db_session, tenant_id, ["t1-one"], ("Fees are billed quarterly.", "The annual rate is 0.85%."))
    outcome = _search(db_session, tenant_id, embeddings, index, "fees rate")
    payload = json.loads(outcome.content)
    assert len(payload["hits"]) == 2 and list(payload["sections"]) == ["S1"]
    assert {hit["section"] for hit in payload["hits"]} == {"S1"}
    assert payload["sections"]["S1"]["section"] == "3. Fees" and payload["sections"]["S1"]["document"] == "Tremblay IMA"
    assert "quarterly" in payload["sections"]["S1"]["text"] and "0.85%" in payload["sections"]["S1"]["text"]
    assert set(outcome.sources) == {hit["id"] for hit in payload["hits"]}  # hit ids stay the citable ids


def test_same_named_sections_of_two_documents_are_two_entries(db_session, tenant_id):
    embeddings, index = _indexed(db_session, tenant_id, ["t1-a", "t1-b"], ("Fees are billed quarterly.",))
    payload = json.loads(_search(db_session, tenant_id, embeddings, index, "fees billed quarterly").content)
    assert len(payload["hits"]) == 2 and sorted(payload["sections"]) == ["S1", "S2"]
