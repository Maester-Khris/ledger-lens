import uuid
from datetime import datetime, timedelta, timezone

from app.reporting.timeline import TimelineItem, build_timeline, document_timeline
from app.assistant.contract_tools import contract_tools
from tests.support import build_fee_scenario
from tests.test_assistant_contract_tools import _ctx
from tests.test_contracts_compare import _contract
from app.assistant.tools import execute

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


def test_build_timeline_sorts_and_keeps_kinds():
    items = [TimelineItem(T0 + timedelta(minutes=2), "decided", "Approved", {}, {}),
             TimelineItem(T0, "ingested", "Stored", {}, {})]
    assert [i.kind for i in build_timeline(items)] == ["ingested", "decided"]


def test_document_timeline_from_ingestion_to_posting(client, db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    document_id = _contract(db_session, tenant_id, scenario.household_id)
    other = _contract(db_session, tenant_id, None, key="timeline-other")
    compare = {s.name: s for s in contract_tools()}["compare_contract_to_billing"]
    execute(compare, _ctx(db_session, tenant_id), {"document_id": str(document_id), "as_of": "2026-09-30"})
    execute(compare, _ctx(db_session, tenant_id), {"document_id": str(other)})
    db_session.commit()
    invocation_id = client.get("/tool-invocations", params={"pending": True}).json()[0]["id"]
    assert client.post(f"/tool-invocations/{invocation_id}/decision", json={"decision": "approved"}).status_code == 201
    items = client.get(f"/documents/{document_id}/timeline").json()
    kinds = [i["kind"] for i in items]
    assert kinds.index("ingested") < kinds.index("extracted") < kinds.index("ai_proposed") < kinds.index("decided") < kinds.index("posted")
    posted = next(i for i in items if i["kind"] == "posted")
    assert {e["direction"] for e in posted["detail"]["entries"]} == {"debit", "credit"}
    assert all(i["detail"].get("document_id") in (None, str(document_id)) for i in items)


def test_rejected_proposal_is_decided_without_a_posting(client, db_session, tenant_id):
    # Review Focus 4
    scenario = build_fee_scenario(db_session, tenant_id)
    document_id = _contract(db_session, tenant_id, scenario.household_id, key="timeline-rejected")
    compare = {s.name: s for s in contract_tools()}["compare_contract_to_billing"]
    execute(compare, _ctx(db_session, tenant_id), {"document_id": str(document_id), "as_of": "2026-09-30"})
    db_session.commit()
    invocation_id = client.get("/tool-invocations", params={"pending": True}).json()[0]["id"]
    client.post(f"/tool-invocations/{invocation_id}/decision", json={"decision": "rejected", "reason": "not now"})
    kinds = [i["kind"] for i in client.get(f"/documents/{document_id}/timeline").json()]
    assert "decided" in kinds and "posted" not in kinds


def test_unknown_document_is_404(client):
    assert client.get(f"/documents/{uuid.uuid4()}/timeline").status_code == 404


def test_field_lookups_stay_in_the_audit_trail_not_the_timeline(client, db_session, tenant_id):
    document_id = _contract(db_session, tenant_id, None, key="timeline-read-only")
    fields = {s.name: s for s in contract_tools()}["get_contract_fields"]
    execute(fields, _ctx(db_session, tenant_id), {"document_id": str(document_id)})
    db_session.commit()
    kinds = [i["kind"] for i in client.get(f"/documents/{document_id}/timeline").json()]
    assert "ai_proposed" not in kinds and "extracted" in kinds
