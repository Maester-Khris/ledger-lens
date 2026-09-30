# Ledger DB Core — Design Spec (Epic 1.1 + 1.2, database side only)

Date: 2026-09-06
Status: Approved, ready for implementation planning

## Context

`artifacts/product-backlog.md` Week 1 opens with Epic 1.1 (schema &
migrations) and Epic 1.2 (balance invariant enforcement). This spec covers
**only the database side of those two epics** — the schema, the deferred
constraint trigger, a thin DAO/transaction layer, and automated tests
validating both. Explicitly out of scope for this run:

- Epic 1.3 (idempotent `POST /postings` endpoint) and anything HTTP-facing
- Epic 1.4 (concurrency/hot-account stress test)
- Epic 1.5 (Aurora deployment)
- Epic 1.6 (README with captured stress numbers — a brief local-setup
  README section is in scope here, the full stress-test README is not)
- Epic 1.7 (compensating reversal) and 1.8 (correlation-ID logging/CI)

`backend/` currently contains only a bare FastAPI skeleton (`app/main.py`
wiring in a `/health` route) — no SQLAlchemy, no Alembic, no DB driver, no
`DATABASE_URL` config exists yet. This is genuinely new infrastructure.

The schema design itself was validated against real, current industry
practice before this spec was written — see
`artifacts/ledger-schema-research.md` (Modern Treasury, TigerBeetle,
Fintechly, System Design Sandbox, and others). That research confirmed the
three-table shape, integer-minor-units amounts, the direction-enum
convention, and the deferred-trigger enforcement mechanism are all
industry-standard, not invented for this project.

## Decisions locked before this spec

- **Local Postgres via a single `docker run` container** — not
  docker-compose, not an assumed pre-existing local install.
- **Sync SQLAlchemy + psycopg** — plain `def` DAO methods, no async
  session/engine complexity. FastAPI supports sync path functions natively,
  so this doesn't block Epic 1.3's future async-capable API.
- **Tests run against a real Postgres `ledger_test` database**, a second
  database inside the same single container (not a second container, not
  transaction-rollback-based isolation) — the deferred constraint trigger
  fires at COMMIT, so a test strategy that rolls back instead of committing
  would never actually exercise it.

## Project layout

```
backend/
  alembic/                       # migration environment (env.py, versions/)
  alembic.ini
  app/
    config.py                    # DATABASE_URL from env, sensible local default
    ledger/
      __init__.py
      models.py                  # SQLAlchemy ORM models: Account, Posting, Entry
      db.py                      # engine, SessionLocal, get_session()
      dao.py                     # create_account(), create_posting()
  scripts/
    db_up.sh                     # idempotent: start/create container, create both DBs, migrate both
  tests/
    conftest.py                  # session fixture bound to ledger_test, per-test cleanup
    test_ledger_schema.py        # Epic 1.2's own listed unit tests
requirements.txt                 # + sqlalchemy, alembic, psycopg[binary], pytest, python-dotenv
README.md                        # new "Local development" section
```

## Schema (Epic 1.1)

UUID primary keys throughout (matches the research — Modern Treasury and
the freeCodeCamp reference implementation both use UUIDs for ledger
entities; `gen_random_uuid()` requires the `pgcrypto` extension, enabled in
the first migration).

**`accounts`**
| column | type | notes |
|---|---|---|
| id | uuid, PK | `server_default=gen_random_uuid()` |
| name | text, not null | |
| currency | text, not null | ISO 4217 code, e.g. `USD` |
| created_at | timestamptz, not null | `server_default=now()` |

**`postings`**
| column | type | notes |
|---|---|---|
| id | uuid, PK | |
| idempotency_key | text, unique, not null | |
| description | text, nullable | |
| created_at | timestamptz, not null | |

No `updated_at` column. No update path exists at all — this table is
append-only by construction, not just by convention.

**`entries`**
| column | type | notes |
|---|---|---|
| id | uuid, PK | |
| posting_id | uuid, FK → postings.id, not null | indexed |
| account_id | uuid, FK → accounts.id, not null | indexed |
| direction | enum (`debit`, `credit`), not null | |
| amount | bigint, not null | minor units (cents); `CHECK (amount > 0)` — sign comes from `direction`, never from the number |
| created_at | timestamptz, not null | |

