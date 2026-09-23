# Ledger Sprint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the double-entry core so every money rule is enforced by Postgres. Then extend it into a small revenue book of record: idempotent posting API, reversals, household fee billing on versioned schedules, human-approved AI postings, and a reproducible GL-ready export.

**Architecture:** Four packages under `backend/app/`: `ledger` (depends on nothing), and `billing`, `governance`, `reporting` (each depends only on `ledger`). Every package keeps the existing `models.py` / `dao.py` pattern. Pure logic lives in framework-free files: `ledger/fingerprint.py`, `billing/fee_math.py`, `reporting/gl_csv.py`. `ledger.dao.create_posting` is the single write path for postings, used inside `ledger.dao.ledger_transaction`. Invariants are enforced by triggers and constraints in hand-written Alembic migrations. The API connects as a restricted `ledger_app` role that can't UPDATE or DELETE.

**Tech Stack:** Python 3.12 (venv at `backend/.venv`), FastAPI + Pydantic v2, SQLAlchemy 2.0 (sync), psycopg 3, Alembic, pytest, httpx, PostgreSQL 18 (Docker, `btree_gist`, temporal keys `WITHOUT OVERLAPS`).

**Spec:** `docs/superpowers/specs/2026-09-22-ledger-sprint-design.md` (read it before Task 1)

## Global Constraints

- All commands run from `backend/` using `.venv/bin/...` (for example `.venv/bin/pytest`).
- Postgres image `postgres:18`, container `fintech-ledger-db`, dev-only password `localdev` for `postgres`, `ledger_owner`, `ledger_app`.
- Databases: `ledger_dev`, `ledger_test`, `ledger_migration_test`, all owned by `ledger_owner`.
- The app and all tests connect as `ledger_app` (SELECT and INSERT on every table; `UPDATE (name, gl_code)` on `accounts` only). Migrations run as `ledger_owner`.
- Money is `BIGINT` minor units (cents), always positive; the sign comes from `direction`. Fee maths uses `decimal.Decimal`, never `float`.
- Demo tenant id: `00000000-0000-0000-0000-000000000001`.
- Idempotency responses: **400** header missing or invalid · **201** created · **200** replay with header `Idempotent-Replayed: true` · **422** `idempotency-key-reused` · **409** `request-in-progress` with header `Retry-After: 1`.
- Fingerprint: SHA-256 hex of canonical JSON (`sort_keys=True`, `separators=(",", ":")`) of `description`, `effective_at` (UTC ISO), `entries` sorted by `(account_id, direction, amount)`, `reverses_posting_id`, `source`.
- Rounding: household fee half-to-even to minor units; split across accounts by largest remainder, ties broken by `str(account_id)` ascending.
- Valuation basis: period-end (`account_valuations.as_of = period_end`).
- Errors: RFC 9457 `application/problem+json`, `type` = `/problems/<slug>`.
- Isolation level: default READ COMMITTED. Never set SERIALIZABLE.
- Only `.../dao.py` files touch the database. Routes only parse → call a package function → return.
- Migrations are frozen snapshots: never import application code inside `alembic/versions/*.py`.
- Commits: conventional commits, stage files explicitly (never `git add -A`), no AI co-author trailer. Branch `feat/ledger`.
- Out of scope, don't build: fee corrections, advisor compensation, average-daily-balance valuation, row-level security, a second real tenant, authentication, reconciliation, a pending posting state, hash-chained audit rows, the chat/LLM side, frontend wiring.

## Deviations from the spec (deliberate; reviewers please confirm)

1. **Migration numbering:** app-role grants get their own migration `0003_app_role_grants`. The spec's `0003`–`0006` become `0004`–`0007`.
2. **`currencies.code` is `text` with `CHECK (code ~ '^[A-Z]{3}$')`**, not `char(3)`, so that it can be a foreign key target for the existing `accounts.currency text` column.
3. **GL export cutoff settle margin (added):** `created_at` is set at the start of a posting's transaction. So the export uses `cutoff = now() - 60s`, and ledger transactions set `statement_timeout = '10s'`. Without this, a transaction that began before the cutoff but committed after the export was read would change the regenerated export. Tests pass a settle margin of 0.
4. **New error types added:** `IdempotencyKeyInvalid` (400), `CursorInvalid` (400), `PostingAlreadyReversed` (409), `HouseholdNotFound` (404), `NothingToBill` (422), `FeeCalculationNotFound` (404), `InvocationNotFound` (404), `GlExportNotFound` (404), `UnknownCurrency` (422), `GlExportIntegrityError` (500).
5. **`POST /postings` accepts `"source": "api" | "stress_test"`** so the concurrency proof can tag its traffic. Clients can't claim `fee_run` or `ai_tool`.
6. **Test isolation:** every test gets a **fresh tenant** (`tenant_id` fixture), and API tests override the tenant dependency. The test database is shared across a session, so this keeps tests from interfering with each other.
7. **Separate database for migrations:** a third database, `ledger_migration_test`, hosts the upgrade → downgrade → upgrade test.

## Review Focus

Inputs the spec doesn't mention but a real user will send. Each has a test in the task named in brackets:

1. **Timestamp without a timezone** (`"effective_at": "2026-09-30T00:00:00"`) → rejected (422 `request-invalid` at the API, `PostingInvalid` in the DAO), never silently treated as local time. [Task 3, Task 4]
2. **`Idempotency-Key` that is blank, whitespace-only, or longer than 255 characters** → 400, not a database error. [Task 4]
3. **A household with nothing to bill** (every account linked after the period ends, or all values 0) → 422 `nothing-to-bill`, not a 500 from the `amount > 0` constraint. [Task 8]
4. **A fee period that spans a schedule version change** → uses the version in effect on `period_end`, deterministically. [Task 8]
5. **A GL export for a period with no postings** → a valid CSV (header plus a `TOTAL` row of zeros), not an error. [Task 10]

---

### Task 1: Postgres 18, two roles, config split, test harness as the app role

**Files:**
- Modify: `backend/scripts/db_up.sh` (whole file)
- Modify: `backend/app/config.py` (whole file)
- Modify: `backend/.env.example`
- Modify: `backend/alembic/env.py:21-22`
- Create: `backend/alembic/versions/0003_app_role_grants.py`
- Create: `backend/tests/support.py`
- Modify: `backend/tests/conftest.py` (whole file)
- Modify: `backend/tests/test_db_session.py` (whole file)
- Create: `backend/tests/test_migrations.py`
- Modify: `backend/tests/test_ledger_dao.py:71-73`

**Interfaces:**
- Produces: `app.config.DATABASE_URL`, `MIGRATION_DATABASE_URL`, `TEST_DATABASE_URL`, `TEST_OWNER_DATABASE_URL`, `MIGRATION_ROUNDTRIP_DATABASE_URL` (str).
- Produces: `tests.support.alembic_config(database_url: str) -> alembic.config.Config`, `tests.support.reset_schema(owner_url: str) -> None`, `tests.support.BACKEND_DIR: Path`.
- Produces fixtures (in `tests/conftest.py`): `migrated_test_database` (session), `session_factory` (session, app role), `owner_session_factory` (session), `db_session` (function, app role), `owner_session` (function).

- [x] **Step 1: Recreate the database container on Postgres 18**

The old container runs `postgres:16`, and there are no volumes, so local dev data is disposable. Run:

```bash
docker rm -f fintech-ledger-db
```

- [x] **Step 2: Replace `backend/scripts/db_up.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="fintech-ledger-db"
PG_IMAGE="postgres:18"
PG_PASSWORD="localdev"
ROLE_PASSWORD="localdev" # dev-only password shared by ledger_owner and ledger_app
PG_PORT="5432"
DATABASES="ledger_dev ledger_test ledger_migration_test"

if docker inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
  current_image=$(docker inspect -f '{{.Config.Image}}' "$CONTAINER_NAME")
  if [ "$current_image" != "$PG_IMAGE" ]; then
    echo "Container $CONTAINER_NAME runs $current_image, expected $PG_IMAGE." >&2
    echo "Recreate it (destroys local dev data): docker rm -f $CONTAINER_NAME && $0" >&2
    exit 1
  fi
  if [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME")" != "true" ]; then
    echo "Starting existing container $CONTAINER_NAME..."
    docker start "$CONTAINER_NAME" >/dev/null
  else
    echo "Container $CONTAINER_NAME already running."
  fi
else
  echo "Creating container $CONTAINER_NAME ($PG_IMAGE)..."
  docker run -d --name "$CONTAINER_NAME" \
    -e POSTGRES_PASSWORD="$PG_PASSWORD" \
    -p "$PG_PORT:5432" \
    "$PG_IMAGE"
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

psql_admin() {
  docker exec "$CONTAINER_NAME" psql -U postgres -v ON_ERROR_STOP=1 -tAc "$1"
}

for role in ledger_owner ledger_app; do
  if [ "$(psql_admin "SELECT 1 FROM pg_roles WHERE rolname='${role}'")" != "1" ]; then
    echo "Creating role ${role}..."
    psql_admin "CREATE ROLE ${role} LOGIN PASSWORD '${ROLE_PASSWORD}'"
  fi
done

for db in $DATABASES; do
  if [ "$(psql_admin "SELECT 1 FROM pg_database WHERE datname='${db}'")" != "1" ]; then
    echo "Creating database ${db}..."
    psql_admin "CREATE DATABASE ${db} OWNER ledger_owner"
  fi
  psql_admin "ALTER DATABASE ${db} OWNER TO ledger_owner" >/dev/null
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ALEMBIC="$SCRIPT_DIR/.venv/bin/alembic"
OWNER_URL="postgresql+psycopg://ledger_owner:${ROLE_PASSWORD}@localhost:${PG_PORT}"

for db in ledger_dev ledger_test; do
  echo "Running migrations against ${db} as ledger_owner..."
  (cd "$SCRIPT_DIR" && ALEMBIC_DATABASE_URL="${OWNER_URL}/${db}" "$ALEMBIC" upgrade head)
done

echo "Done. ledger_dev and ledger_test are up to date (ledger_migration_test is managed by the test suite)."
```

- [x] **Step 3: Replace `backend/app/config.py`**

```python
import os

from dotenv import load_dotenv

load_dotenv()

_LOCAL = "localhost:5432"

# Runtime app role: SELECT/INSERT only (see migration 0003/0004 grants).
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"postgresql+psycopg://ledger_app:localdev@{_LOCAL}/ledger_dev",
)

# Schema owner: runs migrations only.
MIGRATION_DATABASE_URL = os.environ.get(
    "MIGRATION_DATABASE_URL",
    f"postgresql+psycopg://ledger_owner:localdev@{_LOCAL}/ledger_dev",
)

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    f"postgresql+psycopg://ledger_app:localdev@{_LOCAL}/ledger_test",
)

TEST_OWNER_DATABASE_URL = os.environ.get(
    "TEST_OWNER_DATABASE_URL",
    f"postgresql+psycopg://ledger_owner:localdev@{_LOCAL}/ledger_test",
)

MIGRATION_ROUNDTRIP_DATABASE_URL = os.environ.get(
    "MIGRATION_ROUNDTRIP_DATABASE_URL",
    f"postgresql+psycopg://ledger_owner:localdev@{_LOCAL}/ledger_migration_test",
)
```

- [x] **Step 4: Replace `backend/.env.example`**

```
DATABASE_URL=postgresql+psycopg://ledger_app:localdev@localhost:5432/ledger_dev
MIGRATION_DATABASE_URL=postgresql+psycopg://ledger_owner:localdev@localhost:5432/ledger_dev
TEST_DATABASE_URL=postgresql+psycopg://ledger_app:localdev@localhost:5432/ledger_test
TEST_OWNER_DATABASE_URL=postgresql+psycopg://ledger_owner:localdev@localhost:5432/ledger_test
MIGRATION_ROUNDTRIP_DATABASE_URL=postgresql+psycopg://ledger_owner:localdev@localhost:5432/ledger_migration_test
```

If a local `backend/.env` exists (gitignored), update it to the same values or delete it. The defaults in `config.py` already match.

- [x] **Step 5: Point Alembic at the owner URL, overridable per call**

In `backend/alembic/env.py`, replace `get_database_url`:

```python
def get_database_url() -> str:
    # Precedence: programmatic (tests) > env var (db_up.sh) > app config (owner role).
    return (
        alembic_config.attributes.get("database_url")
        or os.environ.get("ALEMBIC_DATABASE_URL")
        or app_config.MIGRATION_DATABASE_URL
    )
```

- [x] **Step 6: Create `backend/alembic/versions/0003_app_role_grants.py`**

```python
"""grant the runtime app role read + insert only

Revision ID: 0003_app_role_grants
Revises: 0002_balance_trigger
"""
from alembic import op

revision = "0003_app_role_grants"
down_revision = "0002_balance_trigger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("GRANT USAGE ON SCHEMA public TO ledger_app")
    op.execute("GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA public TO ledger_app")
    # Tables created later by ledger_owner get the same grants automatically.
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT ON TABLES TO ledger_app"
    )


def downgrade() -> None:
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT, INSERT ON TABLES FROM ledger_app"
    )
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM ledger_app")
    op.execute("REVOKE USAGE ON SCHEMA public FROM ledger_app")
```

- [x] **Step 7: Create `backend/tests/support.py`**

```python
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, text

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
```

- [x] **Step 8: Replace `backend/tests/conftest.py`**

```python
import pytest
from alembic import command

from app import config
from app.ledger.db import make_session_factory
from tests.support import alembic_config, reset_schema


@pytest.fixture(scope="session")
def migrated_test_database() -> None:
    # Rebuilt once per session. Tests never clean up (the app role can't DELETE);
    # they isolate themselves with unique ids and a per-test tenant instead.
    reset_schema(config.TEST_OWNER_DATABASE_URL)
    command.upgrade(alembic_config(config.TEST_OWNER_DATABASE_URL), "head")


@pytest.fixture(scope="session")
def session_factory(migrated_test_database):
    return make_session_factory(config.TEST_DATABASE_URL)


@pytest.fixture(scope="session")
def owner_session_factory(migrated_test_database):
    return make_session_factory(config.TEST_OWNER_DATABASE_URL)


@pytest.fixture()
def db_session(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def owner_session(owner_session_factory):
    session = owner_session_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
```

- [x] **Step 9: Write the failing role tests (replace `backend/tests/test_db_session.py`)**

```python
import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError


def test_app_session_connects_as_restricted_role(db_session):
    assert db_session.execute(text("SELECT current_user")).scalar_one() == "ledger_app"


def test_app_role_cannot_delete_ledger_rows(db_session):
    with pytest.raises(ProgrammingError) as exc_info:
        db_session.execute(text("DELETE FROM postings"))
    assert exc_info.value.orig.sqlstate == "42501"  # insufficient_privilege


def test_owner_session_connects_as_schema_owner(owner_session):
    assert owner_session.execute(text("SELECT current_user")).scalar_one() == "ledger_owner"
```

- [x] **Step 10: Write the failing migration round-trip test (`backend/tests/test_migrations.py`)**

```python
from alembic import command

from app import config
from tests.support import alembic_config, reset_schema


def test_migrations_upgrade_downgrade_upgrade():
    url = config.MIGRATION_ROUNDTRIP_DATABASE_URL
    reset_schema(url)
    alembic = alembic_config(url)

    command.upgrade(alembic, "head")
    command.downgrade(alembic, "base")
    command.upgrade(alembic, "head")
```

- [x] **Step 11: Make the existing DAO test independent of other tests' rows**

In `backend/tests/test_ledger_dao.py`, replace the last two lines of `test_unbalanced_posting_leaves_zero_partial_rows` with:

```python
    db_session.rollback()
    assert db_session.query(Posting).filter(Posting.idempotency_key == key).count() == 0
    assert (
        db_session.query(Entry)
        .filter(Entry.account_id.in_([cash.id, revenue.id]))
        .count()
        == 0
    )
```

- [x] **Step 12: Run the tests before bringing the database up, to confirm they fail**

Run: `.venv/bin/pytest -v`
Expected: FAIL/ERROR with a connection error (role `ledger_app` / database not found), since the container isn't up yet.

- [x] **Step 13: Bring up the database and run the full suite**

Run: `./scripts/db_up.sh && .venv/bin/pytest -v`
Expected: PASS. That's 3 role tests, 1 migration round-trip, and the 4 existing DAO tests.

- [x] **Step 14: Commit**

```bash
git add scripts/db_up.sh app/config.py .env.example alembic/env.py alembic/versions/0003_app_role_grants.py tests/support.py tests/conftest.py tests/test_db_session.py tests/test_migrations.py tests/test_ledger_dao.py
git commit -m "chore(db): move to Postgres 18 with owner and least-privilege app roles" -m "Tests now run as the restricted ledger_app role against a per-session rebuilt schema, and migrations round-trip on a dedicated database."
```

---

### Task 2: Migration 0004 — ledger core schema and database-enforced invariants

**Files:**
- Create: `backend/app/ledger/types.py`
- Modify: `backend/app/ledger/models.py` (whole file)
- Create: `backend/alembic/versions/0004_ledger_core.py`
- Modify: `backend/tests/support.py` (append helpers)
- Modify: `backend/tests/conftest.py` (append `tenant_id` fixture)
- Create: `backend/tests/test_ledger_invariants.py`
- Delete: `backend/tests/test_ledger_dao.py` (it tests the old DAO signatures, which no longer match the schema; Task 3 replaces it with a full rewrite)

**Interfaces:**
- Consumes: fixtures from Task 1.
- Produces (`app.ledger.types`): `Direction`, `NormalBalance`, `PostingSource` (`str` enums; values `debit|credit`, `debit|credit`, `api|fee_run|ai_tool|stress_test`), `DEMO_TENANT_ID: uuid.UUID`.
- Produces (`app.ledger.models`): `Base`, `Currency(code, minor_units)`, `Tenant(id, name, created_at)`, `Account(id, tenant_id, name, currency, normal_balance, gl_code, created_at)`, `Posting(id, tenant_id, idempotency_key, description, effective_at, request_fingerprint, source, reverses_posting_id, created_at, entries)`, `Entry(id, posting_id, account_id, direction, amount, created_at, posting)`. `Direction` stays importable from `app.ledger.models`.
- Produces (`tests.support`): `make_account(session, tenant_id, *, currency="CAD", normal_balance=NormalBalance.debit, gl_code=None, name=None) -> Account` (commits), `insert_raw_posting(session, tenant_id, entries, *, reverses_posting_id=None) -> uuid.UUID` (no commit; fires the deferred checks immediately), `make_tenant(session) -> uuid.UUID` (commits).
- Produces fixture: `tenant_id` (function scope: a new tenant per test).
- Produces database objects later tasks rely on: `forbid_mutation()` (trigger function raising SQLSTATE 23001), constraint names `uq_postings_tenant_idempotency_key` and `uq_postings_reverses_posting_id`, the check-violation SQLSTATE 23514 from `assert_posting_valid`.

- [x] **Step 1: Create `backend/app/ledger/types.py`**

```python
import enum
import uuid

# Pure types shared by models, DAO and pure logic. No SQLAlchemy or FastAPI imports here.

DEMO_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class Direction(str, enum.Enum):
    debit = "debit"
    credit = "credit"


class NormalBalance(str, enum.Enum):
    debit = "debit"
    credit = "credit"


class PostingSource(str, enum.Enum):
    api = "api"
    fee_run = "fee_run"
    ai_tool = "ai_tool"
    stress_test = "stress_test"
```

- [x] **Step 2: Add the test helpers to `backend/tests/support.py`**

Append:

```python
import uuid

from sqlalchemy.orm import Session

from app.ledger.models import Account, Entry, Posting, Tenant
from app.ledger.types import Direction, NormalBalance, PostingSource


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
```

Move the new imports to the top of the file, next to the existing ones.

- [x] **Step 3: Add the `tenant_id` fixture to `backend/tests/conftest.py`**

Append:

```python
from tests.support import make_tenant


@pytest.fixture()
def tenant_id(db_session):
    """A fresh tenant per test, so assertions never see other tests' rows."""
    return make_tenant(db_session)
```

Move the import to the top of the file.

- [x] **Step 4: Write the failing invariant tests (`backend/tests/test_ledger_invariants.py`)**

