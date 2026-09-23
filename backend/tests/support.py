import uuid
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.ledger.models import Account, Entry, Posting, Tenant
from app.ledger.types import Direction, NormalBalance, PostingSource

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
