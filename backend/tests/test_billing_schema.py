
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.billing import dao as billing_dao
from app.billing.fee_math import Tier
from app.billing.types import FeeMethod
from tests.support import build_fee_scenario, make_account

ONE_TIER = (Tier(None, Decimal("100")),)


def test_scenario_builds_with_adjacent_non_overlapping_versions(db_session, tenant_id):
    build_fee_scenario(db_session, tenant_id)


def test_overlapping_schedule_versions_are_rejected(db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    with pytest.raises(IntegrityError) as exc_info:
        billing_dao.add_schedule_version(
            db_session, schedule_id=scenario.schedule_id, version=3, method=FeeMethod.cliff,
            valid_from=date(2026, 6, 15), valid_until=date(2026, 12, 31), tiers=ONE_TIER,
        )
    assert exc_info.value.orig.sqlstate == "23P01"  # exclusion_violation


def test_overlapping_household_assignments_are_rejected(db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    with pytest.raises(IntegrityError) as exc_info:
        billing_dao.assign_schedule(
            db_session, household_id=scenario.household_id, schedule_id=scenario.schedule_id,
            valid_from=date(2026, 3, 1), valid_until=None,
        )
    assert exc_info.value.orig.sqlstate == "23P01"


def test_invalid_tier_table_never_reaches_the_database(db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    with pytest.raises(ValueError):
        billing_dao.add_schedule_version(
            db_session, schedule_id=scenario.schedule_id, version=3, method=FeeMethod.graduated,
            valid_from=date(2030, 1, 1), valid_until=None,
            tiers=(Tier(200, Decimal("1")), Tier(100, Decimal("1")), Tier(None, Decimal("1"))),
        )


def test_negative_and_duplicate_valuations_are_rejected(db_session, tenant_id):
    account = make_account(db_session, tenant_id)
    with pytest.raises(IntegrityError) as negative:
        billing_dao.record_valuation(db_session, account_id=account.id, as_of=date(2026, 9, 30), market_value_minor=-1, source="t")
    assert negative.value.orig.sqlstate == "23514"
    db_session.rollback()
    billing_dao.record_valuation(db_session, account_id=account.id, as_of=date(2026, 9, 30), market_value_minor=1, source="t")
    with pytest.raises(IntegrityError) as duplicate:
        billing_dao.record_valuation(db_session, account_id=account.id, as_of=date(2026, 9, 30), market_value_minor=2, source="t")
    assert duplicate.value.orig.sqlstate == "23505"


def test_schedule_versions_are_append_only(db_session, owner_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    statement = text("UPDATE fee_schedule_versions SET method = 'cliff' WHERE schedule_id = :id")
    with pytest.raises(ProgrammingError):
        db_session.execute(statement, {"id": scenario.schedule_id})
    with pytest.raises(IntegrityError) as exc_info:
        owner_session.execute(statement, {"id": scenario.schedule_id})
    assert exc_info.value.orig.sqlstate == "23001"
