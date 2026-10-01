import uuid
from datetime import date

import pytest

from app import config
from app.assistant import dao as assistant_dao
from app.assistant.contract_tools import contract_tools
from app.assistant.tools import ToolContext, execute
from app.contracts import dao
from app.contracts.models import FieldReview
from app.contracts.types import FieldRouting, ReviewDecision
from app.governance.dao import ModelConfig
from app.retrieval.vector_index import InMemoryVectorIndex
from tests.fakes import RecordingEmbeddings
from tests.support import build_fee_scenario
from tests.test_contracts_compare import _contract
from tests.test_reviews_api import _run

TOOLS = {spec.name: spec for spec in contract_tools()}


@pytest.fixture()
def demo(monkeypatch):
    monkeypatch.setattr(config, "DEMO_MODE", True)


def _guest(client) -> dict[str, str]:
    return {"X-Guest-Id": client.post("/guests").json()["id"]}


def _body(run, field_path, decision):
    return {"run_id": str(run.id), "field_path": field_path, "decision": decision}


def _status(client, headers, document_id, path):
    fields = client.get(f"/documents/{document_id}/terms", headers=headers).json()["extraction"]["fields"]
    return next(f["status"] for f in fields if f["path"] == path)


def test_two_guests_see_their_own_queue_terms_and_timeline(demo, client, db_session, tenant_id):
    version, run = _run(db_session, tenant_id)
    a, b = _guest(client), _guest(client)
    decided = client.post("/reviews", headers=a, json=_body(run, "termination_notice_days", "confirmed"))
    assert decided.status_code == 201 and decided.json()["decided_by"] == "you (demo)"

    assert [r["field_path"] for r in client.get("/reviews", headers=a).json()] == ["fee_method"]
    assert [r["field_path"] for r in client.get("/reviews", headers=b).json()] == ["fee_method", "termination_notice_days"]
    assert _status(client, a, version.document_id, "termination_notice_days") == "confirmed"
    assert _status(client, b, version.document_id, "termination_notice_days") == "needs_review"
    timeline = f"/documents/{version.document_id}/timeline"
    assert "reviewed" in [i["kind"] for i in client.get(timeline, headers=a).json()]
    assert "reviewed" not in [i["kind"] for i in client.get(timeline, headers=b).json()]
    assert db_session.get(FieldReview, (run.id, "termination_notice_days")) is None


def test_a_demo_decision_without_a_known_guest_is_refused(demo, client, db_session, tenant_id):
    _, run = _run(db_session, tenant_id)
    for headers in ({}, {"X-Guest-Id": str(uuid.uuid4())}, {"X-Guest-Id": "not-a-uuid"}):
        response = client.post("/reviews", headers=headers, json=_body(run, "fee_method", "confirmed"))
        assert response.status_code == 400 and response.json()["type"] == "/problems/guest-required"
    assert client.get("/reviews", headers={"X-Guest-Id": str(uuid.uuid4())}).status_code == 200  # reads fall back
    assert db_session.get(FieldReview, (run.id, "fee_method")) is None


def test_turning_demo_mode_off_ignores_the_overlays(client, db_session, tenant_id, monkeypatch):
    version, run = _run(db_session, tenant_id)
    monkeypatch.setattr(config, "DEMO_MODE", True)
    a = _guest(client)
    assert client.post("/reviews", headers=a, json=_body(run, "termination_notice_days", "confirmed")).status_code == 201
    monkeypatch.setattr(config, "DEMO_MODE", False)
    assert [r["field_path"] for r in client.get("/reviews", headers=a).json()] == ["fee_method", "termination_notice_days"]
    assert _status(client, a, version.document_id, "termination_notice_days") == "needs_review"


def test_the_agent_compares_billing_with_the_guests_own_decisions(db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    document_id = _contract(db_session, tenant_id, scenario.household_id, tier_routing=FieldRouting.needs_review)
    a = assistant_dao.register_guest(db_session, tenant_id, None)
    b = assistant_dao.register_guest(db_session, tenant_id, None)
    view = dao.terms_view(db_session, tenant_id, document_id, date.today())
    for field in (f for f in view.fields if f.status == "needs_review"):
        dao.record_review(db_session, tenant_id=tenant_id, run_id=view.run_id, field_path=field.path,
                          decision=ReviewDecision.confirmed, corrected_value=None, reason=None, decided_by="x", overlay_guest=a)

    def compare(guest):
        ctx = ToolContext(session=db_session, tenant_id=tenant_id, session_id="s", turn_id=uuid.uuid4(),
                          embeddings=RecordingEmbeddings(), vector_index=InMemoryVectorIndex(),
                          model=ModelConfig("fake", "scripted", "p", 0), hmac_key=config.PII_HMAC_KEY,
                          vault_key=config.PII_VAULT_KEY, overlay_guest=guest)
        return execute(TOOLS["compare_contract_to_billing"], ctx, {"document_id": str(document_id), "as_of": "2026-09-30"})

    assert compare(a).result_amount_minor == 40_000  # guest A validated the tiers: comparable, 0.05% gap on tier 2
    assert compare(b).system_notice is not None and "fee_tiers" in compare(b).system_notice  # guest B did not
