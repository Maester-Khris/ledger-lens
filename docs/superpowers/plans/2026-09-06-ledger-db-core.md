# Ledger DB Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the database side of Epic 1.1 (schema & migrations) and Epic 1.2 (balance invariant enforcement) from `artifacts/product-backlog.md` — a real Postgres-backed ledger schema, a deferred-trigger balance guarantee, a thin sync DAO, and tests proving both, plus a one-command local setup script.

**Architecture:** A single `backend/app/ledger/` module holds SQLAlchemy 2.0 ORM models, a session factory, and two plain DAO functions (`create_account`, `create_posting`). Alembic manages migrations, including one hand-written raw-SQL migration for the deferred constraint trigger that autogenerate can't produce. A local Postgres 16 container (`fintech-ledger-db`) hosts two databases — `ledger_dev` for running the app, `ledger_test` for the test suite — both stood up and migrated by one idempotent script.

**Tech Stack:** Python 3.11, SQLAlchemy 2.0 (sync), psycopg (v3) driver, Alembic, pytest, PostgreSQL 16 (Docker), bash.

**Spec:** `docs/superpowers/specs/2026-09-06-ledger-db-schema-design.md`

## Global Constraints

- Sync SQLAlchemy only — no async engine, no `async def` anywhere in this plan.
- Driver is `psycopg` (v3), installed as `psycopg[binary]`.
- Postgres image is `postgres:16`, container name `fintech-ledger-db`, local-only password `localdev`, default `postgres` superuser role (no least-privilege app role in this pass).
- Two databases: `ledger_dev` (app) and `ledger_test` (test suite) — same container, never the same database.
- All primary keys are `UUID`, generated server-side via `gen_random_uuid()` (`pgcrypto` extension).
- All monetary amounts are `BIGINT` minor units (cents), `CHECK (amount > 0)` — sign comes from the `direction` enum column, never from the number.
- `postings` has no `updated_at` and no update path — append-only by construction.
- Isolation level is `READ COMMITTED` (documented, not overridden anywhere in code).
- DAO layer is plain functions taking a `Session` — no repository classes, no dependency-injection framework.
- Out of scope, do not build: the `POST /postings` REST endpoint, idempotency-conflict/payload-hash handling, concurrency/hot-account stress testing, Aurora deployment, compensating reversal, correlation-ID logging, CI pipeline.

---

### Task 1: Local Postgres container + both databases

**Files:**
- Create: `backend/scripts/db_up.sh`

**Interfaces:**
- Consumes: nothing (first task, no code dependencies)
- Produces: a running Docker container named `fintech-ledger-db` (Postgres 16, port 5432, password `localdev`) with two empty databases, `ledger_dev` and `ledger_test`. Later tasks connect to these by name.

- [ ] **Step 1: Write `backend/scripts/db_up.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="fintech-ledger-db"
PG_PASSWORD="localdev"
PG_PORT="5432"

if ! docker inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
  echo "Creating container $CONTAINER_NAME..."
  docker run -d --name "$CONTAINER_NAME" \
    -e POSTGRES_PASSWORD="$PG_PASSWORD" \
    -p "$PG_PORT:5432" \
    postgres:16
elif [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME")" != "true" ]; then
  echo "Starting existing container $CONTAINER_NAME..."
  docker start "$CONTAINER_NAME" >/dev/null
else
  echo "Container $CONTAINER_NAME already running."
fi

echo "Waiting for Postgres to accept connections..."
ready=false
for _ in $(seq 1 30); do
  if docker exec "$CONTAINER_NAME" pg_isready -U postgres >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done
if [ "$ready" != "true" ]; then
  echo "Postgres did not become ready in time" >&2
  exit 1
fi

for db in ledger_dev ledger_test; do
  exists=$(docker exec "$CONTAINER_NAME" psql -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${db}'")
  if [ "$exists" != "1" ]; then
    echo "Creating database ${db}..."
    docker exec "$CONTAINER_NAME" psql -U postgres -c "CREATE DATABASE ${db}"
  else
    echo "Database ${db} already exists."
  fi
done

echo "Postgres and both databases are ready. (Migrations are wired in a later step.)"
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x backend/scripts/db_up.sh`

- [ ] **Step 3: Run it and verify both databases exist**

Run: `./backend/scripts/db_up.sh`
Expected output ends with: `Postgres and both databases are ready.`