```python
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.ledger.types import Direction, NormalBalance
from tests.support import insert_raw_posting, make_account, make_tenant

DEBIT, CREDIT = Direction.debit, Direction.credit


def _sqlstate(exc_info) -> str:
    return exc_info.value.orig.sqlstate


def test_balanced_posting_is_accepted(db_session, tenant_id):
    cash, revenue = make_account(db_session, tenant_id), make_account(db_session, tenant_id)
    insert_raw_posting(db_session, tenant_id, [(cash.id, DEBIT, 1000), (revenue.id, CREDIT, 1000)])


def test_unbalanced_posting_is_rejected(db_session, tenant_id):
    cash, revenue = make_account(db_session, tenant_id), make_account(db_session, tenant_id)
    with pytest.raises(IntegrityError) as exc_info:
        insert_raw_posting(db_session, tenant_id, [(cash.id, DEBIT, 1000), (revenue.id, CREDIT, 900)])
    assert _sqlstate(exc_info) == "23514"


def test_posting_without_entries_is_rejected(db_session, tenant_id):
    with pytest.raises(IntegrityError) as exc_info:
        insert_raw_posting(db_session, tenant_id, [])
    assert _sqlstate(exc_info) == "23514"


def test_posting_with_only_debits_is_rejected(db_session, tenant_id):
    cash = make_account(db_session, tenant_id)
    with pytest.raises(IntegrityError) as exc_info:
        insert_raw_posting(db_session, tenant_id, [(cash.id, DEBIT, 1000)])
    assert _sqlstate(exc_info) == "23514"


def test_cross_currency_posting_that_only_nets_overall_is_rejected(db_session, tenant_id):
    cad = make_account(db_session, tenant_id, currency="CAD")
    usd = make_account(db_session, tenant_id, currency="USD")
    with pytest.raises(IntegrityError) as exc_info:
        insert_raw_posting(db_session, tenant_id, [(cad.id, DEBIT, 1000), (usd.id, CREDIT, 1000)])
    assert _sqlstate(exc_info) == "23514"


def test_posting_balanced_per_currency_is_accepted(db_session, tenant_id):
    cad_a, cad_b = make_account(db_session, tenant_id), make_account(db_session, tenant_id)
    usd_a = make_account(db_session, tenant_id, currency="USD")
    usd_b = make_account(db_session, tenant_id, currency="USD")
    insert_raw_posting(
        db_session,
        tenant_id,
        [(cad_a.id, DEBIT, 1000), (cad_b.id, CREDIT, 1000), (usd_a.id, DEBIT, 750), (usd_b.id, CREDIT, 750)],
    )


def test_entry_on_another_tenants_account_is_rejected(db_session, tenant_id):
    other_tenant = make_tenant(db_session)
    mine = make_account(db_session, tenant_id)
    theirs = make_account(db_session, other_tenant)
    with pytest.raises(IntegrityError) as exc_info:
        insert_raw_posting(db_session, tenant_id, [(mine.id, DEBIT, 500), (theirs.id, CREDIT, 500)])
    assert _sqlstate(exc_info) == "23514"


def test_reversal_must_mirror_the_original(db_session, tenant_id):
    cash, revenue = make_account(db_session, tenant_id), make_account(db_session, tenant_id)
    original = insert_raw_posting(db_session, tenant_id, [(cash.id, DEBIT, 1000), (revenue.id, CREDIT, 1000)])
    db_session.commit()
    with pytest.raises(IntegrityError) as exc_info:
        insert_raw_posting(
            db_session,
            tenant_id,
            [(cash.id, CREDIT, 900), (revenue.id, DEBIT, 900)],
            reverses_posting_id=original,
        )
    assert _sqlstate(exc_info) == "23514"


def test_exact_mirror_reversal_is_accepted(db_session, tenant_id):
    cash, revenue = make_account(db_session, tenant_id), make_account(db_session, tenant_id)
    original = insert_raw_posting(db_session, tenant_id, [(cash.id, DEBIT, 1000), (revenue.id, CREDIT, 1000)])
    db_session.commit()
    insert_raw_posting(
        db_session,
        tenant_id,
        [(cash.id, CREDIT, 1000), (revenue.id, DEBIT, 1000)],
        reverses_posting_id=original,
    )


def test_posting_can_be_reversed_only_once(db_session, tenant_id):
    cash, revenue = make_account(db_session, tenant_id), make_account(db_session, tenant_id)
    original = insert_raw_posting(db_session, tenant_id, [(cash.id, DEBIT, 1000), (revenue.id, CREDIT, 1000)])
    db_session.commit()
    mirror = [(cash.id, CREDIT, 1000), (revenue.id, DEBIT, 1000)]
    insert_raw_posting(db_session, tenant_id, mirror, reverses_posting_id=original)
    db_session.commit()
    with pytest.raises(IntegrityError) as exc_info:
        insert_raw_posting(db_session, tenant_id, mirror, reverses_posting_id=original)
    assert _sqlstate(exc_info) == "23505"


def test_app_role_cannot_update_or_delete_postings(db_session, tenant_id):
    cash, revenue = make_account(db_session, tenant_id), make_account(db_session, tenant_id)
    posting_id = insert_raw_posting(db_session, tenant_id, [(cash.id, DEBIT, 10), (revenue.id, CREDIT, 10)])
    db_session.commit()
    for statement in (
        "UPDATE postings SET description = 'x' WHERE id = :id",
        "DELETE FROM entries WHERE posting_id = :id",
    ):
        with pytest.raises(ProgrammingError) as exc_info:
            db_session.execute(text(statement), {"id": posting_id})
        assert _sqlstate(exc_info) == "42501"
        db_session.rollback()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE postings SET description = 'x' WHERE id = :id",
        "DELETE FROM entries WHERE posting_id = :id",
        "TRUNCATE entries",
    ],
)
def test_even_the_owner_cannot_rewrite_history(db_session, owner_session, tenant_id, statement):
    cash, revenue = make_account(db_session, tenant_id), make_account(db_session, tenant_id)
    posting_id = insert_raw_posting(db_session, tenant_id, [(cash.id, DEBIT, 10), (revenue.id, CREDIT, 10)])
    db_session.commit()
    with pytest.raises(IntegrityError) as exc_info:
        owner_session.execute(text(statement), {"id": posting_id})
    assert _sqlstate(exc_info) == "23001"


def test_account_name_is_editable_by_app_role(db_session, tenant_id):
    account = make_account(db_session, tenant_id)
    db_session.execute(text("UPDATE accounts SET name = 'Renamed' WHERE id = :id"), {"id": account.id})
    db_session.commit()


def test_gl_code_can_be_set_once_but_never_changed(db_session, tenant_id):
    account = make_account(db_session, tenant_id)
    db_session.execute(text("UPDATE accounts SET gl_code = '4000' WHERE id = :id"), {"id": account.id})
    db_session.commit()
    with pytest.raises(IntegrityError) as exc_info:
        db_session.execute(text("UPDATE accounts SET gl_code = '4001' WHERE id = :id"), {"id": account.id})
    assert _sqlstate(exc_info) == "23001"


def test_account_currency_and_normal_balance_are_frozen_even_for_owner(db_session, owner_session, tenant_id):
    account = make_account(db_session, tenant_id, normal_balance=NormalBalance.debit)
    for statement in (
        "UPDATE accounts SET currency = 'USD' WHERE id = :id",
        "UPDATE accounts SET normal_balance = 'credit' WHERE id = :id",
        "DELETE FROM accounts WHERE id = :id",
    ):
        with pytest.raises(IntegrityError) as exc_info:
            owner_session.execute(text(statement), {"id": account.id})
        assert _sqlstate(exc_info) == "23001"
        owner_session.rollback()


def test_unknown_currency_is_rejected(db_session, tenant_id):
    with pytest.raises(IntegrityError) as exc_info:
        make_account(db_session, tenant_id, currency="XYZ")
    assert _sqlstate(exc_info) == "23503"
```

- [x] **Step 5: Run the tests to confirm they fail**

Run: `.venv/bin/pytest tests/test_ledger_invariants.py -v`
Expected: ERROR, with `ImportError: cannot import name 'Tenant' from 'app.ledger.models'`.

- [x] **Step 6: Replace `backend/app/ledger/models.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, SmallInteger, Text, TIMESTAMP, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.ledger.types import Direction, NormalBalance, PostingSource

__all__ = ["Base", "Currency", "Tenant", "Account", "Posting", "Entry", "Direction"]


class Base(DeclarativeBase):
    pass


class Currency(Base):
    __tablename__ = "currencies"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    minor_units: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class Tenant(Base):
    __tablename__ = "tenants"
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class Account(Base):
    __tablename__ = "accounts"
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(Text, ForeignKey("currencies.code"), nullable=False)
    normal_balance: Mapped[NormalBalance] = mapped_column(
        SAEnum(NormalBalance, name="normal_balance", native_enum=True), nullable=False
    )
    gl_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class Posting(Base):
    __tablename__ = "postings"
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[PostingSource] = mapped_column(
        SAEnum(PostingSource, name="posting_source", native_enum=True), nullable=False
    )
    reverses_posting_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("postings.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    entries: Mapped[list["Entry"]] = relationship(back_populates="posting", order_by="Entry.id")


class Entry(Base):
    __tablename__ = "entries"
    __mapper_args__ = {"eager_defaults": True}

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

    __table_args__ = (CheckConstraint("amount > 0", name="ck_entries_amount_positive"),)
```

- [x] **Step 7: Create `backend/alembic/versions/0004_ledger_core.py`**

```python
"""ledger core: tenants, currencies, fingerprints, append-only facts, posting validity

Revision ID: 0004_ledger_core
Revises: 0003_app_role_grants
"""
from alembic import op

revision = "0004_ledger_core"
down_revision = "0003_app_role_grants"
branch_labels = None
depends_on = None

DEMO_TENANT_ID = "00000000-0000-0000-0000-000000000001"


# Helpers are local on purpose: a migration is a frozen snapshot and must never
# import code that can change after it ships.
def _run(*statements: str) -> None:
    for statement in statements:
        op.execute(statement)


def _append_only(table: str) -> None:
    _run(
        f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION forbid_mutation()",
        f"CREATE TRIGGER trg_{table}_no_truncate BEFORE TRUNCATE ON {table} "
        "FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()",
    )


def _drop_append_only(table: str) -> None:
    _run(
        f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}",
        f"DROP TRIGGER IF EXISTS trg_{table}_no_truncate ON {table}",
    )


def upgrade() -> None:
    # --- reference data -------------------------------------------------------
    _run(
        "CREATE TABLE currencies ("
        " code text PRIMARY KEY CHECK (code ~ '^[A-Z]{3}$'),"
        " minor_units smallint NOT NULL CHECK (minor_units BETWEEN 0 AND 4))",
        "INSERT INTO currencies (code, minor_units) VALUES ('CAD', 2), ('USD', 2)",
        "CREATE TABLE tenants ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " name text NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now())",
        f"INSERT INTO tenants (id, name) VALUES ('{DEMO_TENANT_ID}', 'Demo tenant')",
        "CREATE TYPE normal_balance AS ENUM ('debit', 'credit')",
        "CREATE TYPE posting_source AS ENUM ('api', 'fee_run', 'ai_tool', 'stress_test')",
    )

    # --- accounts ----------------------------------------------------------------
    _run(
        f"ALTER TABLE accounts ADD COLUMN tenant_id uuid NOT NULL DEFAULT '{DEMO_TENANT_ID}' REFERENCES tenants(id)",
        "ALTER TABLE accounts ALTER COLUMN tenant_id DROP DEFAULT",
        "ALTER TABLE accounts ADD CONSTRAINT fk_accounts_currency FOREIGN KEY (currency) REFERENCES currencies(code)",
        "ALTER TABLE accounts ADD COLUMN normal_balance normal_balance NOT NULL DEFAULT 'debit'",
        "ALTER TABLE accounts ALTER COLUMN normal_balance DROP DEFAULT",
        "ALTER TABLE accounts ADD COLUMN gl_code text NULL CONSTRAINT ck_accounts_gl_code_not_blank CHECK (gl_code <> '')",
    )

    # --- postings ----------------------------------------------------------------
    _run(
        f"ALTER TABLE postings ADD COLUMN tenant_id uuid NOT NULL DEFAULT '{DEMO_TENANT_ID}' REFERENCES tenants(id)",
        "ALTER TABLE postings ALTER COLUMN tenant_id DROP DEFAULT",
        "ALTER TABLE postings ADD COLUMN effective_at timestamptz NOT NULL DEFAULT now()",
        "ALTER TABLE postings ADD COLUMN request_fingerprint text",
        # Legacy dev rows were never seen by an API client; fingerprint them by id.
        "UPDATE postings SET request_fingerprint = encode(sha256(id::text::bytea), 'hex')",
        "ALTER TABLE postings ALTER COLUMN request_fingerprint SET NOT NULL",
        "ALTER TABLE postings ADD CONSTRAINT ck_postings_fingerprint_sha256 CHECK (request_fingerprint ~ '^[0-9a-f]{64}$')",
        "ALTER TABLE postings ADD COLUMN source posting_source NOT NULL DEFAULT 'api'",
        "ALTER TABLE postings ALTER COLUMN source DROP DEFAULT",
        "ALTER TABLE postings ADD COLUMN reverses_posting_id uuid NULL REFERENCES postings(id)",
        "ALTER TABLE postings ADD CONSTRAINT uq_postings_reverses_posting_id UNIQUE (reverses_posting_id)",
        "ALTER TABLE postings ADD CONSTRAINT ck_postings_not_self_reversal CHECK (reverses_posting_id <> id)",
        "ALTER TABLE postings DROP CONSTRAINT postings_idempotency_key_key",
        "ALTER TABLE postings ADD CONSTRAINT uq_postings_tenant_idempotency_key UNIQUE (tenant_id, idempotency_key)",
        "ALTER TABLE postings ADD CONSTRAINT ck_postings_idempotency_key_length CHECK (char_length(idempotency_key) BETWEEN 1 AND 255)",
        "CREATE INDEX ix_postings_tenant_created ON postings (tenant_id, created_at DESC, id DESC)",
    )

    # --- replace the insert-only balance trigger ------------------------------------
    _run(
        "DROP TRIGGER trg_check_posting_balance ON entries",
        "DROP FUNCTION check_posting_balance()",
    )

    # --- append-only facts ----------------------------------------------------------
    _run(
        """
        CREATE FUNCTION forbid_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION '% is append-only: % is not allowed; record a new fact (reversal or new version) instead',
            TG_TABLE_NAME, TG_OP
            USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in ("currencies", "postings", "entries"):
        _append_only(table)

    _run(
        """
        CREATE FUNCTION guard_account_change() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'accounts cannot be deleted' USING ERRCODE = 'restrict_violation';
          END IF;
          IF NEW.id IS DISTINCT FROM OLD.id
             OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
             OR NEW.currency IS DISTINCT FROM OLD.currency
             OR NEW.normal_balance IS DISTINCT FROM OLD.normal_balance
             OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
            RAISE EXCEPTION 'account % : only name and a first gl_code may change', OLD.id
              USING ERRCODE = 'restrict_violation';
          END IF;
          IF OLD.gl_code IS NOT NULL AND NEW.gl_code IS DISTINCT FROM OLD.gl_code THEN
            RAISE EXCEPTION 'account % : gl_code can be set once and never changed', OLD.id
              USING ERRCODE = 'restrict_violation';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """,
        "CREATE TRIGGER trg_accounts_guard BEFORE UPDATE OR DELETE ON accounts "
        "FOR EACH ROW EXECUTE FUNCTION guard_account_change()",
        "CREATE TRIGGER trg_accounts_no_truncate BEFORE TRUNCATE ON accounts "
        "FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()",
        "GRANT UPDATE (name, gl_code) ON accounts TO ledger_app",
    )

    # --- posting validity, checked at commit ----------------------------------------------
    _run(
        """
        CREATE FUNCTION assert_posting_valid(p_id uuid) RETURNS void AS $$
        DECLARE
          v_tenant uuid;
          v_reverses uuid;
        BEGIN
          SELECT tenant_id, reverses_posting_id INTO v_tenant, v_reverses
            FROM postings WHERE id = p_id;

          IF NOT EXISTS (SELECT 1 FROM entries WHERE posting_id = p_id AND direction = 'debit')
             OR NOT EXISTS (SELECT 1 FROM entries WHERE posting_id = p_id AND direction = 'credit') THEN
            RAISE EXCEPTION 'posting % needs at least one debit and one credit entry', p_id
              USING ERRCODE = 'check_violation';
          END IF;

          IF EXISTS (
            SELECT 1
              FROM entries e JOIN accounts a ON a.id = e.account_id
             WHERE e.posting_id = p_id
             GROUP BY a.currency
            HAVING SUM(CASE WHEN e.direction = 'debit' THEN e.amount ELSE -e.amount END) <> 0
          ) THEN
            RAISE EXCEPTION 'posting % does not balance per currency', p_id
              USING ERRCODE = 'check_violation';
          END IF;

          IF EXISTS (
            SELECT 1 FROM entries e JOIN accounts a ON a.id = e.account_id
             WHERE e.posting_id = p_id AND a.tenant_id <> v_tenant
          ) THEN
            RAISE EXCEPTION 'posting % touches an account of another tenant', p_id
              USING ERRCODE = 'check_violation';
          END IF;

          IF v_reverses IS NOT NULL AND EXISTS (
            (SELECT account_id,
                    CASE direction WHEN 'debit' THEN 'credit'::entry_direction ELSE 'debit'::entry_direction END,
                    amount
               FROM entries WHERE posting_id = v_reverses
             EXCEPT ALL
             SELECT account_id, direction, amount FROM entries WHERE posting_id = p_id)
            UNION ALL
            (SELECT account_id, direction, amount FROM entries WHERE posting_id = p_id
             EXCEPT ALL
             SELECT account_id,
                    CASE direction WHEN 'debit' THEN 'credit'::entry_direction ELSE 'debit'::entry_direction END,
                    amount
               FROM entries WHERE posting_id = v_reverses)
          ) THEN
            RAISE EXCEPTION 'posting % must exactly mirror the posting it reverses (%)', p_id, v_reverses
              USING ERRCODE = 'check_violation';
          END IF;
        END;
        $$ LANGUAGE plpgsql
        """,
        """
        CREATE FUNCTION check_posting_from_posting() RETURNS trigger AS $$
        BEGIN
          PERFORM assert_posting_valid(NEW.id);
          RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """,
        """
        CREATE FUNCTION check_posting_from_entry() RETURNS trigger AS $$
        BEGIN
          PERFORM assert_posting_valid(NEW.posting_id);
          RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """,
        # On postings too: a posting with zero entries never fires an entries trigger.
        "CREATE CONSTRAINT TRIGGER trg_postings_valid AFTER INSERT ON postings "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_posting_from_posting()",
        "CREATE CONSTRAINT TRIGGER trg_entries_valid AFTER INSERT ON entries "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_posting_from_entry()",
    )


def downgrade() -> None:
    _run(
        "DROP TRIGGER IF EXISTS trg_entries_valid ON entries",
        "DROP TRIGGER IF EXISTS trg_postings_valid ON postings",
        "DROP FUNCTION IF EXISTS check_posting_from_entry()",
        "DROP FUNCTION IF EXISTS check_posting_from_posting()",
        "DROP FUNCTION IF EXISTS assert_posting_valid(uuid)",
        "REVOKE UPDATE ON accounts FROM ledger_app",
        "DROP TRIGGER IF EXISTS trg_accounts_no_truncate ON accounts",
        "DROP TRIGGER IF EXISTS trg_accounts_guard ON accounts",
        "DROP FUNCTION IF EXISTS guard_account_change()",
    )
    for table in ("entries", "postings", "currencies"):
        _drop_append_only(table)
    _run(
        "DROP FUNCTION IF EXISTS forbid_mutation()",
        "DROP INDEX IF EXISTS ix_postings_tenant_created",
        "ALTER TABLE postings DROP CONSTRAINT uq_postings_tenant_idempotency_key",
        "ALTER TABLE postings ADD CONSTRAINT postings_idempotency_key_key UNIQUE (idempotency_key)",
        "ALTER TABLE postings DROP CONSTRAINT ck_postings_idempotency_key_length",
        "ALTER TABLE postings DROP CONSTRAINT ck_postings_not_self_reversal",
        "ALTER TABLE postings DROP CONSTRAINT uq_postings_reverses_posting_id",
        "ALTER TABLE postings DROP COLUMN reverses_posting_id",
        "ALTER TABLE postings DROP COLUMN source",
        "ALTER TABLE postings DROP COLUMN request_fingerprint",
        "ALTER TABLE postings DROP COLUMN effective_at",
        "ALTER TABLE postings DROP COLUMN tenant_id",
        "ALTER TABLE accounts DROP COLUMN gl_code",
        "ALTER TABLE accounts DROP COLUMN normal_balance",
        "ALTER TABLE accounts DROP CONSTRAINT fk_accounts_currency",
        "ALTER TABLE accounts DROP COLUMN tenant_id",
        "DROP TYPE posting_source",
        "DROP TYPE normal_balance",
        "DROP TABLE tenants",
        "DROP TABLE currencies",
        # restore migration 0002's insert-only balance trigger exactly
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
              NEW.posting_id, imbalance
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;

          RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """,
        "CREATE CONSTRAINT TRIGGER trg_check_posting_balance AFTER INSERT ON entries "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_posting_balance()",
    )
```

- [x] **Step 8: Delete the obsolete DAO tests**

```bash
git rm tests/test_ledger_dao.py
```

These tests call `create_account(session, name, currency)` and `create_posting(session, key, description, entries)`, which can no longer satisfy the new NOT NULL columns. Task 3 rewrites the DAO and adds a complete replacement test file.

- [x] **Step 9: Run the invariant tests and the migration round-trip**

Run: `.venv/bin/pytest tests/test_ledger_invariants.py tests/test_migrations.py tests/test_db_session.py -v`
Expected: PASS (all tests, including 3 parametrized owner cases).

- [x] **Step 10: Commit**

```bash
git add app/ledger/types.py app/ledger/models.py alembic/versions/0004_ledger_core.py tests/support.py tests/conftest.py tests/test_ledger_invariants.py
git commit -m "feat(ledger): enforce append-only history and per-currency posting validity in Postgres" -m "Adds tenants, currencies, fingerprints, reversal links and database triggers so unbalanced, empty, cross-tenant or non-mirroring postings and any rewrite of history are rejected even for the schema owner."
```

---

### Task 3: Fingerprint, domain errors, and the single posting write path

**Files:**
- Create: `backend/app/errors.py`
- Create: `backend/app/ledger/errors.py`
- Create: `backend/app/ledger/fingerprint.py`
- Modify: `backend/app/ledger/dao.py` (whole file)
- Create: `backend/tests/test_fingerprint.py`
- Create: `backend/tests/test_ledger_dao.py`

**Interfaces:**
- Consumes: models and types from Task 2; the `tenant_id` fixture.
- Produces (`app.errors`): `DomainError(detail: str, **extensions)` with class attributes `status: int`, `type_slug: str`, `title: str`, and method `headers() -> dict[str, str]`.
- Produces (`app.ledger.errors`): `PostingInvalid(reasons: list[str])`, `IdempotencyKeyMissing`, `IdempotencyKeyInvalid`, `IdempotencyKeyReused`, `RequestInProgress`, `PostingNotFound`, `PostingAlreadyReversed`, `AppendOnlyViolation`, `CursorInvalid`, all subclasses of `DomainError`.
- Produces (`app.ledger.fingerprint`): `canonical_json(value: object) -> str`, `sha256_hex(text: str) -> str`, `posting_fingerprint(*, description: str | None, effective_at: datetime | None, source: str, reverses_posting_id: uuid.UUID | None, entries: Iterable[tuple[uuid.UUID, str, int]]) -> str`.
- Produces (`app.ledger.dao`):
  - `EntryInput(account_id: uuid.UUID, direction: Direction, amount: int)` (frozen dataclass)
  - `PostingRequest(tenant_id, idempotency_key, entries: tuple[EntryInput, ...], description=None, source=PostingSource.api, effective_at=None, reverses_posting_id=None)` (frozen)
  - `PostingResult(posting: Posting, replayed: bool)` (frozen)
  - `create_account(session, *, tenant_id, name, currency, normal_balance, gl_code=None) -> Account` (commits)
  - `ledger_transaction(session) -> ContextManager[None]`
  - `create_posting(session, request: PostingRequest) -> PostingResult` (use inside `ledger_transaction`)
  - `reverse_posting(session, *, tenant_id, posting_id, description=None) -> PostingResult` (use inside `ledger_transaction`)
  - `get_posting(session, *, tenant_id, posting_id) -> Posting` (entries loaded; raises `PostingNotFound`)
  - `list_postings(session, *, tenant_id, source: PostingSource | None, include_stress: bool, limit: int, before: tuple[datetime, uuid.UUID] | None) -> list[Posting]`
  - `reversal_ids_for(session, posting_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]` (original id → reversal id)

- [ ] **Step 1: Write the failing fingerprint tests (`backend/tests/test_fingerprint.py`)**

```python
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.ledger.fingerprint import canonical_json, posting_fingerprint

A = uuid.UUID("00000000-0000-0000-0000-00000000000a")
B = uuid.UUID("00000000-0000-0000-0000-00000000000b")


def _fp(entries, *, effective_at=None, description="Fee"):
    return posting_fingerprint(
        description=description,
        effective_at=effective_at,
        source="api",
        reverses_posting_id=None,
        entries=entries,
    )


def test_canonical_json_sorts_keys_and_strips_whitespace():
    assert canonical_json({"b": 1, "a": [1, 2]}) == '{"a":[1,2],"b":1}'


def test_fingerprint_ignores_entry_order():
    assert _fp([(A, "debit", 100), (B, "credit", 100)]) == _fp([(B, "credit", 100), (A, "debit", 100)])


def test_fingerprint_changes_when_an_amount_changes():
    assert _fp([(A, "debit", 100), (B, "credit", 100)]) != _fp([(A, "debit", 101), (B, "credit", 101)])


def test_fingerprint_treats_equal_instants_in_different_offsets_as_equal():
    utc = datetime(2026, 9, 30, 0, 0, tzinfo=timezone.utc)
    toronto = datetime(2026, 9, 29, 20, 0, tzinfo=timezone(timedelta(hours=-4)))
    entries = [(A, "debit", 1), (B, "credit", 1)]
    assert _fp(entries, effective_at=utc) == _fp(entries, effective_at=toronto)


def test_fingerprint_rejects_naive_timestamps():
    with pytest.raises(ValueError):
        _fp([(A, "debit", 1), (B, "credit", 1)], effective_at=datetime(2026, 9, 30))


def test_fingerprint_is_64_lowercase_hex():
    value = _fp([(A, "debit", 1), (B, "credit", 1)])
    assert len(value) == 64 and value == value.lower()
```

- [ ] **Step 2: Run to confirm it fails**

Run: `.venv/bin/pytest tests/test_fingerprint.py -v`
Expected: ERROR `ModuleNotFoundError: No module named 'app.ledger.fingerprint'`.

- [ ] **Step 3: Create `backend/app/ledger/fingerprint.py`**

