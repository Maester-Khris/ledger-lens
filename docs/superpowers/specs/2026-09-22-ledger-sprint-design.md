# Ledger sprint (`feat/ledger`): design

**Date:** 2026-09-22 · **Status:** approved in brainstorming, pending written-spec review
**Backlog:** PureFacts Thursday-screen MVP → Ledger MVP (Epics 1.3, 1.4 shortened, 1.7), plus the additions below
**Research basis:** `artifacts/research/2026-09-22-ledger-engineering.md`

## 1. Goal

Harden the existing double-entry core and extend it into a small **revenue book of record**: every money rule enforced by the database, and the whole path demonstrable end to end:

> household fee computed from versioned schedules → posted idempotently → (AI figure approved by a human → posted) → reversible → exported GL-ready

**Success criteria**
- Every invariant listed in §6 is enforced **in Postgres**, and each has a test that fails if the invariant is removed.
- Tests connect as the restricted application role, not as a superuser.
- The concurrency proof reports 0 duplicates and 0 imbalances, with real p50/p99.
- A fee calculation and a GL export can each be reproduced exactly from stored data.

## 2. Decisions (settled; don't reopen during implementation)

| Topic | Decision |
|---|---|
| Code structure | Split into packages: `app/ledger`, `app/billing`, `app/governance`, `app/reporting`, each with its own `models.py` / `dao.py`. Dependencies point only toward `ledger`. Pure logic lives in framework-free files. |
| Idempotency responses | **400** header missing · **201** created · **200** replay (+ `Idempotent-Replayed: true`) · **422** key reused with a different payload · **409** + `Retry-After` while the original is still in flight |
| Fingerprint | SHA-256 hex over canonical JSON (sorted keys, no whitespace; equivalent to RFC 8785 for our integer/string payloads) of the business fields only, with entries sorted by `(account_id, direction, amount)` (the existing `entries.amount` column, in minor units) |
| Tenancy | A `tenant_id` column now, **one fixed demo tenant**; households are the grouping inside it. No row-level security this sprint. |
| Valuation basis | Period-end market value |
| Rounding | Household fee rounded **half-to-even**; split across accounts by the **largest-remainder** method, ties broken by `account_id` ascending |
| AI approval | Only **critical** tool results need human approval. Critical = the result would create a ledger posting. |
| GL export | Built in this sprint |
| Postgres | Upgrade the local image to **18** (native temporal keys `WITHOUT OVERLAPS`). Check Aurora's version support before Epic 1.5. |
| Isolation level | Postgres' default READ COMMITTED. Every rule is either a unique constraint or a check within one posting, and nothing reads a balance and then decides on it, so write skew can't happen. |
| Reversal chains | A reversal may itself be reversed (backlog Epic 1.7 decision); each posting can be reversed **at most once**. |
| Currency | Balance is checked per currency; demo data is CAD only (the backlog's Icebox excludes multi-currency features). |

## 3. Architecture

```
app/
  ledger/        models.py  dao.py  fingerprint.py  errors.py     ← depends on nothing
  billing/       models.py  dao.py  fee_math.py     errors.py     ← depends on ledger
  governance/    models.py  dao.py                  errors.py     ← depends on ledger
  reporting/     models.py  dao.py  gl_csv.py       errors.py     ← depends on ledger
  routes/        postings.py  fee_runs.py  tool_invocations.py  gl_exports.py  health.py
  problem.py     RFC 9457 problem+json responses and error-type mapping
```

- **One write path:** `ledger.dao.create_posting(...)` is the only function that inserts postings. The API, fee runs and AI approvals all call it.
- Other packages point at ledger rows (`posting_id`, `account_id`); **the ledger never imports another package**.
- Reporting reads ledger data only through a ledger query function (`sum_entries_by_account(period, cutoff)`).
- Routes follow CLAUDE.md: Pydantic request model → dataclass DTO → call the package function → response.
- **Pure, framework-free files:**
  - `ledger/fingerprint.py`
  - `billing/fee_math.py` (tiers, period fraction, proration, rounding, split across accounts)
  - `reporting/gl_csv.py` (turns rows into CSV plus hash)
- **CLAUDE.md update:** the layering rule changes from "no direct DB access outside `app/ledger/dao.py`" to "outside each package's own `dao.py`".

## 4. Schema

### 4.1 Ledger core (migration `0003`)

```
currencies   code char(3) PK, minor_units smallint NOT NULL          -- seeded CAD 2, USD 2
tenants      id uuid PK, name text, created_at                      -- seeded fixed demo tenant

accounts     + tenant_id      uuid NOT NULL → tenants
             currency         → FK currencies(code)                  (was free text)
             + normal_balance enum(debit, credit) NOT NULL
             + gl_code        text NULL

postings     + tenant_id           uuid NOT NULL → tenants
             + effective_at        timestamptz NOT NULL DEFAULT now()
             + request_fingerprint char(64) NOT NULL
             + source              enum(api, fee_run, ai_tool, stress_test) NOT NULL
             + reverses_posting_id uuid NULL → postings, UNIQUE
             UNIQUE(idempotency_key) → UNIQUE(tenant_id, idempotency_key)

entries      unchanged
```

**Backfilling existing dev rows:** demo tenant; `normal_balance = 'debit'`; `source = 'api'`; `request_fingerprint = encode(sha256(id::text::bytea), 'hex')`. No API client has ever seen these rows. The migration must work in both directions.

### 4.2 Billing (migration `0004`)

```
households            id, tenant_id, name, created_at
clients               id, tenant_id, household_id → households, name, created_at
client_accounts       account_id PK → accounts, client_id → clients, linked_on date NOT NULL
account_valuations    account_id → accounts, as_of date, market_value_minor bigint CHECK >= 0,
                      source text, created_at, UNIQUE(account_id, as_of)
fee_schedules         id, tenant_id, name, revenue_account_id → accounts
fee_schedule_versions schedule_id → fee_schedules, version int, method enum(graduated, cliff),
                      valid_during daterange, created_at,
                      PRIMARY KEY (schedule_id, valid_during WITHOUT OVERLAPS),
                      UNIQUE (schedule_id, version)
fee_schedule_tiers    schedule_id, version, tier_no int, up_to_minor bigint NULL (NULL = no upper limit),
                      rate_bps numeric(8,4) CHECK >= 0,
                      PK (schedule_id, version, tier_no), FK (schedule_id, version) → versions
household_fee_assignments household_id → households, schedule_id → fee_schedules,
                      valid_during daterange,
                      PRIMARY KEY (household_id, valid_during WITHOUT OVERLAPS)
fee_calculations      id, tenant_id, household_id, period daterange,
                      schedule_id, schedule_version, method,
                      inputs jsonb, household_value_minor bigint, period_fee_minor bigint,
                      allocations jsonb, rounding_remainder_minor bigint,
                      posting_id → postings NOT NULL, created_at
```

Needs the `btree_gist` extension. The link from client to account lives in billing, so the ledger has no client concept.

### 4.3 Governance (migration `0005`)

```
tool_invocations      id, tenant_id, session_id text, created_at,
                      tool_name, tool_version, model_provider, model_id, prompt_version,
                      temperature numeric(3,2),
                      input jsonb, input_hash char(64),
                      result_amount_minor bigint NULL, result_currency → currencies NULL,
                      citation jsonb,
                      proposed_entries jsonb NULL,
                      approval_required bool NOT NULL,
                      CHECK (approval_required = (proposed_entries IS NOT NULL)),
                      UNIQUE (id, approval_required)
tool_invocation_decisions
                      invocation_id PK, approval_required bool NOT NULL CHECK (approval_required),
                      FK (invocation_id, approval_required) → tool_invocations(id, approval_required),
                      decision enum(approved, rejected), decided_by text, reason text,
                      decided_at, posting_id → postings NULL,
                      CHECK ((decision = 'approved') = (posting_id IS NOT NULL))
```

### 4.4 Reporting (migration `0006`)

```
gl_exports            id, tenant_id, period daterange, currency → currencies,
                      cutoff timestamptz, line_count int,
                      total_debits_minor bigint, total_credits_minor bigint,
                      content_sha256 char(64), created_at
```

Export lines are **not stored**. They are recomputed from postings whose `effective_at` falls in the period and whose `created_at ≤ cutoff`, excluding `source = stress_test`. The stored hash proves each regeneration matches.

## 5. Flows

### 5.1 `create_posting` (the single write path)
1. Python validation: at least one debit and one credit; amounts > 0; accounts exist and belong to the tenant; balanced per currency. Failure → `PostingInvalid`.
2. Compute the fingerprint.
3. `SET LOCAL lock_timeout = '2s'`. Insert the posting, then the entries, then commit; the deferred triggers run at commit.
4. On a unique violation of `(tenant_id, idempotency_key)`: roll back, re-read. Same fingerprint → return the existing posting and mark it as a replay; different fingerprint → `IdempotencyKeyReused`.
5. Lock timeout (SQLSTATE 55P03) → `RequestInProgress`.

### 5.2 Reversal
`POST /postings/{id}/reversal` → `create_posting` with the entries mirrored (directions swapped), `reverses_posting_id = id`, key `reverse:<id>` (set by the server, so it's automatically idempotent), and `effective_at` copied from the original.

### 5.3 Fee run
1. Find the assignment whose `valid_during` contains `period_end`, then the matching schedule version and its tiers. None → `NoScheduleAssigned`.
2. Member accounts: `client_accounts` of the household's clients with `linked_on ≤ period_end`.
3. Valuations `as_of = period_end` for every member account. Any missing → `MissingValuation` (never treated as zero).
4. `fee_math`:
   - household value = sum of the member values;
   - annual fee = graduated (each tranche at its own rate) or cliff (the whole value at the reached tier's rate);
   - period fee = annual fee × days in period ÷ days in year;
   - split across accounts in proportion to value, prorated by `days linked in period ÷ days in period`;
   - household fee rounded half-to-even to minor units; accounts split by largest remainder.
5. One transaction:
   - `create_posting(key = fee:<household_id>:<period_end>, source = fee_run, effective_at = period_end)`, debiting each client account by its allocation and crediting `revenue_account_id` with the total;
   - insert `fee_calculations` with `posting_id`.

   If `create_posting` reports a replay, **no new `fee_calculations` row is inserted**; the existing one is looked up by `posting_id` and returned (200). If `create_posting` raises `IdempotencyKeyReused` (different inputs for an already-billed period), billing re-raises it as `AlreadyBilled` (422).

### 5.4 AI decision
`POST /tool-invocations/{id}/decision`, in one transaction:
- **approved:** `create_posting(entries = proposed_entries, key = ai:<invocation_id>, source = ai_tool)`, then insert the decision with `posting_id`;
- **rejected:** insert the decision only.

Errors:
- the invocation isn't critical → `NotCritical` (422);
- it's already decided → `AlreadyDecided` (409, from the primary-key violation).

`governance.dao.record_invocation(...)` is a Python function called directly by the chat sprint (the in-process rule).

### 5.5 GL export
`POST /gl-exports {period_start, period_end, currency}`:
1. `cutoff = now()`.
2. `ledger.sum_entries_by_account(...)`.
3. Any account in the result without a `gl_code` → `GlCodeMissing` (422, listing the accounts).
4. `gl_csv` builds one line per `gl_code` (account name, currency, total debits, total credits, net, posting count) plus a control-total row.
5. Hash the CSV and insert the `gl_exports` row.

`GET /gl-exports/{id}.csv` regenerates the CSV and checks it against `content_sha256`. A mismatch is an integrity error (500).

## 6. Database-level enforcement

| # | Invariant | Mechanism |
|---|---|---|
| E1 | Facts are never updated or deleted | `forbid_mutation()` as `BEFORE UPDATE OR DELETE` (row) and `BEFORE TRUNCATE` (statement) on postings, entries, account_valuations, fee_schedule_versions, fee_schedule_tiers, household_fee_assignments, client_accounts, fee_calculations, tool_invocations, tool_invocation_decisions, gl_exports. Raises 23001. |
| E2 | Accounts are partly editable | Trigger: no DELETE; `tenant_id`, `currency`, `normal_balance` can't change; `gl_code` only NULL → value, once. |
| E3 | The app role can't bypass rules | `ledger_owner` owns the tables and runs migrations; `ledger_app` has `SELECT, INSERT` everywhere, `UPDATE (name, gl_code)` on accounts, no DELETE or TRUNCATE. |
| E4 | Postings are valid | `assert_posting_valid(p)` via deferred constraint triggers after insert on postings **and** on entries: at least one debit and one credit; nets to zero per currency (entries joined to accounts, grouped by currency); every entry's account tenant = the posting tenant; if `reverses_posting_id` is set, the entries are the exact mirror of the original (`EXCEPT` comparison both ways). Raises 23514. |
| E5 | No duplicate effects | `UNIQUE(tenant_id, idempotency_key)`; `UNIQUE(reverses_posting_id)`; decision primary key on `invocation_id` |
| E6 | Versions and assignments never overlap | Temporal primary keys `WITHOUT OVERLAPS` |
| E7 | Approval rules | Composite FK on `(invocation_id, approval_required)`; `CHECK approval_required`; `CHECK (approved ⇔ posting_id)` |

## 7. API

| Method and path | Responses |
|---|---|
| `POST /postings` (header `Idempotency-Key`) | 201 · 200 replay · 400 · 422 `posting-invalid` · 422 `idempotency-key-reused` · 409 |
| `POST /postings/{id}/reversal` | 201 · 200 replay · 404 |
| `GET /postings?source=&include_stress=false&cursor=&limit=` | 200 (paginated by `(created_at, id)`) |
| `GET /postings/{id}` | 200 · 404 (ledger data only: entries, what it reverses, what reversed it) |
| `POST /fee-runs` | 201 · 200 replay · 422 `already-billed` / `missing-valuation` / `no-schedule-assigned` |
| `GET /fee-calculations/{id}` | 200 · 404 |
| `GET /tool-invocations?posting_id=&pending=` | 200 |
| `POST /tool-invocations/{id}/decision` | 201 · 404 · 409 `already-decided` · 422 `not-critical` |
| `POST /gl-exports` · `GET /gl-exports/{id}.csv` | 201 · 422 `gl-code-missing` · 200 CSV |

Every error body is RFC 9457 `application/problem+json`, with a stable `type` URI per error kind.

## 8. Testing (write the failing test first)

1. **Unit, no database:**
   - fingerprint ignores entry order and key order;
   - `fee_math` worked examples: graduated vs. cliff, value exactly on a tier boundary, proration, half-even rounding, split across accounts with a deterministic tie-break;
   - a seeded-random test (1,000 cases): account fees always add up exactly to the household fee.
2. **Database rules, as `ledger_app`:** each of E1–E7 violated → rejected; E1/E2 also violated as the owner (trigger) → rejected.
3. **API:** every response in §7, including the replay header, both kinds of 422, and a genuine 409 from a second connection holding the lock.
4. **Reproducibility:** a fee calculation recomputed from stored `inputs` gives the same result; a GL export regenerated after new postings still matches the stored hash.
5. **Concurrency proof (`pytest -m stress`, not in the default run):**
   - 500 async requests via `httpx.AsyncClient` against a running uvicorn server (new postings, identical retries fired concurrently, a hot account);
   - checks: postings = distinct keys, duplicates = 0, per-currency imbalance = 0;
   - writes p50/p99 to `backend/reports/concurrency.json`.
6. **Migrations:** `0003`–`0006` upgrade → downgrade → upgrade.

**Isolation:** the test database is rebuilt once per session (drop the schema, then migrations as the owner). Tests use unique ids and keys. Rule tests use `SET CONSTRAINTS ALL IMMEDIATE` so the at-commit checks run immediately, then roll back. `tests/test_ledger_dao.py` is updated to the new signatures.

## 9. Infrastructure changes

- `backend/scripts/db_up.sh`: image `postgres:18`; creates `ledger_owner` and `ledger_app` in both databases; migrations run as the owner.
- `app/config.py`: `DATABASE_URL` (app role) and `MIGRATION_DATABASE_URL` (owner).
- `backend/requirements.txt`: add `httpx` (FastAPI `TestClient` and the stress test need it).
- `backend/scripts/seed_demo.py`: demo tenant, CAD, accounts with GL codes and normal balances, 2 households / 3 clients / 4 accounts, one schedule with 2 non-overlapping versions (graduated), assignments, period-end valuations.
- `CLAUDE.md`: update the layering rule (§3) and note Postgres 18.

## 10. Build order (the implementation plan will break this down)

1. Postgres 18, roles, config split, test harness as the app role.
2. `0003` ledger core + E1–E5 + fingerprint + `create_posting` rewrite.
3. `POST /postings`, `GET` endpoints, reversal, problem+json.
4. Concurrency proof.
5. `0004` billing + `fee_math` + fee run.
6. `0005` governance + decision flow.
7. `0006` reporting + GL export.
8. Seed script, CLAUDE.md, README numbers.

If time runs short, cut in this order: GL export first, then governance, then billing. The ledger core (steps 1–4) must not be cut.

## 11. Out of scope (explicit)

Fee corrections (reverse and re-bill), advisor compensation, average-daily-balance valuation, a second tenant or row-level security, login, reconciliation, a pending posting state, hash-chained audit rows, the chat/LLM side of tool invocations (Document Intelligence sprint), and frontend wiring (a separate sprint).
