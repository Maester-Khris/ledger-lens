from app.ledger.models import Account
import dataclasses
from datetime import datetime, time, timezone
from decimal import Decimal

from sqlalchemy import select, func

from app.billing.errors import (
    AlreadyBilled,
    FeeCalculationNotFound,
    HouseholdNotFound,
    MissingValuation,
    NoScheduleAssigned,
    NothingToBill,
)
from app.billing.fee_math import AccountValue, FeeInputs, FeeResult, calculate_household_fee, inputs_to_json
from app.billing.models import FeeCalculation
from app.ledger.dao import EntryInput, PostingRequest, create_posting, ledger_transaction
from app.ledger.errors import IdempotencyKeyReused
from app.ledger.types import Direction, PostingSource
import uuid
from collections.abc import Sequence
from datetime import date

from sqlalchemy.orm import Session

from app.billing.fee_math import Tier, validate_tiers
from app.billing.models import (
    AccountValuation,
    Client,
    ClientAccount,
    FeeSchedule,
    FeeScheduleTier,
    FeeScheduleVersion,
    Household,
    HouseholdFeeAssignment,
)
from app.billing.types import FeeMethod
from app.ranges import date_range


def _add(session: Session, row):
    session.add(row)
    session.commit()
    return row


def create_household(session: Session, *, tenant_id: uuid.UUID, name: str) -> Household:
    return _add(session, Household(tenant_id=tenant_id, name=name))


def create_client(session: Session, *, tenant_id: uuid.UUID, household_id: uuid.UUID, name: str) -> Client:
    return _add(session, Client(tenant_id=tenant_id, household_id=household_id, name=name))


def link_account(session: Session, *, client_id: uuid.UUID, account_id: uuid.UUID, linked_on: date) -> ClientAccount:
    return _add(session, ClientAccount(client_id=client_id, account_id=account_id, linked_on=linked_on))


def record_valuation(
    session: Session, *, account_id: uuid.UUID, as_of: date, market_value_minor: int, source: str
) -> AccountValuation:
    return _add(
        session,
        AccountValuation(account_id=account_id, as_of=as_of, market_value_minor=market_value_minor, source=source),
    )


def create_fee_schedule(
    session: Session, *, tenant_id: uuid.UUID, name: str, revenue_account_id: uuid.UUID
) -> FeeSchedule:
    return _add(session, FeeSchedule(tenant_id=tenant_id, name=name, revenue_account_id=revenue_account_id))


def add_schedule_version(
    session: Session,
    *,
    schedule_id: uuid.UUID,
    version: int,
    method: FeeMethod,
    valid_from: date,
    valid_until: date | None,
    tiers: Sequence[Tier],
) -> FeeScheduleVersion:
    validate_tiers(tiers)
    row = FeeScheduleVersion(
        schedule_id=schedule_id, version=version, method=method, valid_during=date_range(valid_from, valid_until)
    )
    session.add(row)
    session.flush()
    session.add_all(
        FeeScheduleTier(schedule_id=schedule_id, version=version, tier_no=n, up_to_minor=t.up_to_minor, rate_bps=t.rate_bps)
        for n, t in enumerate(tiers, start=1)
    )
    session.commit()
    return row


def assign_schedule(
    session: Session, *, household_id: uuid.UUID, schedule_id: uuid.UUID, valid_from: date, valid_until: date | None
) -> HouseholdFeeAssignment:
    return _add(
        session,
        HouseholdFeeAssignment(
            household_id=household_id, schedule_id=schedule_id, valid_during=date_range(valid_from, valid_until)
        ),
    )
@dataclasses.dataclass(frozen=True)
class FeeRunResult:
    calculation: FeeCalculation
    replayed: bool


def _effective_version(
    session: Session, household_id: uuid.UUID, on: date
) -> tuple[FeeSchedule, FeeScheduleVersion, tuple[Tier, ...]]:
    assignment = session.scalars(
        select(HouseholdFeeAssignment).where(
            HouseholdFeeAssignment.household_id == household_id,
            HouseholdFeeAssignment.valid_during.contains(on),
        )
    ).one_or_none()
    if assignment is None:
        raise NoScheduleAssigned(f"No fee schedule is assigned to household {household_id} on {on}.")
    version = session.scalars(
        select(FeeScheduleVersion).where(
            FeeScheduleVersion.schedule_id == assignment.schedule_id,
            FeeScheduleVersion.valid_during.contains(on),
        )
    ).one_or_none()
    if version is None:
        raise NoScheduleAssigned(f"Fee schedule {assignment.schedule_id} has no version in effect on {on}.")
    tiers = tuple(
        Tier(row.up_to_minor, Decimal(row.rate_bps))
        for row in session.scalars(
            select(FeeScheduleTier)
            .where(FeeScheduleTier.schedule_id == version.schedule_id, FeeScheduleTier.version == version.version)
            .order_by(FeeScheduleTier.tier_no)
        )
    )
    schedule = session.get(FeeSchedule, assignment.schedule_id)
    return schedule, version, tiers


