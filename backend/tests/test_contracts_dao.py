import uuid
from decimal import Decimal

from app.contracts import dao
from app.contracts.fields import FieldResult
from app.contracts.models import FieldReview
from app.contracts.types import FieldRouting, ReviewDecision
from tests.test_retrieval_index import parsed_version

CONFIG = dao.RunConfig("contract-terms-v1", "scripted", "p", Decimal(0), "c" * 64, "d" * 64)


def _field(path, value, routing):
    return FieldResult(path, value, [], "q", routing is FieldRouting.accepted, [], "GOOD", routing)


def _run(db_session, version, *results):
    run = dao.save_run(db_session, version.id, CONFIG, {"raw": True}, results)
    db_session.commit()
    return run


def test_only_accepted_or_reviewed_fields_are_served(db_session, tenant_id):
    version = parsed_version(db_session, tenant_id)
    run = _run(db_session, version, _field("currency", "CAD", FieldRouting.accepted),
               _field("fee_method", "cliff", FieldRouting.needs_review),
               _field("termination_notice_days", 30, FieldRouting.needs_review),
               _field("adviser", "X", FieldRouting.accepted))
    db_session.add_all([
        FieldReview(run_id=run.id, field_path="fee_method", decision=ReviewDecision.corrected,
                    corrected_value="graduated", decided_by="test", reason="table says next"),
        FieldReview(run_id=run.id, field_path="adviser", decision=ReviewDecision.rejected, decided_by="test"),
    ])
    db_session.commit()
    served = dao.served_fields(db_session, tenant_id, version.document_id)
    assert {path: f.value for path, f in served.fields.items()} == {"currency": "CAD", "fee_method": "graduated"}
    assert sorted(served.unserved) == ["adviser", "termination_notice_days"]


def test_latest_run_wins(db_session, tenant_id):
    version = parsed_version(db_session, tenant_id)
    _run(db_session, version, _field("currency", "USD", FieldRouting.accepted))
    _run(db_session, version, _field("currency", "CAD", FieldRouting.accepted))
    assert dao.served_fields(db_session, tenant_id, version.document_id).fields["currency"].value == "CAD"


def test_never_extracted_is_none(db_session, tenant_id):
    version = parsed_version(db_session, tenant_id)
    assert dao.served_fields(db_session, tenant_id, version.document_id) is None
    assert dao.served_fields(db_session, uuid.uuid4(), version.document_id) is None  # other tenant sees nothing