```python
import hashlib
import json
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone


def canonical_json(value: object) -> str:
    """Deterministic JSON: sorted keys, no whitespace.

    Equivalent to RFC 8785 (JCS) for payloads that contain no floats, which is
    guaranteed here because amounts are integer minor units.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("effective_at must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


def posting_fingerprint(
    *,
    description: str | None,
    effective_at: datetime | None,
    source: str,
    reverses_posting_id: uuid.UUID | None,
    entries: Iterable[tuple[uuid.UUID, str, int]],
) -> str:
    """Hash of the business meaning of a posting request, used to tell a retry from a key reuse."""
    normalized_entries = sorted(
        (
            {"account_id": str(account_id), "direction": direction, "amount": amount}
            for account_id, direction, amount in entries
        ),
        key=lambda entry: (entry["account_id"], entry["direction"], entry["amount"]),
    )
    payload = {
        "description": description,
        "effective_at": _utc_iso(effective_at),
        "entries": normalized_entries,
        "reverses_posting_id": None if reverses_posting_id is None else str(reverses_posting_id),
        "source": source,
    }
    return sha256_hex(canonical_json(payload))
```

- [ ] **Step 4: Run the fingerprint tests**

Run: `.venv/bin/pytest tests/test_fingerprint.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Create `backend/app/errors.py`**

```python
class DomainError(Exception):
    """An expected business error that the API renders as RFC 9457 problem+json."""

    status: int = 500
    type_slug: str = "internal-error"
    title: str = "Internal error"

    def __init__(self, detail: str, **extensions: object) -> None:
        super().__init__(detail)
        self.detail = detail
        self.extensions = extensions

    def headers(self) -> dict[str, str]:
        return {}
```

- [ ] **Step 6: Create `backend/app/ledger/errors.py`**

```python
from app.errors import DomainError


class PostingInvalid(DomainError):
    status = 422
    type_slug = "posting-invalid"
    title = "Posting is invalid"

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons), reasons=reasons)
        self.reasons = reasons


class IdempotencyKeyMissing(DomainError):
    status = 400
    type_slug = "idempotency-key-missing"
    title = "Idempotency-Key header is required"


class IdempotencyKeyInvalid(DomainError):
    status = 400
    type_slug = "idempotency-key-invalid"
    title = "Idempotency-Key header is invalid"


class IdempotencyKeyReused(DomainError):
    status = 422
    type_slug = "idempotency-key-reused"
    title = "Idempotency-Key was already used with a different payload"


class RequestInProgress(DomainError):
    status = 409
    type_slug = "request-in-progress"
    title = "A request with this Idempotency-Key is still being processed"

    def headers(self) -> dict[str, str]:
        return {"Retry-After": "1"}


class PostingNotFound(DomainError):
    status = 404
    type_slug = "posting-not-found"
    title = "Posting not found"


class PostingAlreadyReversed(DomainError):
    status = 409
    type_slug = "posting-already-reversed"
    title = "Posting has already been reversed"


class AppendOnlyViolation(DomainError):
    status = 500
    type_slug = "append-only-violation"
    title = "Attempted to rewrite append-only history"


class CursorInvalid(DomainError):
    status = 400
    type_slug = "cursor-invalid"
    title = "Pagination cursor is invalid"
```

- [ ] **Step 7: Write the failing DAO tests (`backend/tests/test_ledger_dao.py`)**

```python
import uuid
from datetime import datetime, timezone

import pytest

from app.ledger.dao import (
    EntryInput,
    PostingRequest,
    create_account,
    create_posting,
    get_posting,
    ledger_transaction,
    list_postings,
    reversal_ids_for,
    reverse_posting,
)
from app.ledger.errors import (
    IdempotencyKeyReused,
    PostingAlreadyReversed,
    PostingInvalid,
    PostingNotFound,
    RequestInProgress,
)
from app.ledger.models import Entry, Posting
from app.ledger.types import Direction, NormalBalance, PostingSource

DEBIT, CREDIT = Direction.debit, Direction.credit


@pytest.fixture()
def pair(db_session, tenant_id):
    cash = create_account(
        db_session, tenant_id=tenant_id, name="Cash", currency="CAD", normal_balance=NormalBalance.debit
    )
    revenue = create_account(
        db_session, tenant_id=tenant_id, name="Revenue", currency="CAD", normal_balance=NormalBalance.credit
    )
    return cash, revenue


def _request(tenant_id, pair, *, key=None, amount=1000, **overrides):
    cash, revenue = pair
    fields = dict(
        tenant_id=tenant_id,
        idempotency_key=key or str(uuid.uuid4()),
        description="Sale",
        entries=(EntryInput(cash.id, DEBIT, amount), EntryInput(revenue.id, CREDIT, amount)),
    )
    fields.update(overrides)
    return PostingRequest(**fields)


def _post(session, request):
    with ledger_transaction(session):
        return create_posting(session, request)


def test_create_account_persists_tenant_and_normal_balance(db_session, tenant_id):
    account = create_account(
        db_session, tenant_id=tenant_id, name="Cash", currency="CAD", normal_balance=NormalBalance.debit, gl_code="1000"
    )
    assert (account.tenant_id, account.currency, account.normal_balance, account.gl_code) == (
        tenant_id, "CAD", NormalBalance.debit, "1000",
    )


def test_new_posting_is_created_with_fingerprint_and_entries(db_session, tenant_id, pair):
    result = _post(db_session, _request(tenant_id, pair))
    assert result.replayed is False
    assert result.posting.source is PostingSource.api
    assert len(result.posting.request_fingerprint) == 64
    assert sorted(e.amount for e in result.posting.entries) == [1000, 1000]


def test_same_key_same_payload_replays_without_a_second_insert(db_session, tenant_id, pair):
    request = _request(tenant_id, pair)
    first = _post(db_session, request)
    second = _post(db_session, request)
    assert second.replayed is True
    assert second.posting.id == first.posting.id
    assert db_session.query(Entry).filter(Entry.posting_id == first.posting.id).count() == 2


def test_same_key_with_entries_reordered_is_still_a_replay(db_session, tenant_id, pair):
    request = _request(tenant_id, pair)
    _post(db_session, request)
    reordered = PostingRequest(
        tenant_id=request.tenant_id,
        idempotency_key=request.idempotency_key,
        description=request.description,
        entries=tuple(reversed(request.entries)),
    )
    assert _post(db_session, reordered).replayed is True


def test_same_key_different_payload_is_rejected(db_session, tenant_id, pair):
    key = str(uuid.uuid4())
    _post(db_session, _request(tenant_id, pair, key=key, amount=1000))
    with pytest.raises(IdempotencyKeyReused):
        _post(db_session, _request(tenant_id, pair, key=key, amount=999))


@pytest.mark.parametrize(
    ("entries_builder", "expected_reason"),
    [
        (lambda c, r: (EntryInput(c.id, DEBIT, 10),), "at least one debit and one credit"),
        (lambda c, r: (EntryInput(c.id, DEBIT, 10), EntryInput(r.id, CREDIT, 9)), "balance per currency"),
        (lambda c, r: (EntryInput(c.id, DEBIT, 0), EntryInput(r.id, CREDIT, 0)), "positive integer"),
        (lambda c, r: (EntryInput(c.id, DEBIT, True), EntryInput(r.id, CREDIT, True)), "positive integer"),
        (lambda c, r: (EntryInput(uuid.uuid4(), DEBIT, 5), EntryInput(r.id, CREDIT, 5)), "unknown accounts"),
    ],
)
def test_invalid_postings_are_rejected_before_the_database(db_session, tenant_id, pair, entries_builder, expected_reason):
    cash, revenue = pair
    request = _request(tenant_id, pair, entries=entries_builder(cash, revenue))
    with pytest.raises(PostingInvalid) as exc_info:
        _post(db_session, request)
    assert any(expected_reason in reason for reason in exc_info.value.reasons)


def test_naive_effective_at_is_rejected(db_session, tenant_id, pair):
    with pytest.raises(PostingInvalid) as exc_info:
        _post(db_session, _request(tenant_id, pair, effective_at=datetime(2026, 9, 30)))
    assert any("timezone" in reason for reason in exc_info.value.reasons)


def test_database_check_violation_is_translated_to_posting_invalid(db_session, tenant_id, pair):
    original = _post(db_session, _request(tenant_id, pair, amount=1000)).posting
    cash, revenue = pair
    # Balanced, so Python validation passes, but it isn't a mirror: only the database catches this.
    not_a_mirror = _request(
        tenant_id,
        pair,
        entries=(EntryInput(cash.id, CREDIT, 400), EntryInput(revenue.id, DEBIT, 400)),
        reverses_posting_id=original.id,
    )
    with pytest.raises(PostingInvalid):
        _post(db_session, not_a_mirror)


def test_reverse_posting_mirrors_links_and_is_idempotent(db_session, tenant_id, pair):
    original = _post(db_session, _request(tenant_id, pair, amount=750)).posting
    with ledger_transaction(db_session):
        first = reverse_posting(db_session, tenant_id=tenant_id, posting_id=original.id)
    with ledger_transaction(db_session):
        second = reverse_posting(db_session, tenant_id=tenant_id, posting_id=original.id)
    assert first.replayed is False and second.replayed is True
    assert first.posting.reverses_posting_id == original.id
    assert first.posting.effective_at == original.effective_at
    mirrored = {(e.account_id, e.direction, e.amount) for e in first.posting.entries}
    flipped = {(e.account_id, CREDIT if e.direction is DEBIT else DEBIT, e.amount) for e in original.entries}
    assert mirrored == flipped
    assert reversal_ids_for(db_session, [original.id]) == {original.id: first.posting.id}


def test_a_reversal_can_itself_be_reversed(db_session, tenant_id, pair):
    original = _post(db_session, _request(tenant_id, pair)).posting
    with ledger_transaction(db_session):
        reversal = reverse_posting(db_session, tenant_id=tenant_id, posting_id=original.id).posting
    with ledger_transaction(db_session):
        re_reversal = reverse_posting(db_session, tenant_id=tenant_id, posting_id=reversal.id).posting
    assert re_reversal.reverses_posting_id == reversal.id


def test_second_reversal_under_a_different_key_is_rejected(db_session, tenant_id, pair):
    original = _post(db_session, _request(tenant_id, pair)).posting
    with ledger_transaction(db_session):
        reverse_posting(db_session, tenant_id=tenant_id, posting_id=original.id)
    cash, revenue = pair
    sneaky = _request(
        tenant_id,
        pair,
        entries=(EntryInput(cash.id, CREDIT, 1000), EntryInput(revenue.id, DEBIT, 1000)),
        reverses_posting_id=original.id,
    )
    with pytest.raises(PostingAlreadyReversed):
        _post(db_session, sneaky)


def test_reversing_an_unknown_posting_raises_not_found(db_session, tenant_id):
    with pytest.raises(PostingNotFound):
        with ledger_transaction(db_session):
            reverse_posting(db_session, tenant_id=tenant_id, posting_id=uuid.uuid4())


def test_get_posting_is_scoped_to_the_tenant(db_session, tenant_id, pair):
    posting = _post(db_session, _request(tenant_id, pair)).posting
    assert get_posting(db_session, tenant_id=tenant_id, posting_id=posting.id).id == posting.id
    with pytest.raises(PostingNotFound):
        get_posting(db_session, tenant_id=uuid.uuid4(), posting_id=posting.id)


def test_list_postings_hides_stress_traffic_and_paginates(db_session, tenant_id, pair):
    api_ids = [_post(db_session, _request(tenant_id, pair)).posting.id for _ in range(3)]
    _post(db_session, _request(tenant_id, pair, source=PostingSource.stress_test))

    page_one = list_postings(db_session, tenant_id=tenant_id, source=None, include_stress=False, limit=2, before=None)
    cursor = (page_one[-1].created_at, page_one[-1].id)
    page_two = list_postings(db_session, tenant_id=tenant_id, source=None, include_stress=False, limit=2, before=cursor)

    assert {p.id for p in page_one} | {p.id for p in page_two} == set(api_ids)
    assert not {p.id for p in page_one} & {p.id for p in page_two}
    only_stress = list_postings(
        db_session, tenant_id=tenant_id, source=PostingSource.stress_test, include_stress=False, limit=10, before=None
    )
    assert [p.source for p in only_stress] == [PostingSource.stress_test]


def test_concurrent_duplicate_times_out_as_request_in_progress(db_session, session_factory, tenant_id, pair):
    request = _request(tenant_id, pair)
    holder = session_factory()
    try:
        create_posting(holder, request)  # flushed, not committed: holds the unique-index slot
        with pytest.raises(RequestInProgress):
            _post(db_session, request)
    finally:
        holder.rollback()
        holder.close()
    assert db_session.query(Posting).filter(Posting.idempotency_key == request.idempotency_key).count() == 0
```

- [ ] **Step 8: Run to confirm it fails**

Run: `.venv/bin/pytest tests/test_ledger_dao.py -v`
Expected: ERROR `ImportError: cannot import name 'PostingRequest' from 'app.ledger.dao'`.

- [ ] **Step 9: Replace `backend/app/ledger/dao.py`**

```python
import dataclasses
import uuid
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import select, text, tuple_
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, selectinload

from app.ledger.errors import (
    AppendOnlyViolation,
    IdempotencyKeyReused,
    PostingAlreadyReversed,
    PostingInvalid,
    PostingNotFound,
    RequestInProgress,
)
from app.ledger.fingerprint import posting_fingerprint
from app.ledger.models import Account, Entry, Posting
from app.ledger.types import Direction, NormalBalance, PostingSource

LOCK_TIMEOUT = "2s"
# Bounds how long any ledger statement can run. The GL export's settle margin depends on this.
STATEMENT_TIMEOUT = "10s"
MAX_IDEMPOTENCY_KEY_LENGTH = 255

UNIQUE_IDEMPOTENCY_CONSTRAINT = "uq_postings_tenant_idempotency_key"
UNIQUE_REVERSAL_CONSTRAINT = "uq_postings_reverses_posting_id"
SQLSTATE_CHECK_VIOLATION = "23514"
SQLSTATE_RESTRICT_VIOLATION = "23001"
SQLSTATE_LOCK_NOT_AVAILABLE = "55P03"


@dataclasses.dataclass(frozen=True)
class EntryInput:
    account_id: uuid.UUID
    direction: Direction
    amount: int


@dataclasses.dataclass(frozen=True)
class PostingRequest:
    tenant_id: uuid.UUID
    idempotency_key: str
    entries: tuple[EntryInput, ...]
    description: str | None = None
    source: PostingSource = PostingSource.api
    effective_at: datetime | None = None
    reverses_posting_id: uuid.UUID | None = None


@dataclasses.dataclass(frozen=True)
class PostingResult:
    posting: Posting
    replayed: bool


def create_account(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    name: str,
    currency: str,
    normal_balance: NormalBalance,
    gl_code: str | None = None,
) -> Account:
    account = Account(
        tenant_id=tenant_id, name=name, currency=currency, normal_balance=normal_balance, gl_code=gl_code
    )
    session.add(account)
    session.commit()
    return account


def _sqlstate(exc: Exception) -> str | None:
    return getattr(getattr(exc, "orig", None), "sqlstate", None)


def _constraint_name(exc: Exception) -> str | None:
    diag = getattr(getattr(exc, "orig", None), "diag", None)
    return getattr(diag, "constraint_name", None)


def _primary_message(exc: Exception) -> str:
    diag = getattr(getattr(exc, "orig", None), "diag", None)
    return getattr(diag, "message_primary", None) or str(exc)


@contextmanager
def ledger_transaction(session: Session) -> Iterator[None]:
    """Unit of work for ledger writes: bounded lock wait and statement time, commit
    on success, database invariant violations translated into domain errors."""
    try:
        session.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
        session.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
        yield
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        state = _sqlstate(exc)
        if state == SQLSTATE_CHECK_VIOLATION:
            raise PostingInvalid([_primary_message(exc)]) from exc
        if state == SQLSTATE_RESTRICT_VIOLATION:
            raise AppendOnlyViolation(_primary_message(exc)) from exc
        raise
    except OperationalError as exc:
        session.rollback()
        if _sqlstate(exc) == SQLSTATE_LOCK_NOT_AVAILABLE:
            raise RequestInProgress(
                "A request with this Idempotency-Key is still being processed; retry shortly."
            ) from exc
        raise
    except BaseException:
        session.rollback()
        raise


def _accounts_by_id(session: Session, request: PostingRequest) -> dict[uuid.UUID, Account]:
    ids = {entry.account_id for entry in request.entries}
    if not ids:
        return {}
    return {account.id: account for account in session.scalars(select(Account).where(Account.id.in_(ids)))}


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _validate(request: PostingRequest, accounts: Mapping[uuid.UUID, Account]) -> None:
    reasons: list[str] = []
    if not 1 <= len(request.idempotency_key) <= MAX_IDEMPOTENCY_KEY_LENGTH:
        reasons.append(f"idempotency_key must be 1-{MAX_IDEMPOTENCY_KEY_LENGTH} characters")
    if request.effective_at is not None and request.effective_at.tzinfo is None:
        reasons.append("effective_at must include a timezone offset")

    directions = {entry.direction for entry in request.entries}
    if Direction.debit not in directions or Direction.credit not in directions:
        reasons.append("a posting needs at least one debit and one credit entry")

    bad_amounts = [entry.amount for entry in request.entries if not _is_positive_int(entry.amount)]
    for amount in bad_amounts:
        reasons.append(f"entry amount must be a positive integer in minor units, got {amount!r}")

    missing = sorted({str(entry.account_id) for entry in request.entries if entry.account_id not in accounts})
    if missing:
        reasons.append(f"unknown accounts: {', '.join(missing)}")

    foreign = sorted({str(a.id) for a in accounts.values() if a.tenant_id != request.tenant_id})
    if foreign:
        reasons.append(f"accounts belong to another tenant: {', '.join(foreign)}")

    if not missing and not bad_amounts:
        net_by_currency: dict[str, int] = defaultdict(int)
        for entry in request.entries:
            signed = entry.amount if entry.direction is Direction.debit else -entry.amount
            net_by_currency[accounts[entry.account_id].currency] += signed
        unbalanced = sorted((c, v) for c, v in net_by_currency.items() if v != 0)
        if unbalanced:
            reasons.append(
                "debits and credits must balance per currency: "
                + ", ".join(f"{currency} off by {value}" for currency, value in unbalanced)
            )

    if reasons:
        raise PostingInvalid(reasons)


def _fingerprint(request: PostingRequest) -> str:
    return posting_fingerprint(
        description=request.description,
        effective_at=request.effective_at,
        source=request.source.value,
        reverses_posting_id=request.reverses_posting_id,
        entries=[(e.account_id, e.direction.value, e.amount) for e in request.entries],
    )


def _replay_or_reject(session: Session, request: PostingRequest, fingerprint: str) -> PostingResult:
    existing = session.scalars(
        select(Posting)
        .options(selectinload(Posting.entries))
        .where(Posting.tenant_id == request.tenant_id, Posting.idempotency_key == request.idempotency_key)
    ).one()
    if existing.request_fingerprint == fingerprint:
        return PostingResult(posting=existing, replayed=True)
    raise IdempotencyKeyReused(
        f"Idempotency-Key {request.idempotency_key!r} was already used with a different payload."
    )


def create_posting(session: Session, request: PostingRequest) -> PostingResult:
    """Add a validated posting to the session's current transaction; call inside ledger_transaction.

    If the same idempotency key was already used with the same payload, the
    existing posting is returned with replayed=True and nothing new is written.
    """
    accounts = _accounts_by_id(session, request)
    _validate(request, accounts)
    fingerprint = _fingerprint(request)

    posting = Posting(
        tenant_id=request.tenant_id,
        idempotency_key=request.idempotency_key,
        description=request.description,
        request_fingerprint=fingerprint,
        source=request.source,
        reverses_posting_id=request.reverses_posting_id,
    )
    if request.effective_at is not None:
        posting.effective_at = request.effective_at

    try:
        # Savepoint: a duplicate key rolls back only this insert, so the caller's
        # transaction can still read the winner and replay it.
        with session.begin_nested():
            session.add(posting)
            session.flush()
    except IntegrityError as exc:
        constraint = _constraint_name(exc)
        if constraint == UNIQUE_IDEMPOTENCY_CONSTRAINT:
            return _replay_or_reject(session, request, fingerprint)
        if constraint == UNIQUE_REVERSAL_CONSTRAINT:
            raise PostingAlreadyReversed(
                f"Posting {request.reverses_posting_id} has already been reversed."
            ) from exc
        raise

    posting.entries.extend(
        Entry(account_id=e.account_id, direction=e.direction, amount=e.amount) for e in request.entries
    )
    session.flush()
    return PostingResult(posting=posting, replayed=False)


def get_posting(session: Session, *, tenant_id: uuid.UUID, posting_id: uuid.UUID) -> Posting:
    posting = session.scalars(
        select(Posting)
        .options(selectinload(Posting.entries))
        .where(Posting.id == posting_id, Posting.tenant_id == tenant_id)
    ).one_or_none()
    if posting is None:
        raise PostingNotFound(f"Posting {posting_id} does not exist.")
    return posting


def _opposite(direction: Direction) -> Direction:
    return Direction.credit if direction is Direction.debit else Direction.debit


def reverse_posting(
    session: Session, *, tenant_id: uuid.UUID, posting_id: uuid.UUID, description: str | None = None
) -> PostingResult:
    original = get_posting(session, tenant_id=tenant_id, posting_id=posting_id)
    mirrored = tuple(
        EntryInput(account_id=e.account_id, direction=_opposite(e.direction), amount=e.amount)
        for e in original.entries
    )
    return create_posting(
        session,
        PostingRequest(
            tenant_id=tenant_id,
            idempotency_key=f"reverse:{posting_id}",
            entries=mirrored,
            description=description or f"Reversal of {posting_id}",
            source=PostingSource.api,
            effective_at=original.effective_at,
            reverses_posting_id=posting_id,
        ),
    )


def list_postings(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    source: PostingSource | None,
    include_stress: bool,
    limit: int,
    before: tuple[datetime, uuid.UUID] | None,
) -> list[Posting]:
    query = select(Posting).options(selectinload(Posting.entries)).where(Posting.tenant_id == tenant_id)
    if source is not None:
        query = query.where(Posting.source == source)
    elif not include_stress:
        query = query.where(Posting.source != PostingSource.stress_test)
    if before is not None:
        query = query.where(tuple_(Posting.created_at, Posting.id) < tuple_(before[0], before[1]))
    query = query.order_by(Posting.created_at.desc(), Posting.id.desc()).limit(limit)
    return list(session.scalars(query))