Then verify directly:
Run: `docker exec fintech-ledger-db psql -U postgres -tAc "SELECT datname FROM pg_database WHERE datname IN ('ledger_dev','ledger_test')"`
Expected: both `ledger_dev` and `ledger_test` printed (order may vary).

- [ ] **Step 4: Run it again to confirm idempotency**

Run: `./backend/scripts/db_up.sh`
Expected output: `Container fintech-ledger-db already running.` and `Database ledger_dev already exists.` / `Database ledger_test already exists.` — no errors, no duplicate creation attempts.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/db_up.sh
git commit -m "Add idempotent local Postgres setup script"
```

---

### Task 2: Python dependencies + config

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/app/config.py`
- Create: `backend/.env.example`
- Modify: `backend/.gitignore`

**Interfaces:**
- Consumes: nothing
- Produces: `app.config.DATABASE_URL: str`, `app.config.TEST_DATABASE_URL: str` — read by every later task that opens a DB connection.

- [ ] **Step 1: Add dependencies to `backend/requirements.txt`**

Replace the file's contents with:

```
fastapi
uvicorn[standard]
sqlalchemy>=2.0
alembic>=1.13
psycopg[binary]>=3.1
python-dotenv
pytest
```

- [ ] **Step 2: Install them**

Run (from `backend/`, with its `.venv` active): `pip install -r requirements.txt`
Expected: all packages install with no errors.

- [ ] **Step 3: Write `backend/app/config.py`**

```python
import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:localdev@localhost:5432/ledger_dev",
)

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:localdev@localhost:5432/ledger_test",
)
```

- [ ] **Step 4: Write `backend/.env.example`**

```
DATABASE_URL=postgresql+psycopg://postgres:localdev@localhost:5432/ledger_dev
TEST_DATABASE_URL=postgresql+psycopg://postgres:localdev@localhost:5432/ledger_test
```

- [ ] **Step 5: Add `.env` to `backend/.gitignore`**

Check `backend/.gitignore` for a `.env` line; append one if missing:

```
.env
```

- [ ] **Step 6: Verify config loads**

Run: `cd backend && python -c "from app import config; print(config.DATABASE_URL); print(config.TEST_DATABASE_URL)"`
Expected: prints both default URLs (from Step 3), no errors — confirms the module imports cleanly with no `.env` file present yet.

- [ ] **Step 7: Commit**

```bash
git add backend/requirements.txt backend/app/config.py backend/.env.example backend/.gitignore
git commit -m "Add DB dependencies and DATABASE_URL config"
```

---

### Task 3: Alembic environment

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/` (empty directory, populated in Task 4)
- Create: `backend/app/ledger/__init__.py` (empty)
- Create: `backend/app/ledger/models.py` (placeholder `Base` only — Task 4 replaces its contents with the real schema)

**Interfaces:**
- Consumes: `app.config.DATABASE_URL` (Task 2)
- Produces: a working `alembic upgrade head` / `alembic revision` command set, resolvable against either database via the `ALEMBIC_DATABASE_URL` environment variable override. Later tasks add revision files under `backend/alembic/versions/`.

- [ ] **Step 1: Initialize Alembic's directory structure**

Run: `cd backend && alembic init alembic`
Expected: creates `alembic.ini` and `alembic/` with `env.py`, `script.py.mako`, `versions/`.

- [ ] **Step 2: Replace `backend/alembic/env.py` with:**

```python
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import config as app_config  # noqa: E402
from app.ledger.models import Base  # noqa: E402

alembic_config = context.config

if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

target_metadata = Base.metadata


def get_database_url() -> str:
    return os.environ.get("ALEMBIC_DATABASE_URL", app_config.DATABASE_URL)


