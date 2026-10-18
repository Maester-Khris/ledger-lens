import uuid
from decimal import Decimal

from app.contracts import dao
from app.contracts.fields import FieldResult
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.models import FieldReview, FieldVerification
from app.contracts.types import FieldRouting, ReviewDecision
from tests.support import verify_all
from tests.test_retrieval_index import parsed_version

CONFIG = dao.RunConfig("contract-terms-v1", "scripted", "p", Decimal(0), "c" * 64, "d" * 64)


def _field(path, value, routing):
    return FieldResult(path, value, [], "q", routing is FieldRouting.accepted, [], "GOOD", routing)


def _run(db_session, version, *results):
    run = dao.save_run(db_session, version.id, CONFIG, {"raw": True}, results)
    verify_all(db_session, run.id)
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


def _check(run, path, layer, outcome, crop_kind="element", verifier="v"):
    return dao.VerificationRow(run.id, path, layer, verifier, crop_kind, None, outcome)


def _unverified_run(db_session, version, *results):
    run = dao.save_run(db_session, version.id, CONFIG, {"raw": True}, results)
    db_session.commit()
    return run


def test_class_a_is_held_until_verified(db_session, tenant_id):
    version = parsed_version(db_session, tenant_id)
    run = _unverified_run(db_session, version, _field("currency", "CAD", FieldRouting.accepted),
                          _field("adviser", "X", FieldRouting.accepted))
    served = dao.served_fields(db_session, tenant_id, version.document_id)
    assert set(served.fields) == {"adviser"} and served.unserved == ["currency"]
    dao.save_verification(db_session, _check(run, "currency", "vision", "agree"))
    db_session.commit()
    assert set(dao.served_fields(db_session, tenant_id, version.document_id).fields) == {"adviser", "currency"}


def test_save_verification_is_idempotent(db_session, tenant_id):
    version = parsed_version(db_session, tenant_id)
    run = _unverified_run(db_session, version, _field("currency", "CAD", FieldRouting.accepted))
    dao.save_verification(db_session, _check(run, "currency", "vision", "agree"))
    dao.save_verification(db_session, _check(run, "currency", "vision", "disagree"))  # a re-run keeps the first result
    db_session.commit()
    rows = db_session.query(FieldVerification).filter_by(run_id=run.id).all()
    assert [r.outcome for r in rows] == ["agree"]


def test_field_verifications_are_append_only(db_session, tenant_id):
    version = parsed_version(db_session, tenant_id)
    run = _unverified_run(db_session, version, _field("currency", "CAD", FieldRouting.accepted))
    dao.save_verification(db_session, _check(run, "currency", "vision", "agree"))
    db_session.commit()
    with pytest.raises(DBAPIError):
        db_session.execute(text("UPDATE field_verifications SET outcome = 'disagree' WHERE run_id = :r"), {"r": run.id})
    db_session.rollback()


def test_element_crop_outranks_the_page_fallback(db_session, tenant_id):
    version = parsed_version(db_session, tenant_id)
    run = _unverified_run(db_session, version, _field("currency", "CAD", FieldRouting.accepted))
    dao.save_verification(db_session, _check(run, "currency", "vision", "disagree", crop_kind="element"))
    dao.save_verification(db_session, _check(run, "currency", "vision", "agree", crop_kind="page"))
    db_session.commit()
    assert dao.verification_outcomes(db_session, run.id) == {"currency": {"vision": "disagree"}}


def test_queue_holds_flagged_fields_but_not_those_awaiting_verification(db_session, tenant_id):
    version = parsed_version(db_session, tenant_id)
    run = _unverified_run(db_session, version, _field("currency", "CAD", FieldRouting.accepted),
                          _field("fee_method", "graduated", FieldRouting.accepted),
                          _field("adviser", "X", FieldRouting.accepted))
    dao.save_verification(db_session, _check(run, "fee_method", "vision", "disagree"))
    dao.save_verification(db_session, _check(run, "adviser", "ocr_local", "unreadable"))
    db_session.commit()
    paths = [p.field_path for p in dao.pending_reviews(db_session, tenant_id) if p.run_id == run.id]
    assert paths == ["adviser", "fee_method"]  # currency only awaits the stage