def reversal_ids_for(session: Session, posting_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    if not posting_ids:
        return {}
    rows = session.execute(
        select(Posting.reverses_posting_id, Posting.id).where(Posting.reverses_posting_id.in_(posting_ids))
    )
    return {original_id: reversal_id for original_id, reversal_id in rows}
```

- [ ] **Step 10: Run the DAO tests**

Run: `.venv/bin/pytest tests/test_ledger_dao.py tests/test_fingerprint.py -v`
Expected: PASS. `test_concurrent_duplicate_times_out_as_request_in_progress` takes about 2s.

- [ ] **Step 11: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS.

- [ ] **Step 12: Commit**

```bash
git add app/errors.py app/ledger/errors.py app/ledger/fingerprint.py app/ledger/dao.py tests/test_fingerprint.py tests/test_ledger_dao.py
git commit -m "feat(ledger): single idempotent posting write path with payload fingerprints" -m "create_posting replays a same-payload retry, rejects a reused key, validates per-currency balance before the database, and ledger_transaction maps database violations and lock timeouts to domain errors."
```

---

### Task 4: HTTP API for postings with problem+json errors

**Files:**
- Modify: `backend/requirements.txt` (add `httpx`)
- Create: `backend/app/problem.py`
- Create: `backend/app/deps.py`
- Create: `backend/app/routes/postings.py`
- Modify: `backend/app/main.py` (whole file)
- Modify: `backend/tests/conftest.py` (append `client` fixture)
- Create: `backend/tests/test_api_postings.py`

**Interfaces:**
- Consumes: the whole of `app.ledger.dao` and `app.ledger.errors` from Task 3.
- Produces (`app.deps`): `get_session() -> Iterator[Session]`, `get_tenant_id() -> uuid.UUID`, `DECIDED_BY = "demo_user"`.
- Produces (`app.problem`): `problem_response(status: int, type_slug: str, title: str, detail: str, headers: dict[str, str] | None = None, **extensions) -> JSONResponse`, `install_problem_handlers(app: FastAPI) -> None`.
- Produces (`app.routes.postings`): `router`, `PostingOut`, `posting_out(posting: Posting, reversed_by: uuid.UUID | None) -> PostingOut`, `mark_replay(response: Response, replayed: bool) -> None`.
- Produces fixture: `client` (FastAPI `TestClient` whose session and tenant are overridden to the test's own).

- [ ] **Step 1: Add the dependency**

Append this line to `backend/requirements.txt`:

```
httpx
```

Run: `.venv/bin/pip install -r requirements.txt`

- [ ] **Step 2: Add the `client` fixture to `backend/tests/conftest.py`**

Append:

```python
from fastapi.testclient import TestClient


@pytest.fixture()
def client(session_factory, tenant_id):
    from app.deps import get_session, get_tenant_id
    from app.main import app

    def test_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = test_session
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
```

Move the import to the top of the file.

- [ ] **Step 3: Write the failing API tests (`backend/tests/test_api_postings.py`)**

```python
import uuid

import pytest

from app.ledger.dao import EntryInput, PostingRequest, create_account, create_posting
from app.ledger.types import Direction, NormalBalance

PROBLEM = "application/problem+json"


@pytest.fixture()
def pair(db_session, tenant_id):
    cash = create_account(db_session, tenant_id=tenant_id, name="Cash", currency="CAD", normal_balance=NormalBalance.debit)
    revenue = create_account(
        db_session, tenant_id=tenant_id, name="Revenue", currency="CAD", normal_balance=NormalBalance.credit
    )
    return cash, revenue


def _body(pair, amount=1000, **extra):
    cash, revenue = pair
    body = {
        "description": "Sale",
        "entries": [
            {"account_id": str(cash.id), "direction": "debit", "amount": amount},
            {"account_id": str(revenue.id), "direction": "credit", "amount": amount},
        ],
    }
    body.update(extra)
    return body


def _post(client, body, key=None):
    headers = {} if key is None else {"Idempotency-Key": key}
    return client.post("/postings", json=body, headers=headers)


def test_create_posting_returns_201_with_entries(client, pair):
    response = _post(client, _body(pair), key=str(uuid.uuid4()))
    assert response.status_code == 201
    assert "Idempotent-Replayed" not in response.headers
    payload = response.json()
    assert payload["source"] == "api"
    assert sorted(e["amount"] for e in payload["entries"]) == [1000, 1000]
    assert payload["reversed_by_posting_id"] is None


def test_retry_with_same_key_and_body_replays_with_200(client, pair):
    key = str(uuid.uuid4())
    first = _post(client, _body(pair), key=key)
    second = _post(client, _body(pair), key=key)
    assert second.status_code == 200
    assert second.headers["Idempotent-Replayed"] == "true"
    assert second.json()["id"] == first.json()["id"]


def test_reused_key_with_different_body_is_422_problem(client, pair):
    key = str(uuid.uuid4())
    _post(client, _body(pair, amount=1000), key=key)
    response = _post(client, _body(pair, amount=5), key=key)
    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM)
    assert response.json()["type"] == "/problems/idempotency-key-reused"


@pytest.mark.parametrize("key", [None, "", "   ", "k" * 256])
def test_missing_or_invalid_idempotency_key_is_400(client, pair, key):
    response = _post(client, _body(pair), key=key)
    assert response.status_code == 400
    assert response.json()["type"] in {"/problems/idempotency-key-missing", "/problems/idempotency-key-invalid"}


def test_unbalanced_posting_is_422_posting_invalid(client, pair):
    body = _body(pair)
    body["entries"][1]["amount"] = 999
    response = _post(client, body, key=str(uuid.uuid4()))
    assert response.status_code == 422
    assert response.json()["type"] == "/problems/posting-invalid"
    assert any("balance per currency" in reason for reason in response.json()["reasons"])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body["entries"][0].update(amount=10.5),
        lambda body: body["entries"][0].update(amount="1000"),
        lambda body: body.update(effective_at="2026-09-30T00:00:00"),  # no timezone
        lambda body: body.update(unexpected="field"),
        lambda body: body.update(source="fee_run"),  # clients cannot claim internal sources
    ],
)
def test_malformed_requests_are_422_request_invalid(client, pair, mutate):
    body = _body(pair)
    mutate(body)
    response = _post(client, body, key=str(uuid.uuid4()))
    assert response.status_code == 422
    assert response.json()["type"] == "/problems/request-invalid"


def test_concurrent_duplicate_is_409_with_retry_after(client, pair, session_factory, tenant_id):
    key = str(uuid.uuid4())
    cash, revenue = pair
    holder = session_factory()
    try:
        create_posting(
            holder,
            PostingRequest(
                tenant_id=tenant_id,
                idempotency_key=key,
                description="Sale",
                entries=(EntryInput(cash.id, Direction.debit, 1000), EntryInput(revenue.id, Direction.credit, 1000)),
            ),
        )
        response = _post(client, _body(pair), key=key)
    finally:
        holder.rollback()
        holder.close()
    assert response.status_code == 409
    assert response.headers["Retry-After"] == "1"
    assert response.json()["type"] == "/problems/request-in-progress"


def test_reversal_endpoint_creates_links_and_replays(client, pair):
    original = _post(client, _body(pair), key=str(uuid.uuid4())).json()
    first = client.post(f"/postings/{original['id']}/reversal")
    second = client.post(f"/postings/{original['id']}/reversal")
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["reverses_posting_id"] == original["id"]
    fetched = client.get(f"/postings/{original['id']}").json()
    assert fetched["reversed_by_posting_id"] == first.json()["id"]


def test_reversal_of_unknown_posting_is_404(client):
    response = client.post(f"/postings/{uuid.uuid4()}/reversal")
    assert response.status_code == 404
    assert response.json()["type"] == "/problems/posting-not-found"


def test_list_hides_stress_postings_and_pages_with_cursor(client, pair):
    ids = {_post(client, _body(pair), key=str(uuid.uuid4())).json()["id"] for _ in range(3)}
    _post(client, _body(pair, source="stress_test"), key=str(uuid.uuid4()))

    first = client.get("/postings", params={"limit": 2}).json()
    second = client.get("/postings", params={"limit": 2, "cursor": first["next_cursor"]}).json()

    seen = [p["id"] for p in first["items"]] + [p["id"] for p in second["items"]]
    assert set(seen) == ids and len(seen) == 3
    assert second["next_cursor"] is None


def test_invalid_cursor_is_400(client):
    response = client.get("/postings", params={"cursor": "not-a-cursor"})
    assert response.status_code == 400
    assert response.json()["type"] == "/problems/cursor-invalid"


def test_get_unknown_posting_is_404(client):
    assert client.get(f"/postings/{uuid.uuid4()}").status_code == 404
```

- [ ] **Step 4: Run to confirm it fails**

Run: `.venv/bin/pytest tests/test_api_postings.py -v`
Expected: ERROR `ModuleNotFoundError: No module named 'app.deps'`.

- [ ] **Step 5: Create `backend/app/deps.py`**

```python
import uuid
from collections.abc import Iterator

from sqlalchemy.orm import Session

from app.ledger.db import SessionLocal
from app.ledger.types import DEMO_TENANT_ID

# ponytail: no authentication yet; the acting user is fixed. Replace with the authenticated principal.
DECIDED_BY = "demo_user"


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_tenant_id() -> uuid.UUID:
    # ponytail: single fixed demo tenant until authentication exists; resolve it from the principal then.
    return DEMO_TENANT_ID
```

- [ ] **Step 6: Create `backend/app/problem.py`**

```python
import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.errors import DomainError

logger = logging.getLogger(__name__)
PROBLEM_MEDIA_TYPE = "application/problem+json"


def problem_response(
    status: int,
    type_slug: str,
    title: str,
    detail: str,
    headers: dict[str, str] | None = None,
    **extensions: object,
) -> JSONResponse:
    body = {"type": f"/problems/{type_slug}", "title": title, "status": status, "detail": detail}
    body.update(jsonable_encoder(extensions))
    return JSONResponse(body, status_code=status, media_type=PROBLEM_MEDIA_TYPE, headers=headers)


def install_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        if exc.status >= 500:
            logger.error("domain error %s: %s", exc.type_slug, exc.detail)
        return problem_response(
            exc.status, exc.type_slug, exc.title, exc.detail, headers=exc.headers(), **exc.extensions
        )

    @app.exception_handler(RequestValidationError)
    async def request_invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        return problem_response(
            422, "request-invalid", "Request is invalid", "The request body or parameters are malformed.",
            errors=exc.errors(),
        )
```

- [ ] **Step 7: Create `backend/app/routes/postings.py`**

```python
import base64
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy.orm import Session

from app.deps import get_session, get_tenant_id
from app.ledger.dao import (
    MAX_IDEMPOTENCY_KEY_LENGTH,
    EntryInput,
    PostingRequest,
    PostingResult,
    create_posting,
    get_posting,
    ledger_transaction,
    list_postings,
    reversal_ids_for,
    reverse_posting,
)
from app.ledger.errors import CursorInvalid, IdempotencyKeyInvalid, IdempotencyKeyMissing
from app.ledger.models import Posting
from app.ledger.types import Direction, PostingSource

router = APIRouter(prefix="/postings", tags=["postings"])

SessionDep = Annotated[Session, Depends(get_session)]
TenantDep = Annotated[uuid.UUID, Depends(get_tenant_id)]


class EntryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: uuid.UUID
    direction: Direction
    amount: StrictInt = Field(gt=0, description="Amount in minor currency units (cents).")


class PostingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str | None = Field(default=None, max_length=500)
    effective_at: AwareDatetime | None = None
    source: Literal["api", "stress_test"] = "api"
    entries: list[EntryIn]


class ReversalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str | None = Field(default=None, max_length=500)


class EntryOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    direction: Direction
    amount: int


class PostingOut(BaseModel):
    id: uuid.UUID
    idempotency_key: str
    description: str | None
    effective_at: datetime
    created_at: datetime
    source: PostingSource
    reverses_posting_id: uuid.UUID | None
    reversed_by_posting_id: uuid.UUID | None
    entries: list[EntryOut]


class PostingPage(BaseModel):
    items: list[PostingOut]
    next_cursor: str | None


def posting_out(posting: Posting, reversed_by: uuid.UUID | None) -> PostingOut:
    return PostingOut(
        id=posting.id,
        idempotency_key=posting.idempotency_key,
        description=posting.description,
        effective_at=posting.effective_at,
        created_at=posting.created_at,
        source=posting.source,
        reverses_posting_id=posting.reverses_posting_id,
        reversed_by_posting_id=reversed_by,
        entries=[EntryOut(id=e.id, account_id=e.account_id, direction=e.direction, amount=e.amount) for e in posting.entries],
    )


def mark_replay(response: Response, replayed: bool) -> None:
    if replayed:
        response.status_code = 200
        response.headers["Idempotent-Replayed"] = "true"