def run_migrations_offline() -> None:
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = alembic_config.get_section(alembic_config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

This imports `app.ledger.models.Base` — which doesn't exist yet. That's expected; Task 4 creates it. This task only needs the import to resolve, so create a minimal placeholder now (Task 4 replaces it properly):

- [ ] **Step 3: Create a temporary placeholder so `env.py` can import successfully**

Create `backend/app/ledger/__init__.py` (empty file) and `backend/app/ledger/models.py`:

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

(Task 4 adds the actual `Account`/`Posting`/`Entry` model classes to this same file — this step only establishes `Base` so Alembic has metadata to point at.)

- [ ] **Step 4: Remove the `sqlalchemy.url` line from `backend/alembic.ini`**

Open `backend/alembic.ini`, find the line starting `sqlalchemy.url = `, and delete it (or comment it out) — `env.py`'s `get_database_url()` supplies the URL instead, so migrations can target either database via the `ALEMBIC_DATABASE_URL` env var.

- [ ] **Step 5: Verify Alembic runs with no migrations yet**

Run: `cd backend && ALEMBIC_DATABASE_URL=postgresql+psycopg://postgres:localdev@localhost:5432/ledger_dev alembic upgrade head`
Expected: runs with no errors, prints nothing about missing revisions (there are none yet) — confirms the connection and `env.py` wiring both work.

- [ ] **Step 6: Commit**

```bash
git add backend/alembic.ini backend/alembic/ backend/app/ledger/
git commit -m "Wire Alembic environment to app config"
```

---

### Task 4: Schema — accounts, postings, entries

**Files:**
- Modify: `backend/app/ledger/models.py`
- Create: `backend/alembic/versions/0001_create_ledger_tables.py`

**Interfaces:**
- Consumes: `Base` (Task 3)
- Produces: ORM classes `Account`, `Posting`, `Entry`, and the enum `Direction` (`Direction.debit`, `Direction.credit`) — consumed by the DAO in Task 6 and the trigger's own SQL (by table/column name) in Task 5.

- [ ] **Step 1: Replace `backend/app/ledger/models.py` with the full schema**

```python
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Text,
    TIMESTAMP,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Direction(str, enum.Enum):
    debit = "debit"
    credit = "credit"


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class Posting(Base):
    __tablename__ = "postings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    entries: Mapped[list["Entry"]] = relationship(back_populates="posting")


class Entry(Base):
    __tablename__ = "entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    posting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("postings.id"), nullable=False, index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True
    )
    direction: Mapped[Direction] = mapped_column(
        SAEnum(Direction, name="entry_direction", native_enum=True), nullable=False
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    posting: Mapped["Posting"] = relationship(back_populates="entries")

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_entries_amount_positive"),
    )
```

- [ ] **Step 2: Generate the migration**

Run: `cd backend && ALEMBIC_DATABASE_URL=postgresql+psycopg://postgres:localdev@localhost:5432/ledger_dev alembic revision --autogenerate -m "create ledger tables"`
Expected: creates a file under `backend/alembic/versions/`. Rename it (and update its `revision =` string inside if autogenerate picked a random hash) to `0001_create_ledger_tables.py` with `revision = "0001_create_ledger_tables"` and `down_revision = None`, so later tasks can reference it by a stable name.

- [ ] **Step 3: Add the pgcrypto extension to the migration's `upgrade()`, before table creation**

Open the generated `backend/alembic/versions/0001_create_ledger_tables.py` and add this as the first line of `upgrade()`:

```python
op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
```

And as the last line of `downgrade()` (after the tables are dropped):

```python
op.execute("DROP EXTENSION IF EXISTS pgcrypto")
```

- [ ] **Step 4: Run the migration against `ledger_dev`**

Run: `cd backend && ALEMBIC_DATABASE_URL=postgresql+psycopg://postgres:localdev@localhost:5432/ledger_dev alembic upgrade head`
Expected: succeeds, no errors.

- [ ] **Step 5: Verify the tables exist with the right shape**

Run: `docker exec fintech-ledger-db psql -U postgres -d ledger_dev -c "\d entries"`
Expected: shows columns `id, posting_id, account_id, direction, amount, created_at`, the `ck_entries_amount_positive` check constraint, and both foreign keys.

- [ ] **Step 6: Verify downgrade is clean**

Run: `cd backend && ALEMBIC_DATABASE_URL=postgresql+psycopg://postgres:localdev@localhost:5432/ledger_dev alembic downgrade -1`
Expected: succeeds with no errors.

Then re-apply it (later tasks need the tables present):
Run: `cd backend && ALEMBIC_DATABASE_URL=postgresql+psycopg://postgres:localdev@localhost:5432/ledger_dev alembic upgrade head`

- [ ] **Step 7: Apply the same migration to `ledger_test`**

Run: `cd backend && ALEMBIC_DATABASE_URL=postgresql+psycopg://postgres:localdev@localhost:5432/ledger_test alembic upgrade head`
Expected: succeeds — `ledger_test` now has the same schema as `ledger_dev`.

- [ ] **Step 8: Commit**

```bash
git add backend/app/ledger/models.py backend/alembic/versions/0001_create_ledger_tables.py
git commit -m "Add accounts/postings/entries schema"
```

---

### Task 5: Balance invariant trigger

**Files:**
- Create: `backend/alembic/versions/0002_balance_trigger.py`

**Interfaces:**
- Consumes: the `entries` table (Task 4)
- Produces: a database-enforced invariant — any transaction that commits entry rows for a posting where debit-direction amounts don't equal credit-direction amounts raises a Postgres exception at COMMIT. Task 6's DAO relies on this to make `create_posting` atomic-and-correct without any application-level balance check of its own.

- [ ] **Step 1: Create `backend/alembic/versions/0002_balance_trigger.py`**

```python
"""balance invariant trigger

Revision ID: 0002_balance_trigger
Revises: 0001_create_ledger_tables
"""
from alembic import op

revision = "0002_balance_trigger"
down_revision = "0001_create_ledger_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION check_posting_balance() RETURNS trigger AS $$
        DECLARE
          imbalance bigint;
        BEGIN
          SELECT COALESCE(
            SUM(CASE WHEN direction = 'debit' THEN amount ELSE -amount END), 0
          )
            INTO imbalance
            FROM entries
            WHERE posting_id = NEW.posting_id;

          IF imbalance != 0 THEN
            RAISE EXCEPTION 'posting % is unbalanced: debit/credit mismatch of %',
              NEW.posting_id, imbalance;
          END IF;

          RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_check_posting_balance
          AFTER INSERT ON entries
          DEFERRABLE INITIALLY DEFERRED
          FOR EACH ROW
          EXECUTE FUNCTION check_posting_balance();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_check_posting_balance ON entries")
    op.execute("DROP FUNCTION IF EXISTS check_posting_balance()")
```

- [ ] **Step 2: Apply it to `ledger_dev`**

Run: `cd backend && ALEMBIC_DATABASE_URL=postgresql+psycopg://postgres:localdev@localhost:5432/ledger_dev alembic upgrade head`
Expected: succeeds.

- [ ] **Step 3: Verify the trigger and function exist**

Run: `docker exec fintech-ledger-db psql -U postgres -d ledger_dev -c "\df check_posting_balance"`
Expected: lists the function.

Run: `docker exec fintech-ledger-db psql -U postgres -d ledger_dev -c "SELECT tgname, tgdeferrable, tginitdeferred FROM pg_trigger WHERE tgname = 'trg_check_posting_balance'"`
Expected: one row, `tgdeferrable = t`, `tginitdeferred = t`.

- [ ] **Step 4: Verify downgrade removes both cleanly**

Run: `cd backend && ALEMBIC_DATABASE_URL=postgresql+psycopg://postgres:localdev@localhost:5432/ledger_dev alembic downgrade -1`
Expected: succeeds.

Run: `docker exec fintech-ledger-db psql -U postgres -d ledger_dev -c "\df check_posting_balance"`
Expected: empty (no rows) — function is gone.

Then re-apply (later tasks need it present):
Run: `cd backend && ALEMBIC_DATABASE_URL=postgresql+psycopg://postgres:localdev@localhost:5432/ledger_dev alembic upgrade head`

- [ ] **Step 5: Apply to `ledger_test` too**

Run: `cd backend && ALEMBIC_DATABASE_URL=postgresql+psycopg://postgres:localdev@localhost:5432/ledger_test alembic upgrade head`
Expected: succeeds.

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/0002_balance_trigger.py
git commit -m "Add deferred constraint trigger enforcing posting balance"
```

---

### Task 6: DB session factory

**Files:**
- Create: `backend/app/ledger/db.py`

**Interfaces:**
- Consumes: a `database_url: str` (caller-supplied, e.g. `app.config.DATABASE_URL` or `app.config.TEST_DATABASE_URL`)
- Produces: `make_session_factory(database_url: str) -> sessionmaker`, module-level `SessionLocal: sessionmaker` (bound to `app.config.DATABASE_URL`), and `get_session() -> contextmanager yielding Session`. Task 7's DAO and Task 8's `conftest.py` both call `make_session_factory` directly (test code points it at `TEST_DATABASE_URL` instead of relying on the app-bound `SessionLocal`).

- [ ] **Step 1: Write `backend/app/ledger/db.py`**

```python
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import config


def make_session_factory(database_url: str) -> sessionmaker:
    engine = create_engine(database_url, future=True)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


SessionLocal = make_session_factory(config.DATABASE_URL)


@contextmanager
def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
```

- [ ] **Step 2: Write a smoke test**

Create `backend/tests/__init__.py` (empty) and `backend/tests/test_db_session.py`:

```python
from sqlalchemy import text

from app import config
from app.ledger.db import make_session_factory


def test_session_connects_to_test_database():
    session_factory = make_session_factory(config.TEST_DATABASE_URL)
    session = session_factory()
    try:
        result = session.execute(text("SELECT 1")).scalar_one()
        assert result == 1
    finally:
        session.close()
```

- [ ] **Step 3: Run it to verify it passes**

Run: `cd backend && pytest tests/test_db_session.py -v`
Expected: PASS (Task 4/5's migrations already applied `ledger_test`, so the connection succeeds).

- [ ] **Step 4: Commit**

```bash
git add backend/app/ledger/db.py backend/tests/__init__.py backend/tests/test_db_session.py
git commit -m "Add DB session factory"
```

---

### Task 7: DAO layer + balance invariant tests

**Files:**
- Create: `backend/app/ledger/dao.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_ledger_dao.py`

**Interfaces:**
- Consumes: `Account`, `Posting`, `Entry`, `Direction` (Task 4), `make_session_factory` (Task 6)
- Produces: `EntryInput(account_id: uuid.UUID, direction: Direction, amount: int)`, `create_account(session, name: str, currency: str) -> Account`, `create_posting(session, idempotency_key: str, description: str | None, entries: list[EntryInput]) -> Posting`. These are the only two operations the ledger DB core exposes in this run — Epic 1.3's future endpoint calls them, doesn't replace them.

- [ ] **Step 1: Write `backend/tests/conftest.py`**

```python
import pytest
from sqlalchemy import text

from app import config
from app.ledger.db import make_session_factory


@pytest.fixture()
def db_session():
    session_factory = make_session_factory(config.TEST_DATABASE_URL)
    session = session_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.execute(text("TRUNCATE TABLE entries, postings, accounts"))
        session.commit()
        session.close()
```

- [ ] **Step 2: Write the failing tests in `backend/tests/test_ledger_dao.py`**

```python
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.ledger.dao import EntryInput, create_account, create_posting
from app.ledger.models import Direction, Entry, Posting


def test_create_account_persists_row(db_session):
    account = create_account(db_session, name="Cash", currency="USD")

    assert account.id is not None
    assert account.name == "Cash"
    assert account.currency == "USD"


def test_balanced_posting_succeeds(db_session):
    cash = create_account(db_session, name="Cash", currency="USD")
    revenue = create_account(db_session, name="Revenue", currency="USD")

    posting = create_posting(
        db_session,
        idempotency_key=str(uuid.uuid4()),
        description="Test sale",
        entries=[
            EntryInput(account_id=cash.id, direction=Direction.debit, amount=1000),
            EntryInput(account_id=revenue.id, direction=Direction.credit, amount=1000),
        ],
    )

    assert posting.id is not None
    stored_entries = (
        db_session.query(Entry).filter(Entry.posting_id == posting.id).all()
    )
    assert len(stored_entries) == 2


def test_unbalanced_posting_is_rejected(db_session):
    cash = create_account(db_session, name="Cash", currency="USD")
    revenue = create_account(db_session, name="Revenue", currency="USD")

    with pytest.raises(IntegrityError):
        create_posting(
            db_session,
            idempotency_key=str(uuid.uuid4()),
            description="Unbalanced",
            entries=[
                EntryInput(account_id=cash.id, direction=Direction.debit, amount=1000),
                EntryInput(account_id=revenue.id, direction=Direction.credit, amount=900),
            ],
        )


def test_unbalanced_posting_leaves_zero_partial_rows(db_session):
    cash = create_account(db_session, name="Cash", currency="USD")
    revenue = create_account(db_session, name="Revenue", currency="USD")
    key = str(uuid.uuid4())

    with pytest.raises(IntegrityError):
        create_posting(
            db_session,
            idempotency_key=key,
            description="Unbalanced",
            entries=[
                EntryInput(account_id=cash.id, direction=Direction.debit, amount=1000),
                EntryInput(account_id=revenue.id, direction=Direction.credit, amount=900),
            ],
        )

    db_session.rollback()
    assert db_session.query(Posting).filter(Posting.idempotency_key == key).count() == 0
    assert db_session.query(Entry).count() == 0
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd backend && pytest tests/test_ledger_dao.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ledger.dao'` (the module doesn't exist yet).

