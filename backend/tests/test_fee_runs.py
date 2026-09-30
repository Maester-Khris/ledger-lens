import uuid
from datetime import date, datetime, timezone

import pytest

from app.billing import dao as billing_dao
from app.billing.errors import AlreadyBilled, MissingValuation, NoScheduleAssigned, NothingToBill
from app.billing.fee_math import calculate_household_fee, inputs_from_json
from app.billing.models import FeeCalculation
from app.ledger.dao import get_posting
from app.ledger.types import Direction, PostingSource
from tests.support import build_fee_scenario, make_account

Q3 = {"period_start": date(2026, 7, 1), "period_end": date(2026, 9, 30)}


def _run(db_session, tenant_id, household_id, **period):
    return billing_dao.run_household_fee(db_session, tenant_id=tenant_id, household_id=household_id, **(period or Q3))


def test_fee_run_posts_the_worked_example(db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    result = _run(db_session, tenant_id, scenario.household_id)

    calculation = result.calculation
    assert result.replayed is False
    assert (calculation.schedule_version, calculation.period_fee_minor, calculation.rounding_remainder_minor) == (2, 366_941, 1)

    posting = get_posting(db_session, tenant_id=tenant_id, posting_id=calculation.posting_id)
    first, second = scenario.client_account_ids
    assert posting.source is PostingSource.fee_run
    assert posting.effective_at == datetime(2026, 9, 30, tzinfo=timezone.utc)
    assert {(e.account_id, e.direction, e.amount) for e in posting.entries} == {
        (first, Direction.debit, 275_580),
        (second, Direction.debit, 91_361),
        (scenario.revenue_account_id, Direction.credit, 366_941),
    }


def test_rerunning_the_same_period_replays_without_a_second_calculation(db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    first = _run(db_session, tenant_id, scenario.household_id)
    second = _run(db_session, tenant_id, scenario.household_id)
    assert second.replayed is True and second.calculation.id == first.calculation.id
    count = db_session.query(FeeCalculation).filter(FeeCalculation.household_id == scenario.household_id).count()
    assert count == 1


def test_billing_the_same_period_end_with_different_inputs_is_already_billed(db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    _run(db_session, tenant_id, scenario.household_id)
    with pytest.raises(AlreadyBilled):
        _run(db_session, tenant_id, scenario.household_id, period_start=date(2026, 8, 1), period_end=date(2026, 9, 30))


def test_period_spanning_a_version_change_uses_the_version_on_period_end(db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    result = _run(db_session, tenant_id, scenario.household_id, period_start=date(2026, 6, 1), period_end=date(2026, 7, 31))
    assert result.calculation.schedule_version == 2


def test_stored_inputs_reproduce_the_exact_result(db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    calculation = _run(db_session, tenant_id, scenario.household_id).calculation
    recomputed = calculate_household_fee(inputs_from_json(calculation.inputs))
    assert recomputed.period_fee_minor == calculation.period_fee_minor
    assert {str(k): v for k, v in recomputed.allocations.items()} == calculation.allocations


def test_missing_valuation_is_reported_with_the_account(db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    with pytest.raises(MissingValuation) as exc_info:
        _run(db_session, tenant_id, scenario.household_id, period_start=date(2026, 10, 1), period_end=date(2026, 12, 31))
    assert set(exc_info.value.extensions["account_ids"]) == {str(a) for a in scenario.client_account_ids}


def test_household_without_assignment_has_no_schedule(db_session, tenant_id):
    household = billing_dao.create_household(db_session, tenant_id=tenant_id, name="Unassigned")
    with pytest.raises(NoScheduleAssigned):
        _run(db_session, tenant_id, household.id)


def test_household_with_only_future_links_has_nothing_to_bill(db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    late_household = billing_dao.create_household(db_session, tenant_id=tenant_id, name="Late")
    client = billing_dao.create_client(db_session, tenant_id=tenant_id, household_id=late_household.id, name="Late client")
    account = make_account(db_session, tenant_id)
    billing_dao.link_account(db_session, client_id=client.id, account_id=account.id, linked_on=date(2026, 10, 1))
    billing_dao.assign_schedule(
        db_session, household_id=late_household.id, schedule_id=scenario.schedule_id,
        valid_from=date(2026, 1, 1), valid_until=None,
    )
    with pytest.raises(NothingToBill):
        _run(db_session, tenant_id, late_household.id)


def test_household_with_zero_value_has_nothing_to_bill(db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    empty = billing_dao.create_household(db_session, tenant_id=tenant_id, name="Empty")
    client = billing_dao.create_client(db_session, tenant_id=tenant_id, household_id=empty.id, name="Zero")
    account = make_account(db_session, tenant_id)
    billing_dao.link_account(db_session, client_id=client.id, account_id=account.id, linked_on=date(2026, 1, 1))
    billing_dao.record_valuation(db_session, account_id=account.id, as_of=date(2026, 9, 30), market_value_minor=0, source="t")
    billing_dao.assign_schedule(db_session, household_id=empty.id, schedule_id=scenario.schedule_id, valid_from=date(2026, 1, 1), valid_until=None)
    with pytest.raises(NothingToBill):
        _run(db_session, tenant_id, empty.id)


# --- API -------------------------------------------------------------------------------------

def _post_run(client, household_id, start="2026-07-01", end="2026-09-30"):
    return client.post("/fee-runs", json={"household_id": str(household_id), "period_start": start, "period_end": end})


def test_fee_run_endpoint_creates_then_replays(client, db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    first = _post_run(client, scenario.household_id)
    second = _post_run(client, scenario.household_id)
    assert first.status_code == 201 and second.status_code == 200
    assert second.headers["Idempotent-Replayed"] == "true"
    body = first.json()
    assert (body["period_fee_minor"], body["schedule_version"], body["period_end"]) == (366_941, 2, "2026-09-30")
    fetched = client.get(f"/fee-calculations/{body['id']}")
    assert fetched.status_code == 200 and fetched.json()["posting_id"] == body["posting_id"]


def test_fee_run_endpoint_maps_business_errors(client, db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    assert _post_run(client, uuid.uuid4()).json()["type"] == "/problems/household-not-found"
    missing = _post_run(client, scenario.household_id, start="2026-10-01", end="2026-12-31")
    assert missing.status_code == 422 and missing.json()["type"] == "/problems/missing-valuation"
    backwards = _post_run(client, scenario.household_id, start="2026-09-30", end="2026-07-01")
    assert backwards.status_code == 422 and backwards.json()["type"] == "/problems/request-invalid"


def test_unknown_fee_calculation_is_404(client):
    assert client.get(f"/fee-calculations/{uuid.uuid4()}").status_code == 404