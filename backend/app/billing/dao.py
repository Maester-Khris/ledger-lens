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