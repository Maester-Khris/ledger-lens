# Demo Mode and Per-Guest Decision Overlay (P2 + P9) — Design

**Date:** 2026-09-30 · **Branch:** `feat/pre-launch-demo` · **Backlog:** P2, P9 (pre-launch sprint) · **Not epic-tracked**
**Status:** approved in brainstorming 2026-09-30, pending written-spec review.

## 1. Purpose

The deployed demo (Vercel `https://ledgerlens.nknext.dev` → Railway API → Railway Postgres 18) is public. Today the
API runs as `ledger_app`, which can insert into every table, and every write route is mounted. Anyone with the URL can
upload documents (spending OpenAI and Pinecone money and changing the corpus every guest shares) or write permanent
rows into the append-only ledger. And every decision a guest makes (a field review, an AI-posting approval) is global:
it changes every other guest's answers, billing gap, review queue and ledger.

This design makes the public demo safe and still worth using:

- **P2:** in demo mode no public request can change shared state. Two independent layers: the write routes are not
  mounted, and the database role the API runs as cannot write the shared tables.
- **P9:** guests can still make the two decisions that carry the product story (review an extracted field, approve an
  AI-proposed posting), but each guest's decisions live in per-guest overlay tables, merged over the real data only
  for that guest.

P2 and P9 are designed together for the final state, so no intermediate grant or table is built and then undone.

## 2. Success criteria

1. With `DEMO_MODE=1`, `POST /documents`, `POST /postings`, `POST /postings/{id}/reversal`, `POST /fee-runs` and
   `POST /gl-exports` are not served (405 where the path also serves GET, 404 otherwise).
2. Connected as `ledger_demo`, an INSERT into `documents`, `postings`, `entries`, `field_reviews` or
   `tool_invocation_decisions` fails with a permission error; an INSERT into either overlay or `chat_turns` succeeds.
3. Two guests make opposite decisions on the same field and get different served values, different agent tool
   results and a different billing comparison (the backlog's guard test).
4. A guest's approval of an AI proposal writes no `postings` or `entries` row, and an invalid proposal (unbalanced,
   unknown account) is refused with the same `PostingInvalid` error as today.
5. A guest sees and decides only proposals produced by their own chat turns.
6. With `DEMO_MODE` off, behaviour is exactly today's: every existing test passes unchanged.

## 3. Decisions (settled 2026-09-30)

