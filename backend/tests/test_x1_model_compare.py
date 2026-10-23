"""X1 extraction-model comparison (spec section 12): candidate extractors run the production prompt and schema on the
labelled documents; their outputs go to a report file, never to extraction_runs; accuracy is scored on the same labels
as the current extractor, with a fee table compared as one unit."""
import uuid

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from sqlalchemy import func, select

from app.contracts import dao
from app.contracts.fields import FieldResult
from app.contracts.models import ExtractedField, ExtractionRun, FieldLabel
from app.contracts.types import FieldRouting
from scripts.x1_model_compare import (baseline_outputs, labelled_version_ids, load_labels, run_candidate, score,
                                      usd)
from tests.fakes import ScriptedChatModel
from tests.test_contracts_dao import CONFIG
from tests.test_contracts_fields import _terms
from tests.test_retrieval_index import parsed_version

BANDS = [{"band_text": "On the first $1,000,000", "rate_text": "1.00%"},
         {"band_text": "On the next $1,500,000", "rate_text": "0.85%"},
         {"band_text": "On assets in excess of $2,500,000", "rate_text": "0.65%"}]


class Metered(ScriptedChatModel):
    """Returns the same terms for every document, with token usage, like a real provider through LangChain."""

    def with_structured_output(self, schema, include_raw=False, **kwargs):
        terms = _terms()
        usage = {"input_tokens": 3000, "output_tokens": 700, "total_tokens": 3700}
        return RunnableLambda(lambda _m: {"raw": AIMessage(content="", usage_metadata=usage), "parsed": terms,
                                          "parsing_error": None})


class Broken(ScriptedChatModel):
    def with_structured_output(self, schema, include_raw=False, **kwargs):
        def fail(_m):
            raise TimeoutError("provider timed out")
        return RunnableLambda(fail)


def _labelled_version(db_session, tenant_id, labels: dict):
    version = parsed_version(db_session, tenant_id)
    run = dao.save_run(db_session, version.id, CONFIG, {}, [
        FieldResult("currency", "USD", [], "q", True, [], "GOOD", FieldRouting.accepted),
        FieldResult("fee_method", "graduated", [], "q", True, [], "GOOD", FieldRouting.accepted)])
    for path, value in labels.items():
        db_session.add(FieldLabel(run_id=run.id, field_path=path, labeller="adjudicated", label_value=value, blind=True))
    db_session.commit()
    return version, run


def test_candidate_outputs_never_touch_extraction_runs(db_session, tenant_id):
    version, _run = _labelled_version(db_session, tenant_id, {"currency": "CAD"})
    runs_before = db_session.scalar(select(func.count()).select_from(ExtractionRun))
    fields_before = db_session.scalar(select(func.count()).select_from(ExtractedField))
    outputs = run_candidate(db_session, chat_model=Metered(), version_ids=[version.id], concurrency=2)
    assert db_session.scalar(select(func.count()).select_from(ExtractionRun)) == runs_before
    assert db_session.scalar(select(func.count()).select_from(ExtractedField)) == fields_before
    [doc] = outputs
    assert doc["version_id"] == str(version.id) and doc["error"] is None
    assert (doc["input_tokens"], doc["output_tokens"]) == (3000, 700)
    by_path = {f["field_path"]: f for f in doc["fields"]}
    assert by_path["currency"]["value"] == "CAD"
    assert by_path["fee_tiers[1]"]["value"]["rate_text"] == "0.85%"
    assert {f["routing"] for f in doc["fields"]} <= {"accepted", "needs_review"}


def test_a_failed_document_is_recorded_not_raised(db_session, tenant_id):
    version, _run = _labelled_version(db_session, tenant_id, {"currency": "CAD"})
    [doc] = run_candidate(db_session, chat_model=Broken(), version_ids=[version.id], concurrency=1)
    assert doc["fields"] == [] and "timed out" in doc["error"]