- [ ] **Step 4: Write `backend/app/ledger/dao.py`**

```python
import dataclasses
import uuid

from sqlalchemy.orm import Session

from app.ledger.models import Account, Direction, Entry, Posting


@dataclasses.dataclass
class EntryInput:
    account_id: uuid.UUID
    direction: Direction
    amount: int


def create_account(session: Session, name: str, currency: str) -> Account:
    account = Account(name=name, currency=currency)
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


def create_posting(
    session: Session,
    idempotency_key: str,
    description: str | None,
    entries: list[EntryInput],
) -> Posting:
    with session.begin():
        posting = Posting(idempotency_key=idempotency_key, description=description)
        session.add(posting)
        session.flush()

        for entry_input in entries:
            session.add(
                Entry(
                    posting_id=posting.id,
                    account_id=entry_input.account_id,
                    direction=entry_input.direction,
                    amount=entry_input.amount,
                )
            )

    session.refresh(posting)
    return posting
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && pytest tests/test_ledger_dao.py -v`
Expected: all 4 tests PASS. `test_unbalanced_posting_is_rejected` and
`test_unbalanced_posting_leaves_zero_partial_rows` passing confirms the
Task 5 trigger actually fires and rolls back the whole transaction, not
just the entry rows.

- [ ] **Step 6: Run the full test suite once to confirm nothing else broke**

