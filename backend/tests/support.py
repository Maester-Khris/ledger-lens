import uuid
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.ledger.models import Account, Entry, Posting, Tenant
from app.ledger.types import Direction, NormalBalance, PostingSource
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.billing import dao as billing_dao
from app.billing.fee_math import Tier
from app.billing.types import FeeMethod

BACKEND_DIR = Path(__file__).resolve().parents[1]


def alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = database_url
    return config


def reset_schema(owner_url: str) -> None:
    """Drop and recreate the public schema. Owner-only, because the app role can't delete anything."""
    engine = create_engine(owner_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()


def make_tenant(session: Session) -> uuid.UUID:
    tenant = Tenant(name=f"test-tenant-{uuid.uuid4().hex[:8]}")
    session.add(tenant)
    session.commit()
    return tenant.id


def make_account(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    currency: str = "CAD",
    normal_balance: NormalBalance = NormalBalance.debit,
    gl_code: str | None = None,
    name: str | None = None,
) -> Account:
    account = Account(
        tenant_id=tenant_id,
        name=name or f"acct-{uuid.uuid4().hex[:8]}",
        currency=currency,
        normal_balance=normal_balance,
        gl_code=gl_code,
    )
    session.add(account)
    session.commit()
    return account


def insert_raw_posting(
    session: Session,
    tenant_id: uuid.UUID,
    entries: list[tuple[uuid.UUID, Direction, int]],
    *,
    reverses_posting_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Bypass Python validation so a test exercises the database invariants directly.

    Flushes the rows, then runs the deferred constraint checks immediately
    (SET CONSTRAINTS ALL IMMEDIATE), so a violation raises here, not at commit.
    """
    posting = Posting(
        tenant_id=tenant_id,
        idempotency_key=f"raw-{uuid.uuid4()}",
        request_fingerprint="0" * 64,
        source=PostingSource.api,
        reverses_posting_id=reverses_posting_id,
    )
    session.add(posting)
    session.flush()
    for account_id, direction, amount in entries:
        session.add(
            Entry(posting_id=posting.id, account_id=account_id, direction=direction, amount=amount)
        )
    session.flush()
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    return posting.id



WORKED_EXAMPLE_TIERS = (
    Tier(100_000_000, Decimal("100")),
    Tier(250_000_000, Decimal("80")),
    Tier(None, Decimal("65")),
)


@dataclass(frozen=True)
class FeeScenario:
    household_id: uuid.UUID
    client_account_ids: tuple[uuid.UUID, uuid.UUID]
    revenue_account_id: uuid.UUID
    schedule_id: uuid.UUID


def build_fee_scenario(session: Session, tenant_id: uuid.UUID) -> FeeScenario:
    """Worked example from the spec: 120M linked Jan 1 + 60M linked Aug 1, v1 then v2 schedules."""
    revenue = make_account(session, tenant_id, normal_balance=NormalBalance.credit, gl_code="4000", name="Advisory Fee Revenue")
    first = make_account(session, tenant_id, normal_balance=NormalBalance.credit, gl_code="2100")
    second = make_account(session, tenant_id, normal_balance=NormalBalance.credit, gl_code="2100")
    household = billing_dao.create_household(session, tenant_id=tenant_id, name="Tremblay")
    marie = billing_dao.create_client(session, tenant_id=tenant_id, household_id=household.id, name="Marie")
    luc = billing_dao.create_client(session, tenant_id=tenant_id, household_id=household.id, name="Luc")
    billing_dao.link_account(session, client_id=marie.id, account_id=first.id, linked_on=date(2026, 1, 1))
    billing_dao.link_account(session, client_id=luc.id, account_id=second.id, linked_on=date(2026, 8, 1))
    for as_of in (date(2026, 7, 31), date(2026, 9, 30)):
        billing_dao.record_valuation(session, account_id=first.id, as_of=as_of, market_value_minor=120_000_000, source="test")
        billing_dao.record_valuation(session, account_id=second.id, as_of=as_of, market_value_minor=60_000_000, source="test")
    schedule = billing_dao.create_fee_schedule(session, tenant_id=tenant_id, name="Standard", revenue_account_id=revenue.id)
    billing_dao.add_schedule_version(
        session, schedule_id=schedule.id, version=1, method=FeeMethod.graduated,
        valid_from=date(2026, 1, 1), valid_until=date(2026, 6, 30), tiers=(Tier(None, Decimal("150")),),
    )
    billing_dao.add_schedule_version(
        session, schedule_id=schedule.id, version=2, method=FeeMethod.graduated,
        valid_from=date(2026, 7, 1), valid_until=None, tiers=WORKED_EXAMPLE_TIERS,
    )
    billing_dao.assign_schedule(
        session, household_id=household.id, schedule_id=schedule.id, valid_from=date(2026, 1, 1), valid_until=None
    )
    return FeeScenario(household.id, (first.id, second.id), revenue.id, schedule.id)
