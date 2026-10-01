from datetime import date

import pytest

from app.assistant import dao as assistant_dao
from app.contracts import dao
from app.contracts.errors import FieldAlreadyReviewed
from app.contracts.models import FieldReview
from app.contracts.types import ReviewDecision
from app.demo import GUEST_DECIDED_BY
from tests.test_reviews_api import _run


def _guest(db_session, tenant_id):
    return assistant_dao.register_guest(db_session, tenant_id, None)


def _review(db_session, tenant_id, run, field_path, decision, *, guest=None, corrected_value=None):
    return dao.record_review(
        db_session, tenant_id=tenant_id, run_id=run.id, field_path=field_path, decision=decision,
        corrected_value=corrected_value, reason=None, decided_by="demo_user", overlay_guest=guest,
    )


def _statuses(db_session, tenant_id, document_id, guest):
    view = dao.terms_view(db_session, tenant_id, document_id, date.today(), overlay_guest=guest)
    return {f.path: f.status for f in view.fields}


def test_two_guests_with_opposite_decisions_are_served_different_terms(db_session, tenant_id):
    version, run = _run(db_session, tenant_id)
    a, b = _guest(db_session, tenant_id), _guest(db_session, tenant_id)
    _review(db_session, tenant_id, run, "termination_notice_days", ReviewDecision.confirmed, guest=a)
    _review(db_session, tenant_id, run, "termination_notice_days", ReviewDecision.rejected, guest=b)
    _review(db_session, tenant_id, run, "fee_method", ReviewDecision.corrected, guest=a, corrected_value="graduated")

    served_a = dao.served_fields(db_session, tenant_id, version.document_id, overlay_guest=a)
    served_b = dao.served_fields(db_session, tenant_id, version.document_id, overlay_guest=b)
    assert served_a.fields["termination_notice_days"].value == 30
    assert served_a.fields["fee_method"].value == "graduated"
    assert "termination_notice_days" not in served_b.fields and "termination_notice_days" in served_b.unserved
    assert _statuses(db_session, tenant_id, version.document_id, a)["termination_notice_days"] == "confirmed"
    assert _statuses(db_session, tenant_id, version.document_id, b)["termination_notice_days"] == "rejected"


def test_a_guest_decision_is_invisible_without_the_guest_and_to_other_guests(db_session, tenant_id):
    version, run = _run(db_session, tenant_id)
    a, b = _guest(db_session, tenant_id), _guest(db_session, tenant_id)
    _review(db_session, tenant_id, run, "termination_notice_days", ReviewDecision.confirmed, guest=a)

    for viewer in (None, b):
        assert "termination_notice_days" not in dao.served_fields(db_session, tenant_id, version.document_id, overlay_guest=viewer).fields
        assert [p.field_path for p in dao.pending_reviews(db_session, tenant_id, overlay_guest=viewer)] == ["fee_method", "termination_notice_days"]
        assert [r for _, reviews in dao.runs_with_reviews(db_session, version.document_id, overlay_guest=viewer) for r in reviews] == []
    assert [p.field_path for p in dao.pending_reviews(db_session, tenant_id, overlay_guest=a)] == ["fee_method"]
    reviews_a = [r for _, reviews in dao.runs_with_reviews(db_session, version.document_id, overlay_guest=a) for r in reviews]
    assert [(r.field_path, r.decided_by) for r in reviews_a] == [("termination_notice_days", GUEST_DECIDED_BY)]
    assert db_session.get(FieldReview, (run.id, "termination_notice_days")) is None  # nothing reached the shared table


def test_guest_decisions_are_final(db_session, tenant_id):
    _, run = _run(db_session, tenant_id)
    a = _guest(db_session, tenant_id)
    _review(db_session, tenant_id, run, "fee_method", ReviewDecision.rejected, guest=a)
    with pytest.raises(FieldAlreadyReviewed):
        _review(db_session, tenant_id, run, "fee_method", ReviewDecision.confirmed, guest=a)


def test_a_guest_cannot_decide_a_field_that_has_a_real_review(db_session, tenant_id):
    version, run = _run(db_session, tenant_id)
    _review(db_session, tenant_id, run, "fee_method", ReviewDecision.corrected, corrected_value="graduated")  # real
    a = _guest(db_session, tenant_id)
    with pytest.raises(FieldAlreadyReviewed):
        _review(db_session, tenant_id, run, "fee_method", ReviewDecision.rejected, guest=a)
    assert dao.served_fields(db_session, tenant_id, version.document_id, overlay_guest=a).fields["fee_method"].value == "graduated"