| # | Decision | Rejected alternatives and why |
|---|----------|-------------------------------|
| D1 | P2 includes the ledger-write routes, not only upload | Upload only: the public could still write permanent postings with `curl` |
| D2 | Reversals are off in demo mode; the Ledger screen hides the button and says so | Per-guest simulated reversals (third overlay, rare path); a rolled-back "would reverse" (half a feature) |
| D3 | An approval is checked read-only by `ledger.dao.check_posting`, the same account load and `_validate` that `create_posting` runs first; nothing is written | Rolled-back `create_posting` (needs INSERT on the ledger for the demo role, so P2's DB layer would not hold); `SET LOCAL ROLE` to a writer role (the demo role could switch anywhere) |
| D4 | Overlays are purged when a new guest is created (`POST /guests`), for guests not seen for 24 hours | A Railway cron service (one more deployed thing for storage that doesn't matter); no purge |
| D5 | Guest decisions are final: no re-decide, no reset | An undo or reset teaches the opposite of the ledger, where a decision is recorded once and a posting is only corrected by a compensating reversal |
| D6 | In demo mode a guest sees only proposals from their own chats | Everyone sees everything (noise; reveals other guests' questions; a guest could decide another's proposal) |
| D7 | The overlay merge is done in Python inside each package's `dao.py` | An SQL merge function (logic split across SQL and Python, a migration per change); separate demo repositories (every reader and the approval path twice) |
| D8 | The frontend learns demo mode from `/config` | A separate Vite build flag (a second switch that can disagree with the API) |

The guest-facing wording of D1–D6 is in `CHANGELOG.md` → "Demo-mode decisions".

## 4. Architecture

### 4.1 Where the demo-mode policy lives

`config.DEMO_MODE` (bool, env `DEMO_MODE`, default off) is read in exactly two places:

- **`app/main.py`** mounts the write routers only when `DEMO_MODE` is off.
- **`app/deps.py`** → two FastAPI dependencies, the only place that decides whether the overlay applies. Guests exist
  in both modes (chat attribution uses them), so "is there a guest" is not the same question as "use the overlay".
  - `get_overlay_guest` (reads): the caller's guest id when `DEMO_MODE` is on, `None` when it is off or when no known
    guest is sent (a read without a guest shows the shared data).
  - `require_overlay_guest` (decision writes): same, except that in demo mode a missing or unknown guest is a 400
    problem response, so a decision can never fall through to the real tables.

Everything below `deps.py` receives `overlay_guest: uuid.UUID | None` as a plain argument from one of those two dependencies. `None` means today's path,
unchanged. No package reads `DEMO_MODE`.

### 4.2 Dependency direction

Unchanged: packages depend toward `ledger`; the ledger imports no other package. New cross-package calls follow
existing edges only (`governance` → `ledger` for `check_posting`; `assistant` → `contracts`/`governance`, as today).
All database access stays in each package's `dao.py`.

## 5. Milestones

Each milestone is one or more commits with its own tests and can ship alone.

### M1 — Close the public writes (code only, no migration)

- Move the write routes onto their own routers: `documents.write_router` (`POST /documents`), `postings.write_router`
  (`POST /postings`, `POST /postings/{id}/reversal`), `fee_runs.write_router` (`POST /fee-runs`),
  `gl_exports.write_router` (`POST /gl-exports`). `main.py` includes them only when `DEMO_MODE` is off. Read routes on
  the same paths stay mounted, which is why `POST /documents` and `POST /postings` answer 405 and the others 404.
- Add `demo_mode: bool` to `ConfigOut` (`GET /config`).
- A temporary dependency `decisions_closed_in_demo` in `deps.py`: in demo mode it raises 403 ("Decisions are not
  available in the public demo yet"); off, it does nothing. Only `POST /reviews` and
  `POST /tool-invocations/{id}/decision` depend on it; read routes are untouched. This is the only throwaway code in
  the plan: M3 replaces it on `POST /reviews` with `require_overlay_guest`, M4 on the decision route, and M4 deletes it.
- Frontend: `api.ts` exposes `demo_mode` from `getConfig()`. In demo mode the Documents screen hides the upload control
  (`Documents.tsx`), and the Ledger screen hides the reversal button and shows "Reversals are off in the public demo."
- Rollout: after deploy, set `DEMO_MODE=1` on Railway.

### M2 — One migration: overlays and the demo role's grants

Migration `0013_demo_role_and_guest_overlays`, run as `ledger_owner`:

```sql
CREATE TABLE guest_field_reviews (
  guest_id uuid NOT NULL REFERENCES guests(id),
  run_id uuid NOT NULL,
  field_path text NOT NULL,
  decision review_decision NOT NULL,
  corrected_value jsonb NULL,
  reason text NULL,
  decided_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (guest_id, run_id, field_path),
  FOREIGN KEY (run_id, field_path) REFERENCES extracted_fields (run_id, field_path),
  CONSTRAINT ck_guest_reviews_corrected_value CHECK ((decision = 'corrected') = (corrected_value IS NOT NULL))
);

CREATE TABLE guest_tool_decisions (
  guest_id uuid NOT NULL REFERENCES guests(id),
  invocation_id uuid NOT NULL,
  approval_required boolean NOT NULL DEFAULT true CONSTRAINT ck_guest_decisions_only_for_critical CHECK (approval_required),
  decision tool_decision NOT NULL,
  reason text NULL,
  decided_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (guest_id, invocation_id),
  CONSTRAINT fk_guest_decisions_critical_invocation FOREIGN KEY (invocation_id, approval_required)
    REFERENCES tool_invocations (id, approval_required)
);

-- ledger_demo: read everything, write only chat state and the overlays
GRANT USAGE ON SCHEMA public TO ledger_demo;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO ledger_demo;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO ledger_demo;
GRANT INSERT ON guests, chat_turns, tool_invocations TO ledger_demo;
GRANT UPDATE (last_seen_at) ON guests TO ledger_demo;
GRANT INSERT, DELETE ON guest_field_reviews, guest_tool_decisions TO ledger_demo;
```

- The overlays mirror their real tables' rules (the corrected-value CHECK, the approval-required composite FK) but carry
  no append-only triggers: they are disposable. Finality (D5) comes from the primary keys plus no UPDATE grant.
- No `decided_by` (the guest is the key) and no `posting_id` (nothing is posted).
- The primary keys lead with `guest_id`, so every guest read is an index lookup; the purge touches few rows. No
  extra index.
- Every key is a `uuid`, so there are no sequences to grant.
- The migration only grants to `ledger_demo`; it does not create it (`ledger_owner` cannot create roles, and a
  migration cannot carry a password). A missing role makes the `GRANT` fail loudly, which is intended.
  - Local: `scripts/db_up.sh` creates `ledger_demo` with the dev password next to `ledger_owner`/`ledger_app`.
  - Railway: the operator runs `CREATE ROLE ledger_demo LOGIN PASSWORD '...'` as the superuser before the migration.
- Future tables the demo must write to (P5 feedback, P7 events) must `GRANT INSERT ... TO ledger_demo` in their own
  migration; the default privileges give read only.
- Downgrade drops the two tables and revokes the grants.
- `backend/.env.example` documents `DEMO_MODE` and `TEST_DEMO_DATABASE_URL` (the test connection as `ledger_demo`, §8).

### M3 — Phase 1: field reviews

`app/contracts/dao.py`:

- New private helper `_reviews_by_field(session, run_id, overlay_guest) -> dict[str, ReviewView]`: the real
  `field_reviews` rows for the run (today's dict), plus, when `overlay_guest` is set, that guest's
  `guest_field_reviews` rows. `ReviewView` is a small frozen dataclass (`decision`, `corrected_value`, `reason`) so both
  sources have one shape. No conflict rule is needed: a guest may only decide a field with no real review (below).
- `served_fields`, `terms_view`, `pending_reviews`, `runs_with_reviews` each gain `overlay_guest: uuid.UUID | None =
  None` and use the helper instead of their inline review query. `field_status` stays the single status rule.
  `pending_reviews` excludes fields the guest decided. `runs_with_reviews` returns the merged reviews per run.
- `record_review` gains `overlay_guest`. With a guest it inserts a `guest_field_reviews` row; it raises
  `FieldAlreadyReviewed` if the field has a real review or the guest already decided it. Without a guest it is
  unchanged.
- New `purge_guest_reviews(session, guest_ids)`.

Callers pass `overlay_guest` through: `routes/reviews.py`, `routes/contract_terms.py`, `reporting/timeline.py` (via
`routes/document_timeline.py`), `reporting/dashboard.py` (pending count, see M4), `assistant/contract_tools.py`,
`contracts/compare.py`, `assistant/service.py` (`_unvalidated_events`).

Agent: `ToolContext` gains `overlay_guest: uuid.UUID | None = None`. `routes/chat.py` takes it from
`get_overlay_guest` and passes it to `run_turn`, which puts it in the context. The tools read the guest's view, so
answers, citations and the billing gap follow that guest's decisions.

Read routes and the chat route use `get_overlay_guest`; `POST /reviews` switches from `decisions_closed_in_demo` to
`require_overlay_guest` in this milestone.

### M4 — Phase 2: approvals

`app/ledger/dao.py`:

- New public `check_posting(session, request: PostingRequest) -> None`: `_accounts_by_id` + `_validate`, no write.
  `create_posting` keeps calling the same two functions first, so the rule has one home.

`app/governance/dao.py`:

- `list_invocations`, `count_pending`, `invocations_for_document` gain `overlay_guest`. With a guest they keep only
  invocations whose `input->>'turn_id'` is a `chat_turns` row of that guest, and read the decision from
  `guest_tool_decisions` (left join on guest and invocation) instead of `tool_invocation_decisions`.
- `decide` gains `overlay_guest`. With a guest: the invocation must belong to the guest (else `InvocationNotFound`, so
  its existence is not revealed); `NotCritical` and `AlreadyDecided` as today; on approve, build the posting request
  with the same helper today's path uses (extracted as `_posting_request(invocation, tenant_id)`) and call
  `check_posting`; `PostingInvalid` propagates unchanged; then insert the overlay row and commit. Without a guest it is
  unchanged (real posting, real decision).
- New `purge_guest_decisions(session, guest_ids)`.

API: `DecisionOut` and the decision inside `InvocationOut` gain `recorded: bool` (true for real decisions, false for
overlay ones; `posting_id` stays null for overlay approvals). Routes pass `overlay_guest` through.

Dashboard: `cached_dashboard_stats` stays tenant-wide and real-only (documents, chunks, chat latency, eval). In demo
mode `routes/stats.py` replaces `reviews_pending` and `approvals_pending` after the cache read with the guest's counts
(`pending_reviews(..., overlay_guest)` and `count_pending(..., overlay_guest)`). The ETag is computed on the final body,
so it differs per guest.

Frontend: the approval card and the document timeline show "Demo posting, not recorded" when `recorded` is false.
The Ledger screen in demo mode adds a "Your demo postings (not recorded)" section listing the guest's approved
proposals from `GET /tool-invocations` (their `proposed_entries` already carry account names and currencies). No new
endpoint.

`POST /tool-invocations/{id}/decision` switches to `require_overlay_guest` in this milestone, and
`decisions_closed_in_demo` is deleted.

### M5 — Purge, role switch, deployed smoke test

- Purge: a small function `purge_stale_overlays(session, now)` in `app/assistant/` (the package that owns guests)
  finds guests with `last_seen_at < now - 24h` through `assistant.dao` and calls `contracts.dao.purge_guest_reviews`
  and `governance.dao.purge_guest_decisions`. `routes/guests.py` calls it on `POST /guests`. It runs in every mode (the
  overlays are empty outside demo mode). `guests` rows are kept: chat turns reference them.
- Rollout (operator): switch Railway `DATABASE_URL` to `ledger_demo`, then run the deployed smoke test (§9).

## 6. Data flow (demo mode)

1. The browser creates or reuses a guest (`POST /guests`, `X-Guest-Id` on every later call).
2. Reads (terms, review queue, timeline, dashboard counts, agent tools) get `overlay_guest` from the dependency and
   merge that guest's overlay rows over the shared rows.
3. A field review goes to `guest_field_reviews`; an approval runs `check_posting`, then goes to `guest_tool_decisions`.
4. Nothing reaches `field_reviews`, `tool_invocation_decisions`, `postings` or `entries`, and the `ledger_demo` role
   could not write them if code tried.
5. After 24 hours without activity, the next new guest's arrival deletes that guest's overlay rows.

## 7. Error handling

The existing problem+json handlers already cover every domain error these paths raise (`FieldAlreadyReviewed`,
`FieldNotFound`, `ReviewInvalid`, `InvocationNotFound`, `NotCritical`, `AlreadyDecided`, `PostingInvalid`). New cases:

- Demo mode, decision route, no or unknown guest → 400.
- M1 only: demo mode, decision route → 403 until M3/M4.
- An insert the role may not do → Postgres `InsufficientPrivilege` → 500. It should never happen, because the route is
  not mounted; the test in §8 proves the database refuses it anyway.

## 8. Testing

- **Routes (M1):** with `DEMO_MODE` on, the five write routes answer 405/404; with it off they work as today.
  `/config` reports `demo_mode`.
- **Database role (M2):** `db_up.sh` creates `ledger_demo` locally; a test engine connects as `ledger_demo` to
  `ledger_test` (URL from a `TEST_DEMO_DATABASE_URL` setting with a localhost default, like the existing test URLs) and
  asserts permission errors on `documents`, `postings`, `entries`, `field_reviews`, `tool_invocation_decisions`, and
  success on both overlays and `chat_turns`. The migration round-trip test covers upgrade and downgrade.
- **Phase 1 (M3):** the two-guest guard test (opposite decisions → different `served_fields`, contract tool output and
  billing comparison); isolation (no guest and another guest see nothing); finality (`FieldAlreadyReviewed` on a
  second decision and on a field with a real review).
- **Phase 2 (M4):** approving writes no `postings`/`entries` row; an invalid proposal raises `PostingInvalid` and
  leaves no overlay row; guest B cannot see or decide guest A's proposal; a second decision raises `AlreadyDecided`;
  dashboard counts reflect only the guest's own pending items; flag off still writes a real posting.
- **Purge (M5):** overlay rows of a guest last seen 25 hours ago are deleted on `POST /guests`; a guest seen an hour
  ago keeps theirs; `guests` rows remain.
- **Regression:** the full existing suite passes unchanged at every milestone; frontend `npm test`, `npm run build`
  and `npm run lint` pass.

## 9. Rollout and rollback

1. After M1 deploys: set `DEMO_MODE=1` on Railway. Public writes are closed from here.
2. After M2 deploys: `CREATE ROLE ledger_demo LOGIN PASSWORD '...'` as the Railway superuser (password in Infisical
   and `.env.demo`); run the migration as `ledger_owner` through the public proxy. `DATABASE_URL` stays on `ledger_app`.
3. After M5 deploys: switch `DATABASE_URL` to `ledger_demo` (private host). Smoke test on the deployed pair:
   upload and posting answer 405/404; two `X-Guest-Id` values with opposite decisions on the same field get different
   terms; a `psql` insert into `postings` as `ledger_demo` is refused; the browser flow (review, approve, "demo
   posting, not recorded", Ledger section) works.

Rollback at any point: `DATABASE_URL` back to `ledger_app`, or `DEMO_MODE` off. The migration only adds tables and
grants, so it never needs reverting to roll back.

## 10. Out of scope

Rate limits and spend caps (P3), retrieval edge cases (P4), feedback/Sentry/usage log (P5–P7; their migrations must
grant INSERT to `ledger_demo`), the document list, starter questions and in-app citation viewer (P8), the stale
`reversePosting` frontend test (separate chore).

## 11. Lenses that informed the design

- **DDIA:** the append-only tables stay the system of record; the overlays are per-guest derived state with
  read-your-writes in the same Postgres (no cache in the path) and no cross-guest conflicts (guest in the key). Purge
  timing only reclaims storage; it never decides visibility.
- **Defense in depth / Pragmatic Programmer (contracts, crash early):** two independent layers for P2 (unmounted
  routes and a role that cannot write); a missing role makes the migration fail loudly.
- **Clean Architecture:** the demo-mode policy lives at the edge (`main.py`, `deps.py`); packages receive a plain
  `overlay_guest` argument and never read configuration; dependency direction unchanged.
- **DRY:** `check_posting` and `create_posting` share `_accounts_by_id` + `_validate`; `field_status` stays the one
  status rule; one review-merge helper per package.
- **DDD (ubiquitous language):** decisions are final, and a posting is corrected only by a compensating reversal; the
  demo keeps that rule instead of adding an undo.
- **Postgres practice:** composite primary keys leading with `guest_id` serve every guest read; least-privilege grants
  with explicit column-level UPDATE.
