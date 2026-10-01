from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.assistant import dao as assistant_dao
from app.assistant.models import Guest
from app.contracts import dao as contracts_dao
from app.contracts.models import GuestFieldReview
from app.contracts.types import ReviewDecision
from app.governance.dao import decide
from app.governance.models import GuestToolDecision
from app.governance.types import ToolDecision
from tests.test_governance import accounts  # noqa: F401  (accounts is a fixture)
from tests.test_guest_decisions import _propose
from tests.test_reviews_api import _run


def _decide_everything(db_session, tenant_id, accounts, run, guest):
    contracts_dao.record_review(db_session, tenant_id=tenant_id, run_id=run.id, field_path="fee_method",
                                decision=ReviewDecision.rejected, corrected_value=None, reason=None,
                                decided_by="x", overlay_guest=guest)
    invocation = _propose(db_session, tenant_id, accounts, guest)
    decide(db_session, tenant_id=tenant_id, invocation_id=invocation.id, decision=ToolDecision.rejected,
           decided_by="x", reason=None, overlay_guest=guest)


def test_a_new_guest_purges_the_overlays_of_guests_idle_for_24_hours(client, db_session, tenant_id, accounts):
    _, run = _run(db_session, tenant_id)
    idle = assistant_dao.register_guest(db_session, tenant_id, None)
    active = assistant_dao.register_guest(db_session, tenant_id, None)
    _decide_everything(db_session, tenant_id, accounts, run, idle)
    _decide_everything(db_session, tenant_id, accounts, run, active)
    now = datetime.now(timezone.utc)
    db_session.execute(update(Guest).where(Guest.id == idle).values(last_seen_at=now - timedelta(hours=25)))
    db_session.execute(update(Guest).where(Guest.id == active).values(last_seen_at=now - timedelta(hours=1)))
    db_session.commit()

    assert client.post("/guests").status_code == 201

    reviewers = set(db_session.scalars(select(GuestFieldReview.guest_id).where(GuestFieldReview.run_id == run.id)))
    deciders = set(db_session.scalars(select(GuestToolDecision.guest_id).where(GuestToolDecision.guest_id.in_([idle, active]))))
    assert reviewers == {active} and deciders == {active}
    assert db_session.get(Guest, idle) is not None  # the guest row stays: chat turns reference it


def test_a_guest_returning_after_24_hours_starts_from_the_shared_data(client, db_session, tenant_id, accounts):
    _, run = _run(db_session, tenant_id)
    returning = assistant_dao.register_guest(db_session, tenant_id, None)
    _decide_everything(db_session, tenant_id, accounts, run, returning)
    db_session.execute(update(Guest).where(Guest.id == returning).values(
        last_seen_at=datetime.now(timezone.utc) - timedelta(hours=25)))
    db_session.commit()

    response = client.post("/guests", headers={"X-Guest-Id": str(returning)})
    assert response.status_code == 201 and response.json()["id"] == str(returning)  # same guest, kept
    assert db_session.scalars(select(GuestFieldReview).where(GuestFieldReview.guest_id == returning)).first() is None
    assert db_session.scalars(select(GuestToolDecision).where(GuestToolDecision.guest_id == returning)).first() is None