Run: `cd backend && pytest -v`
Expected: all tests across every file PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/ledger/dao.py backend/tests/conftest.py backend/tests/test_ledger_dao.py
git commit -m "Add ledger DAO and balance invariant tests"
```

---

### Task 8: Wire migrations into db_up.sh + README

**Files:**
- Modify: `backend/scripts/db_up.sh`
- Modify: `README.md`

**Interfaces:**
- Consumes: `alembic upgrade head` (Tasks 3-5), the two databases (Task 1)
- Produces: a single command (`./backend/scripts/db_up.sh`) that takes a completely fresh machine to "app and test suite both ready to run" — the deliverable this whole plan was building toward.

- [ ] **Step 1: Add the migration step to the end of `backend/scripts/db_up.sh`**

Replace the final line (`echo "Postgres and both databases are ready. (Migrations are wired in a later step.)"`) with:

```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Running migrations against ledger_dev..."
(cd "$SCRIPT_DIR" && ALEMBIC_DATABASE_URL="postgresql+psycopg://postgres:${PG_PASSWORD}@localhost:${PG_PORT}/ledger_dev" alembic upgrade head)

echo "Running migrations against ledger_test..."
(cd "$SCRIPT_DIR" && ALEMBIC_DATABASE_URL="postgresql+psycopg://postgres:${PG_PASSWORD}@localhost:${PG_PORT}/ledger_test" alembic upgrade head)