## Balance invariant (Epic 1.2)

A trigger function `check_posting_balance()`, installed via a hand-written
raw-SQL Alembic migration (`op.execute(...)` — autogenerate cannot produce
trigger DDL from ORM models):

```sql
CREATE FUNCTION check_posting_balance() RETURNS trigger AS $$
DECLARE
  imbalance bigint;
BEGIN
  SELECT COALESCE(SUM(CASE WHEN direction = 'debit' THEN amount ELSE -amount END), 0)
    INTO imbalance
    FROM entries
    WHERE posting_id = NEW.posting_id;

  IF imbalance != 0 THEN
    RAISE EXCEPTION 'posting % is unbalanced: debit/credit mismatch of %', NEW.posting_id, imbalance;
  END IF;

  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trg_check_posting_balance
  AFTER INSERT ON entries
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW
  EXECUTE FUNCTION check_posting_balance();
```

Deferred so it only fires once, at COMMIT, after every entry row for a
posting has been inserted in the same transaction — a plain `AFTER INSERT`
trigger would reject the first entry before its balancing entry ever lands.

**Isolation level**, stated as a decision in the README, not left as an
unexamined default: `READ COMMITTED` is correct and sufficient here —
there is no read-then-conditional-write step in this scope (no
overdraft/limit check reading current balance before allowing an insert).

## DAO layer

`app/ledger/db.py`: `create_engine(DATABASE_URL)`, a `SessionLocal`
sessionmaker, and a `get_session()` context manager.

`app/ledger/dao.py`: plain functions, no repository classes —
- `create_account(session, name, currency) -> Account`
- `create_posting(session, idempotency_key, description, entries: list[EntryInput]) -> Posting`

`create_posting` wraps the posting-row insert and every entry-row insert in
one `session.begin()` block, so the deferred trigger fires exactly once at
that commit. A balanced posting commits clean; an unbalanced one raises
`IntegrityError`, and the whole transaction — posting row included, not
just the entries — rolls back.

## Tests

Exactly Epic 1.2's own listed cases, run against `ledger_test`:
1. A balanced posting (debits sum equals credits sum) succeeds and is
   readable back afterward.
2. An unbalanced posting raises (the deferred trigger fires at commit).
3. After that rejection, zero rows exist anywhere for the attempted
   posting — the posting header row included, confirming the whole
   transaction rolled back rather than partially landing.

`conftest.py` provides a session fixture bound to `ledger_test` and
truncates all three tables between tests for isolation.

## `scripts/db_up.sh`

Idempotent, single-container flow:
1. Check for a container named `fintech-ledger-db`. If it exists but is
   stopped, `docker start` it. If it doesn't exist, `docker run -d --name
   fintech-ledger-db -e POSTGRES_PASSWORD=localdev -p 5432:5432 postgres:16`
   — a fixed local-only password, never used outside this container, not a
   secret worth managing.
2. Poll (`pg_isready` or a retry-loop `psql` connection attempt) until
   Postgres accepts connections.
3. Create `ledger_dev` and `ledger_test` databases if either is missing,
   connecting as the container's default `postgres` superuser role — no
   separate least-privilege app role in this pass (that's an Aurora/Epic
   1.5 deployment concern, not a local-dev one).
4. Run `alembic upgrade head` against both databases.

One command takes a fresh machine from nothing to "ready to run the app
and the test suite." The README's new "Local development" section
documents this as the first thing to run, plus how to point the app at the
DB (`DATABASE_URL` env var / a `.env.example` committed alongside a
gitignored `.env`) and how to run tests (`pytest`).

## Out of scope, explicitly

- No REST endpoint anywhere in this run (Epic 1.3).
- No idempotency-conflict/payload-hash handling on retry (Epic 1.3) — the
  `idempotency_key` unique constraint exists in the schema, but nothing
  yet calls `create_posting` twice with the same key and asserts on the
  resulting behavior; that assertion belongs to Epic 1.3's own tests.
- No concurrency/hot-account stress test (Epic 1.4).
- No Aurora deployment (Epic 1.5).
- No correlation-ID logging or CI pipeline (Epic 1.8).
