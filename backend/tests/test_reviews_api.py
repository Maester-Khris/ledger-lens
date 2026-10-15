import uuid
from decimal import Decimal

from sqlalchemy import select

from app.contracts import dao
from app.contracts.fields import FieldResult
from app.contracts.types import FieldRouting
from app.documents.models import DocumentElement
from tests.test_retrieval_index import parsed_version

CONFIG = dao.RunConfig("contract-terms-v1", "scripted", "p", Decimal(0), "c" * 64, "d" * 64)


def _run(db_session, tenant_id):
    version = parsed_version(db_session, tenant_id)
    element_ids = list(db_session.scalars(select(DocumentElement.id).where(DocumentElement.version_id == version.id)))
    run = dao.save_run(db_session, version.id, CONFIG, {"raw": True}, [
        FieldResult("currency", "CAD", [], "q", True, [], "GOOD", FieldRouting.accepted),
        FieldResult("fee_method", "cliff", element_ids[:1], "on the entire", False, [], "FAIR", FieldRouting.needs_review),
        FieldResult("termination_notice_days", 30, [], "thirty days", False, ["not a number"], "GOOD", FieldRouting.needs_review),
    ])
    db_session.commit()
    return version, run


def _decide(client, run, field_path, decision, **extra):
    return client.post("/reviews", json={"run_id": str(run.id), "field_path": field_path, "decision": decision, **extra})


def test_queue_lists_only_unreviewed_needs_review_fields(client, db_session, tenant_id):
    version, _ = _run(db_session, tenant_id)
    rows = client.get("/reviews").json()
    assert [r["field_path"] for r in rows] == ["fee_method", "termination_notice_days"]
    first = rows[0]
    assert first["document_id"] == str(version.document_id) and first["document_title"] == "Tremblay IMA"
    assert (first["version"], first["page"], first["page_grade"], first["value"]) == (1, 1, "FAIR", "cliff")
    assert rows[1]["page"] is None and rows[1]["validator_errors"] == ["not a number"]


def test_confirming_serves_the_field_and_leaves_the_queue(client, db_session, tenant_id):
    version, run = _run(db_session, tenant_id)
    response = _decide(client, run, "termination_notice_days", "confirmed")
    assert response.status_code == 201 and response.json()["decided_by"] == "demo_user"
    assert [r["field_path"] for r in client.get("/reviews").json()] == ["fee_method"]
    assert dao.served_fields(db_session, tenant_id, version.document_id).fields["termination_notice_days"].value == 30


def test_correction_requires_a_value_and_serves_it(client, db_session, tenant_id):
    version, run = _run(db_session, tenant_id)
    missing = _decide(client, run, "fee_method", "corrected")
    assert missing.status_code == 422 and missing.json()["type"] == "/problems/review-invalid"
    stray = _decide(client, run, "fee_method", "confirmed", corrected_value="graduated")
    assert stray.status_code == 422
    corrected = _decide(client, run, "fee_method", "corrected", corrected_value="graduated", reason="table says next")
    assert corrected.status_code == 201 and corrected.json()["corrected_value"] == "graduated"
    assert dao.served_fields(db_session, tenant_id, version.document_id).fields["fee_method"].value == "graduated"


def test_a_second_decision_is_a_conflict(client, db_session, tenant_id):
    _, run = _run(db_session, tenant_id)
    assert _decide(client, run, "fee_method", "rejected").status_code == 201
    again = _decide(client, run, "fee_method", "confirmed")
    assert again.status_code == 409 and again.json()["type"] == "/problems/field-already-reviewed"


def test_unknown_field_or_run_is_not_found(client, db_session, tenant_id):
    _, run = _run(db_session, tenant_id)
    assert _decide(client, run, "nope", "confirmed").status_code == 404
    unknown = client.post("/reviews", json={"run_id": str(uuid.uuid4()), "field_path": "fee_method", "decision": "confirmed"})
    assert unknown.status_code == 404 and unknown.json()["type"] == "/problems/field-not-found"