def _require_idempotency_key(raw: str | None) -> str:
    key = (raw or "").strip()
    if not key:
        raise IdempotencyKeyMissing("This operation requires an Idempotency-Key header.")
    if len(key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise IdempotencyKeyInvalid(f"Idempotency-Key must be at most {MAX_IDEMPOTENCY_KEY_LENGTH} characters.")
    return key


def _encode_cursor(posting: Posting) -> str:
    raw = f"{posting.created_at.isoformat()}|{posting.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        created_at, posting_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        return datetime.fromisoformat(created_at), uuid.UUID(posting_id)
    except ValueError as exc:  # also covers binascii.Error and UnicodeDecodeError
        raise CursorInvalid("The cursor is not a value previously returned by this API.") from exc


def _respond(session: Session, response: Response, result: PostingResult) -> PostingOut:
    mark_replay(response, result.replayed)
    reversed_by = reversal_ids_for(session, [result.posting.id]).get(result.posting.id)
    return posting_out(result.posting, reversed_by)


@router.post("", status_code=201, response_model=PostingOut)
def create_posting_endpoint(
    body: PostingIn,
    response: Response,
    session: SessionDep,
    tenant_id: TenantDep,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> PostingOut:
    key = _require_idempotency_key(idempotency_key)
    request = PostingRequest(
        tenant_id=tenant_id,
        idempotency_key=key,
        description=body.description,
        effective_at=body.effective_at,
        source=PostingSource(body.source),
        entries=tuple(EntryInput(e.account_id, e.direction, e.amount) for e in body.entries),
    )
    with ledger_transaction(session):
        result = create_posting(session, request)
    return _respond(session, response, result)


@router.post("/{posting_id}/reversal", status_code=201, response_model=PostingOut)
def reverse_posting_endpoint(
    posting_id: uuid.UUID,
    response: Response,
    session: SessionDep,
    tenant_id: TenantDep,
    body: ReversalIn | None = None,
) -> PostingOut:
    with ledger_transaction(session):
        result = reverse_posting(
            session, tenant_id=tenant_id, posting_id=posting_id, description=body.description if body else None
        )
    return _respond(session, response, result)


@router.get("", response_model=PostingPage)
def list_postings_endpoint(
    session: SessionDep,
    tenant_id: TenantDep,
    source: PostingSource | None = None,
    include_stress: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> PostingPage:
    before = _decode_cursor(cursor) if cursor else None
    postings = list_postings(
        session, tenant_id=tenant_id, source=source, include_stress=include_stress, limit=limit, before=before
    )
    reversals = reversal_ids_for(session, [p.id for p in postings])
    next_cursor = _encode_cursor(postings[-1]) if len(postings) == limit else None
    return PostingPage(items=[posting_out(p, reversals.get(p.id)) for p in postings], next_cursor=next_cursor)


@router.get("/{posting_id}", response_model=PostingOut)
def get_posting_endpoint(posting_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> PostingOut:
    posting = get_posting(session, tenant_id=tenant_id, posting_id=posting_id)
    return posting_out(posting, reversal_ids_for(session, [posting.id]).get(posting.id))
```

- [ ] **Step 8: Replace `backend/app/main.py`**

```python
from fastapi import FastAPI

from app.problem import install_problem_handlers
from app.routes import health, postings

app = FastAPI(title="Fintech Ledger + Document Intelligence")
install_problem_handlers(app)

app.include_router(health.router)
app.include_router(postings.router)
```

- [ ] **Step 9: Run the API tests**

Run: `.venv/bin/pytest tests/test_api_postings.py -v`
Expected: PASS. The 409 test takes about 2s.

A subtle case to check: if the paging test ever fails because it returns 4 postings, `include_stress` is being ignored. `list_postings` must exclude `stress_test` when `source is None`.

- [ ] **Step 10: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add requirements.txt app/deps.py app/problem.py app/routes/postings.py app/main.py tests/conftest.py tests/test_api_postings.py
git commit -m "feat(api): idempotent POST /postings, reversal and read endpoints with problem+json errors" -m "Implements the agreed contract: 400 missing key, 201 created, 200 replay with Idempotent-Replayed, 422 reused key or invalid posting, 409 with Retry-After while a duplicate is in flight."
```

---

### Task 5: Concurrency proof against a live server (shortened Epic 1.4)

**Files:**
- Create: `backend/pytest.ini`
- Create: `backend/tests/stress/__init__.py` (empty)
- Create: `backend/tests/stress/test_concurrency.py`
- Create (generated by the run, then committed): `backend/reports/concurrency.json`

**Interfaces:**
- Consumes: `POST /postings` from Task 4 (with `"source": "stress_test"`), `create_account` from Task 3, and the `migrated_test_database` / `db_session` fixtures.
- Produces: `backend/reports/concurrency.json` with keys `run_at`, `requests`, `distinct_keys`, `postings_created`, `duplicate_postings`, `imbalanced_currencies`, `hot_account_lost_updates`, `status_counts`, `latency_ms` (`p50`, `p99`, `max`), `concurrency`, `workers`.

- [ ] **Step 1: Create `backend/pytest.ini`**

```ini
[pytest]
markers =
    stress: end-to-end concurrency proof against a live uvicorn server (run with: pytest -m stress)
addopts = -m "not stress"
```

- [ ] **Step 2: Write the stress test (`backend/tests/stress/test_concurrency.py`)**

```python
import asyncio
import json
import os
import random
import statistics
import subprocess
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import text

from app import config
from app.ledger.dao import create_account
from app.ledger.types import DEMO_TENANT_ID, NormalBalance
from tests.support import BACKEND_DIR

pytestmark = pytest.mark.stress

PORT = 8765
BASE_URL = f"http://127.0.0.1:{PORT}"
WORKERS = 4
CONCURRENCY = 50
NEW_KEYS = 300
DUPLICATED_KEYS = 50
COPIES_PER_DUPLICATE = 3
HOT_ACCOUNT_POSTINGS = 50
MAX_409_RETRIES = 5
REPORT_PATH = BACKEND_DIR / "reports" / "concurrency.json"


@pytest.fixture(scope="module")
def live_server(migrated_test_database):
    env = {**os.environ, "DATABASE_URL": config.TEST_DATABASE_URL}
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT),
         "--workers", str(WORKERS), "--log-level", "warning"],
        cwd=BACKEND_DIR,
        env=env,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{BASE_URL}/health", timeout=1).status_code == 200:
                    break
            except httpx.TransportError:
                time.sleep(0.2)
        else:
            pytest.fail("uvicorn did not start within 20s")
        yield BASE_URL
    finally:
        process.terminate()
        process.wait(timeout=10)


def _body(debit_id, credit_id, amount):
    return {
        "description": "stress",
        "source": "stress_test",
        "entries": [
            {"account_id": str(debit_id), "direction": "debit", "amount": amount},
            {"account_id": str(credit_id), "direction": "credit", "amount": amount},
        ],
    }


def _build_requests(run_id, accounts, hot_account, counter_account, rng):
    requests = []
    for n in range(NEW_KEYS):
        debit, credit = rng.sample(accounts, 2)
        requests.append((f"stress-{run_id}-new-{n}", _body(debit, credit, rng.randint(1, 10_000))))
    for n in range(DUPLICATED_KEYS):
        debit, credit = rng.sample(accounts, 2)
        body = _body(debit, credit, rng.randint(1, 10_000))
        requests.extend([(f"stress-{run_id}-dup-{n}", body)] * COPIES_PER_DUPLICATE)
    hot_amounts = [rng.randint(1, 10_000) for _ in range(HOT_ACCOUNT_POSTINGS)]
    for n, amount in enumerate(hot_amounts):
        requests.append((f"stress-{run_id}-hot-{n}", _body(hot_account, counter_account, amount)))
    rng.shuffle(requests)
    return requests, sum(hot_amounts)


async def _fire_all(base_url, requests):
    results = []  # (key, final_status, first_attempt_seconds)
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def fire(client, key, body):
        async with semaphore:
            start = time.perf_counter()
            response = await client.post("/postings", json=body, headers={"Idempotency-Key": key})
            first_latency = time.perf_counter() - start
            retries = 0
            while response.status_code == 409 and retries < MAX_409_RETRIES:
                await asyncio.sleep(float(response.headers.get("Retry-After", "1")))
                response = await client.post("/postings", json=body, headers={"Idempotency-Key": key})
                retries += 1
            results.append((key, response.status_code, first_latency))

    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        await asyncio.gather(*(fire(client, key, body) for key, body in requests))
    return results


def test_concurrent_postings_keep_every_invariant(live_server, db_session):
    rng = random.Random(20260922)
    run_id = uuid.uuid4().hex[:8]
    accounts = [
        create_account(db_session, tenant_id=DEMO_TENANT_ID, name=f"stress-{run_id}-{i}",
                       currency="CAD", normal_balance=NormalBalance.debit).id
        for i in range(20)
    ]
    hot, counter = accounts[0], accounts[1]
    requests, hot_total = _build_requests(run_id, accounts, hot, counter, rng)

    results = asyncio.run(_fire_all(live_server, requests))

    statuses = Counter(status for _, status, _ in results)
    created_per_key = Counter(key for key, status, _ in results if status == 201)
    distinct_keys = {key for key, _ in requests}
    like = f"stress-{run_id}-%"

    postings_created = db_session.execute(
        text("SELECT count(*) FROM postings WHERE idempotency_key LIKE :like"), {"like": like}
    ).scalar_one()
    postings_without_two_entries = db_session.execute(
        text(
            "SELECT count(*) FROM (SELECT p.id FROM postings p JOIN entries e ON e.posting_id = p.id "
            "WHERE p.idempotency_key LIKE :like GROUP BY p.id HAVING count(*) <> 2) AS bad"
        ),
        {"like": like},
    ).scalar_one()
    imbalanced_currencies = db_session.execute(
        text(
            "SELECT count(*) FROM (SELECT a.currency FROM entries e JOIN postings p ON p.id = e.posting_id "
            "JOIN accounts a ON a.id = e.account_id WHERE p.idempotency_key LIKE :like GROUP BY a.currency "
            "HAVING SUM(CASE WHEN e.direction = 'debit' THEN e.amount ELSE -e.amount END) <> 0) AS bad"
        ),
        {"like": like},
    ).scalar_one()
    hot_debits = db_session.execute(
        text(
            "SELECT COALESCE(SUM(e.amount), 0) FROM entries e JOIN postings p ON p.id = e.posting_id "
            "WHERE p.idempotency_key LIKE :hot AND e.account_id = :account AND e.direction = 'debit'"
        ),
        {"hot": f"stress-{run_id}-hot-%", "account": hot},
    ).scalar_one()

    latencies_ms = sorted(seconds * 1000 for _, _, seconds in results)
    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "requests": len(requests),
        "distinct_keys": len(distinct_keys),
        "postings_created": postings_created,
        "duplicate_postings": postings_created - len(distinct_keys),
        "imbalanced_currencies": imbalanced_currencies,
        "hot_account_lost_updates": hot_total - int(hot_debits),
        "status_counts": {str(code): count for code, count in sorted(statuses.items())},
        "latency_ms": {
            "p50": round(statistics.median(latencies_ms), 1),
            "p99": round(statistics.quantiles(latencies_ms, n=100)[98], 1),
            "max": round(latencies_ms[-1], 1),
        },
        "concurrency": CONCURRENCY,
        "workers": WORKERS,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n")

    assert set(statuses) <= {200, 201}, f"unexpected statuses: {statuses}"
    assert all(created_per_key[key] == 1 for key in distinct_keys)
    assert postings_created == len(distinct_keys)
    assert postings_without_two_entries == 0
    assert imbalanced_currencies == 0
    assert int(hot_debits) == hot_total
```

- [ ] **Step 3: Confirm the default run skips it**

Run: `.venv/bin/pytest -v`
Expected: PASS, with `tests/stress/test_concurrency.py` deselected.

- [ ] **Step 4: Run the stress proof**

Run: `.venv/bin/pytest -m stress -v -s`
Expected: PASS, with `reports/concurrency.json` written. Open it and check that `duplicate_postings`, `imbalanced_currencies` and `hot_account_lost_updates` are all 0.

If a 409 survives 5 retries, the assertion `set(statuses) <= {200, 201}` fails. That means lock waits exceed 2s under this load. Lower `CONCURRENCY` to 25 and record the change in the report. **Don't raise `LOCK_TIMEOUT`.**

- [ ] **Step 5: Commit**

```bash
git add pytest.ini tests/stress/__init__.py tests/stress/test_concurrency.py reports/concurrency.json
git commit -m "test(ledger): concurrency proof with duplicate storms and a hot account" -m "500 concurrent requests against a live multi-worker server; asserts one posting per key, two entries per posting, zero per-currency imbalance and no lost updates, and records p50/p99 latency."
```

---

### Task 6: Fee maths — pure functions (tiers, proration, rounding, allocation)

**Files:**
- Create: `backend/app/billing/__init__.py` (empty)
- Create: `backend/app/billing/types.py`
- Create: `backend/app/billing/fee_math.py`
- Create: `backend/tests/test_fee_math.py`

**Interfaces:**
- Consumes: nothing. This code is pure stdlib and must not import SQLAlchemy, FastAPI or `app.ledger.models`.
- Produces (`app.billing.types`): `FeeMethod(str, Enum)` with values `graduated`, `cliff`.
- Produces (`app.billing.fee_math`):
  - `Tier(up_to_minor: int | None, rate_bps: Decimal)` (frozen). `up_to_minor` is an **inclusive** upper bound in minor units; `None` means no upper limit.
  - `AccountValue(account_id: uuid.UUID, value_minor: int, linked_on: date)` (frozen)
  - `FeeInputs(period_start: date, period_end: date, method: FeeMethod, tiers: tuple[Tier, ...], accounts: tuple[AccountValue, ...])` (frozen; the period is inclusive of both dates)
  - `FeeResult(household_value_minor: int, annual_fee: Decimal, period_fee_minor: int, allocations: dict[uuid.UUID, int], rounding_remainder_minor: int)` (frozen)
  - `validate_tiers(tiers: Sequence[Tier]) -> None` (raises `ValueError`)
  - `annual_fee(value_minor: int, tiers: Sequence[Tier], method: FeeMethod) -> Decimal`
  - `days_in_period(start: date, end: date) -> int`
  - `period_fraction(start: date, end: date) -> Decimal`
  - `linked_fraction(linked_on: date, start: date, end: date) -> Decimal`
  - `round_half_even(amount: Decimal) -> int`
  - `allocate(total_minor: int, weights: Mapping[uuid.UUID, Decimal]) -> tuple[dict[uuid.UUID, int], int]` (returns the allocations plus the number of minor units handed out as remainders)
  - `calculate_household_fee(inputs: FeeInputs) -> FeeResult`
  - `inputs_to_json(inputs: FeeInputs, *, schedule_id: uuid.UUID, schedule_version: int) -> dict`
  - `inputs_from_json(data: Mapping) -> FeeInputs`

- [ ] **Step 1: Create `backend/app/billing/types.py`**

```python
import enum


class FeeMethod(str, enum.Enum):
    graduated = "graduated"  # each tranche billed at its own tier's rate
    cliff = "cliff"  # the whole value billed at the rate of the tier it reaches
```

- [ ] **Step 2: Write the failing tests (`backend/tests/test_fee_math.py`)**

Worked example used throughout: tiers are 1.00% up to $1,000,000.00, 0.80% up to $2,500,000.00, and 0.65% above that. The values are in minor units (cents).

```python
import random
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.billing.fee_math import (
    AccountValue,
    FeeInputs,
    Tier,
    allocate,
    annual_fee,
    calculate_household_fee,
    inputs_from_json,
    inputs_to_json,
    linked_fraction,
    period_fraction,
    round_half_even,
    validate_tiers,
)
from app.billing.types import FeeMethod

TIERS = (
    Tier(up_to_minor=100_000_000, rate_bps=Decimal("100")),
    Tier(up_to_minor=250_000_000, rate_bps=Decimal("80")),
    Tier(up_to_minor=None, rate_bps=Decimal("65")),
)
A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
B = uuid.UUID("00000000-0000-0000-0000-0000000000b2")
C = uuid.UUID("00000000-0000-0000-0000-0000000000c3")
Q3_START, Q3_END = date(2026, 7, 1), date(2026, 9, 30)  # 92 days, 2026 is not a leap year


@pytest.mark.parametrize(
    ("value", "graduated", "cliff"),
    [
        (180_000_000, Decimal("1640000"), Decimal("1440000")),
        (100_000_000, Decimal("1000000"), Decimal("1000000")),  # exactly on the boundary: tier 1 rate
        (100_000_001, Decimal("1000000.008"), Decimal("800000.008")),  # one cent over: cliff drops the rate
        (300_000_000, Decimal("2525000"), Decimal("1950000")),
        (0, Decimal("0"), Decimal("0")),
    ],
)
def test_annual_fee_graduated_vs_cliff(value, graduated, cliff):
    assert annual_fee(value, TIERS, FeeMethod.graduated) == graduated
    assert annual_fee(value, TIERS, FeeMethod.cliff) == cliff


@pytest.mark.parametrize(
    "tiers",
    [
        (),
        (Tier(100, Decimal("1")), Tier(50, Decimal("1")), Tier(None, Decimal("1"))),  # caps not ascending
        (Tier(None, Decimal("1")), Tier(100, Decimal("1"))),  # open-ended tier not last
        (Tier(100, Decimal("1")),),  # no open-ended final tier
        (Tier(None, Decimal("-1")),),  # negative rate
    ],
)
def test_invalid_tier_tables_are_rejected(tiers):
    with pytest.raises(ValueError):
        validate_tiers(tiers)


def test_period_fraction_uses_inclusive_days_over_year_length():
    assert period_fraction(Q3_START, Q3_END) == Decimal(92) / Decimal(365)
    assert period_fraction(date(2028, 1, 1), date(2028, 3, 31)) == Decimal(91) / Decimal(366)


def test_period_end_before_start_is_rejected():
    with pytest.raises(ValueError):
        period_fraction(Q3_END, Q3_START)


def test_linked_fraction_prorates_mid_period_links():
    assert linked_fraction(date(2026, 1, 1), Q3_START, Q3_END) == Decimal(1)
    assert linked_fraction(date(2026, 8, 1), Q3_START, Q3_END) == Decimal(61) / Decimal(92)
    assert linked_fraction(date(2026, 10, 1), Q3_START, Q3_END) == Decimal(0)


@pytest.mark.parametrize(("amount", "expected"), [("2.5", 2), ("3.5", 4), ("-2.5", -2), ("413369.863", 413370)])
def test_round_half_even(amount, expected):
    assert round_half_even(Decimal(amount)) == expected


def test_allocate_gives_leftover_cents_to_largest_remainders():
    allocations, remainder = allocate(10, {A: Decimal(2), B: Decimal(1)})
    assert allocations == {A: 7, B: 3} and remainder == 1  # exact shares 6.67 / 3.33


def test_allocate_breaks_exact_ties_by_account_id():
    allocations, remainder = allocate(10, {C: Decimal(1), B: Decimal(1), A: Decimal(1)})
    assert allocations == {A: 4, B: 3, C: 3} and remainder == 1


def test_allocate_zero_total_is_all_zero():
    assert allocate(0, {A: Decimal(0), B: Decimal(0)}) == ({A: 0, B: 0}, 0)


def test_household_fee_worked_example_with_proration():
    inputs = FeeInputs(
        period_start=Q3_START,
        period_end=Q3_END,
        method=FeeMethod.graduated,
        tiers=TIERS,
        accounts=(
            AccountValue(A, 120_000_000, date(2026, 1, 1)),
            AccountValue(B, 60_000_000, date(2026, 8, 1)),  # linked 61 of 92 days
        ),
    )
    result = calculate_household_fee(inputs)
    assert result.household_value_minor == 180_000_000
    assert result.annual_fee == Decimal("1640000")
    assert result.period_fee_minor == 366_941
    assert result.allocations == {A: 275_580, B: 91_361}
    assert result.rounding_remainder_minor == 1  # one leftover cent goes to the larger fractional share (B)


def test_household_fee_is_zero_when_nothing_is_linked_in_the_period():
    inputs = FeeInputs(Q3_START, Q3_END, FeeMethod.graduated, TIERS, (AccountValue(A, 50_000_000, date(2026, 10, 1)),))
    result = calculate_household_fee(inputs)
    assert result.period_fee_minor == 0 and result.allocations == {A: 0}


def test_allocations_always_sum_to_the_household_fee():
    rng = random.Random(42)
    for _ in range(1000):
        accounts = tuple(
            AccountValue(uuid.UUID(int=rng.getrandbits(128)), rng.randint(0, 5_000_000_000),
                         date(2026, rng.randint(1, 9), rng.randint(1, 28)))
            for _ in range(rng.randint(1, 5))
        )
        method = rng.choice([FeeMethod.graduated, FeeMethod.cliff])
        result = calculate_household_fee(FeeInputs(Q3_START, Q3_END, method, TIERS, accounts))
        assert sum(result.allocations.values()) == result.period_fee_minor
        assert all(v >= 0 for v in result.allocations.values())
        assert 0 <= result.rounding_remainder_minor < len(accounts)


def test_inputs_round_trip_through_json():
    inputs = FeeInputs(Q3_START, Q3_END, FeeMethod.cliff, TIERS, (AccountValue(A, 1, date(2026, 1, 1)),))
    schedule_id = uuid.uuid4()
    data = inputs_to_json(inputs, schedule_id=schedule_id, schedule_version=2)
    assert data["schedule"] == {"id": str(schedule_id), "version": 2, "method": "cliff",
                                "tiers": [{"up_to_minor": 100_000_000, "rate_bps": "100"},
                                          {"up_to_minor": 250_000_000, "rate_bps": "80"},
                                          {"up_to_minor": None, "rate_bps": "65"}]}
    assert inputs_from_json(data) == inputs
```

- [ ] **Step 3: Run to confirm it fails**

Run: `.venv/bin/pytest tests/test_fee_math.py -v`
Expected: ERROR `ModuleNotFoundError: No module named 'app.billing.fee_math'`.

- [ ] **Step 4: Create `backend/app/billing/fee_math.py`**

```python
import calendar
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Decimal

from app.billing.types import FeeMethod

BPS_PER_UNIT = Decimal(10_000)


@dataclass(frozen=True)
class Tier:
    up_to_minor: int | None  # inclusive upper bound in minor units; None = no upper limit
    rate_bps: Decimal  # annual rate in basis points (100 bps = 1%)


@dataclass(frozen=True)
class AccountValue:
    account_id: uuid.UUID
    value_minor: int  # period-end market value
    linked_on: date


@dataclass(frozen=True)
class FeeInputs:
    period_start: date
    period_end: date  # inclusive
    method: FeeMethod
    tiers: tuple[Tier, ...]
    accounts: tuple[AccountValue, ...]


@dataclass(frozen=True)
class FeeResult:
    household_value_minor: int
    annual_fee: Decimal
    period_fee_minor: int
    allocations: dict[uuid.UUID, int]
    rounding_remainder_minor: int


def validate_tiers(tiers: Sequence[Tier]) -> None:
    if not tiers:
        raise ValueError("a fee schedule needs at least one tier")
    if tiers[-1].up_to_minor is not None:
        raise ValueError("the last tier must have no upper limit")
    caps = [tier.up_to_minor for tier in tiers[:-1]]
    if any(cap is None for cap in caps):
        raise ValueError("only the last tier may have no upper limit")
    if any(cap <= 0 for cap in caps) or caps != sorted(set(caps)):
        raise ValueError("tier upper limits must be positive and strictly ascending")
    if any(tier.rate_bps < 0 for tier in tiers):
        raise ValueError("tier rates must not be negative")


def _rate(rate_bps: Decimal) -> Decimal:
    return rate_bps / BPS_PER_UNIT


def annual_fee(value_minor: int, tiers: Sequence[Tier], method: FeeMethod) -> Decimal:
    validate_tiers(tiers)
    value = Decimal(value_minor)
    if method is FeeMethod.cliff:
        tier = next(t for t in tiers if t.up_to_minor is None or value_minor <= t.up_to_minor)
        return value * _rate(tier.rate_bps)
    fee, lower = Decimal(0), Decimal(0)
    for tier in tiers:
        upper = value if tier.up_to_minor is None else min(value, Decimal(tier.up_to_minor))
        if upper <= lower:
            break
        fee += (upper - lower) * _rate(tier.rate_bps)
        lower = upper
    return fee


def days_in_period(start: date, end: date) -> int:
    if end < start:
        raise ValueError(f"period end {end} is before period start {start}")
    return (end - start).days + 1


def period_fraction(start: date, end: date) -> Decimal:
    year_days = 366 if calendar.isleap(end.year) else 365
    return Decimal(days_in_period(start, end)) / Decimal(year_days)


def linked_fraction(linked_on: date, start: date, end: date) -> Decimal:
    if linked_on > end:
        return Decimal(0)
    first_day = max(start, linked_on)
    return Decimal((end - first_day).days + 1) / Decimal(days_in_period(start, end))


def round_half_even(amount: Decimal) -> int:
    return int(amount.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def allocate(total_minor: int, weights: Mapping[uuid.UUID, Decimal]) -> tuple[dict[uuid.UUID, int], int]:
    """Split total_minor by weight: floor each share, then hand the leftover minor units
    to the largest fractional remainders (ties broken by account id)."""
    if total_minor == 0:
        return {key: 0 for key in weights}, 0
    weight_sum = sum(weights.values(), Decimal(0))
    if weight_sum <= 0:
        raise ValueError("cannot allocate a positive total with no positive weight")
    exact = {key: Decimal(total_minor) * weight / weight_sum for key, weight in weights.items()}
    floors = {key: int(share.to_integral_value(rounding=ROUND_FLOOR)) for key, share in exact.items()}
    remainder = total_minor - sum(floors.values())
    by_largest_remainder = sorted(exact, key=lambda key: (-(exact[key] - floors[key]), str(key)))
    for key in by_largest_remainder[:remainder]:
        floors[key] += 1
    return floors, remainder


def calculate_household_fee(inputs: FeeInputs) -> FeeResult:
    if any(account.value_minor < 0 for account in inputs.accounts):
        raise ValueError("account values must not be negative")
    household_value = sum(account.value_minor for account in inputs.accounts)
    yearly = annual_fee(household_value, inputs.tiers, inputs.method)
    period_fee_exact = yearly * period_fraction(inputs.period_start, inputs.period_end)

    per_account_exact = {
        account.account_id: (
            Decimal(0)
            if household_value == 0
            else period_fee_exact
            * Decimal(account.value_minor)
            / Decimal(household_value)
            * linked_fraction(account.linked_on, inputs.period_start, inputs.period_end)
        )
        for account in inputs.accounts
    }
    period_fee_minor = round_half_even(sum(per_account_exact.values(), Decimal(0)))
    allocations, remainder = allocate(period_fee_minor, per_account_exact)
    return FeeResult(
        household_value_minor=household_value,
        annual_fee=yearly,
        period_fee_minor=period_fee_minor,
        allocations=allocations,
        rounding_remainder_minor=remainder,
    )


def inputs_to_json(inputs: FeeInputs, *, schedule_id: uuid.UUID, schedule_version: int) -> dict:
    return {
        "period": {"start": inputs.period_start.isoformat(), "end": inputs.period_end.isoformat()},
        "schedule": {
            "id": str(schedule_id),
            "version": schedule_version,
            "method": inputs.method.value,
            "tiers": [{"up_to_minor": t.up_to_minor, "rate_bps": str(t.rate_bps)} for t in inputs.tiers],
        },
        "accounts": [
            {"account_id": str(a.account_id), "value_minor": a.value_minor, "linked_on": a.linked_on.isoformat()}
            for a in inputs.accounts
        ],
    }


def inputs_from_json(data: Mapping) -> FeeInputs:
    schedule = data["schedule"]
    return FeeInputs(
        period_start=date.fromisoformat(data["period"]["start"]),
        period_end=date.fromisoformat(data["period"]["end"]),
        method=FeeMethod(schedule["method"]),
        tiers=tuple(Tier(t["up_to_minor"], Decimal(t["rate_bps"])) for t in schedule["tiers"]),
        accounts=tuple(
            AccountValue(uuid.UUID(a["account_id"]), a["value_minor"], date.fromisoformat(a["linked_on"]))
            for a in data["accounts"]
        ),
    )
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/pytest tests/test_fee_math.py -v`
Expected: PASS. These tests need no database.

- [ ] **Step 6: Commit**

```bash
git add app/billing/__init__.py app/billing/types.py app/billing/fee_math.py tests/test_fee_math.py
git commit -m "feat(billing): pure fee maths for graduated and cliff schedules" -m "Tier fees, day-count proration, half-even rounding and largest-remainder allocation, with worked examples and a 1,000-case property test that allocations always sum to the household fee."
```

---

### Task 7: Migration 0005 — billing schema with non-overlapping schedule versions

**Files:**
- Create: `backend/alembic/versions/0005_billing.py`
- Create: `backend/app/billing/models.py`
- Create: `backend/app/billing/errors.py`
- Create: `backend/app/ranges.py` (inclusive date-range helpers shared by billing and reporting, so reporting never imports billing)
- Create: `backend/app/billing/dao.py` (setup functions only; the fee run arrives in Task 8)
- Modify: `backend/alembic/env.py` (import billing models so metadata is complete)
- Modify: `backend/tests/support.py` (append `FeeScenario`, `build_fee_scenario`)
- Create: `backend/tests/test_billing_schema.py`

**Interfaces:**
- Consumes: `forbid_mutation()` (Task 2), `Base`, `Account`, `create_account` (Tasks 2–3), `Tier`, `validate_tiers`, `FeeMethod` (Task 6).
- Produces (`app.billing.models`): `Household`, `Client`, `ClientAccount`, `AccountValuation`, `FeeSchedule`, `FeeScheduleVersion`, `FeeScheduleTier`, `HouseholdFeeAssignment`, `FeeCalculation`. The `period` / `valid_during` columns are `DATERANGE`, mapped to `sqlalchemy.dialects.postgresql.Range[date]`.
- Produces (`app.billing.dao`), all committing:
  - `create_household(session, *, tenant_id, name) -> Household`
  - `create_client(session, *, tenant_id, household_id, name) -> Client`
  - `link_account(session, *, client_id, account_id, linked_on: date) -> ClientAccount`
  - `record_valuation(session, *, account_id, as_of: date, market_value_minor: int, source: str) -> AccountValuation`
  - `create_fee_schedule(session, *, tenant_id, name, revenue_account_id) -> FeeSchedule`
  - `add_schedule_version(session, *, schedule_id, version, method: FeeMethod, valid_from: date, valid_until: date | None, tiers: Sequence[Tier]) -> FeeScheduleVersion`
  - `assign_schedule(session, *, household_id, schedule_id, valid_from: date, valid_until: date | None) -> HouseholdFeeAssignment`
- Produces (`app.ranges`): `date_range(valid_from: date, valid_until: date | None) -> Range[date]` (both ends inclusive; open-ended when `valid_until` is None) and `range_end_inclusive(value: Range[date]) -> date | None`.
- Produces (`tests.support`): `FeeScenario` dataclass (`household_id`, `client_account_ids: tuple[uuid.UUID, uuid.UUID]`, `revenue_account_id`, `schedule_id`) and `build_fee_scenario(session, tenant_id) -> FeeScenario`. This is the spec's worked example: account 1 is worth 120,000,000 and linked 2026-01-01; account 2 is worth 60,000,000 and linked 2026-08-01; valuations exist as of 2026-09-30 and 2026-07-31. Version 1 is `[2026-01-01, 2026-06-30]`, graduated, 1.50% flat. Version 2 is `[2026-07-01, ∞)` with the Task 6 tiers.

- [ ] **Step 1: Create `backend/alembic/versions/0005_billing.py`**

```python
"""billing: households, valuations, versioned fee schedules, fee calculations

Revision ID: 0005_billing
Revises: 0004_ledger_core
"""
from alembic import op

revision = "0005_billing"
down_revision = "0004_ledger_core"
branch_labels = None
depends_on = None

APPEND_ONLY = (
    "client_accounts",
    "account_valuations",
    "fee_schedule_versions",
    "fee_schedule_tiers",
    "household_fee_assignments",
    "fee_calculations",
)


def _run(*statements: str) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    _run(
        "CREATE EXTENSION IF NOT EXISTS btree_gist",
        "CREATE TYPE fee_method AS ENUM ('graduated', 'cliff')",
        "CREATE TABLE households ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " tenant_id uuid NOT NULL REFERENCES tenants(id),"
        " name text NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now())",
        "CREATE TABLE clients ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " tenant_id uuid NOT NULL REFERENCES tenants(id),"
        " household_id uuid NOT NULL REFERENCES households(id),"
        " name text NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now())",
        "CREATE INDEX ix_clients_household ON clients (household_id)",
        "CREATE TABLE client_accounts ("
        " account_id uuid PRIMARY KEY REFERENCES accounts(id),"
        " client_id uuid NOT NULL REFERENCES clients(id),"
        " linked_on date NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now())",
        "CREATE INDEX ix_client_accounts_client ON client_accounts (client_id)",
        "CREATE TABLE account_valuations ("
        " account_id uuid NOT NULL REFERENCES accounts(id),"
        " as_of date NOT NULL,"
        " market_value_minor bigint NOT NULL CONSTRAINT ck_account_valuations_non_negative CHECK (market_value_minor >= 0),"
        " source text NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " PRIMARY KEY (account_id, as_of))",
        "CREATE TABLE fee_schedules ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " tenant_id uuid NOT NULL REFERENCES tenants(id),"
        " name text NOT NULL,"
        " revenue_account_id uuid NOT NULL REFERENCES accounts(id),"
        " created_at timestamptz NOT NULL DEFAULT now())",
        "CREATE TABLE fee_schedule_versions ("
        " schedule_id uuid NOT NULL REFERENCES fee_schedules(id),"
        " version int NOT NULL CHECK (version > 0),"
        " method fee_method NOT NULL,"
        " valid_during daterange NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " PRIMARY KEY (schedule_id, valid_during WITHOUT OVERLAPS),"
        " CONSTRAINT uq_fee_schedule_versions_version UNIQUE (schedule_id, version))",
        "CREATE TABLE fee_schedule_tiers ("
        " schedule_id uuid NOT NULL,"
        " version int NOT NULL,"
        " tier_no int NOT NULL CHECK (tier_no > 0),"
        " up_to_minor bigint NULL CHECK (up_to_minor > 0),"
        " rate_bps numeric(8,4) NOT NULL CHECK (rate_bps >= 0),"
        " PRIMARY KEY (schedule_id, version, tier_no),"
        " FOREIGN KEY (schedule_id, version) REFERENCES fee_schedule_versions (schedule_id, version))",
        "CREATE TABLE household_fee_assignments ("
        " household_id uuid NOT NULL REFERENCES households(id),"
        " schedule_id uuid NOT NULL REFERENCES fee_schedules(id),"
        " valid_during daterange NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " PRIMARY KEY (household_id, valid_during WITHOUT OVERLAPS))",
        "CREATE TABLE fee_calculations ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " tenant_id uuid NOT NULL REFERENCES tenants(id),"
        " household_id uuid NOT NULL REFERENCES households(id),"
        " period daterange NOT NULL,"
        " schedule_id uuid NOT NULL,"
        " schedule_version int NOT NULL,"
        " method fee_method NOT NULL,"
        " inputs jsonb NOT NULL,"
        " household_value_minor bigint NOT NULL CHECK (household_value_minor >= 0),"
        " period_fee_minor bigint NOT NULL CHECK (period_fee_minor > 0),"
        " allocations jsonb NOT NULL,"
        " rounding_remainder_minor bigint NOT NULL CHECK (rounding_remainder_minor >= 0),"
        " posting_id uuid NOT NULL REFERENCES postings(id),"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT uq_fee_calculations_posting UNIQUE (posting_id),"
        " FOREIGN KEY (schedule_id, schedule_version) REFERENCES fee_schedule_versions (schedule_id, version))",
    )
    for table in APPEND_ONLY:
        _run(
            f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_mutation()",
            f"CREATE TRIGGER trg_{table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()",
        )


def downgrade() -> None:
    _run(
        "DROP TABLE fee_calculations",
        "DROP TABLE household_fee_assignments",
        "DROP TABLE fee_schedule_tiers",
        "DROP TABLE fee_schedule_versions",
        "DROP TABLE fee_schedules",
        "DROP TABLE account_valuations",
        "DROP TABLE client_accounts",
        "DROP TABLE clients",
        "DROP TABLE households",
        "DROP TYPE fee_method",
        "DROP EXTENSION IF EXISTS btree_gist",
    )
```

- [ ] **Step 2: Create `backend/app/billing/models.py`**

```python
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Integer, Numeric, Text, TIMESTAMP, Date, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import DATERANGE, JSONB, UUID, Range
from sqlalchemy.orm import Mapped, mapped_column

from app.billing.types import FeeMethod
from app.ledger.models import Base

_fee_method = SAEnum(FeeMethod, name="fee_method", native_enum=True)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())


def _created_at() -> Mapped[datetime]:
    return mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class Household(Base):
    __tablename__ = "households"
    __mapper_args__ = {"eager_defaults": True}
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class Client(Base):
    __tablename__ = "clients"
    __mapper_args__ = {"eager_defaults": True}
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    household_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("households.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class ClientAccount(Base):
    __tablename__ = "client_accounts"
    __mapper_args__ = {"eager_defaults": True}
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id"), primary_key=True)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)
    linked_on: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class AccountValuation(Base):
    __tablename__ = "account_valuations"
    __mapper_args__ = {"eager_defaults": True}
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id"), primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, primary_key=True)
    market_value_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class FeeSchedule(Base):
    __tablename__ = "fee_schedules"
    __mapper_args__ = {"eager_defaults": True}
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    revenue_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class FeeScheduleVersion(Base):
    # Database primary key is (schedule_id, valid_during WITHOUT OVERLAPS); the ORM
    # identifies rows by the equally unique (schedule_id, version).
    __tablename__ = "fee_schedule_versions"
    __mapper_args__ = {"eager_defaults": True}
    schedule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fee_schedules.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    method: Mapped[FeeMethod] = mapped_column(_fee_method, nullable=False)
    valid_during: Mapped[Range[date]] = mapped_column(DATERANGE, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class FeeScheduleTier(Base):
    __tablename__ = "fee_schedule_tiers"
    schedule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    tier_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    up_to_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rate_bps: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)


class HouseholdFeeAssignment(Base):
    __tablename__ = "household_fee_assignments"
    __mapper_args__ = {"eager_defaults": True}
    household_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("households.id"), primary_key=True)
    valid_during: Mapped[Range[date]] = mapped_column(DATERANGE, primary_key=True)
    schedule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fee_schedules.id"), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class FeeCalculation(Base):
    __tablename__ = "fee_calculations"
    __mapper_args__ = {"eager_defaults": True}
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    household_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("households.id"), nullable=False)
    period: Mapped[Range[date]] = mapped_column(DATERANGE, nullable=False)
    schedule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    schedule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[FeeMethod] = mapped_column(_fee_method, nullable=False)
    inputs: Mapped[dict] = mapped_column(JSONB, nullable=False)
    household_value_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    period_fee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    allocations: Mapped[dict] = mapped_column(JSONB, nullable=False)
    rounding_remainder_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    posting_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("postings.id"), nullable=False)
    created_at: Mapped[datetime] = _created_at()
```

- [ ] **Step 3: Create `backend/app/billing/errors.py`**

```python
from app.errors import DomainError


class HouseholdNotFound(DomainError):
    status = 404
    type_slug = "household-not-found"
    title = "Household not found"


class NoScheduleAssigned(DomainError):
    status = 422
    type_slug = "no-schedule-assigned"
    title = "No fee schedule applies to this household and period"


class MissingValuation(DomainError):
    status = 422
    type_slug = "missing-valuation"
    title = "A period-end valuation is missing"


class NothingToBill(DomainError):
    status = 422
    type_slug = "nothing-to-bill"
    title = "The household has no billable value in this period"


class AlreadyBilled(DomainError):
    status = 422
    type_slug = "already-billed"
    title = "The household is already billed for this period with different inputs"


class FeeCalculationNotFound(DomainError):
    status = 404
    type_slug = "fee-calculation-not-found"
    title = "Fee calculation not found"
```

- [ ] **Step 4: Create `backend/app/ranges.py`, then `backend/app/billing/dao.py` (setup functions)**

`backend/app/ranges.py`:

```python
from datetime import date, timedelta

from sqlalchemy.dialects.postgresql import Range


def date_range(valid_from: date, valid_until: date | None) -> Range[date]:
    """Inclusive [from, until]; open-ended when until is None. Postgres stores it as [from, until+1)."""
    if valid_until is None:
        return Range(valid_from, None, bounds="[)")
    return Range(valid_from, valid_until, bounds="[]")


def range_end_inclusive(value: Range[date]) -> date | None:
    if value.upper is None:
        return None
    return value.upper if value.bounds[1] == "]" else value.upper - timedelta(days=1)
```

`backend/app/billing/dao.py`:

```python
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
```

- [ ] **Step 5: Register billing models with Alembic**

In `backend/alembic/env.py`, below `from app.ledger.models import Base  # noqa: E402`, add:

```python
import app.billing.models  # noqa: E402,F401  (registers tables on Base.metadata)
```

- [ ] **Step 6: Add the scenario builder to `backend/tests/support.py`**

Append (and move the imports to the top of the file):

```python
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.billing import dao as billing_dao
from app.billing.fee_math import Tier
from app.billing.types import FeeMethod

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
```

- [ ] **Step 7: Write the failing schema tests (`backend/tests/test_billing_schema.py`)**

```python
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
```

- [ ] **Step 8: Run the tests**

Run: `.venv/bin/pytest tests/test_billing_schema.py tests/test_migrations.py -v`
Expected: PASS. The round-trip now also covers `0005`.

- [ ] **Step 9: Commit**

```bash
git add alembic/versions/0005_billing.py alembic/env.py app/ranges.py app/billing/models.py app/billing/errors.py app/billing/dao.py tests/support.py tests/test_billing_schema.py
git commit -m "feat(billing): households, valuations and versioned fee schedules with temporal keys" -m "Schedule versions and household assignments use Postgres 18 WITHOUT OVERLAPS primary keys so two rules can never apply on the same day; all billing facts are append-only."
```

---

### Task 8: Fee run — calculate, post idempotently, store a reproducible record

**Files:**
- Modify: `backend/app/billing/dao.py` (append the fee run functions)
- Create: `backend/app/routes/fee_runs.py`
- Modify: `backend/app/main.py` (include the router)
- Create: `backend/tests/test_fee_runs.py`

**Interfaces:**
- Consumes: `create_posting`, `ledger_transaction`, `EntryInput`, `PostingRequest` (Task 3); `IdempotencyKeyReused` (Task 3); `calculate_household_fee`, `inputs_to_json`, `inputs_from_json`, `FeeInputs`, `AccountValue`, `Tier` (Task 6); billing models and errors (Task 7); `mark_replay` (Task 4); `build_fee_scenario` (Task 7).
- Produces (`app.billing.dao`): `FeeRunResult(calculation: FeeCalculation, replayed: bool)`, `run_household_fee(session, *, tenant_id, household_id, period_start: date, period_end: date) -> FeeRunResult`, `get_fee_calculation(session, *, tenant_id, calculation_id) -> FeeCalculation`.
- Produces endpoints: `POST /fee-runs`, `GET /fee-calculations/{id}`.

- [ ] **Step 1: Write the failing tests (`backend/tests/test_fee_runs.py`)**

```python
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
```

- [ ] **Step 2: Run to confirm it fails**

Run: `.venv/bin/pytest tests/test_fee_runs.py -v`
Expected: FAIL with `AttributeError: module 'app.billing.dao' has no attribute 'run_household_fee'`.

- [ ] **Step 3: Append the fee run to `backend/app/billing/dao.py`**

Add these imports at the top of the file:

```python
import dataclasses
from datetime import datetime, time, timezone
from decimal import Decimal

from sqlalchemy import select

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
```

Then append:

```python
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
```

- [ ] **Step 4: Create `backend/app/routes/fee_runs.py`**

```python
import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.orm import Session

from app.billing.dao import get_fee_calculation, run_household_fee
from app.billing.models import FeeCalculation
from app.billing.types import FeeMethod
from app.deps import get_session, get_tenant_id
from app.ranges import range_end_inclusive
from app.routes.postings import mark_replay

router = APIRouter(tags=["billing"])

SessionDep = Annotated[Session, Depends(get_session)]
TenantDep = Annotated[uuid.UUID, Depends(get_tenant_id)]


class FeeRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    household_id: uuid.UUID
    period_start: date
    period_end: date

    @model_validator(mode="after")
    def end_not_before_start(self) -> "FeeRunIn":
        if self.period_end < self.period_start:
            raise ValueError("period_end must not be before period_start")
        return self


class FeeCalculationOut(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    period_start: date
    period_end: date
    schedule_id: uuid.UUID
    schedule_version: int
    method: FeeMethod
    household_value_minor: int
    period_fee_minor: int
    allocations: dict[str, int]
    rounding_remainder_minor: int
    posting_id: uuid.UUID
    inputs: dict
    created_at: datetime


def _out(calculation: FeeCalculation) -> FeeCalculationOut:
    return FeeCalculationOut(
        id=calculation.id,
        household_id=calculation.household_id,
        period_start=calculation.period.lower,
        period_end=range_end_inclusive(calculation.period),
        schedule_id=calculation.schedule_id,
        schedule_version=calculation.schedule_version,
        method=calculation.method,
        household_value_minor=calculation.household_value_minor,
        period_fee_minor=calculation.period_fee_minor,
        allocations=calculation.allocations,
        rounding_remainder_minor=calculation.rounding_remainder_minor,
        posting_id=calculation.posting_id,
        inputs=calculation.inputs,
        created_at=calculation.created_at,
    )


@router.post("/fee-runs", status_code=201, response_model=FeeCalculationOut)
def run_fee(body: FeeRunIn, response: Response, session: SessionDep, tenant_id: TenantDep) -> FeeCalculationOut:
    result = run_household_fee(
        session, tenant_id=tenant_id, household_id=body.household_id,
        period_start=body.period_start, period_end=body.period_end,
    )
    mark_replay(response, result.replayed)
    return _out(result.calculation)


@router.get("/fee-calculations/{calculation_id}", response_model=FeeCalculationOut)
def read_fee_calculation(calculation_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> FeeCalculationOut:
    return _out(get_fee_calculation(session, tenant_id=tenant_id, calculation_id=calculation_id))
```

- [ ] **Step 5: Include the router in `backend/app/main.py`**

Change the import to `from app.routes import fee_runs, health, postings` and add:

```python
app.include_router(fee_runs.router)
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/pytest tests/test_fee_runs.py -v`
Expected: PASS (13 tests).

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/billing/dao.py app/routes/fee_runs.py app/main.py tests/test_fee_runs.py
git commit -m "feat(billing): idempotent household fee runs posted to the ledger" -m "Resolves the schedule version effective on period end, refuses to guess missing valuations, posts one fee per household and period through the ledger write path, and stores inputs that reproduce the result exactly."
```

---

### Task 9: Governance — AI tool invocations and human approval decisions

**Files:**
- Create: `backend/alembic/versions/0006_governance.py`
- Create: `backend/app/governance/__init__.py` (empty)
- Create: `backend/app/governance/types.py`
- Create: `backend/app/governance/models.py`
- Create: `backend/app/governance/errors.py`
- Create: `backend/app/governance/dao.py`
- Create: `backend/app/routes/tool_invocations.py`
- Modify: `backend/app/main.py` (include the router)
- Modify: `backend/alembic/env.py` (import governance models)
- Create: `backend/tests/test_governance.py`

**Interfaces:**
- Consumes: `create_posting`, `ledger_transaction`, `EntryInput`, `PostingRequest` (Task 3); `canonical_json`, `sha256_hex` (Task 3); `DECIDED_BY`, `get_session`, `get_tenant_id` (Task 4); `forbid_mutation()` (Task 2); `make_account` (Task 2).
- Produces (`app.governance.types`): `ToolDecision(str, Enum)` with values `approved`, `rejected`.
- Produces (`app.governance.dao`):
  - `ModelConfig(provider: str, model_id: str, prompt_version: str, temperature: Decimal)` (frozen)
  - `InvocationRecord(tenant_id, session_id, tool_name, tool_version, model: ModelConfig, input: Mapping[str, object], result_amount_minor: int | None = None, result_currency: str | None = None, citation: Mapping[str, object] | None = None, proposed_entries: tuple[EntryInput, ...] | None = None)` (frozen)
  - `record_invocation(session, record: InvocationRecord) -> ToolInvocation` (commits; **the function the chat sprint calls in-process**)
  - `list_invocations(session, *, tenant_id, posting_id: uuid.UUID | None = None, pending: bool | None = None, limit: int = 50) -> list[tuple[ToolInvocation, ToolInvocationDecision | None]]`
  - `decide(session, *, tenant_id, invocation_id, decision: ToolDecision, decided_by: str, reason: str | None) -> ToolInvocationDecision`
- Produces endpoints: `GET /tool-invocations`, `POST /tool-invocations/{id}/decision`.

- [ ] **Step 1: Create `backend/alembic/versions/0006_governance.py`**

```python
"""governance: AI tool invocations and human approval decisions

Revision ID: 0006_governance
Revises: 0005_billing
"""
from alembic import op

revision = "0006_governance"
down_revision = "0005_billing"
branch_labels = None
depends_on = None


def _run(*statements: str) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    _run(
        "CREATE TYPE tool_decision AS ENUM ('approved', 'rejected')",
        "CREATE TABLE tool_invocations ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " tenant_id uuid NOT NULL REFERENCES tenants(id),"
        " session_id text NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " tool_name text NOT NULL,"
        " tool_version text NOT NULL,"
        " model_provider text NOT NULL,"
        " model_id text NOT NULL,"
        " prompt_version text NOT NULL,"
        " temperature numeric(3,2) NOT NULL CHECK (temperature >= 0),"
        " input jsonb NOT NULL,"
        " input_hash text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),"
        " result_amount_minor bigint NULL,"
        " result_currency text NULL REFERENCES currencies(code),"
        " citation jsonb NULL,"
        " proposed_entries jsonb NULL,"
        " approval_required boolean NOT NULL,"
        " CONSTRAINT ck_tool_invocations_approval_iff_proposal CHECK (approval_required = (proposed_entries IS NOT NULL)),"
        " CONSTRAINT ck_tool_invocations_currency_with_amount CHECK ((result_amount_minor IS NULL) = (result_currency IS NULL)),"
        " CONSTRAINT uq_tool_invocations_id_approval UNIQUE (id, approval_required))",
        "CREATE INDEX ix_tool_invocations_tenant_created ON tool_invocations (tenant_id, created_at DESC)",
        "CREATE TABLE tool_invocation_decisions ("
        " invocation_id uuid PRIMARY KEY,"
        " approval_required boolean NOT NULL DEFAULT true CONSTRAINT ck_decisions_only_for_critical CHECK (approval_required),"
        " decision tool_decision NOT NULL,"
        " decided_by text NOT NULL,"
        " reason text NULL,"
        " decided_at timestamptz NOT NULL DEFAULT now(),"
        " posting_id uuid NULL REFERENCES postings(id),"
        " CONSTRAINT uq_decisions_posting UNIQUE (posting_id),"
        " CONSTRAINT fk_decisions_critical_invocation FOREIGN KEY (invocation_id, approval_required)"
        "   REFERENCES tool_invocations (id, approval_required),"
        " CONSTRAINT ck_decisions_approved_iff_posting CHECK ((decision = 'approved') = (posting_id IS NOT NULL)))",
    )
    for table in ("tool_invocations", "tool_invocation_decisions"):
        _run(
            f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_mutation()",
            f"CREATE TRIGGER trg_{table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()",
        )


def downgrade() -> None:
    _run(
        "DROP TABLE tool_invocation_decisions",
        "DROP TABLE tool_invocations",
        "DROP TYPE tool_decision",
    )
```

- [ ] **Step 2: Create `backend/app/governance/types.py`, `models.py` and `errors.py`**

`backend/app/governance/types.py`:

```python
import enum


class ToolDecision(str, enum.Enum):
    approved = "approved"
    rejected = "rejected"
```

`backend/app/governance/models.py`:

```python
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, ForeignKey, Numeric, Text, TIMESTAMP, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.governance.types import ToolDecision
from app.ledger.models import Base


class ToolInvocation(Base):
    __tablename__ = "tool_invocations"
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    tool_version: Mapped[str] = mapped_column(Text, nullable=False)
    model_provider: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    temperature: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)
    input: Mapped[dict] = mapped_column(JSONB, nullable=False)
    input_hash: Mapped[str] = mapped_column(Text, nullable=False)
    result_amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    result_currency: Mapped[str | None] = mapped_column(Text, ForeignKey("currencies.code"), nullable=True)
    citation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    proposed_entries: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False)


class ToolInvocationDecision(Base):
    __tablename__ = "tool_invocation_decisions"
    __mapper_args__ = {"eager_defaults": True}

    invocation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    decision: Mapped[ToolDecision] = mapped_column(SAEnum(ToolDecision, name="tool_decision", native_enum=True), nullable=False)
    decided_by: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    posting_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("postings.id"), nullable=True)
```

`backend/app/governance/errors.py`:

```python
from app.errors import DomainError


class InvocationNotFound(DomainError):
    status = 404
    type_slug = "invocation-not-found"
    title = "Tool invocation not found"


class NotCritical(DomainError):
    status = 422
    type_slug = "not-critical"
    title = "Only critical tool results (ones that would post to the ledger) take a decision"


class AlreadyDecided(DomainError):
    status = 409
    type_slug = "already-decided"
    title = "This tool invocation has already been decided"
```

- [ ] **Step 3: Register governance models with Alembic**

In `backend/alembic/env.py`, below the billing import, add:

```python
import app.governance.models  # noqa: E402,F401
```

- [ ] **Step 4: Write the failing tests (`backend/tests/test_governance.py`)**

```python
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.governance.dao import InvocationRecord, ModelConfig, decide, list_invocations, record_invocation
from app.governance.errors import AlreadyDecided, InvocationNotFound, NotCritical
from app.governance.models import ToolInvocationDecision
from app.governance.types import ToolDecision
from app.ledger.dao import EntryInput, get_posting
from app.ledger.errors import PostingInvalid
from app.ledger.types import Direction, NormalBalance, PostingSource
from tests.support import make_account

MODEL = ModelConfig(provider="openai", model_id="gpt-4o-2024-08-06", prompt_version="tax-qa-v3", temperature=Decimal("0.20"))


@pytest.fixture()
def accounts(db_session, tenant_id):
    receivable = make_account(db_session, tenant_id, normal_balance=NormalBalance.debit, name="Employment Income Receivable")
    income = make_account(db_session, tenant_id, normal_balance=NormalBalance.credit, name="Reported Income")
    return receivable, income


def _record(db_session, tenant_id, accounts, *, critical=True, amount=9_450_000):
    receivable, income = accounts
    proposed = (
        (EntryInput(receivable.id, Direction.debit, amount), EntryInput(income.id, Direction.credit, amount))
        if critical else None
    )
    return record_invocation(
        db_session,
        InvocationRecord(
            tenant_id=tenant_id,
            session_id="ses_5d21",
            tool_name="total_reported_income",
            tool_version="1.0.0",
            model=MODEL,
            input={"document_id": "doc_7f3a21c9"},
            result_amount_minor=amount,
            result_currency="CAD",
            citation={"document_id": "doc_7f3a21c9", "page": 1, "section": "Employment income"},
            proposed_entries=proposed,
        ),
    )


def test_recording_a_critical_invocation_pins_the_ai_configuration(db_session, tenant_id, accounts):
    invocation = _record(db_session, tenant_id, accounts)
    assert invocation.approval_required is True
    assert (invocation.model_id, invocation.prompt_version, invocation.temperature) == ("gpt-4o-2024-08-06", "tax-qa-v3", Decimal("0.20"))
    assert len(invocation.input_hash) == 64
    assert invocation.proposed_entries[0]["amount"] == 9_450_000


def test_approval_posts_exactly_the_proposed_entries(db_session, tenant_id, accounts):
    invocation = _record(db_session, tenant_id, accounts)
    decision = decide(db_session, tenant_id=tenant_id, invocation_id=invocation.id,
                      decision=ToolDecision.approved, decided_by="demo_user", reason="matches T4 box 14")
    posting = get_posting(db_session, tenant_id=tenant_id, posting_id=decision.posting_id)
    assert posting.source is PostingSource.ai_tool
    assert posting.idempotency_key == f"ai:{invocation.id}"
    receivable, income = accounts
    assert {(e.account_id, e.direction, e.amount) for e in posting.entries} == {
        (receivable.id, Direction.debit, 9_450_000), (income.id, Direction.credit, 9_450_000),
    }


def test_rejection_records_a_decision_without_posting(db_session, tenant_id, accounts):
    invocation = _record(db_session, tenant_id, accounts)
    decision = decide(db_session, tenant_id=tenant_id, invocation_id=invocation.id,
                      decision=ToolDecision.rejected, decided_by="demo_user", reason="wrong document")
    assert decision.posting_id is None


def test_an_invocation_is_decided_only_once(db_session, tenant_id, accounts):
    invocation = _record(db_session, tenant_id, accounts)
    decide(db_session, tenant_id=tenant_id, invocation_id=invocation.id, decision=ToolDecision.rejected, decided_by="demo_user", reason=None)
    with pytest.raises(AlreadyDecided):
        decide(db_session, tenant_id=tenant_id, invocation_id=invocation.id, decision=ToolDecision.approved, decided_by="demo_user", reason=None)


def test_non_critical_invocations_take_no_decision(db_session, tenant_id, accounts):
    invocation = _record(db_session, tenant_id, accounts, critical=False)
    with pytest.raises(NotCritical):
        decide(db_session, tenant_id=tenant_id, invocation_id=invocation.id, decision=ToolDecision.approved, decided_by="demo_user", reason=None)


def test_unknown_invocation_is_not_found(db_session, tenant_id):
    with pytest.raises(InvocationNotFound):
        decide(db_session, tenant_id=tenant_id, invocation_id=uuid.uuid4(), decision=ToolDecision.approved, decided_by="demo_user", reason=None)


def test_invalid_proposal_fails_approval_atomically(db_session, tenant_id, accounts):
    receivable, income = accounts
    invocation = record_invocation(
        db_session,
        InvocationRecord(
            tenant_id=tenant_id, session_id="s", tool_name="t", tool_version="1", model=MODEL, input={"document_id": "d"},
            proposed_entries=(EntryInput(receivable.id, Direction.debit, 10), EntryInput(income.id, Direction.credit, 9)),
        ),
    )
    with pytest.raises(PostingInvalid):
        decide(db_session, tenant_id=tenant_id, invocation_id=invocation.id, decision=ToolDecision.approved, decided_by="demo_user", reason=None)
    assert db_session.get(ToolInvocationDecision, invocation.id) is None


def test_database_rejects_decisions_on_non_critical_invocations(db_session, tenant_id, accounts):
    invocation = _record(db_session, tenant_id, accounts, critical=False)
    with pytest.raises(IntegrityError) as exc_info:  # composite FK finds no (id, true) row
        db_session.execute(
            text("INSERT INTO tool_invocation_decisions (invocation_id, decision, decided_by) VALUES (:id, 'rejected', 'x')"),
            {"id": invocation.id},
        )
    assert exc_info.value.orig.sqlstate == "23503"


def test_database_rejects_approval_without_posting(db_session, tenant_id, accounts):
    invocation = _record(db_session, tenant_id, accounts)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.execute(
            text("INSERT INTO tool_invocation_decisions (invocation_id, decision, decided_by) VALUES (:id, 'approved', 'x')"),
            {"id": invocation.id},
        )
    assert exc_info.value.orig.sqlstate == "23514"


def test_list_filters_pending_and_by_posting(db_session, tenant_id, accounts):
    pending = _record(db_session, tenant_id, accounts)
    approved = _record(db_session, tenant_id, accounts)
    decision = decide(db_session, tenant_id=tenant_id, invocation_id=approved.id, decision=ToolDecision.approved, decided_by="demo_user", reason=None)
    assert [inv.id for inv, _ in list_invocations(db_session, tenant_id=tenant_id, pending=True)] == [pending.id]
    by_posting = list_invocations(db_session, tenant_id=tenant_id, posting_id=decision.posting_id)
    assert [(inv.id, d.decision) for inv, d in by_posting] == [(approved.id, ToolDecision.approved)]


# --- API -------------------------------------------------------------------------------------

def test_decision_endpoint_and_listing(client, db_session, tenant_id, accounts):
    invocation = _record(db_session, tenant_id, accounts)
    pending = client.get("/tool-invocations", params={"pending": "true"}).json()
    assert [row["id"] for row in pending] == [str(invocation.id)]

    created = client.post(f"/tool-invocations/{invocation.id}/decision", json={"decision": "approved", "reason": "ok"})
    assert created.status_code == 201
    posting_id = created.json()["posting_id"]
    provenance = client.get("/tool-invocations", params={"posting_id": posting_id}).json()
    assert provenance[0]["model_id"] == "gpt-4o-2024-08-06"
    assert provenance[0]["decision"]["decided_by"] == "demo_user"

    again = client.post(f"/tool-invocations/{invocation.id}/decision", json={"decision": "approved"})
    assert again.status_code == 409 and again.json()["type"] == "/problems/already-decided"


def test_decision_endpoint_errors(client, db_session, tenant_id, accounts):
    lookup = _record(db_session, tenant_id, accounts, critical=False)
    assert client.post(f"/tool-invocations/{lookup.id}/decision", json={"decision": "approved"}).status_code == 422
    assert client.post(f"/tool-invocations/{uuid.uuid4()}/decision", json={"decision": "approved"}).status_code == 404
```

- [ ] **Step 5: Run to confirm it fails**

Run: `.venv/bin/pytest tests/test_governance.py -v`
Expected: ERROR `ModuleNotFoundError: No module named 'app.governance.dao'`.

- [ ] **Step 6: Create `backend/app/governance/dao.py`**

```python
import dataclasses
import uuid
from collections.abc import Mapping
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.governance.errors import AlreadyDecided, InvocationNotFound, NotCritical
from app.governance.models import ToolInvocation, ToolInvocationDecision
from app.governance.types import ToolDecision
from app.ledger.dao import EntryInput, PostingRequest, create_posting, ledger_transaction
from app.ledger.fingerprint import canonical_json, sha256_hex
from app.ledger.types import Direction, PostingSource


@dataclasses.dataclass(frozen=True)
class ModelConfig:
    provider: str
    model_id: str  # exact snapshot, e.g. "gpt-4o-2024-08-06", never an alias
    prompt_version: str
    temperature: Decimal


@dataclasses.dataclass(frozen=True)
class InvocationRecord:
    tenant_id: uuid.UUID
    session_id: str
    tool_name: str
    tool_version: str
    model: ModelConfig
    input: Mapping[str, object]
    result_amount_minor: int | None = None
    result_currency: str | None = None
    citation: Mapping[str, object] | None = None
    proposed_entries: tuple[EntryInput, ...] | None = None  # present = critical, needs a human decision


def _entries_to_json(entries: tuple[EntryInput, ...]) -> list[dict]:
    return [{"account_id": str(e.account_id), "direction": e.direction.value, "amount": e.amount} for e in entries]


def _entries_from_json(data: list[dict]) -> tuple[EntryInput, ...]:
    return tuple(EntryInput(uuid.UUID(e["account_id"]), Direction(e["direction"]), int(e["amount"])) for e in data)


def record_invocation(session: Session, record: InvocationRecord) -> ToolInvocation:
    """Append an AI tool call with its full configuration. Called in-process by the chat pipeline."""
    proposed = None if record.proposed_entries is None else _entries_to_json(record.proposed_entries)
    invocation = ToolInvocation(
        tenant_id=record.tenant_id,
        session_id=record.session_id,
        tool_name=record.tool_name,
        tool_version=record.tool_version,
        model_provider=record.model.provider,
        model_id=record.model.model_id,
        prompt_version=record.model.prompt_version,
        temperature=record.model.temperature,
        input=dict(record.input),
        input_hash=sha256_hex(canonical_json(dict(record.input))),
        result_amount_minor=record.result_amount_minor,
        result_currency=record.result_currency,
        citation=None if record.citation is None else dict(record.citation),
        proposed_entries=proposed,
        approval_required=proposed is not None,
    )
    session.add(invocation)
    session.commit()
    return invocation


def list_invocations(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    posting_id: uuid.UUID | None = None,
    pending: bool | None = None,
    limit: int = 50,
) -> list[tuple[ToolInvocation, ToolInvocationDecision | None]]:
    query = (
        select(ToolInvocation, ToolInvocationDecision)
        .outerjoin(ToolInvocationDecision, ToolInvocationDecision.invocation_id == ToolInvocation.id)
        .where(ToolInvocation.tenant_id == tenant_id)
    )
    if posting_id is not None:
        query = query.where(ToolInvocationDecision.posting_id == posting_id)
    if pending is True:
        query = query.where(ToolInvocation.approval_required.is_(True), ToolInvocationDecision.invocation_id.is_(None))
    elif pending is False:
        query = query.where(ToolInvocationDecision.invocation_id.is_not(None))
    query = query.order_by(ToolInvocation.created_at.desc(), ToolInvocation.id.desc()).limit(limit)
    return [(invocation, decision) for invocation, decision in session.execute(query)]


def decide(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    invocation_id: uuid.UUID,
    decision: ToolDecision,
    decided_by: str,
    reason: str | None,
) -> ToolInvocationDecision:
    invocation = session.get(ToolInvocation, invocation_id)
    if invocation is None or invocation.tenant_id != tenant_id:
        raise InvocationNotFound(f"Tool invocation {invocation_id} does not exist.")
    if not invocation.approval_required:
        raise NotCritical(f"Tool invocation {invocation_id} proposed no ledger posting.")
    if session.get(ToolInvocationDecision, invocation_id) is not None:
        raise AlreadyDecided(f"Tool invocation {invocation_id} has already been decided.")

    with ledger_transaction(session):
        posting_id = None
        if decision is ToolDecision.approved:
            posted = create_posting(
                session,
                PostingRequest(
                    tenant_id=tenant_id,
                    idempotency_key=f"ai:{invocation_id}",
                    entries=_entries_from_json(invocation.proposed_entries),
                    description=f"Approved {invocation.tool_name} result ({invocation_id})",
                    source=PostingSource.ai_tool,
                ),
            )
            posting_id = posted.posting.id
        record = ToolInvocationDecision(
            invocation_id=invocation_id, decision=decision, decided_by=decided_by, reason=reason, posting_id=posting_id
        )
        try:
            with session.begin_nested():
                session.add(record)
                session.flush()
        except IntegrityError as exc:  # a concurrent decision won the primary key
            raise AlreadyDecided(f"Tool invocation {invocation_id} has already been decided.") from exc
    return record
```

- [ ] **Step 7: Create `backend/app/routes/tool_invocations.py`**

```python
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.deps import DECIDED_BY, get_session, get_tenant_id
from app.governance.dao import decide, list_invocations
from app.governance.models import ToolInvocation, ToolInvocationDecision
from app.governance.types import ToolDecision

router = APIRouter(prefix="/tool-invocations", tags=["governance"])

SessionDep = Annotated[Session, Depends(get_session)]
TenantDep = Annotated[uuid.UUID, Depends(get_tenant_id)]


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: ToolDecision
    reason: str | None = Field(default=None, max_length=1000)


class DecisionOut(BaseModel):
    invocation_id: uuid.UUID
    decision: ToolDecision
    decided_by: str
    reason: str | None
    decided_at: datetime
    posting_id: uuid.UUID | None


class InvocationOut(BaseModel):
    id: uuid.UUID
    session_id: str
    created_at: datetime
    tool_name: str
    tool_version: str
    model_provider: str
    model_id: str
    prompt_version: str
    temperature: Decimal
    input: dict
    result_amount_minor: int | None
    result_currency: str | None
    citation: dict | None
    proposed_entries: list | None
    approval_required: bool
    decision: DecisionOut | None


def _decision_out(decision: ToolInvocationDecision) -> DecisionOut:
    return DecisionOut(
        invocation_id=decision.invocation_id, decision=decision.decision, decided_by=decision.decided_by,
        reason=decision.reason, decided_at=decision.decided_at, posting_id=decision.posting_id,
    )


def _invocation_out(invocation: ToolInvocation, decision: ToolInvocationDecision | None) -> InvocationOut:
    return InvocationOut(
        id=invocation.id, session_id=invocation.session_id, created_at=invocation.created_at,
        tool_name=invocation.tool_name, tool_version=invocation.tool_version,
        model_provider=invocation.model_provider, model_id=invocation.model_id,
        prompt_version=invocation.prompt_version, temperature=invocation.temperature,
        input=invocation.input, result_amount_minor=invocation.result_amount_minor,
        result_currency=invocation.result_currency, citation=invocation.citation,
        proposed_entries=invocation.proposed_entries, approval_required=invocation.approval_required,
        decision=None if decision is None else _decision_out(decision),
    )


@router.get("", response_model=list[InvocationOut])
def list_tool_invocations(
    session: SessionDep,
    tenant_id: TenantDep,
    posting_id: uuid.UUID | None = None,
    pending: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[InvocationOut]:
    rows = list_invocations(session, tenant_id=tenant_id, posting_id=posting_id, pending=pending, limit=limit)
    return [_invocation_out(invocation, decision) for invocation, decision in rows]


@router.post("/{invocation_id}/decision", status_code=201, response_model=DecisionOut)
def decide_tool_invocation(
    invocation_id: uuid.UUID, body: DecisionIn, session: SessionDep, tenant_id: TenantDep
) -> DecisionOut:
    decision = decide(
        session, tenant_id=tenant_id, invocation_id=invocation_id,
        decision=body.decision, decided_by=DECIDED_BY, reason=body.reason,
    )
    return _decision_out(decision)
```

- [ ] **Step 8: Include the router in `backend/app/main.py`**

Change the import to `from app.routes import fee_runs, health, postings, tool_invocations` and add:

```python
app.include_router(tool_invocations.router)
```

- [ ] **Step 9: Run the tests**

Run: `.venv/bin/pytest tests/test_governance.py tests/test_migrations.py -v`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add alembic/versions/0006_governance.py alembic/env.py app/governance app/routes/tool_invocations.py app/main.py tests/test_governance.py
git commit -m "feat(governance): audited AI tool invocations with human approval before posting" -m "Every tool call pins tool, model, prompt version and temperature; only critical results take a decision, approval posts exactly the proposed entries atomically, and the database refuses decisions on non-critical calls or approvals without a posting."
```

---

### Task 10: Reporting — reproducible GL-ready export

**Files:**
- Create: `backend/alembic/versions/0007_reporting.py`
- Modify: `backend/app/ledger/dao.py` (append `GlCodeTotal`, `GlTotals`, `sum_entries_by_gl_code`)
- Create: `backend/app/reporting/__init__.py` (empty)
- Create: `backend/app/reporting/gl_csv.py`
- Create: `backend/app/reporting/models.py`
- Create: `backend/app/reporting/errors.py`
- Create: `backend/app/reporting/dao.py`
- Create: `backend/app/routes/gl_exports.py`
- Modify: `backend/app/main.py` (include the router)
- Modify: `backend/alembic/env.py` (import reporting models)
- Create: `backend/tests/test_gl_csv.py`
- Create: `backend/tests/test_gl_exports.py`

**Interfaces:**
- Consumes: `Posting`, `Entry`, `Account`, `Currency` (Task 2); `sha256_hex` (Task 3); `app.ranges.date_range`, `range_end_inclusive` (Task 7); `build_fee_scenario` (Task 7); `run_household_fee` (Task 8); `create_posting`, `ledger_transaction`, `PostingRequest`, `EntryInput` (Task 3).
- Produces (`app.ledger.dao`): `GlCodeTotal(gl_code: str, account_names: tuple[str, ...], debit_minor: int, credit_minor: int, posting_count: int)`, `GlTotals(lines: tuple[GlCodeTotal, ...], accounts_missing_gl_code: tuple[uuid.UUID, ...])`, `sum_entries_by_gl_code(session, *, tenant_id, currency, period_start: date, period_end: date, cutoff: datetime) -> GlTotals`.
- Produces (`app.reporting.gl_csv`): `HEADER`, `format_minor(amount_minor: int, minor_units: int) -> str`, `RenderedExport(content: str, sha256: str, line_count: int, total_debits_minor: int, total_credits_minor: int)`, `render(lines: Sequence[GlCodeTotal], *, currency: str, minor_units: int) -> RenderedExport`.
- Produces (`app.reporting.dao`): `SETTLE_MARGIN: timedelta`, `create_gl_export(session, *, tenant_id, currency, period_start, period_end, settle_margin=SETTLE_MARGIN) -> GlExport`, `export_csv(session, *, tenant_id, export_id) -> tuple[GlExport, str]`.
- Produces endpoints: `POST /gl-exports`, `GET /gl-exports/{id}.csv`; dependency `get_settle_margin() -> timedelta` (tests override it to `timedelta(0)`).

- [ ] **Step 1: Create `backend/alembic/versions/0007_reporting.py`**

```python
"""reporting: reproducible GL export records

Revision ID: 0007_reporting
Revises: 0006_governance
"""
from alembic import op

revision = "0007_reporting"
down_revision = "0006_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in (
        "CREATE TABLE gl_exports ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " tenant_id uuid NOT NULL REFERENCES tenants(id),"
        " period daterange NOT NULL,"
        " currency text NOT NULL REFERENCES currencies(code),"
        " cutoff timestamptz NOT NULL,"
        " line_count int NOT NULL CHECK (line_count >= 0),"
        " total_debits_minor bigint NOT NULL CHECK (total_debits_minor >= 0),"
        " total_credits_minor bigint NOT NULL,"
        " content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT ck_gl_exports_balanced CHECK (total_debits_minor = total_credits_minor))",
        "CREATE TRIGGER trg_gl_exports_append_only BEFORE UPDATE OR DELETE ON gl_exports "
        "FOR EACH ROW EXECUTE FUNCTION forbid_mutation()",
        "CREATE TRIGGER trg_gl_exports_no_truncate BEFORE TRUNCATE ON gl_exports "
        "FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE gl_exports")
```

- [ ] **Step 2: Write the failing CSV unit tests (`backend/tests/test_gl_csv.py`)**

```python
import pytest

from app.ledger.dao import GlCodeTotal
from app.reporting.gl_csv import format_minor, render


@pytest.mark.parametrize(
    ("amount", "units", "expected"),
    [(366_941, 2, "3669.41"), (0, 2, "0.00"), (-1200, 2, "-12.00"), (5, 0, "5"), (7, 3, "0.007")],
)
def test_format_minor(amount, units, expected):
    assert format_minor(amount, units) == expected


def test_render_writes_lines_and_a_balanced_control_row():
    lines = [
        GlCodeTotal("2100", ("Client cash A", "Client cash B"), 366_941, 0, 1),
        GlCodeTotal("4000", ("Advisory Fee Revenue",), 0, 366_941, 1),
    ]
    rendered = render(lines, currency="CAD", minor_units=2)
    assert rendered.content.splitlines() == [
        "gl_code,account_names,currency,debit,credit,net,posting_count",
        "2100,Client cash A; Client cash B,CAD,3669.41,0.00,3669.41,1",
        "4000,Advisory Fee Revenue,CAD,0.00,3669.41,-3669.41,1",
        "TOTAL,,CAD,3669.41,3669.41,0.00,",
    ]
    assert (rendered.line_count, rendered.total_debits_minor, rendered.total_credits_minor) == (2, 366_941, 366_941)
    assert rendered.sha256 == render(lines, currency="CAD", minor_units=2).sha256


def test_render_empty_period_is_header_and_zero_total():
    rendered = render([], currency="CAD", minor_units=2)
    assert rendered.content.splitlines() == [
        "gl_code,account_names,currency,debit,credit,net,posting_count",
        "TOTAL,,CAD,0.00,0.00,0.00,",
    ]


def test_render_refuses_unbalanced_input():
    with pytest.raises(ValueError):
        render([GlCodeTotal("1000", ("x",), 10, 9, 1)], currency="CAD", minor_units=2)
```

- [ ] **Step 3: Run to confirm it fails**

Run: `.venv/bin/pytest tests/test_gl_csv.py -v`
Expected: ERROR `ImportError: cannot import name 'GlCodeTotal' from 'app.ledger.dao'`.

- [ ] **Step 4: Append the GL query to `backend/app/ledger/dao.py`**

Add these imports at the top of the file: `from datetime import date, time, timedelta, timezone` (extend the existing `datetime` import) and `from sqlalchemy import case, distinct, func`. Then append:

```python
@dataclasses.dataclass(frozen=True)
class GlCodeTotal:
    gl_code: str
    account_names: tuple[str, ...]
    debit_minor: int
    credit_minor: int
    posting_count: int


@dataclasses.dataclass(frozen=True)
class GlTotals:
    lines: tuple[GlCodeTotal, ...]
    accounts_missing_gl_code: tuple[uuid.UUID, ...]


def sum_entries_by_gl_code(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    currency: str,
    period_start: date,
    period_end: date,
    cutoff: datetime,
) -> GlTotals:
    """Per-GL-code totals for postings effective in [period_start, period_end] (UTC days)
    and recorded at or before cutoff. Stress-test traffic is always excluded."""
    window_start = datetime.combine(period_start, time.min, tzinfo=timezone.utc)
    window_end = datetime.combine(period_end + timedelta(days=1), time.min, tzinfo=timezone.utc)
    in_scope = (
        Posting.tenant_id == tenant_id,
        Account.currency == currency,
        Posting.effective_at >= window_start,
        Posting.effective_at < window_end,
        Posting.created_at <= cutoff,
        Posting.source != PostingSource.stress_test,
    )

    def joined(*columns):
        return (
            select(*columns)
            .select_from(Entry)
            .join(Posting, Posting.id == Entry.posting_id)
            .join(Account, Account.id == Entry.account_id)
        )

    missing = session.scalars(joined(distinct(Account.id)).where(*in_scope, Account.gl_code.is_(None))).all()

    debit = func.coalesce(func.sum(case((Entry.direction == Direction.debit, Entry.amount), else_=0)), 0)
    credit = func.coalesce(func.sum(case((Entry.direction == Direction.credit, Entry.amount), else_=0)), 0)
    rows = session.execute(
        joined(Account.gl_code, func.array_agg(distinct(Account.name)), debit, credit, func.count(distinct(Posting.id)))
        .where(*in_scope, Account.gl_code.is_not(None))
        .group_by(Account.gl_code)
        .order_by(Account.gl_code)
    ).all()
    lines = tuple(
        GlCodeTotal(gl_code, tuple(sorted(names)), int(debit_sum), int(credit_sum), int(count))
        for gl_code, names, debit_sum, credit_sum, count in rows
    )
    return GlTotals(lines=lines, accounts_missing_gl_code=tuple(sorted(missing, key=str)))
```

- [ ] **Step 5: Create `backend/app/reporting/gl_csv.py`**

```python
import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.ledger.dao import GlCodeTotal
from app.ledger.fingerprint import sha256_hex

HEADER = ("gl_code", "account_names", "currency", "debit", "credit", "net", "posting_count")


@dataclass(frozen=True)
class RenderedExport:
    content: str
    sha256: str
    line_count: int
    total_debits_minor: int
    total_credits_minor: int


def format_minor(amount_minor: int, minor_units: int) -> str:
    quantum = Decimal(1).scaleb(-minor_units)
    return str(Decimal(amount_minor).scaleb(-minor_units).quantize(quantum))


def render(lines: Sequence[GlCodeTotal], *, currency: str, minor_units: int) -> RenderedExport:
    """CSV with one row per GL code plus a TOTAL control row; net = debit - credit."""
    total_debits = sum(line.debit_minor for line in lines)
    total_credits = sum(line.credit_minor for line in lines)
    if total_debits != total_credits:
        raise ValueError(f"GL export does not balance: debits {total_debits} != credits {total_credits}")

    def money(amount: int) -> str:
        return format_minor(amount, minor_units)

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(HEADER)
    for line in lines:
        writer.writerow([
            line.gl_code, "; ".join(line.account_names), currency,
            money(line.debit_minor), money(line.credit_minor), money(line.debit_minor - line.credit_minor),
            line.posting_count,
        ])
    writer.writerow(["TOTAL", "", currency, money(total_debits), money(total_credits), money(0), ""])
    content = buffer.getvalue()
    return RenderedExport(content, sha256_hex(content), len(lines), total_debits, total_credits)
```

- [ ] **Step 6: Run the CSV tests**

Run: `.venv/bin/pytest tests/test_gl_csv.py -v`
Expected: PASS.

- [ ] **Step 7: Create `backend/app/reporting/models.py` and `errors.py`**

`backend/app/reporting/models.py`:

```python
import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, ForeignKey, Integer, Text, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import DATERANGE, UUID, Range
from sqlalchemy.orm import Mapped, mapped_column

from app.ledger.models import Base


class GlExport(Base):
    __tablename__ = "gl_exports"
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    period: Mapped[Range[date]] = mapped_column(DATERANGE, nullable=False)
    currency: Mapped[str] = mapped_column(Text, ForeignKey("currencies.code"), nullable=False)
    cutoff: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_debits_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_credits_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
```

`backend/app/reporting/errors.py`:

```python
from app.errors import DomainError


class GlCodeMissing(DomainError):
    status = 422
    type_slug = "gl-code-missing"
    title = "Some accounts in this period have no GL code"


class UnknownCurrency(DomainError):
    status = 422
    type_slug = "unknown-currency"
    title = "Currency is not configured"


class GlExportNotFound(DomainError):
    status = 404
    type_slug = "gl-export-not-found"
    title = "GL export not found"


class GlExportIntegrityError(DomainError):
    status = 500
    type_slug = "gl-export-integrity"
    title = "Regenerated GL export does not match its recorded hash"
```

In `backend/alembic/env.py`, add below the governance import:

```python
import app.reporting.models  # noqa: E402,F401
```

- [ ] **Step 8: Write the failing export tests (`backend/tests/test_gl_exports.py`)**

```python
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.billing.dao import run_household_fee
from app.ledger.dao import EntryInput, PostingRequest, create_posting, ledger_transaction
from app.ledger.types import Direction, PostingSource
from app.reporting.dao import create_gl_export, export_csv
from app.reporting.errors import GlCodeMissing
from tests.support import build_fee_scenario, make_account

Q3 = {"period_start": date(2026, 7, 1), "period_end": date(2026, 9, 30)}
NO_SETTLE = timedelta(0)


def _billed_scenario(db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    run_household_fee(db_session, tenant_id=tenant_id, household_id=scenario.household_id, **Q3)
    return scenario


def _export(db_session, tenant_id, **period):
    return create_gl_export(db_session, tenant_id=tenant_id, currency="CAD", settle_margin=NO_SETTLE, **(period or Q3))


def test_export_groups_the_fee_posting_by_gl_code(db_session, tenant_id):
    _billed_scenario(db_session, tenant_id)
    export = _export(db_session, tenant_id)
    _, content = export_csv(db_session, tenant_id=tenant_id, export_id=export.id)
    lines = content.splitlines()
    assert lines[1].startswith("2100,") and ",CAD,3669.41,0.00,3669.41,1" in lines[1]
    assert lines[2] == "4000,Advisory Fee Revenue,CAD,0.00,3669.41,-3669.41,1"
    assert lines[3] == "TOTAL,,CAD,3669.41,3669.41,0.00,"
    assert (export.line_count, export.total_debits_minor, export.total_credits_minor) == (2, 366_941, 366_941)


def test_regeneration_matches_the_hash_after_later_postings(db_session, tenant_id):
    scenario = _billed_scenario(db_session, tenant_id)
    export = _export(db_session, tenant_id)
    first, _ = scenario.client_account_ids
    with ledger_transaction(db_session):  # later posting, same period: after the cutoff, so excluded
        create_posting(db_session, PostingRequest(
            tenant_id=tenant_id, idempotency_key=str(uuid.uuid4()),
            entries=(EntryInput(first, Direction.debit, 5), EntryInput(scenario.revenue_account_id, Direction.credit, 5)),
        ))
    regenerated_export, content = export_csv(db_session, tenant_id=tenant_id, export_id=export.id)
    assert regenerated_export.content_sha256 == export.content_sha256
    assert "TOTAL,,CAD,3669.41,3669.41,0.00," in content


def test_stress_postings_are_excluded(db_session, tenant_id):
    scenario = _billed_scenario(db_session, tenant_id)
    first, _ = scenario.client_account_ids
    with ledger_transaction(db_session):
        create_posting(db_session, PostingRequest(
            tenant_id=tenant_id, idempotency_key=str(uuid.uuid4()), source=PostingSource.stress_test,
            entries=(EntryInput(first, Direction.debit, 7), EntryInput(scenario.revenue_account_id, Direction.credit, 7)),
        ))
    export = _export(db_session, tenant_id)
    assert export.total_debits_minor == 366_941


def test_accounts_without_gl_code_block_the_export(db_session, tenant_id):
    scenario = _billed_scenario(db_session, tenant_id)
    uncoded = make_account(db_session, tenant_id)
    with ledger_transaction(db_session):
        create_posting(db_session, PostingRequest(
            tenant_id=tenant_id, idempotency_key=str(uuid.uuid4()),
            effective_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
            entries=(EntryInput(uncoded.id, Direction.debit, 3), EntryInput(scenario.revenue_account_id, Direction.credit, 3)),
        ))
    with pytest.raises(GlCodeMissing) as exc_info:
        _export(db_session, tenant_id)
    assert exc_info.value.extensions["account_ids"] == [str(uncoded.id)]


def test_empty_period_exports_header_and_zero_total(db_session, tenant_id):
    export = _export(db_session, tenant_id, period_start=date(2020, 1, 1), period_end=date(2020, 3, 31))
    _, content = export_csv(db_session, tenant_id=tenant_id, export_id=export.id)
    assert content.splitlines()[-1] == "TOTAL,,CAD,0.00,0.00,0.00,"
    assert export.line_count == 0


# --- API -------------------------------------------------------------------------------------

@pytest.fixture()
def no_settle(client):
    from app.main import app
    from app.routes.gl_exports import get_settle_margin

    app.dependency_overrides[get_settle_margin] = lambda: NO_SETTLE
    return client


def test_export_endpoints_create_and_download(no_settle, db_session, tenant_id):
    _billed_scenario(db_session, tenant_id)
    created = no_settle.post("/gl-exports", json={"period_start": "2026-07-01", "period_end": "2026-09-30", "currency": "CAD"})
    assert created.status_code == 201
    download = no_settle.get(created.json()["csv_url"])
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("text/csv")
    assert download.text.splitlines()[-1] == "TOTAL,,CAD,3669.41,3669.41,0.00,"


def test_export_endpoint_errors(no_settle):
    assert no_settle.get(f"/gl-exports/{uuid.uuid4()}.csv").status_code == 404
    unknown = no_settle.post("/gl-exports", json={"period_start": "2026-07-01", "period_end": "2026-09-30", "currency": "EUR"})
    assert unknown.status_code == 422 and unknown.json()["type"] == "/problems/unknown-currency"
```

- [ ] **Step 9: Run to confirm it fails**

Run: `.venv/bin/pytest tests/test_gl_exports.py -v`
Expected: ERROR `ModuleNotFoundError: No module named 'app.reporting.dao'`.

- [ ] **Step 10: Create `backend/app/reporting/dao.py`**

```python
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ledger.dao import sum_entries_by_gl_code
from app.ledger.models import Currency
from app.ranges import date_range, range_end_inclusive
from app.reporting.errors import GlCodeMissing, GlExportIntegrityError, GlExportNotFound, UnknownCurrency
from app.reporting.gl_csv import RenderedExport, render
from app.reporting.models import GlExport

# ponytail: postings carry created_at = their transaction's start time, so a transaction that
# began before the cutoff but commits after the export read would appear on regeneration.
# Ledger statements are capped at 10s (ledger.dao.STATEMENT_TIMEOUT) and a posting is a handful
# of statements, so a 60s margin excludes them. Upgrade path if long transactions ever appear:
# cut off by a commit-ordered marker (pg_current_snapshot) instead of a timestamp.
SETTLE_MARGIN = timedelta(seconds=60)


def _render(
    session: Session, tenant_id: uuid.UUID, currency: str, period_start: date, period_end: date, cutoff: datetime
) -> RenderedExport:
    currency_row = session.get(Currency, currency)
    if currency_row is None:
        raise UnknownCurrency(f"Currency {currency!r} is not configured.")
    totals = sum_entries_by_gl_code(
        session, tenant_id=tenant_id, currency=currency, period_start=period_start, period_end=period_end, cutoff=cutoff
    )
    if totals.accounts_missing_gl_code:
        missing = [str(account_id) for account_id in totals.accounts_missing_gl_code]
        raise GlCodeMissing(
            f"{len(missing)} account(s) with activity in this period have no GL code; set one before exporting.",
            account_ids=missing,
        )
    return render(totals.lines, currency=currency, minor_units=currency_row.minor_units)


def create_gl_export(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    currency: str,
    period_start: date,
    period_end: date,
    settle_margin: timedelta = SETTLE_MARGIN,
) -> GlExport:
    cutoff = session.execute(select(func.now())).scalar_one() - settle_margin
    rendered = _render(session, tenant_id, currency, period_start, period_end, cutoff)
    export = GlExport(
        tenant_id=tenant_id,
        period=date_range(period_start, period_end),
        currency=currency,
        cutoff=cutoff,
        line_count=rendered.line_count,
        total_debits_minor=rendered.total_debits_minor,
        total_credits_minor=rendered.total_credits_minor,
        content_sha256=rendered.sha256,
    )
    session.add(export)
    session.commit()
    return export


def export_csv(session: Session, *, tenant_id: uuid.UUID, export_id: uuid.UUID) -> tuple[GlExport, str]:
    export = session.get(GlExport, export_id)
    if export is None or export.tenant_id != tenant_id:
        raise GlExportNotFound(f"GL export {export_id} does not exist.")
    rendered = _render(
        session, tenant_id, export.currency, export.period.lower, range_end_inclusive(export.period), export.cutoff
    )
    if rendered.sha256 != export.content_sha256:
        raise GlExportIntegrityError(f"GL export {export_id} no longer reproduces; the ledger history changed.")
    return export, rendered.content
```

- [ ] **Step 11: Create `backend/app/routes/gl_exports.py`**

```python
import uuid
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.deps import get_session, get_tenant_id
from app.ranges import range_end_inclusive
from app.reporting.dao import SETTLE_MARGIN, create_gl_export, export_csv
from app.reporting.models import GlExport

router = APIRouter(prefix="/gl-exports", tags=["reporting"])

SessionDep = Annotated[Session, Depends(get_session)]
TenantDep = Annotated[uuid.UUID, Depends(get_tenant_id)]


def get_settle_margin() -> timedelta:
    return SETTLE_MARGIN


class GlExportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date
    period_end: date
    currency: str = Field(pattern=r"^[A-Z]{3}$")

    @model_validator(mode="after")
    def end_not_before_start(self) -> "GlExportIn":
        if self.period_end < self.period_start:
            raise ValueError("period_end must not be before period_start")
        return self


class GlExportOut(BaseModel):
    id: uuid.UUID
    period_start: date
    period_end: date
    currency: str
    cutoff: datetime
    line_count: int
    total_debits_minor: int
    total_credits_minor: int
    content_sha256: str
    created_at: datetime
    csv_url: str


def _out(export: GlExport) -> GlExportOut:
    return GlExportOut(
        id=export.id, period_start=export.period.lower, period_end=range_end_inclusive(export.period),
        currency=export.currency, cutoff=export.cutoff, line_count=export.line_count,
        total_debits_minor=export.total_debits_minor, total_credits_minor=export.total_credits_minor,
        content_sha256=export.content_sha256, created_at=export.created_at, csv_url=f"/gl-exports/{export.id}.csv",
    )


@router.post("", status_code=201, response_model=GlExportOut)
def create_export(
    body: GlExportIn,
    session: SessionDep,
    tenant_id: TenantDep,
    settle_margin: Annotated[timedelta, Depends(get_settle_margin)],
) -> GlExportOut:
    export = create_gl_export(
        session, tenant_id=tenant_id, currency=body.currency,
        period_start=body.period_start, period_end=body.period_end, settle_margin=settle_margin,
    )
    return _out(export)


@router.get("/{export_id}.csv", response_class=PlainTextResponse)
def download_export(export_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> PlainTextResponse:
    export, content = export_csv(session, tenant_id=tenant_id, export_id=export_id)
    return PlainTextResponse(
        content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="gl-export-{export.id}.csv"',
            "X-Content-SHA256": export.content_sha256,
        },
    )
```

- [ ] **Step 12: Include the router in `backend/app/main.py`**

Change the import to `from app.routes import fee_runs, gl_exports, health, postings, tool_invocations` and add:

```python
app.include_router(gl_exports.router)
```

- [ ] **Step 13: Run the tests**

Run: `.venv/bin/pytest tests/test_gl_csv.py tests/test_gl_exports.py tests/test_migrations.py -v`
Expected: PASS.

- [ ] **Step 14: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS.

- [ ] **Step 15: Commit**

```bash
git add alembic/versions/0007_reporting.py alembic/env.py app/ledger/dao.py app/reporting app/routes/gl_exports.py app/main.py tests/test_gl_csv.py tests/test_gl_exports.py
git commit -m "feat(reporting): reproducible GL-ready CSV export with control totals" -m "Exports group ledger activity by GL code for a period and cutoff, refuse accounts without a GL code, store only a hash, and regenerate byte-identical output from the immutable ledger."
```

---

### Task 11: Demo seed, documentation, changelog, knowledge graph

**Files:**
- Create: `backend/scripts/seed_demo.py`
- Modify: `CLAUDE.md` (sections "Tech Stack", "Current Scope", "Code Conventions", "Running Locally")
- Modify: `README.md` (add a "Ledger core" section after "Local development — ledger DB core")
- Modify: `CHANGELOG.md` (add a sprint section at the top)

**Interfaces:**
- Consumes: every package's models; `reports/concurrency.json` from Task 5.
- Produces: nothing code depends on.

- [ ] **Step 1: Create `backend/scripts/seed_demo.py`**

```python
"""Seed ledger_dev with the demo tenant's book: run `./scripts/db_up.sh` first, then
`.venv/bin/python scripts/seed_demo.py` from backend/. Safe to run twice."""
import sys
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.dialects.postgresql import Range  # noqa: E402

from app.billing.models import (  # noqa: E402
    AccountValuation, Client, ClientAccount, FeeSchedule, FeeScheduleTier,
    FeeScheduleVersion, Household, HouseholdFeeAssignment,
)
from app.billing.types import FeeMethod  # noqa: E402
from app.ledger.db import SessionLocal  # noqa: E402
from app.ledger.models import Account  # noqa: E402
from app.ledger.types import DEMO_TENANT_ID, NormalBalance  # noqa: E402

T = DEMO_TENANT_ID
ID = {name: uuid.uuid5(uuid.NAMESPACE_URL, f"ledger-lens-demo/{name}") for name in (
    "revenue", "cash_marie", "cash_luc", "cash_ada", "receivable", "reported_income",
    "hh_tremblay", "hh_okafor", "client_marie", "client_luc", "client_ada", "schedule",
)}


def main() -> None:
    with SessionLocal() as session:
        if session.get(Household, ID["hh_tremblay"]) is not None:
            print("Demo data already present; nothing to do.")
            return
        session.add_all([
            Account(id=ID["revenue"], tenant_id=T, name="Advisory Fee Revenue", currency="CAD", normal_balance=NormalBalance.credit, gl_code="4000"),
            Account(id=ID["cash_marie"], tenant_id=T, name="Client cash - Tremblay, Marie", currency="CAD", normal_balance=NormalBalance.credit, gl_code="2100"),
            Account(id=ID["cash_luc"], tenant_id=T, name="Client cash - Tremblay, Luc", currency="CAD", normal_balance=NormalBalance.credit, gl_code="2100"),
            Account(id=ID["cash_ada"], tenant_id=T, name="Client cash - Okafor, Ada", currency="CAD", normal_balance=NormalBalance.credit, gl_code="2100"),
            Account(id=ID["receivable"], tenant_id=T, name="Employment Income Receivable", currency="CAD", normal_balance=NormalBalance.debit, gl_code="1200"),
            Account(id=ID["reported_income"], tenant_id=T, name="Reported Income", currency="CAD", normal_balance=NormalBalance.credit, gl_code="4100"),
            Household(id=ID["hh_tremblay"], tenant_id=T, name="Tremblay"),
            Household(id=ID["hh_okafor"], tenant_id=T, name="Okafor"),
        ])
        session.flush()
        session.add_all([
            Client(id=ID["client_marie"], tenant_id=T, household_id=ID["hh_tremblay"], name="Marie Tremblay"),
            Client(id=ID["client_luc"], tenant_id=T, household_id=ID["hh_tremblay"], name="Luc Tremblay"),
            Client(id=ID["client_ada"], tenant_id=T, household_id=ID["hh_okafor"], name="Ada Okafor"),
            FeeSchedule(id=ID["schedule"], tenant_id=T, name="Standard wealth", revenue_account_id=ID["revenue"]),
        ])
        session.flush()
        session.add_all([
            ClientAccount(account_id=ID["cash_marie"], client_id=ID["client_marie"], linked_on=date(2026, 1, 1)),
            ClientAccount(account_id=ID["cash_luc"], client_id=ID["client_luc"], linked_on=date(2026, 8, 1)),
            ClientAccount(account_id=ID["cash_ada"], client_id=ID["client_ada"], linked_on=date(2026, 1, 1)),
            AccountValuation(account_id=ID["cash_marie"], as_of=date(2026, 9, 30), market_value_minor=120_000_000, source="seed"),
            AccountValuation(account_id=ID["cash_luc"], as_of=date(2026, 9, 30), market_value_minor=60_000_000, source="seed"),
            AccountValuation(account_id=ID["cash_ada"], as_of=date(2026, 9, 30), market_value_minor=45_000_000, source="seed"),
            FeeScheduleVersion(schedule_id=ID["schedule"], version=1, method=FeeMethod.graduated,
                               valid_during=Range(date(2026, 1, 1), date(2026, 6, 30), bounds="[]")),
            FeeScheduleVersion(schedule_id=ID["schedule"], version=2, method=FeeMethod.graduated,
                               valid_during=Range(date(2026, 7, 1), None, bounds="[)")),
        ])
        session.flush()
        session.add_all([
            FeeScheduleTier(schedule_id=ID["schedule"], version=1, tier_no=1, up_to_minor=None, rate_bps=Decimal("150")),
            FeeScheduleTier(schedule_id=ID["schedule"], version=2, tier_no=1, up_to_minor=100_000_000, rate_bps=Decimal("100")),
            FeeScheduleTier(schedule_id=ID["schedule"], version=2, tier_no=2, up_to_minor=250_000_000, rate_bps=Decimal("80")),
            FeeScheduleTier(schedule_id=ID["schedule"], version=2, tier_no=3, up_to_minor=None, rate_bps=Decimal("65")),
            HouseholdFeeAssignment(household_id=ID["hh_tremblay"], schedule_id=ID["schedule"], valid_during=Range(date(2026, 1, 1), None, bounds="[)")),
            HouseholdFeeAssignment(household_id=ID["hh_okafor"], schedule_id=ID["schedule"], valid_during=Range(date(2026, 1, 1), None, bounds="[)")),
        ])
        session.commit()
        print("Seeded. Try the Q3 fee run:")
        print(f"  curl -s -X POST localhost:8000/fee-runs -H 'content-type: application/json' "
              f"-d '{{\"household_id\":\"{ID['hh_tremblay']}\",\"period_start\":\"2026-07-01\",\"period_end\":\"2026-09-30\"}}'")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify the seed end to end**

Run:

```bash
./scripts/db_up.sh && .venv/bin/python scripts/seed_demo.py && .venv/bin/python scripts/seed_demo.py
```

Expected: `Seeded. Try the Q3 fee run:` the first time, `Demo data already present; nothing to do.` the second time.

Then start the API with `.venv/bin/uvicorn app.main:app` and run the printed `curl`. Expected: HTTP 201 with `"period_fee_minor":366941`.

- [ ] **Step 3: Update `CLAUDE.md`**

- **Tech Stack table:** change the DB row to `PostgreSQL 18 + pgvector — localhost for dev (roles: ledger_owner migrates, ledger_app runs the API with SELECT/INSERT only), Aurora PostgreSQL for the demo/deploy run (verify 18 support before Epic 1.5)`.
- **Current Scope:** move "`POST /postings` (Epic 1.3), concurrency stress test (Epic 1.4)" from *Not yet built* to *Done*. Add to *Done*: `append-only ledger enforced by triggers + revoked privileges, reversals (Epic 1.7), household fee billing on versioned schedules, AI tool-invocation governance tables, GL-ready export`.
- **Code Conventions → Layering:** replace "no direct DB access outside `app/ledger/dao.py`. This is a two-file pattern today (`models.py`/`dao.py`); keep new domain logic in that module, not in routes." with:
  > No direct DB access outside each package's own `dao.py` (`app/ledger`, `app/billing`, `app/governance`, `app/reporting`). Dependencies point only toward `ledger`; the ledger imports no other package. Pure logic lives in framework-free files (`ledger/fingerprint.py`, `billing/fee_math.py`, `reporting/gl_csv.py`). Postings are written only through `ledger.dao.create_posting` inside `ledger.dao.ledger_transaction`.
- **Running Locally → Backend:** add `.venv/bin/pytest` (default suite, runs as `ledger_app`), `.venv/bin/pytest -m stress` (concurrency proof, writes `backend/reports/concurrency.json`), and `.venv/bin/python scripts/seed_demo.py`.

- [ ] **Step 4: Add the README section**

Add this section to `README.md` after "Local development — ledger DB core", filling in the three numbers from `backend/reports/concurrency.json`:

```markdown
## Ledger core — what the database guarantees

Every rule below is enforced by PostgreSQL itself and has a test that fails if it is removed.
The API connects as `ledger_app`, which can only `SELECT` and `INSERT`.

- **Double-entry, per currency:** a posting commits only if it has at least one debit and one
  credit and nets to zero in every currency (deferred constraint trigger on `postings` and `entries`).
- **Append-only history:** `UPDATE`/`DELETE`/`TRUNCATE` on postings, entries, schedules, valuations,
  fee calculations, AI decisions and GL exports are refused — even for the table owner. Mistakes are
  fixed by a reversal posting that must exactly mirror the original, at most once.
- **Idempotent writes:** `POST /postings` requires `Idempotency-Key`; a retry returns the original
  (`200`, `Idempotent-Replayed: true`), a reused key with a different payload is `422`, an in-flight
  duplicate is `409` with `Retry-After`.
- **Point-in-time fee rules:** schedule versions and household assignments use Postgres 18 temporal
  keys (`WITHOUT OVERLAPS`); a fee run uses the version in effect on the period end and stores the
  inputs that reproduce it exactly.
- **Governed AI:** a tool result that would move money is recorded with tool, model, prompt version and
  temperature, and posts only after a human approval — exactly the proposed entries, atomically.
- **Reproducible GL export:** a GL-ready CSV per period and cutoff, stored as a hash; regeneration
  must be byte-identical.

**Concurrency proof** (`pytest -m stress`, local, 4 workers, 50 concurrent clients):
500 requests → <postings_created> postings for <distinct_keys> keys, **0 duplicates, 0 per-currency
imbalances, 0 lost updates** on a hot account; p50 <p50> ms, p99 <p99> ms.

**Out of scope for this demo:** Aurora deployment, row-level security / multiple real tenants,
authentication, reconciliation, fee corrections, advisor compensation, event streaming.
```

- [ ] **Step 5: Add the CHANGELOG section at the top of `CHANGELOG.md` (below the header rule)**

```markdown
## [Sprint — feat/ledger] · Ledger hardening + revenue book of record

### Completed

- `design` — industry research (`artifacts/research/2026-09-22-ledger-engineering.md`) and sprint spec → **Not epic-tracked** (PureFacts alignment)
- `db` — Postgres 18, owner/app roles, tests run as the least-privilege role → **Epic 1.1**
- `db` — append-only history, per-currency balance, ≥1 debit/credit, tenant and mirror checks in Postgres → **Epic 1.2**
- `api` — idempotent `POST /postings` with fingerprints, replay/422/409/400 contract, read endpoints → **Epic 1.3**
- `test` — concurrency proof against a live multi-worker server → **Epic 1.4**
- `api` — compensating reversal endpoint → **Epic 1.7**
- `billing` — households, versioned fee schedules (temporal keys), reproducible fee runs → **Not epic-tracked** (PureFacts alignment)
- `governance` — AI tool-invocation audit and human approval before posting → **Epic 2.5** (governance tables; chat wiring deferred)
- `reporting` — reproducible GL-ready export → **Not epic-tracked** (PureFacts alignment)

### Deferred

- `infra` — Aurora deployment (verify Postgres 18 support) → **Epic 1.5**
- `ops` — correlation-ID logging + CI gate → **Epic 1.8**
- `billing` — fee corrections (reverse and re-bill), advisor compensation → **Not epic-tracked**
- `recon` — statement-vs-ledger reconciliation matcher → **Epic 2.2**
```

- [ ] **Step 6: Refresh the knowledge graph and run everything one last time**

Run (from the repo root): `graphify update .`
Then, from `backend/`, run `.venv/bin/pytest -v && .venv/bin/pytest -m stress -v`.
Expected: both PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/seed_demo.py ../CLAUDE.md ../README.md ../CHANGELOG.md
git commit -m "docs: document ledger guarantees, demo seed and sprint changelog" -m "README states every database-enforced invariant with the measured concurrency numbers; CLAUDE.md records the package layering rule and Postgres 18 roles."
```