def _member_values(session: Session, household_id: uuid.UUID, period_end: date) -> tuple[AccountValue, ...]:
    links = list(
        session.scalars(
            select(ClientAccount)
            .join(Client, Client.id == ClientAccount.client_id)
            .where(Client.household_id == household_id, ClientAccount.linked_on <= period_end)
        )
    )
    if not links:
        raise NothingToBill(f"Household {household_id} has no accounts linked by {period_end}.")
    valuations = {
        row.account_id: row.market_value_minor
        for row in session.scalars(
            select(AccountValuation).where(
                AccountValuation.account_id.in_([link.account_id for link in links]),
                AccountValuation.as_of == period_end,
            )
        )
    }
    missing = sorted(str(link.account_id) for link in links if link.account_id not in valuations)
    if missing:
        raise MissingValuation(
            f"No valuation as of {period_end} for {len(missing)} account(s); a missing value is never treated as zero.",
            account_ids=missing,
        )
    return tuple(
        AccountValue(link.account_id, valuations[link.account_id], link.linked_on)
        for link in sorted(links, key=lambda link: str(link.account_id))
    )


def _fee_posting(
    tenant_id: uuid.UUID, household_id: uuid.UUID, inputs: FeeInputs, result: FeeResult, revenue_account_id: uuid.UUID
) -> PostingRequest:
    debits = [
        EntryInput(account_id, Direction.debit, amount)
        for account_id, amount in sorted(result.allocations.items(), key=lambda item: str(item[0]))
        if amount > 0
    ]
    credit = EntryInput(revenue_account_id, Direction.credit, result.period_fee_minor)
    return PostingRequest(
        tenant_id=tenant_id,
        idempotency_key=f"fee:{household_id}:{inputs.period_end.isoformat()}",
        entries=(*debits, credit),
        description=f"Advisory fee {inputs.period_start.isoformat()} to {inputs.period_end.isoformat()}",
        source=PostingSource.fee_run,
        effective_at=datetime.combine(inputs.period_end, time.min, tzinfo=timezone.utc),
    )


def run_household_fee(
    session: Session, *, tenant_id: uuid.UUID, household_id: uuid.UUID, period_start: date, period_end: date
) -> FeeRunResult:
    household = session.get(Household, household_id)
    if household is None or household.tenant_id != tenant_id:
        raise HouseholdNotFound(f"Household {household_id} does not exist.")
    schedule, version, tiers = _effective_version(session, household_id, period_end)
    inputs = FeeInputs(period_start, period_end, version.method, tiers, _member_values(session, household_id, period_end))
    result = calculate_household_fee(inputs)
    if result.period_fee_minor == 0:
        raise NothingToBill(f"Household {household_id} has no billable value between {period_start} and {period_end}.")

    try:
        with ledger_transaction(session):
            posted = create_posting(session, _fee_posting(tenant_id, household_id, inputs, result, schedule.revenue_account_id))
            if posted.replayed:
                existing = session.scalars(
                    select(FeeCalculation).where(FeeCalculation.posting_id == posted.posting.id)
                ).one()
                return FeeRunResult(calculation=existing, replayed=True)
            calculation = FeeCalculation(
                tenant_id=tenant_id,
                household_id=household_id,
                period=date_range(period_start, period_end),
                schedule_id=version.schedule_id,
                schedule_version=version.version,
                method=version.method,
                inputs=inputs_to_json(inputs, schedule_id=version.schedule_id, schedule_version=version.version),
                household_value_minor=result.household_value_minor,
                period_fee_minor=result.period_fee_minor,
                allocations={str(account_id): amount for account_id, amount in result.allocations.items()},
                rounding_remainder_minor=result.rounding_remainder_minor,
                posting_id=posted.posting.id,
            )
            session.add(calculation)
            session.flush()
    except IdempotencyKeyReused as exc:
        raise AlreadyBilled(
            f"Household {household_id} is already billed for the period ending {period_end} with different inputs; "
            "reverse the existing fee posting before re-billing."
        ) from exc
    return FeeRunResult(calculation=calculation, replayed=False)


def get_fee_calculation(session: Session, *, tenant_id: uuid.UUID, calculation_id: uuid.UUID) -> FeeCalculation:
    calculation = session.get(FeeCalculation, calculation_id)
    if calculation is None or calculation.tenant_id != tenant_id:
        raise FeeCalculationNotFound(f"Fee calculation {calculation_id} does not exist.")
    return calculation

def schedule_in_effect(session: Session, household_id: uuid.UUID, on: date) -> tuple[FeeSchedule, FeeScheduleVersion, tuple[Tier, ...]]:
    """Public read for other packages (contracts): the schedule version a household is billed on, on a date."""
    return _effective_version(session, household_id, on)


def household_accounts(session: Session, household_id: uuid.UUID, as_of: date) -> tuple[AccountValue, ...]:
    return _member_values(session, household_id, as_of)


def revenue_currency(session: Session, schedule_id: uuid.UUID) -> str:
    schedule = session.get(FeeSchedule, schedule_id)
    return session.get(Account, schedule.revenue_account_id).currency


def latest_valuation_date(session: Session, household_id: uuid.UUID) -> date | None:
    return session.scalar(
        select(func.max(AccountValuation.as_of))
        .join(ClientAccount, ClientAccount.account_id == AccountValuation.account_id)
        .join(Client, Client.id == ClientAccount.client_id)
        .where(Client.household_id == household_id)
    )