echo "Done. ledger_dev and ledger_test are up to date."
```

- [ ] **Step 2: Add a "Local development" section to `README.md`**

Append:

```markdown
## Local development — ledger DB core

Prerequisites: Docker running locally.

1. `./backend/scripts/db_up.sh` — idempotent: creates (or starts) a single
   Postgres 16 container named `fintech-ledger-db`, creates the `ledger_dev`
   and `ledger_test` databases if they don't already exist, and runs Alembic
   migrations against both. Safe to re-run any time — it only creates what's
   missing.
2. Copy `backend/.env.example` to `backend/.env` if you need to override the
   default connection settings (defaults work out of the box against the
   container from step 1).
3. Run the test suite: `cd backend && pytest`

**Isolation level:** the balance-invariant trigger relies only on
`READ COMMITTED` (Postgres's default) — there is no read-then-conditional-write
step in this part of the system, so no stricter isolation level is set
anywhere.
```

- [ ] **Step 3: Verify the full script end-to-end from a clean state**

Run: `docker rm -f fintech-ledger-db`
Run: `./backend/scripts/db_up.sh`
Expected: creates the container, creates both databases, runs both
migrations, ends with `Done. ledger_dev and ledger_test are up to date.`

- [ ] **Step 4: Run the full test suite against the freshly-migrated state**

Run: `cd backend && pytest -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/db_up.sh README.md
git commit -m "Wire migrations into db_up.sh and document local setup"
```