def test_labels_are_joined_on_version_and_field(db_session, tenant_id):
    version, run = _labelled_version(db_session, tenant_id, {"currency": "CAD", "fee_tiers": BANDS})
    labels = [l for l in load_labels(db_session) if l[0] == version.id]
    assert sorted((p, c) for _v, p, c, _value in labels) == [("currency", "A"), ("fee_tiers", "A")]
    assert version.id in labelled_version_ids(db_session)


def test_score_compares_fee_tables_as_one_unit_and_counts_misses():
    v1, v2 = uuid.uuid4(), uuid.uuid4()
    labels = [(v1, "currency", "A", "CAD"), (v1, "fee_tiers", "A", BANDS), (v1, "adviser", "B", "Maple Ridge"),
              (v2, "currency", "A", "USD")]
    outputs = [
        {"version_id": str(v1), "error": None, "fields": [
            {"field_path": "currency", "value": "CAD", "routing": "accepted"},
            {"field_path": "fee_tiers[1]", "value": {**BANDS[1], "up_to_minor": 1, "rate_bps": "85"}, "routing": "accepted"},
            {"field_path": "fee_tiers[0]", "value": {**BANDS[0], "up_to_minor": 1, "rate_bps": "100"}, "routing": "accepted"},
            {"field_path": "fee_tiers[2]", "value": {**BANDS[2], "up_to_minor": None, "rate_bps": "65"}, "routing": "needs_review"},
            {"field_path": "adviser", "value": "Birch Hill", "routing": "accepted"}]},
        {"version_id": str(v2), "error": "provider timed out", "fields": []},  # a failed document scores as wrong
    ]
    result = score(outputs, labels)
    assert result["by_class"]["A"] == {"n": 3, "correct": 2, "accuracy": pytest.approx(2 / 3)}
    assert result["by_class"]["B"] == {"n": 1, "correct": 0, "accuracy": 0.0}
    assert result["review_rate"] == pytest.approx(1 / 5)  # fields routed to review over fields produced
    assert result["failed_documents"] == 1


def test_baseline_scores_the_current_extractor_from_its_runs(db_session, tenant_id):
    version, _run = _labelled_version(db_session, tenant_id, {"currency": "USD"})
    [doc] = baseline_outputs(db_session, [version.id])
    assert {f["field_path"]: f["value"] for f in doc["fields"]}["currency"] == "USD"
    assert score([doc], [(version.id, "currency", "A", "USD")])["by_class"]["A"]["correct"] == 1


def test_usd_uses_list_prices_per_million_tokens():
    assert usd(3000, 700, (0.40, 1.60)) == pytest.approx(0.00232)


def test_outputs_are_revealed_before_scoring(db_session, tenant_id):
    # The model reads redacted text, so personal names come back as tokens; labels are raw text.
    from app import config
    from app.documents import dao as documents_dao
    from app.documents.redact import make_token
    from tests.test_contracts_fields import _text

    token = make_token(tenant_id, "PERSON", "Fred Alger", config.PII_HMAC_KEY)
    documents_dao.save_tokens(db_session, tenant_id, {token: ("PERSON", "Fred Alger")}, config.PII_VAULT_KEY)
    version, run = _labelled_version(db_session, tenant_id, {"adviser": "Fred Alger Management, LLC"})

    class Tokenised(ScriptedChatModel):
        def with_structured_output(self, schema, include_raw=False, **kwargs):
            terms = _terms(adviser=_text(f"{token} Management, LLC", "q"))
            return RunnableLambda(lambda _m: {"raw": AIMessage(content=""), "parsed": terms, "parsing_error": None})

    [doc] = run_candidate(db_session, chat_model=Tokenised(), version_ids=[version.id], concurrency=1)
    assert {f["field_path"]: f["value"] for f in doc["fields"]}["adviser"] == "Fred Alger Management, LLC"
    labels = [l for l in load_labels(db_session) if l[0] == version.id]
    assert score([doc], labels)["by_class"]["B"]["correct"] == 1
