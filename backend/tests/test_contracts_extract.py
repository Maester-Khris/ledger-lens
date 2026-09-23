import pytest

from app.contracts import dao as contracts_dao
from app.contracts.extract import ExtractionFailed, config_hash, render_input, run_extraction
from app.documents import dao as documents_dao
from app.documents.types import VersionStage
from tests.fakes import ScriptedChatModel
from tests.test_contracts_fields import _terms
from tests.test_retrieval_index import parsed_version


def test_render_input_tags_elements_with_ids_pages_and_sections(db_session, tenant_id):
    version = parsed_version(db_session, tenant_id, texts=("Fees are billed quarterly.",))
    rendered = render_input(documents_dao.list_elements(db_session, version.id))
    assert rendered.startswith("<document>\n")
    assert '<element id="E1" page="1" section="3. Fees">Fees are billed quarterly.</element>' in rendered


def test_config_hash_changes_with_model():
    assert config_hash("m1", "docling 2") != config_hash("m2", "docling 2")
    assert len(config_hash("m1", "docling 2")) == 64


def test_stage_saves_a_run_and_extracted_event(db_session, tenant_id):
    version = parsed_version(db_session, tenant_id)
    model = ScriptedChatModel(replies=[_terms()])
    run_extraction(db_session, version.id, chat_model=model, model_id="scripted")
    events = documents_dao.version_events(db_session, version.id)
    assert events[-1].stage is VersionStage.extracted
    assert events[-1].detail["needs_review"] >= 1  # the fake terms cite E1..E4, which this version doesn't have
    served = contracts_dao.served_fields(db_session, tenant_id, version.document_id)
    assert served is not None and "fee_tiers[0]" in served.unserved


def test_two_schema_failures_raise(db_session, tenant_id):
    version = parsed_version(db_session, tenant_id)

    class Failing(ScriptedChatModel):
        def with_structured_output(self, schema, include_raw=False, **kwargs):
            from langchain_core.runnables import RunnableLambda
            return RunnableLambda(lambda _m: {"raw": None, "parsed": None, "parsing_error": "missing field currency"})

    with pytest.raises(ExtractionFailed, match="currency"):
        run_extraction(db_session, version.id, chat_model=Failing(), model_id="scripted")
