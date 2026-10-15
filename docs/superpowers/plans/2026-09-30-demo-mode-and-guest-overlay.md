# Demo Mode and Per-Guest Decision Overlay (P2 + P9) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **This project:** Gemini executes Tasks 1–9 in order; Claude reviews at each **REVIEW CHECKPOINT** before the next task starts. Stop at every checkpoint and hand over: the commit hash, the exact test/build/lint output, and `git status`. Task 10 is done by the operator (the user), not by Gemini.

**Goal:** Make the public demo unable to change shared state (P2) while each guest can still review fields and approve AI postings in a private, per-guest overlay (P9).

**Architecture:** `DEMO_MODE` is read only at the edge: `main.py` leaves out the write routers, and two FastAPI dependencies in `deps.py` decide whose overlay applies. Every package below receives a plain `overlay_guest: UUID | None` argument (None = today's path, byte for byte). Two new overlay tables hold guest decisions; a new `ledger_demo` database role can read everything but write only chat state and the overlays.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2.0 / Alembic / PostgreSQL 18 / pytest; React (Vite) + TypeScript / vitest.

**Spec:** `docs/superpowers/specs/2026-09-30-demo-mode-and-guest-overlay-design.md` — read it in full before Task 1. Section numbers below (§) refer to it.

## Deviations from the spec (found while mapping the code; the spec is amended to match)

1. **Proposal ownership (M4):** the spec scoped a guest's proposals through `chat_turns.guest_id`. That would make `governance` import `assistant` (which already imports `governance`: an import cycle), and the chat turn row is saved only after the answer streams, so a fast Approve click could race it. Instead, in demo mode the tool runner records `"guest_id"` in the proposal's `input` (Task 7), and `governance` filters on `input->>'guest_id'`. With the flag off the recorded input is unchanged.
2. **Purge permission (M2/M5):** the purge runs in every mode, and outside the demo the API runs as `ledger_app`, so the migration also grants `DELETE` on the two overlays to `ledger_app` (the backlog's original "ledger_app gets DELETE like element_search").
3. **Frontend reads (M1):** the frontend sends `X-Guest-Id` only on POSTs today. The reads that the overlay changes (review queue, terms, timeline, proposals, stats) must send it too, or a guest would never see their own decisions. Task 2 adds that.

## Global Constraints

- Branch `feat/pre-launch-demo` (already checked out). Never commit to `main`/`preview`. Stage files explicitly (never `git add -A` or `git add .`). Conventional commits. **No AI co-author line, no "Generated with" line.** Do not push.
- Backend commands run from `backend/` with `/home/niki/Documents/workenv/pydev/bin/<tool>` (e.g. `.../bin/pytest`). Never create or use a `.venv`.
- Frontend commands run from `frontend/`: `npm test`, `npm run build`, `npm run lint`.
- No new Python dependency, no new npm package.
- Python: type hints on every function signature; dataclasses for DTOs; SQLAlchemy 2.0 style; do not call `session.begin()`.
- Layering: routes stay thin (parse → call a package function → return); database access only in each package's `dao.py`; packages never read `config.DEMO_MODE` (only `main.py` and `deps.py` do).
- With `DEMO_MODE` off, behaviour is exactly today's: **the full existing backend suite must pass unchanged after every task** (`/home/niki/Documents/workenv/pydev/bin/pytest -q`). The only existing tests you may edit are the ones a task names explicitly.
- TypeScript: no `any`; a props interface for every component. Existing CSS custom properties only.
- The frontend suite has one pre-existing failure ("reverses with a key derived from the posting id so a retry replays"), tracked as a separate chore. Do not fix it and do not count it as yours; any *other* failure is yours.
- Do not touch `backend/.env`, `backend/.env.demo`, `backend/.env.demo.local`, `frontend/.env.vercel`.

## Review Focus

1. **A demo request with an unknown or missing guest** (a stale `X-Guest-Id` after a database reset, or none): reads must fall back to the shared view (200), decisions must be refused with 400 `guest-required`, never a 500 and never a write to a shared table. Test: Task 5, `test_a_demo_decision_without_a_known_guest_is_refused`.
2. **A field that already has a real review** (history from before demo mode): the guest cannot decide it (409), and the guest's view shows the real decision. Test: Task 4, `test_a_guest_cannot_decide_a_field_that_has_a_real_review`.
3. **Approving a proposal the ledger would reject** (unbalanced, unknown account): refused with the same 422 `posting-invalid` as today, and no overlay row is left behind. Test: Task 6, `test_an_invalid_proposal_is_refused_and_leaves_no_decision`.
4. **Demo mode on while `DATABASE_URL` is still `ledger_app`** (rollout step 2 in §9): everything must work, because `ledger_app` gets INSERT on the overlays from the 0003 default privileges and DELETE from the new migration. Covered by every demo-mode API test in Tasks 5 and 7 (the test suite runs as `ledger_app`).
5. **Turning demo mode off after guests decided**: the overlays are ignored and the shared view is exactly today's. Test: Task 5, `test_turning_demo_mode_off_ignores_the_overlays`.

---

## M1 — Close the public writes

### Task 1: Backend demo-mode switch (write routers, `/config`, temporary decision guard)

**Files:**
- Modify: `backend/app/config.py`, `backend/app/errors.py`, `backend/app/deps.py`, `backend/app/main.py`, `backend/app/routes/documents.py`, `backend/app/routes/postings.py`, `backend/app/routes/fee_runs.py`, `backend/app/routes/gl_exports.py`, `backend/app/routes/reviews.py`, `backend/app/routes/tool_invocations.py`, `backend/app/routes/stats.py`, `backend/.env.example`
- Create: `backend/tests/test_demo_mode.py`

**Interfaces:**
- Produces: `config.DEMO_MODE: bool`; `app.main.include_routes(app: FastAPI, *, demo_mode: bool) -> None`; `write_router` in `documents.py`, `postings.py`, `fee_runs.py`, `gl_exports.py`; `ConfigOut.demo_mode: bool`; `deps.decisions_closed_in_demo() -> None` and `errors.DecisionsClosed` (both temporary, deleted in Task 7).

- [ ] **Step 1: Write the failing tests** — create `backend/tests/test_demo_mode.py`:

```python
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config
from app.main import include_routes

WRITES = {
    ("/documents", "POST"), ("/postings", "POST"), ("/postings/{posting_id}/reversal", "POST"),
    ("/fee-runs", "POST"), ("/gl-exports", "POST"),
}


def _mounted(demo_mode: bool) -> set[tuple[str, str]]:
    app = FastAPI()
    include_routes(app, demo_mode=demo_mode)
    return {(route.path, method) for route in app.routes for method in (getattr(route, "methods", None) or ())}


def test_public_writes_are_mounted_outside_demo_mode():
    assert WRITES <= _mounted(demo_mode=False)


def test_demo_mode_leaves_out_every_public_write_and_keeps_the_reads():
    mounted = _mounted(demo_mode=True)
    assert not WRITES & mounted
    assert {
        ("/documents", "GET"), ("/postings", "GET"), ("/fee-calculations/{calculation_id}", "GET"),
        ("/gl-exports/{export_id}.csv", "GET"), ("/reviews", "POST"), ("/tool-invocations/{invocation_id}/decision", "POST"),
    } <= mounted


def test_demo_mode_answers_405_or_404_for_the_writes():
    app = FastAPI()
    include_routes(app, demo_mode=True)
    client = TestClient(app)
    assert client.post("/documents").status_code == 405  # the path still serves GET
    assert client.post("/postings", json={}).status_code == 405
    assert client.post(f"/postings/{uuid.uuid4()}/reversal").status_code == 404
    assert client.post("/fee-runs", json={}).status_code == 404
    assert client.post("/gl-exports", json={}).status_code == 404


def test_config_reports_demo_mode(client, monkeypatch):
    assert client.get("/config").json()["demo_mode"] is False
    monkeypatch.setattr(config, "DEMO_MODE", True)
    assert client.get("/config").json()["demo_mode"] is True


def test_decisions_are_closed_in_demo_mode_until_their_overlay_exists(client, monkeypatch):
    monkeypatch.setattr(config, "DEMO_MODE", True)
    review = client.post("/reviews", json={"run_id": str(uuid.uuid4()), "field_path": "fee_method", "decision": "confirmed"})
    assert review.status_code == 403 and review.json()["type"] == "/problems/decisions-closed-in-demo"
    decision = client.post(f"/tool-invocations/{uuid.uuid4()}/decision", json={"decision": "approved"})
    assert decision.status_code == 403
```

- [ ] **Step 2: Run them and confirm they fail** — `/home/niki/Documents/workenv/pydev/bin/pytest tests/test_demo_mode.py -q`. Expected: `ImportError: cannot import name 'include_routes'`.

- [ ] **Step 3: Add the switch to `backend/app/config.py`** — directly after the `FRONTEND_ORIGINS = ...` line, add:

```python

# Public demo (docs/superpowers/specs/2026-09-30-demo-mode-and-guest-overlay-design.md): the write routes that change
# shared state are not mounted, and guest decisions go to per-guest overlays. Off unless set to 1, true or yes.
DEMO_MODE = os.environ.get("DEMO_MODE", "").strip().lower() in {"1", "true", "yes"}
```

- [ ] **Step 4: Add the temporary error to `backend/app/errors.py`** — append at the end of the file:

```python


class DecisionsClosed(DomainError):
    """Temporary (spec M1): demo-mode decisions stay closed until their per-guest overlay exists. Deleted in Task 7."""

    status = 403
    type_slug = "decisions-closed-in-demo"
    title = "Decisions are not available in the public demo yet"
```

- [ ] **Step 5: Add the temporary guard to `backend/app/deps.py`** — add `from app import config` and `from app.errors import DecisionsClosed` to the imports (keep them sorted with the existing `from app...` imports), then append at the end of the file:

```python


def decisions_closed_in_demo() -> None:
    """Temporary (spec M1): replaced by require_overlay_guest in Task 5 (reviews) and Task 7 (tool decisions)."""
    if config.DEMO_MODE:
        raise DecisionsClosed("Decisions are not available in the public demo yet.")
```

- [ ] **Step 6: Put the guard on the two decision routes.**
  - `backend/app/routes/reviews.py`: add `decisions_closed_in_demo` to the `from app.deps import ...` line, and change the decorator of `submit_review` to
    `@router.post("", status_code=201, response_model=ReviewOut, dependencies=[Depends(decisions_closed_in_demo)])`.
  - `backend/app/routes/tool_invocations.py`: add `decisions_closed_in_demo` to the `from app.deps import ...` line, and change the decorator of `decide_tool_invocation` to
    `@router.post("/{invocation_id}/decision", status_code=201, response_model=DecisionOut, dependencies=[Depends(decisions_closed_in_demo)])`.

- [ ] **Step 7: Split the write routes onto their own routers.**
  - `backend/app/routes/documents.py`: after `router = APIRouter(prefix="/documents", tags=["documents"])` add
    `write_router = APIRouter(prefix="/documents", tags=["documents"])  # not mounted in the public demo (DEMO_MODE)`,
    and change the upload decorator `@router.post("", status_code=202, response_model=UploadOut)` to `@write_router.post("", status_code=202, response_model=UploadOut)`.
  - `backend/app/routes/postings.py`: after `router = APIRouter(prefix="/postings", tags=["postings"])` add
    `write_router = APIRouter(prefix="/postings", tags=["postings"])  # not mounted in the public demo (DEMO_MODE)`,
    and change both POST decorators to use it: `@write_router.post("", status_code=201, response_model=PostingOut)` and `@write_router.post("/{posting_id}/reversal", status_code=201, response_model=PostingOut)`.
  - `backend/app/routes/fee_runs.py`: after `router = APIRouter(tags=["billing"])` add
    `write_router = APIRouter(tags=["billing"])  # not mounted in the public demo (DEMO_MODE)`,
    and change `@router.post("/fee-runs", ...)` to `@write_router.post("/fee-runs", status_code=201, response_model=FeeCalculationOut)`.
  - `backend/app/routes/gl_exports.py`: after `router = APIRouter(prefix="/gl-exports", tags=["reporting"])` add
    `write_router = APIRouter(prefix="/gl-exports", tags=["reporting"])  # not mounted in the public demo (DEMO_MODE)`,
    and change `@router.post("", status_code=201, response_model=GlExportOut)` to `@write_router.post("", status_code=201, response_model=GlExportOut)`.
  Do not change anything else in these four files.

- [ ] **Step 8: Mount routes through `include_routes` in `backend/app/main.py`** — replace the twelve `app.include_router(...)` lines at the end of the file with:

```python
# Reads and the two decision routes: mounted in every mode.
ROUTERS = (
    health.router, postings.router, fee_runs.router, tool_invocations.router, reviews.router, gl_exports.router,
    documents.router, chat.router, stats.router, guests.router, contract_terms.router, document_timeline.router,
)
# Public writes to shared state (corpus, ledger, billing, exports): not mounted in the public demo.
WRITE_ROUTERS = (documents.write_router, postings.write_router, fee_runs.write_router, gl_exports.write_router)


def include_routes(app: FastAPI, *, demo_mode: bool) -> None:
    for router in ROUTERS:
        app.include_router(router)
    if not demo_mode:
        for router in WRITE_ROUTERS:
            app.include_router(router)


include_routes(app, demo_mode=config.DEMO_MODE)
```

- [ ] **Step 9: Report demo mode on `/config`** — in `backend/app/routes/stats.py`:
  - add `demo_mode: bool = False` as the last field of `class ConfigOut(BaseModel)`;
  - in `get_config`, change `body = _config_out()` to
    `body = _config_out().model_copy(update={"demo_mode": config.DEMO_MODE})  # outside the lru_cache: read per request`.

- [ ] **Step 10: Document the switch** — in `backend/.env.example`, append at the end of the file (blank line before it):

```
# --- Public demo ---
# 1 = public demo: upload and ledger writes are not mounted, and guest decisions go to per-guest overlays.
# Leave empty locally and anywhere the real write paths are needed.
DEMO_MODE=
```

- [ ] **Step 11: Run the tests** — `/home/niki/Documents/workenv/pydev/bin/pytest tests/test_demo_mode.py -q` → 5 passed. Then `/home/niki/Documents/workenv/pydev/bin/pytest -q` → no failures.

- [ ] **Step 12: Commit** — `git add backend/app/config.py backend/app/errors.py backend/app/deps.py backend/app/main.py backend/app/routes/documents.py backend/app/routes/postings.py backend/app/routes/fee_runs.py backend/app/routes/gl_exports.py backend/app/routes/reviews.py backend/app/routes/tool_invocations.py backend/app/routes/stats.py backend/.env.example backend/tests/test_demo_mode.py`, check `git diff --staged --stat` shows exactly these 13 files, then
`git commit -m "feat(api): demo mode leaves out the public writes and closes decisions until their overlay lands"`.

**REVIEW CHECKPOINT 1.**

---

### Task 2: Frontend demo mode (hide upload and reversal, send the guest on reads)

**Files:**
- Create: `frontend/src/lib/useDemoMode.ts`
- Modify: `frontend/src/api.ts`, `frontend/src/screens/Documents.tsx`, `frontend/src/screens/Ledger.tsx`

**Interfaces:**
- Consumes: `GET /config` → `demo_mode` (Task 1).
- Produces: `useDemoMode(): boolean`; `ConfigDto.demo_mode`; reads `listReviews`, `getTerms`, `getTimeline`, `listToolInvocations`, `getStats` send `X-Guest-Id`.

- [ ] **Step 1: Types and the guest header on reads** — in `frontend/src/api.ts`:
  - add `demo_mode: boolean;` as the last member of `export type ConfigDto = { ... }`;
  - directly after the `guestHeaders` function, add:

```ts
/** GET with the guest header: in the public demo the API merges this guest's own decisions into the answer. */
async function getWithGuest<T>(url: string): Promise<T> {
  return fetch(url, { headers: await guestHeaders() }).then((r) => json<T>(r));
}
```

  - change these five functions to use it (keep their signatures; the bodies become):
    - `listToolInvocations`: keep the `const url = withQuery(...)` lines, replace the `return fetch(url).then(...)` line with `return getWithGuest<ToolInvocationDto[]>(url);`
    - `listReviews`: `return getWithGuest<ReviewItemDto[]>(`${API_BASE}/reviews`);`
    - `getStats`: `return getWithGuest<StatsDto>(`${API_BASE}/stats`);`
    - `getTerms`: `return getWithGuest<TermsDto>(`${API_BASE}/documents/${documentId}/terms`);`
    - `getTimeline`: `return getWithGuest<TimelineItemDto[]>(`${API_BASE}/documents/${documentId}/timeline`);`

- [ ] **Step 2: The hook** — create `frontend/src/lib/useDemoMode.ts`:

```ts
import { useEffect, useState } from 'react';
import { getConfig } from '../api';

/** True when the API runs as the public demo (writes to shared state are off). False until /config answers. */
export function useDemoMode(): boolean {
  const [demoMode, setDemoMode] = useState(false);
  useEffect(() => {
    let cancelled = false;
    getConfig()
      .then((c) => !cancelled && setDemoMode(c.demo_mode))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);
  return demoMode;
}
```

- [ ] **Step 3: Hide upload** — in `frontend/src/screens/Documents.tsx`: import `useDemoMode` from `'../lib/useDemoMode'`; add `const demoMode = useDemoMode();` as the first line inside `export function Documents() {`; replace the whole `<div className="documents__upload"> ... </div>` block (the one holding the file input and the "Upload document" button) with:

```tsx
          {demoMode ? (
            <div className="documents__upload">
              <span className="mono">Uploads are off in the public demo.</span>
            </div>
          ) : (
            <div className="documents__upload">
              {/* the existing children of documents__upload, unchanged */}
            </div>
          )}
```

  Move the existing children (file `<input>`, button, hint `<span>`, error `<span>`) into the second branch unchanged.

- [ ] **Step 4: Hide reversal** — in `frontend/src/screens/Ledger.tsx`: import `useDemoMode` from `'../lib/useDemoMode'`; add `const demoMode = useDemoMode();` as the first line inside `export function Ledger() {`; in the `ledger__detail-actions` block, change the final `) : (` branch that renders `<ReverseAction .../>` so it reads:

```tsx
                ) : demoMode ? (
                  <p className="ledger__help">
                    Reversals are off in the public demo: the ledger is append-only, so a public reversal would stay forever.
                  </p>
                ) : (
                  <ReverseAction
                    key={selected.id}
                    posting={selected}
                    onReversed={(reversalId) => {
                      setSelectedId(reversalId);
                      void load();
                    }}
                  />
                )}
```

- [ ] **Step 5: Verify** — from `frontend/`: `npm test` (only the known pre-existing failure), `npm run build` (passes), `npm run lint` (no new warnings or errors).

- [ ] **Step 6: Commit** — `git add frontend/src/lib/useDemoMode.ts frontend/src/api.ts frontend/src/screens/Documents.tsx frontend/src/screens/Ledger.tsx`, check the staged stat, then
`git commit -m "feat(frontend): demo mode hides upload and reversal and sends the guest on reads"`.

**REVIEW CHECKPOINT 2.**

---

## M2 — One migration: overlays and the demo role

### Task 3: Migration 0013, overlay models, the `ledger_demo` role

**Files:**
- Create: `backend/alembic/versions/0013_demo_role_and_guest_overlays.py`, `backend/app/demo.py`, `backend/tests/test_demo_role.py`
- Modify: `backend/app/contracts/models.py`, `backend/app/governance/models.py`, `backend/app/config.py`, `backend/scripts/db_up.sh`, `backend/.env.example`

**Interfaces:**
- Produces: tables `guest_field_reviews`, `guest_tool_decisions`; ORM `GuestFieldReview` (contracts) and `GuestToolDecision` (governance), each with a `decided_by` property; `ToolInvocationDecision.recorded -> True`, `GuestToolDecision.recorded -> False`, `GuestToolDecision.posting_id -> None`; `app.demo.GUEST_DECIDED_BY = "you (demo)"`; `config.TEST_DEMO_DATABASE_URL`.

- [ ] **Step 1: Create the role locally** — in `backend/scripts/db_up.sh`:
  - change `for role in ledger_owner ledger_app; do` to `for role in ledger_owner ledger_app ledger_demo; do`;
  - change the comment on `ROLE_PASSWORD=` to `# dev-only password shared by ledger_owner, ledger_app and ledger_demo`.
  Then run `./scripts/db_up.sh` from `backend/` and confirm it ends with "Done." (it creates `ledger_demo` and changes nothing else).

- [ ] **Step 2: Test URL** — in `backend/app/config.py`, directly after the `TEST_OWNER_DATABASE_URL = os.environ.get(...)` block, add:

```python

# The public demo's API role (grants in migration 0013), used by tests/test_demo_role.py.
TEST_DEMO_DATABASE_URL = os.environ.get(
    "TEST_DEMO_DATABASE_URL",
    f"postgresql+psycopg://ledger_demo:localdev@{_LOCAL}/ledger_test",
)
```

  and in `backend/.env.example`, directly after the `TEST_OWNER_DATABASE_URL=...` line, add
  `TEST_DEMO_DATABASE_URL=postgresql+psycopg://ledger_demo:localdev@localhost:5432/ledger_test`.

- [ ] **Step 3: Write the failing tests** — create `backend/tests/test_demo_role.py`:

```python
import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app import config
from app.ledger.db import make_session_factory

SHARED = (
    "documents", "document_versions", "document_elements", "pii_tokens", "extraction_runs", "extracted_fields",
    "field_reviews", "postings", "entries", "accounts", "tool_invocation_decisions", "fee_calculations", "gl_exports",
)
OVERLAYS = ("guest_field_reviews", "guest_tool_decisions")


@pytest.fixture(scope="module")
def demo_factory(migrated_test_database):
    return make_session_factory(config.TEST_DEMO_DATABASE_URL)


@pytest.fixture()
def demo_session(demo_factory):
    session = demo_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _can(session, role: str, table: str, privilege: str) -> bool:
    return session.scalar(text("SELECT has_table_privilege(:r, :t, :p)"), {"r": role, "t": table, "p": privilege})


@pytest.mark.parametrize("table", SHARED)
def test_demo_role_cannot_insert_into_shared_tables(demo_session, table):
    with pytest.raises(ProgrammingError) as caught:
        demo_session.execute(text(f"INSERT INTO {table} DEFAULT VALUES"))
    assert isinstance(caught.value.orig, psycopg.errors.InsufficientPrivilege)


def test_demo_role_reads_everything_and_writes_only_chat_state_and_the_overlays(owner_session):
    for table in SHARED + ("guests", "chat_turns", "tool_invocations") + OVERLAYS:
        assert _can(owner_session, "ledger_demo", table, "SELECT"), table
    for table in ("guests", "chat_turns", "tool_invocations") + OVERLAYS:
        assert _can(owner_session, "ledger_demo", table, "INSERT"), table
    for table in OVERLAYS:
        assert _can(owner_session, "ledger_demo", table, "DELETE"), table
        assert not _can(owner_session, "ledger_demo", table, "UPDATE"), table  # decisions are final
    for table in SHARED + ("guests",):
        assert not _can(owner_session, "ledger_demo", table, "DELETE"), table
    column = "SELECT has_column_privilege('ledger_demo', 'guests', :c, 'UPDATE')"
    assert owner_session.scalar(text(column), {"c": "last_seen_at"})
    assert not owner_session.scalar(text(column), {"c": "tenant_id"})


def test_app_role_may_purge_the_overlays(owner_session):
    for table in OVERLAYS:
        assert _can(owner_session, "ledger_app", table, "DELETE"), table
```

- [ ] **Step 4: Run them and confirm they fail** — `/home/niki/Documents/workenv/pydev/bin/pytest tests/test_demo_role.py -q`. Expected: failures, because the overlay tables and the grants do not exist yet (e.g. `relation "guest_field_reviews" does not exist`, or `InsufficientPrivilege` missing on SELECT).

- [ ] **Step 5: Write the migration** — create `backend/alembic/versions/0013_demo_role_and_guest_overlays.py`:

```python
"""demo role grants and the per-guest decision overlays

Revision ID: 0013_demo_role_and_guest_overlays
Revises: 0012_guests_and_turn_scope
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0013_demo_role_and_guest_overlays"
down_revision: Union[str, Sequence[str], None] = "0012_guests_and_turn_scope"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OVERLAYS = "guest_field_reviews, guest_tool_decisions"


def _run(*statements: str) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    _run(
        # A demo guest's decisions (spec P2+P9): same rules as the real tables, keyed by guest, never shared.
        # No append-only triggers: the rows are disposable (24-hour purge). Finality comes from the primary keys
        # and from the demo role having no UPDATE.
        "CREATE TABLE guest_field_reviews ("
        " guest_id uuid NOT NULL REFERENCES guests(id),"
        " run_id uuid NOT NULL,"
        " field_path text NOT NULL,"
        " decision review_decision NOT NULL,"
        " corrected_value jsonb NULL,"
        " reason text NULL,"
        " decided_at timestamptz NOT NULL DEFAULT now(),"
        " PRIMARY KEY (guest_id, run_id, field_path),"
        " FOREIGN KEY (run_id, field_path) REFERENCES extracted_fields (run_id, field_path),"
        " CONSTRAINT ck_guest_reviews_corrected_value CHECK ((decision = 'corrected') = (corrected_value IS NOT NULL)))",
        "CREATE TABLE guest_tool_decisions ("
        " guest_id uuid NOT NULL REFERENCES guests(id),"
        " invocation_id uuid NOT NULL,"
        " approval_required boolean NOT NULL DEFAULT true CONSTRAINT ck_guest_decisions_only_for_critical CHECK (approval_required),"
        " decision tool_decision NOT NULL,"
        " reason text NULL,"
        " decided_at timestamptz NOT NULL DEFAULT now(),"
        " PRIMARY KEY (guest_id, invocation_id),"
        " CONSTRAINT fk_guest_decisions_critical_invocation FOREIGN KEY (invocation_id, approval_required)"
        "   REFERENCES tool_invocations (id, approval_required))",
        # ledger_app (non-demo API): SELECT and INSERT come from 0003's default privileges; DELETE is for the purge.
        f"GRANT DELETE ON {OVERLAYS} TO ledger_app",
        # ledger_demo (the public demo's API role): read everything, write only chat state and the overlays.
        # The role is created outside migrations (scripts/db_up.sh locally, by hand on Railway): a migration cannot
        # carry a password and ledger_owner cannot create roles. A missing role makes these GRANTs fail, on purpose.
        "GRANT USAGE ON SCHEMA public TO ledger_demo",
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO ledger_demo",
        # Later tables are readable too. A later table the demo must WRITE needs its own explicit GRANT INSERT.
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO ledger_demo",
        "GRANT INSERT ON guests, chat_turns, tool_invocations TO ledger_demo",
        "GRANT UPDATE (last_seen_at) ON guests TO ledger_demo",
        f"GRANT INSERT, DELETE ON {OVERLAYS} TO ledger_demo",
    )


def downgrade() -> None:
    _run(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM ledger_demo",
        "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM ledger_demo",
        "REVOKE USAGE ON SCHEMA public FROM ledger_demo",
        "DROP TABLE guest_tool_decisions",
        "DROP TABLE guest_field_reviews",
    )
```

- [ ] **Step 6: The shared label** — create `backend/app/demo.py`:

```python
"""Public demo (DEMO_MODE, spec P2+P9): wording shared by the per-guest overlay decisions."""

# The overlays store no decided_by: the guest is the key, and only that guest ever sees the row.
GUEST_DECIDED_BY = "you (demo)"
```

- [ ] **Step 7: The overlay models.**
  - `backend/app/contracts/models.py`: add `from app.demo import GUEST_DECIDED_BY` to the imports and append:

```python


class GuestFieldReview(Base):
    """A demo guest's field review (spec P2+P9): private to that guest, purged after 24 hours of inactivity."""

    __tablename__ = "guest_field_reviews"
    __mapper_args__ = {"eager_defaults": True}
    guest_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    field_path: Mapped[str] = mapped_column(Text, primary_key=True)
    decision: Mapped[ReviewDecision] = mapped_column(SAEnum(ReviewDecision, name="review_decision", native_enum=True), nullable=False)
    corrected_value: Mapped[object | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    @property
    def decided_by(self) -> str:
        return GUEST_DECIDED_BY
```

  - `backend/app/governance/models.py`: add `from app.demo import GUEST_DECIDED_BY` to the imports; add to the end of `class ToolInvocationDecision` (after its `posting_id` column):

```python

    @property
    def recorded(self) -> bool:
        """A real decision: an approval wrote a posting."""
        return True
```

  and append:

```python


class GuestToolDecision(Base):
    """A demo guest's decision on a proposal (spec P2+P9): checked by the ledger, never posted, private to that guest."""

    __tablename__ = "guest_tool_decisions"
    __mapper_args__ = {"eager_defaults": True}

    guest_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    invocation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    decision: Mapped[ToolDecision] = mapped_column(SAEnum(ToolDecision, name="tool_decision", native_enum=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    @property
    def decided_by(self) -> str:
        return GUEST_DECIDED_BY

    @property
    def posting_id(self) -> None:
        """Nothing is ever posted for a demo guest."""
        return None

    @property
    def recorded(self) -> bool:
        return False
```

  (No ORM `ForeignKey` on the overlay models on purpose: the foreign keys live in the database, and the referenced `guests` model belongs to another package.)

- [ ] **Step 8: Run the tests** — `/home/niki/Documents/workenv/pydev/bin/pytest tests/test_demo_role.py tests/test_migrations.py -q` → all pass (the migration round-trip covers upgrade → downgrade → upgrade). Then the full suite `/home/niki/Documents/workenv/pydev/bin/pytest -q` → no failures.

- [ ] **Step 9: Commit** — `git add backend/alembic/versions/0013_demo_role_and_guest_overlays.py backend/app/demo.py backend/app/contracts/models.py backend/app/governance/models.py backend/app/config.py backend/scripts/db_up.sh backend/.env.example backend/tests/test_demo_role.py`, check the staged stat (8 files), then
`git commit -m "feat(db): per-guest decision overlays and the ledger_demo role's grants"`.

**REVIEW CHECKPOINT 3.**

---

## M3 — Phase 1: field reviews

### Task 4: Overlay dependencies and the contracts readers

**Files:**
- Modify: `backend/app/errors.py`, `backend/app/deps.py`, `backend/app/contracts/dao.py`
- Create: `backend/tests/test_guest_reviews.py`

**Interfaces:**
- Consumes: `GuestFieldReview` (Task 3), `GUEST_DECIDED_BY` (Task 3).
- Produces:
  - `deps.get_overlay_guest(guest_id) -> uuid.UUID | None` (reads), `deps.require_overlay_guest(guest_id) -> uuid.UUID | None` (decision writes), `errors.GuestRequired` (400, `guest-required`).
  - `contracts.dao.Review = FieldReview | GuestFieldReview`.
  - New keyword/positional parameter `overlay_guest: uuid.UUID | None = None` (always last) on `served_fields(session, tenant_id, document_id, overlay_guest=None)`, `runs_with_reviews(session, document_id, overlay_guest=None) -> list[tuple[ExtractionRun, list[Review]]]`, `pending_reviews(session, tenant_id, overlay_guest=None)`, `terms_view(session, tenant_id, document_id, on, overlay_guest=None)`, and keyword-only `record_review(..., overlay_guest=None) -> Review`.

- [ ] **Step 1: Write the failing tests** — create `backend/tests/test_guest_reviews.py`:

```python
from datetime import date

import pytest

from app.assistant import dao as assistant_dao
from app.contracts import dao
from app.contracts.errors import FieldAlreadyReviewed
from app.contracts.models import FieldReview
from app.contracts.types import ReviewDecision
from app.demo import GUEST_DECIDED_BY
from tests.test_reviews_api import _run


def _guest(db_session, tenant_id):
    return assistant_dao.register_guest(db_session, tenant_id, None)


def _review(db_session, tenant_id, run, field_path, decision, *, guest=None, corrected_value=None):
    return dao.record_review(
        db_session, tenant_id=tenant_id, run_id=run.id, field_path=field_path, decision=decision,
        corrected_value=corrected_value, reason=None, decided_by="demo_user", overlay_guest=guest,
    )


def _statuses(db_session, tenant_id, document_id, guest):
    view = dao.terms_view(db_session, tenant_id, document_id, date.today(), overlay_guest=guest)
    return {f.path: f.status for f in view.fields}


def test_two_guests_with_opposite_decisions_are_served_different_terms(db_session, tenant_id):
    version, run = _run(db_session, tenant_id)
    a, b = _guest(db_session, tenant_id), _guest(db_session, tenant_id)
    _review(db_session, tenant_id, run, "termination_notice_days", ReviewDecision.confirmed, guest=a)
    _review(db_session, tenant_id, run, "termination_notice_days", ReviewDecision.rejected, guest=b)
    _review(db_session, tenant_id, run, "fee_method", ReviewDecision.corrected, guest=a, corrected_value="graduated")

    served_a = dao.served_fields(db_session, tenant_id, version.document_id, overlay_guest=a)
    served_b = dao.served_fields(db_session, tenant_id, version.document_id, overlay_guest=b)
    assert served_a.fields["termination_notice_days"].value == 30
    assert served_a.fields["fee_method"].value == "graduated"
    assert "termination_notice_days" not in served_b.fields and "termination_notice_days" in served_b.unserved
    assert _statuses(db_session, tenant_id, version.document_id, a)["termination_notice_days"] == "confirmed"
    assert _statuses(db_session, tenant_id, version.document_id, b)["termination_notice_days"] == "rejected"


def test_a_guest_decision_is_invisible_without_the_guest_and_to_other_guests(db_session, tenant_id):
    version, run = _run(db_session, tenant_id)
    a, b = _guest(db_session, tenant_id), _guest(db_session, tenant_id)
    _review(db_session, tenant_id, run, "termination_notice_days", ReviewDecision.confirmed, guest=a)

    for viewer in (None, b):
        assert "termination_notice_days" not in dao.served_fields(db_session, tenant_id, version.document_id, overlay_guest=viewer).fields
        assert [p.field_path for p in dao.pending_reviews(db_session, tenant_id, overlay_guest=viewer)] == ["fee_method", "termination_notice_days"]
        assert [r for _, reviews in dao.runs_with_reviews(db_session, version.document_id, overlay_guest=viewer) for r in reviews] == []
    assert [p.field_path for p in dao.pending_reviews(db_session, tenant_id, overlay_guest=a)] == ["fee_method"]
    reviews_a = [r for _, reviews in dao.runs_with_reviews(db_session, version.document_id, overlay_guest=a) for r in reviews]
    assert [(r.field_path, r.decided_by) for r in reviews_a] == [("termination_notice_days", GUEST_DECIDED_BY)]
    assert db_session.get(FieldReview, (run.id, "termination_notice_days")) is None  # nothing reached the shared table


def test_guest_decisions_are_final(db_session, tenant_id):
    _, run = _run(db_session, tenant_id)
    a = _guest(db_session, tenant_id)
    _review(db_session, tenant_id, run, "fee_method", ReviewDecision.rejected, guest=a)
    with pytest.raises(FieldAlreadyReviewed):
        _review(db_session, tenant_id, run, "fee_method", ReviewDecision.confirmed, guest=a)


def test_a_guest_cannot_decide_a_field_that_has_a_real_review(db_session, tenant_id):
    version, run = _run(db_session, tenant_id)
    _review(db_session, tenant_id, run, "fee_method", ReviewDecision.corrected, corrected_value="graduated")  # real
    a = _guest(db_session, tenant_id)
    with pytest.raises(FieldAlreadyReviewed):
        _review(db_session, tenant_id, run, "fee_method", ReviewDecision.rejected, guest=a)
    assert dao.served_fields(db_session, tenant_id, version.document_id, overlay_guest=a).fields["fee_method"].value == "graduated"
```

- [ ] **Step 2: Run them and confirm they fail** — `/home/niki/Documents/workenv/pydev/bin/pytest tests/test_guest_reviews.py -q`. Expected: `TypeError: ... unexpected keyword argument 'overlay_guest'`.

- [ ] **Step 3: The error** — append to `backend/app/errors.py`:

```python


class GuestRequired(DomainError):
    """Demo mode: a decision needs a known guest, so it can never fall through to the shared tables."""

    status = 400
    type_slug = "guest-required"
    title = "A known guest is required"
```

- [ ] **Step 4: The two dependencies** — in `backend/app/deps.py`, add `GuestRequired` to the `from app.errors import ...` line, and insert directly after the `get_guest_id` function:

```python


def get_overlay_guest(guest_id: Annotated[uuid.UUID | None, Depends(get_guest_id)]) -> uuid.UUID | None:
    """Reads: the guest whose overlay applies in the public demo. None (flag off, or no known guest) = shared view."""
    return guest_id if config.DEMO_MODE else None


def require_overlay_guest(guest_id: Annotated[uuid.UUID | None, Depends(get_guest_id)]) -> uuid.UUID | None:
    """Decision writes: in the public demo a known guest is required. None (flag off) = today's real tables."""
    if not config.DEMO_MODE:
        return None
    if guest_id is None:
        raise GuestRequired("Send the X-Guest-Id of a known guest (POST /guests) to decide in the public demo.")
    return guest_id
```

- [ ] **Step 5: The merge helper** — in `backend/app/contracts/dao.py`:
  - change the models import to `from app.contracts.models import ExtractedField, ExtractionRun, FieldReview, GuestFieldReview`;
  - directly after the `ServedTerms` dataclass, add:

```python


# A real review, or a demo guest's own (spec P2+P9). Both expose field_path, decision, corrected_value, reason,
# decided_by and decided_at.
Review = FieldReview | GuestFieldReview


def _reviews_by_field(session: Session, run_id: uuid.UUID, overlay_guest: uuid.UUID | None) -> dict[str, Review]:
    """The run's real reviews, plus the guest's own when a guest is given. A guest can only decide a field that has
    no real review (record_review), so the two never overlap."""
    reviews: dict[str, Review] = {
        r.field_path: r for r in session.scalars(select(FieldReview).where(FieldReview.run_id == run_id))
    }
    if overlay_guest is not None:
        reviews |= {r.field_path: r for r in session.scalars(select(GuestFieldReview).where(
            GuestFieldReview.run_id == run_id, GuestFieldReview.guest_id == overlay_guest))}
    return reviews
```

- [ ] **Step 6: The four readers use it.**
  - `served_fields`: signature becomes `def served_fields(session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID, overlay_guest: uuid.UUID | None = None) -> ServedTerms | None:` and its line `reviews = {r.field_path: r for r in session.scalars(select(FieldReview).where(FieldReview.run_id == run.id))}` becomes `reviews = _reviews_by_field(session, run.id, overlay_guest)`.
  - `runs_with_reviews` becomes:

```python
def runs_with_reviews(session: Session, document_id: uuid.UUID, overlay_guest: uuid.UUID | None = None
                      ) -> list[tuple[ExtractionRun, list[Review]]]:
    runs = session.scalars(
        select(ExtractionRun).join(DocumentVersion, DocumentVersion.id == ExtractionRun.version_id)
        .where(DocumentVersion.document_id == document_id).order_by(ExtractionRun.created_at)
    ).all()
    return [(run, list(_reviews_by_field(session, run.id, overlay_guest).values())) for run in runs]
```

  - `pending_reviews`: signature becomes `def pending_reviews(session: Session, tenant_id: uuid.UUID, overlay_guest: uuid.UUID | None = None) -> list[PendingField]:` and its line `reviewed = set(session.scalars(select(FieldReview.field_path).where(FieldReview.run_id == run.id)))` becomes `reviewed = set(_reviews_by_field(session, run.id, overlay_guest))`.
  - `terms_view`: signature becomes `def terms_view(session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID, on: date, overlay_guest: uuid.UUID | None = None) -> TermsView | None:` and its line `reviews = {r.field_path: r for r in session.scalars(select(FieldReview).where(FieldReview.run_id == run.id))}` becomes `reviews = _reviews_by_field(session, run.id, overlay_guest)`.

- [ ] **Step 7: The write** — in `record_review`, add `overlay_guest: uuid.UUID | None = None,` as the last keyword parameter, change the return annotation to `-> Review`, and directly after the `raise FieldNotFound(...)` line insert:

```python
    if overlay_guest is not None:
        return _record_guest_review(session, run_id=run_id, field_path=field_path, decision=decision,
                                    corrected_value=corrected_value, reason=reason, guest_id=overlay_guest)
```

  Then add this function directly after `record_review`:

```python


def _record_guest_review(
    session: Session, *, run_id: uuid.UUID, field_path: str, decision: ReviewDecision, corrected_value: object | None,
    reason: str | None, guest_id: uuid.UUID,
) -> GuestFieldReview:
    """Demo mode: the decision goes to the guest's overlay. Final, like a real review: one per guest and field, and
    never on a field that already has a real review."""
    if session.get(FieldReview, (run_id, field_path)) is not None:
        raise FieldAlreadyReviewed(f"Field {field_path} of extraction run {run_id} has already been reviewed.")
    review = GuestFieldReview(guest_id=guest_id, run_id=run_id, field_path=field_path, decision=decision,
                              corrected_value=corrected_value, reason=reason)
    session.add(review)
    try:
        session.commit()
    except IntegrityError as exc:  # the primary key allows one decision per guest and field
        session.rollback()
        raise FieldAlreadyReviewed(f"Field {field_path} of extraction run {run_id} has already been reviewed.") from exc
    return review
```

- [ ] **Step 8: Run the tests** — `/home/niki/Documents/workenv/pydev/bin/pytest tests/test_guest_reviews.py -q` → 4 passed; full suite `/home/niki/Documents/workenv/pydev/bin/pytest -q` → no failures.

- [ ] **Step 9: Commit** — `git add backend/app/errors.py backend/app/deps.py backend/app/contracts/dao.py backend/tests/test_guest_reviews.py`, check the staged stat, then
`git commit -m "feat(contracts): merge a demo guest's own field reviews into every reader"`.

**REVIEW CHECKPOINT 4.**

---

### Task 5: Field-review overlay through the routes and the agent

**Files:**
- Modify: `backend/app/routes/reviews.py`, `backend/app/routes/contract_terms.py`, `backend/app/routes/document_timeline.py`, `backend/app/reporting/timeline.py`, `backend/app/contracts/compare.py`, `backend/app/assistant/tools.py`, `backend/app/assistant/contract_tools.py`, `backend/app/assistant/service.py`, `backend/app/routes/chat.py`, `backend/tests/test_demo_mode.py`
- Create: `backend/tests/test_guest_reviews_api.py`

**Interfaces:**
- Consumes: `get_overlay_guest`, `require_overlay_guest` and the `overlay_guest` parameters (Task 4).
- Produces: `ToolContext.overlay_guest: uuid.UUID | None = None`; `compare_contract_to_billing(..., overlay_guest=None)`; `run_turn(..., overlay_guest=None)`; `document_timeline(session, tenant_id, document_id, overlay_guest=None)`.

- [ ] **Step 1: Write the failing tests** — create `backend/tests/test_guest_reviews_api.py`:

```python
import uuid
from datetime import date

import pytest

from app import config
from app.assistant import dao as assistant_dao
from app.assistant.contract_tools import contract_tools
from app.assistant.tools import ToolContext, execute
from app.contracts import dao
from app.contracts.models import FieldReview
from app.contracts.types import FieldRouting, ReviewDecision
from app.governance.dao import ModelConfig
from app.retrieval.vector_index import InMemoryVectorIndex
from tests.fakes import RecordingEmbeddings
from tests.support import build_fee_scenario
from tests.test_contracts_compare import _contract
from tests.test_reviews_api import _run

TOOLS = {spec.name: spec for spec in contract_tools()}


@pytest.fixture()
def demo(monkeypatch):
    monkeypatch.setattr(config, "DEMO_MODE", True)


def _guest(client) -> dict[str, str]:
    return {"X-Guest-Id": client.post("/guests").json()["id"]}


def _body(run, field_path, decision):
    return {"run_id": str(run.id), "field_path": field_path, "decision": decision}


def _status(client, headers, document_id, path):
    fields = client.get(f"/documents/{document_id}/terms", headers=headers).json()["extraction"]["fields"]
    return next(f["status"] for f in fields if f["path"] == path)


def test_two_guests_see_their_own_queue_terms_and_timeline(demo, client, db_session, tenant_id):
    version, run = _run(db_session, tenant_id)
    a, b = _guest(client), _guest(client)
    decided = client.post("/reviews", headers=a, json=_body(run, "termination_notice_days", "confirmed"))
    assert decided.status_code == 201 and decided.json()["decided_by"] == "you (demo)"

    assert [r["field_path"] for r in client.get("/reviews", headers=a).json()] == ["fee_method"]
    assert [r["field_path"] for r in client.get("/reviews", headers=b).json()] == ["fee_method", "termination_notice_days"]
    assert _status(client, a, version.document_id, "termination_notice_days") == "confirmed"
    assert _status(client, b, version.document_id, "termination_notice_days") == "needs_review"
    timeline = f"/documents/{version.document_id}/timeline"
    assert "reviewed" in [i["kind"] for i in client.get(timeline, headers=a).json()]
    assert "reviewed" not in [i["kind"] for i in client.get(timeline, headers=b).json()]
    assert db_session.get(FieldReview, (run.id, "termination_notice_days")) is None


def test_a_demo_decision_without_a_known_guest_is_refused(demo, client, db_session, tenant_id):
    _, run = _run(db_session, tenant_id)
    for headers in ({}, {"X-Guest-Id": str(uuid.uuid4())}, {"X-Guest-Id": "not-a-uuid"}):
        response = client.post("/reviews", headers=headers, json=_body(run, "fee_method", "confirmed"))
        assert response.status_code == 400 and response.json()["type"] == "/problems/guest-required"
    assert client.get("/reviews", headers={"X-Guest-Id": str(uuid.uuid4())}).status_code == 200  # reads fall back
    assert db_session.get(FieldReview, (run.id, "fee_method")) is None


def test_turning_demo_mode_off_ignores_the_overlays(client, db_session, tenant_id, monkeypatch):
    version, run = _run(db_session, tenant_id)
    monkeypatch.setattr(config, "DEMO_MODE", True)
    a = _guest(client)
    assert client.post("/reviews", headers=a, json=_body(run, "termination_notice_days", "confirmed")).status_code == 201
    monkeypatch.setattr(config, "DEMO_MODE", False)
    assert [r["field_path"] for r in client.get("/reviews", headers=a).json()] == ["fee_method", "termination_notice_days"]
    assert _status(client, a, version.document_id, "termination_notice_days") == "needs_review"


def test_the_agent_compares_billing_with_the_guests_own_decisions(db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    document_id = _contract(db_session, tenant_id, scenario.household_id, tier_routing=FieldRouting.needs_review)
    a = assistant_dao.register_guest(db_session, tenant_id, None)
    b = assistant_dao.register_guest(db_session, tenant_id, None)
    view = dao.terms_view(db_session, tenant_id, document_id, date.today())
    for field in (f for f in view.fields if f.status == "needs_review"):
        dao.record_review(db_session, tenant_id=tenant_id, run_id=view.run_id, field_path=field.path,
                          decision=ReviewDecision.confirmed, corrected_value=None, reason=None, decided_by="x", overlay_guest=a)

    def compare(guest):
        ctx = ToolContext(session=db_session, tenant_id=tenant_id, session_id="s", turn_id=uuid.uuid4(),
                          embeddings=RecordingEmbeddings(), vector_index=InMemoryVectorIndex(),
                          model=ModelConfig("fake", "scripted", "p", 0), hmac_key=config.PII_HMAC_KEY,
                          vault_key=config.PII_VAULT_KEY, overlay_guest=guest)
        return execute(TOOLS["compare_contract_to_billing"], ctx, {"document_id": str(document_id), "as_of": "2026-09-30"})

    assert compare(a).result_amount_minor == 40_000  # guest A validated the tiers: comparable, 0.05% gap on tier 2
    assert compare(b).system_notice is not None and "fee_tiers" in compare(b).system_notice  # guest B did not
```

  Also, in `backend/tests/test_demo_mode.py`, the review route is no longer closed after this task: in `test_decisions_are_closed_in_demo_mode_until_their_overlay_exists`, **delete the two lines** that post to `/reviews` and assert on `review` (keep the tool-decision assertion, which Task 7 removes).

- [ ] **Step 2: Run them and confirm they fail** — `/home/niki/Documents/workenv/pydev/bin/pytest tests/test_guest_reviews_api.py -q`. Expected: failures (403 `decisions-closed-in-demo` on `POST /reviews`, and `TypeError` for `overlay_guest` in `ToolContext`).

- [ ] **Step 3: Review routes** — in `backend/app/routes/reviews.py`:
  - change the deps import to `from app.deps import decided_by, get_guest_id, get_overlay_guest, get_session, get_tenant_id, require_overlay_guest` (remove `decisions_closed_in_demo`);
  - after `TenantDep = ...` add `OverlayGuest = Annotated[uuid.UUID | None, Depends(get_overlay_guest)]`;
  - `list_pending_reviews` becomes `def list_pending_reviews(session: SessionDep, tenant_id: TenantDep, overlay_guest: OverlayGuest) -> list[ReviewItemOut]:` and calls `contracts_dao.pending_reviews(session, tenant_id, overlay_guest)`;
  - `submit_review`: decorator back to `@router.post("", status_code=201, response_model=ReviewOut)`; add the parameter `overlay_guest: Annotated[uuid.UUID | None, Depends(require_overlay_guest)]` after `guest_id`; pass `overlay_guest=overlay_guest` to `contracts_dao.record_review(...)`. The response construction stays as it is (a guest review has the same attributes).

- [ ] **Step 4: Terms and timeline routes.**
  - `backend/app/routes/contract_terms.py`: change the deps import to `from app.deps import get_overlay_guest, get_session, get_tenant_id`; add the parameter `overlay_guest: Annotated[uuid.UUID | None, Depends(get_overlay_guest)]` to `get_terms`; call `contracts_dao.terms_view(session, tenant_id, document_id, date.today(), overlay_guest)`.
  - `backend/app/routes/document_timeline.py`: same import change; add the same parameter to `get_timeline`; call `document_timeline(session, tenant_id, document_id, overlay_guest)`.
  - `backend/app/reporting/timeline.py`: signature becomes `def document_timeline(session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID, overlay_guest: uuid.UUID | None = None) -> list[TimelineItem] | None:` and the loop header becomes `for run, reviews in contracts_dao.runs_with_reviews(session, document_id, overlay_guest):`. (The governance part changes in Task 7.)

- [ ] **Step 5: Billing comparison** — in `backend/app/contracts/compare.py`, `compare_contract_to_billing` gets `overlay_guest: uuid.UUID | None = None` as its last keyword parameter, and its call becomes `served = dao.served_fields(session, tenant_id, document_id, overlay_guest)`.

- [ ] **Step 6: The agent carries the guest.**
  - `backend/app/assistant/tools.py`: in `class ToolContext`, after `document_id: ...`, add `overlay_guest: uuid.UUID | None = None  # public demo: this guest's own decisions apply (spec P2+P9)`.
  - `backend/app/assistant/contract_tools.py`: `_get_contract_fields` calls `contracts_dao.served_fields(ctx.session, ctx.tenant_id, args.document_id, ctx.overlay_guest)`; `_compare` calls `compare_contract_to_billing(ctx.session, tenant_id=ctx.tenant_id, document_id=args.document_id, as_of=args.as_of, overlay_guest=ctx.overlay_guest)`.
  - `backend/app/assistant/service.py`:
    - `_unvalidated_events` gets a fourth parameter `overlay_guest: uuid.UUID | None` and calls `contracts_dao.terms_view(session, tenant_id, uuid.UUID(document_id), date.today(), overlay_guest)`;
    - `run_turn` gets `overlay_guest: uuid.UUID | None = None` after `document_id: uuid.UUID | None = None`;
    - the `ToolContext(...)` call gains `overlay_guest=overlay_guest` after `document_id=document_id`;
    - the call `_unvalidated_events(session, tenant_id, state.get("unvalidated", []))` becomes `_unvalidated_events(session, tenant_id, state.get("unvalidated", []), overlay_guest)`.
  - `backend/app/routes/chat.py`: change the deps import to `from app.deps import get_guest_id, get_overlay_guest, get_tenant_id`; add the parameter `overlay_guest: Annotated[uuid.UUID | None, Depends(get_overlay_guest)]` after `guest_id` in `chat`; pass `overlay_guest=overlay_guest` to `run_turn(...)`.

- [ ] **Step 7: Run the tests** — `/home/niki/Documents/workenv/pydev/bin/pytest tests/test_guest_reviews_api.py tests/test_demo_mode.py -q` → all pass; full suite → no failures.

- [ ] **Step 8: Commit** — `git add backend/app/routes/reviews.py backend/app/routes/contract_terms.py backend/app/routes/document_timeline.py backend/app/reporting/timeline.py backend/app/contracts/compare.py backend/app/assistant/tools.py backend/app/assistant/contract_tools.py backend/app/assistant/service.py backend/app/routes/chat.py backend/tests/test_demo_mode.py backend/tests/test_guest_reviews_api.py`, check the staged stat (11 files), then
`git commit -m "feat(api): demo guests review fields in their own overlay, and the agent answers with it"`.

**REVIEW CHECKPOINT 5.**

---

## M4 — Phase 2: approvals

### Task 6: Read-only posting check and the governance overlay

**Files:**
- Modify: `backend/app/ledger/dao.py`, `backend/app/governance/dao.py`
- Create: `backend/tests/test_guest_decisions.py`

**Interfaces:**
- Consumes: `GuestToolDecision`, `ToolInvocationDecision.recorded` (Task 3).
- Produces:
  - `ledger.dao.check_posting(session, request: PostingRequest) -> None` (raises `PostingInvalid`, writes nothing).
  - `governance.dao.Decision = ToolInvocationDecision | GuestToolDecision`.
  - `overlay_guest: uuid.UUID | None = None` on `list_invocations(..., overlay_guest=None) -> list[tuple[ToolInvocation, Decision | None]]`, `invocations_for_document(session, tenant_id, document_id, overlay_guest=None)`, `count_pending(session, tenant_id, overlay_guest=None)`, `decide(..., overlay_guest=None) -> Decision`.
  - A guest's proposals are those whose `input["guest_id"] == str(guest_id)` (Task 7 records it).

- [ ] **Step 1: Write the failing tests** — create `backend/tests/test_guest_decisions.py`:

```python
import dataclasses
import uuid

import pytest
from sqlalchemy import func, select

from app.assistant import dao as assistant_dao
from app.demo import GUEST_DECIDED_BY
from app.governance.dao import (InvocationRecord, count_pending, decide, invocations_for_document, list_invocations,
                                record_invocation)
from app.governance.errors import AlreadyDecided, InvocationNotFound
from app.governance.models import ToolInvocationDecision
from app.governance.types import ToolDecision
from app.ledger.dao import EntryInput, PostingRequest, check_posting
from app.ledger.errors import PostingInvalid
from app.ledger.models import Posting
from app.ledger.types import Direction
from tests.test_governance import MODEL, accounts  # noqa: F401  (accounts is a fixture)

DOCUMENT = uuid.uuid4()


def _guest(db_session, tenant_id):
    return assistant_dao.register_guest(db_session, tenant_id, None)


def _propose(db_session, tenant_id, accounts, guest, *, amount=40_000, credit_amount=None):
    receivable, income = accounts
    return record_invocation(db_session, InvocationRecord(
        tenant_id=tenant_id, session_id="ses_demo", tool_name="compare_contract_to_billing", tool_version="1.0.0",
        model=MODEL, input={"document_id": str(DOCUMENT), "guest_id": str(guest)},
        result_amount_minor=amount, result_currency="CAD",
        proposed_entries=(EntryInput(receivable.id, Direction.debit, amount),
                          EntryInput(income.id, Direction.credit, amount if credit_amount is None else credit_amount)),
    ))


def _postings(db_session, tenant_id) -> int:
    return db_session.scalar(select(func.count()).select_from(Posting).where(Posting.tenant_id == tenant_id))


def _decide(db_session, tenant_id, invocation, decision, guest):
    return decide(db_session, tenant_id=tenant_id, invocation_id=invocation.id, decision=decision,
                  decided_by="guest:x", reason=None, overlay_guest=guest)


def test_check_posting_runs_the_ledger_validation_without_writing(db_session, tenant_id, accounts):
    receivable, income = accounts
    balanced = PostingRequest(tenant_id=tenant_id, idempotency_key="check-1", entries=(
        EntryInput(receivable.id, Direction.debit, 500), EntryInput(income.id, Direction.credit, 500)))
    check_posting(db_session, balanced)
    unbalanced = dataclasses.replace(balanced, entries=(
        EntryInput(receivable.id, Direction.debit, 500), EntryInput(income.id, Direction.credit, 400)))
    with pytest.raises(PostingInvalid, match="balance"):
        check_posting(db_session, unbalanced)
    assert _postings(db_session, tenant_id) == 0


def test_a_guest_approval_is_checked_and_kept_for_that_guest_only(db_session, tenant_id, accounts):
    a = _guest(db_session, tenant_id)
    invocation = _propose(db_session, tenant_id, accounts, a)
    assert count_pending(db_session, tenant_id, overlay_guest=a) == 1

    decision = _decide(db_session, tenant_id, invocation, ToolDecision.approved, a)
    assert (decision.recorded, decision.posting_id, decision.decided_by) == (False, None, GUEST_DECIDED_BY)
    assert _postings(db_session, tenant_id) == 0
    assert db_session.get(ToolInvocationDecision, invocation.id) is None
    [(_, seen)] = list_invocations(db_session, tenant_id=tenant_id, overlay_guest=a)
    assert seen.decision is ToolDecision.approved
    assert count_pending(db_session, tenant_id, overlay_guest=a) == 0
    [(_, real)] = list_invocations(db_session, tenant_id=tenant_id)
    assert real is None  # the real decision table is untouched
    assert [(i.id, d.decision) for i, d in invocations_for_document(db_session, tenant_id, DOCUMENT, overlay_guest=a)] == [
        (invocation.id, ToolDecision.approved)]


def test_a_guest_cannot_see_or_decide_another_guests_proposal(db_session, tenant_id, accounts):
    a, b = _guest(db_session, tenant_id), _guest(db_session, tenant_id)
    invocation = _propose(db_session, tenant_id, accounts, a)
    with pytest.raises(InvocationNotFound):
        _decide(db_session, tenant_id, invocation, ToolDecision.approved, b)
    assert list_invocations(db_session, tenant_id=tenant_id, overlay_guest=b) == []
    assert invocations_for_document(db_session, tenant_id, DOCUMENT, overlay_guest=b) == []
    assert count_pending(db_session, tenant_id, overlay_guest=b) == 0


def test_an_invalid_proposal_is_refused_and_leaves_no_decision(db_session, tenant_id, accounts):
    a = _guest(db_session, tenant_id)
    invocation = _propose(db_session, tenant_id, accounts, a, credit_amount=39_999)
    with pytest.raises(PostingInvalid):
        _decide(db_session, tenant_id, invocation, ToolDecision.approved, a)
    [(_, decision)] = list_invocations(db_session, tenant_id=tenant_id, overlay_guest=a)
    assert decision is None


def test_guest_decisions_are_final(db_session, tenant_id, accounts):
    a = _guest(db_session, tenant_id)
    invocation = _propose(db_session, tenant_id, accounts, a)
    _decide(db_session, tenant_id, invocation, ToolDecision.rejected, a)
    with pytest.raises(AlreadyDecided):
        _decide(db_session, tenant_id, invocation, ToolDecision.approved, a)
```

- [ ] **Step 2: Run them and confirm they fail** — `/home/niki/Documents/workenv/pydev/bin/pytest tests/test_guest_decisions.py -q`. Expected: `ImportError: cannot import name 'check_posting'`.

- [ ] **Step 3: `check_posting`** — in `backend/app/ledger/dao.py`, directly before `def create_posting(`, add:

```python
def check_posting(session: Session, request: PostingRequest) -> None:
    """Run create_posting's own validation and write nothing: the public demo's approvals (spec D3).
    Raises PostingInvalid exactly as create_posting would; the database's balance trigger is not exercised."""
    _validate(request, _accounts_by_id(session, request))
```

- [ ] **Step 4: The governance overlay** — in `backend/app/governance/dao.py`:
  - imports: `from sqlalchemy import ColumnElement, func, select`; `from app.governance.models import GuestToolDecision, ToolInvocation, ToolInvocationDecision`; `from app.ledger.dao import EntryInput, PostingRequest, check_posting, create_posting, ledger_transaction`.
  - directly after `_entries_from_json`, add:

```python


# A real decision, or a demo guest's own (spec P2+P9). Both expose invocation_id, decision, decided_by, reason,
# decided_at, posting_id and recorded.
Decision = ToolInvocationDecision | GuestToolDecision


def _decisions_join(overlay_guest: uuid.UUID | None
                    ) -> tuple[type[ToolInvocationDecision] | type[GuestToolDecision], ColumnElement[bool]]:
    """The decision table a reader outer-joins: the real one, or this guest's overlay rows."""
    if overlay_guest is None:
        return ToolInvocationDecision, ToolInvocationDecision.invocation_id == ToolInvocation.id
    return GuestToolDecision, (GuestToolDecision.invocation_id == ToolInvocation.id) & (GuestToolDecision.guest_id == overlay_guest)


def _of_guest(guest_id: uuid.UUID) -> ColumnElement[bool]:
    """Proposals from this guest's own chats: in demo mode the tool runner records the guest in the input."""
    return ToolInvocation.input["guest_id"].astext == str(guest_id)


def _posting_request(invocation: ToolInvocation) -> PostingRequest:
    return PostingRequest(
        tenant_id=invocation.tenant_id,
        idempotency_key=f"ai:{invocation.id}",
        entries=_entries_from_json(invocation.proposed_entries),
        description=f"Approved {invocation.tool_name} result ({invocation.id})",
        source=PostingSource.ai_tool,
    )
```

  - replace `list_invocations` with:

```python
def list_invocations(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    posting_id: uuid.UUID | None = None,
    pending: bool | None = None,
    limit: int = 50,
    session_id: str | None = None,
    overlay_guest: uuid.UUID | None = None,
) -> list[tuple[ToolInvocation, Decision | None]]:
    if posting_id is not None:
        overlay_guest = None  # the provenance of a real posting always reads the real decision
    decisions, joined = _decisions_join(overlay_guest)
    query = select(ToolInvocation, decisions).outerjoin(decisions, joined).where(ToolInvocation.tenant_id == tenant_id)
    if overlay_guest is not None:
        query = query.where(_of_guest(overlay_guest))
    if posting_id is not None:
        query = query.where(ToolInvocationDecision.posting_id == posting_id)
    if pending is True:
        query = query.where(ToolInvocation.approval_required.is_(True), decisions.invocation_id.is_(None))
    elif pending is False:
        query = query.where(decisions.invocation_id.is_not(None))
    if session_id is not None:
        query = query.where(ToolInvocation.session_id == session_id)
    query = query.order_by(ToolInvocation.created_at.desc(), ToolInvocation.id.desc()).limit(limit)
    return [(invocation, decision) for invocation, decision in session.execute(query)]
```

  - replace `invocations_for_document` with:

```python
def invocations_for_document(session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID,
                             overlay_guest: uuid.UUID | None = None) -> list[tuple[ToolInvocation, Decision | None]]:
    # ponytail: scans tool_invocations by JSONB; add an index on (tenant_id, (input->>'document_id')) when volume grows
    decisions, joined = _decisions_join(overlay_guest)
    query = (
        select(ToolInvocation, decisions)
        .outerjoin(decisions, joined)
        .where(ToolInvocation.tenant_id == tenant_id, ToolInvocation.input["document_id"].astext == str(document_id))
        .order_by(ToolInvocation.created_at)
    )
    if overlay_guest is not None:
        query = query.where(_of_guest(overlay_guest))
    return [(i, d) for i, d in session.execute(query)]
```

  - in `decide`: add `overlay_guest: uuid.UUID | None = None,` as the last keyword parameter and change the return annotation to `-> Decision`; change the first check to

```python
    invocation = session.get(ToolInvocation, invocation_id)
    if invocation is None or invocation.tenant_id != tenant_id or (
        overlay_guest is not None and invocation.input.get("guest_id") != str(overlay_guest)
    ):  # another guest's proposal is reported as missing, never as existing
        raise InvocationNotFound(f"Tool invocation {invocation_id} does not exist.")
    if not invocation.approval_required:
        raise NotCritical(f"Tool invocation {invocation_id} proposed no ledger posting.")
    if overlay_guest is not None:
        return _decide_as_guest(session, invocation, decision=decision, reason=reason, guest_id=overlay_guest)
```

    keep the existing `AlreadyDecided` check and real path after it, but replace its inline `PostingRequest(...)` argument with `_posting_request(invocation)`.
  - add after `decide`:

```python


def _decide_as_guest(session: Session, invocation: ToolInvocation, *, decision: ToolDecision, reason: str | None,
                     guest_id: uuid.UUID) -> GuestToolDecision:
    """Demo mode: the ledger's own validation runs, nothing is posted, and the decision goes to the guest's overlay."""
    if session.get(GuestToolDecision, (guest_id, invocation.id)) is not None:
        raise AlreadyDecided(f"Tool invocation {invocation.id} has already been decided.")
    if decision is ToolDecision.approved:
        check_posting(session, _posting_request(invocation))
    record = GuestToolDecision(guest_id=guest_id, invocation_id=invocation.id, decision=decision, reason=reason)
    session.add(record)
    try:
        session.commit()
    except IntegrityError as exc:  # a concurrent decision by the same guest won the primary key
        session.rollback()
        raise AlreadyDecided(f"Tool invocation {invocation.id} has already been decided.") from exc
    return record
```

  - replace `count_pending` with:

```python
def count_pending(session: Session, tenant_id: uuid.UUID, overlay_guest: uuid.UUID | None = None) -> int:
    decisions, joined = _decisions_join(overlay_guest)
    query = (
        select(func.count())
        .select_from(ToolInvocation)
        .outerjoin(decisions, joined)
        .where(
            ToolInvocation.tenant_id == tenant_id,
            ToolInvocation.approval_required.is_(True),
            decisions.invocation_id.is_(None),
        )
    )
    if overlay_guest is not None:
        query = query.where(_of_guest(overlay_guest))
    return session.scalar(query) or 0
```

- [ ] **Step 5: Run the tests** — `/home/niki/Documents/workenv/pydev/bin/pytest tests/test_guest_decisions.py tests/test_governance.py -q` → all pass; full suite → no failures.

- [ ] **Step 6: Commit** — `git add backend/app/ledger/dao.py backend/app/governance/dao.py backend/tests/test_guest_decisions.py`, check the staged stat, then
`git commit -m "feat(governance): demo guests decide proposals in their own overlay, checked by the ledger"`.

**REVIEW CHECKPOINT 6.**

---

### Task 7: Approval overlay through the routes, timeline and dashboard; remove the M1 guard

**Files:**
- Modify: `backend/app/assistant/tools.py`, `backend/app/routes/tool_invocations.py`, `backend/app/reporting/timeline.py`, `backend/app/reporting/dashboard.py`, `backend/app/routes/stats.py`, `backend/app/deps.py`, `backend/app/errors.py`, `backend/tests/test_demo_mode.py`
- Create: `backend/tests/test_guest_decisions_api.py`

**Interfaces:**
- Consumes: Task 6's `overlay_guest` parameters and `Decision`; `ToolContext.overlay_guest` (Task 5).
- Produces: `DecisionOut.recorded: bool`; timeline "decided" items carry `detail["recorded"]`; `reporting.dashboard.with_guest_queues(stats, session, tenant_id, overlay_guest) -> DashboardStats`.

- [ ] **Step 1: Write the failing tests** — create `backend/tests/test_guest_decisions_api.py`:

```python
import uuid

import pytest

from app import config
from app.assistant.contract_tools import contract_tools
from app.assistant.tools import ToolContext, execute
from app.governance.dao import ModelConfig
from app.governance.models import ToolInvocation
from app.reporting import dashboard
from app.retrieval.vector_index import InMemoryVectorIndex
from sqlalchemy import select
from tests.fakes import RecordingEmbeddings
from tests.support import build_fee_scenario
from tests.test_contracts_compare import _contract
from tests.test_governance import accounts  # noqa: F401  (accounts is a fixture)
from tests.test_guest_decisions import _propose

TOOLS = {spec.name: spec for spec in contract_tools()}


@pytest.fixture()
def demo(monkeypatch):
    monkeypatch.setattr(config, "DEMO_MODE", True)
    dashboard._cache.clear()
    yield
    dashboard._cache.clear()


def _guest(client) -> dict[str, str]:
    return {"X-Guest-Id": client.post("/guests").json()["id"]}


def _compare_as(db_session, tenant_id, document_id, guest):
    ctx = ToolContext(session=db_session, tenant_id=tenant_id, session_id="s", turn_id=uuid.uuid4(),
                      embeddings=RecordingEmbeddings(), vector_index=InMemoryVectorIndex(),
                      model=ModelConfig("fake", "scripted", "p", 0), hmac_key=config.PII_HMAC_KEY,
                      vault_key=config.PII_VAULT_KEY, overlay_guest=guest)
    return execute(TOOLS["compare_contract_to_billing"], ctx, {"document_id": str(document_id), "as_of": "2026-09-30"})


def test_the_tool_runner_records_the_guest_only_in_demo_mode(db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    document_id = _contract(db_session, tenant_id, scenario.household_id)
    guest = uuid.uuid4()
    _compare_as(db_session, tenant_id, document_id, guest)
    _compare_as(db_session, tenant_id, document_id, None)
    inputs = [i.input for i in db_session.scalars(select(ToolInvocation).where(ToolInvocation.tenant_id == tenant_id))]
    assert sorted(i.get("guest_id", "") for i in inputs) == ["", str(guest)]  # one per call, in either order


def test_a_demo_approval_is_not_recorded_and_stays_with_the_guest(demo, client, db_session, tenant_id, accounts):
    a, b = _guest(client), _guest(client)
    invocation = _propose(db_session, tenant_id, accounts, uuid.UUID(a["X-Guest-Id"]))
    assert client.get("/stats", headers=a).json()["approvals_pending"] == 1
    assert client.get("/stats", headers=b).json()["approvals_pending"] == 0

    response = client.post(f"/tool-invocations/{invocation.id}/decision", headers=a, json={"decision": "approved"})
    assert response.status_code == 201
    body = response.json()
    assert (body["recorded"], body["posting_id"], body["decided_by"]) == (False, None, "you (demo)")
    assert [i["decision"]["recorded"] for i in client.get("/tool-invocations", headers=a).json()] == [False]
    assert client.get("/tool-invocations", headers=b).json() == []
    assert client.post(f"/tool-invocations/{invocation.id}/decision", headers=b, json={"decision": "approved"}).status_code == 404
    assert client.get("/stats", headers=a).json()["approvals_pending"] == 0


def test_the_guests_timeline_shows_an_unrecorded_approval_and_no_posting(demo, client, db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    document_id = _contract(db_session, tenant_id, scenario.household_id)
    a = _guest(client)
    _compare_as(db_session, tenant_id, document_id, uuid.UUID(a["X-Guest-Id"]))
    invocation_id = db_session.scalars(select(ToolInvocation.id).where(ToolInvocation.tenant_id == tenant_id)).one()
    assert client.post(f"/tool-invocations/{invocation_id}/decision", headers=a, json={"decision": "approved"}).status_code == 201
    items = client.get(f"/documents/{document_id}/timeline", headers=a).json()
    decided = next(i for i in items if i["kind"] == "decided")
    assert decided["detail"]["recorded"] is False and decided["title"] == "approved by you (demo)"
    assert "posted" not in [i["kind"] for i in items]


def test_outside_demo_mode_an_approval_is_recorded(client, db_session, tenant_id, accounts):
    invocation = _propose(db_session, tenant_id, accounts, uuid.uuid4())
    body = client.post(f"/tool-invocations/{invocation.id}/decision", json={"decision": "approved"}).json()
    assert body["recorded"] is True and body["posting_id"] is not None
```

  In `backend/tests/test_demo_mode.py`, **delete the whole test** `test_decisions_are_closed_in_demo_mode_until_their_overlay_exists` (the guard it tests is removed in Step 6).

- [ ] **Step 2: Run them and confirm they fail** — `/home/niki/Documents/workenv/pydev/bin/pytest tests/test_guest_decisions_api.py -q`. Expected: failures (no `guest_id` in the recorded input, 403 on the decision route, no `recorded` field).

- [ ] **Step 3: Record the guest on the proposal** — in `backend/app/assistant/tools.py`, inside `execute`, change the `input=` argument of `InvocationRecord(...)` to:

```python
        model=ctx.model, input={
            "turn_id": str(ctx.turn_id),
            # public demo: whose chat produced this proposal (spec P2+P9); absent outside the demo
            **({"guest_id": str(ctx.overlay_guest)} if ctx.overlay_guest is not None else {}),
            **parsed.model_dump(mode="json"),
        },
```

- [ ] **Step 4: Tool-invocation routes** — in `backend/app/routes/tool_invocations.py`:
  - imports: `from app.deps import decided_by, get_guest_id, get_overlay_guest, get_session, get_tenant_id, require_overlay_guest` (remove `decisions_closed_in_demo`); `from app.governance.dao import Decision, decide, list_invocations`; remove `ToolInvocationDecision` from the models import only if nothing else in the file uses it (keep `ToolInvocation`).
  - `class DecisionOut`: add `recorded: bool` after `posting_id`.
  - `_decision_out(decision: Decision) -> DecisionOut`: add `recorded=decision.recorded` to the constructor call.
  - `_invocation_out(session: Session, invocation: ToolInvocation, decision: Decision | None) -> InvocationOut` (annotation only).
  - `list_tool_invocations`: add the parameter `overlay_guest: Annotated[uuid.UUID | None, Depends(get_overlay_guest)]` and pass `overlay_guest=overlay_guest` to `list_invocations(...)`.
  - `decide_tool_invocation`: decorator back to `@router.post("/{invocation_id}/decision", status_code=201, response_model=DecisionOut)`; add the parameter `overlay_guest: Annotated[uuid.UUID | None, Depends(require_overlay_guest)]`; pass `overlay_guest=overlay_guest` to `decide(...)`.

- [ ] **Step 5: Timeline and dashboard.**
  - `backend/app/reporting/timeline.py`: the loop header becomes `for invocation, decision in governance_dao.invocations_for_document(session, tenant_id, document_id, overlay_guest):` and the "decided" item's detail becomes `{"reason": decision.reason, "recorded": decision.recorded}`.
  - `backend/app/reporting/dashboard.py`: add `import dataclasses` to the imports, and after `invalidate_dashboard_stats` add:

```python


def with_guest_queues(stats: DashboardStats, session: Session, tenant_id: uuid.UUID,
                      overlay_guest: uuid.UUID | None) -> DashboardStats:
    """Public demo: the cached aggregates stay shared; the two work queues are this guest's own."""
    if overlay_guest is None:
        return stats
    return dataclasses.replace(
        stats,
        reviews_pending=len(contracts_dao.pending_reviews(session, tenant_id, overlay_guest)),
        approvals_pending=governance_dao.count_pending(session, tenant_id, overlay_guest),
    )
```

    (`contracts_dao` and `governance_dao` are already imported in `dashboard.py`; if either is not, add `from app.contracts import dao as contracts_dao` / `from app.governance import dao as governance_dao`.)
  - `backend/app/routes/stats.py`: import `get_overlay_guest` from `app.deps` and `with_guest_queues` from `app.reporting.dashboard`; `get_stats` gets the parameter `overlay_guest: Annotated[uuid.UUID | None, Depends(get_overlay_guest)]` (before `if_none_match`), and its first line becomes `s = with_guest_queues(cached_dashboard_stats(session, tenant_id), session, tenant_id, overlay_guest)`.

- [ ] **Step 6: Remove the M1 guard** — delete `decisions_closed_in_demo` (and its now-unused `DecisionsClosed` import) from `backend/app/deps.py`, and delete `class DecisionsClosed` from `backend/app/errors.py`. Then `grep -rn "decisions_closed_in_demo\|DecisionsClosed" backend/` must print nothing.

- [ ] **Step 7: Run the tests** — `/home/niki/Documents/workenv/pydev/bin/pytest tests/test_guest_decisions_api.py tests/test_demo_mode.py tests/test_governance.py tests/test_document_timeline.py tests/test_stats_api.py -q` → all pass; full suite → no failures.

- [ ] **Step 8: Commit** — `git add backend/app/assistant/tools.py backend/app/routes/tool_invocations.py backend/app/reporting/timeline.py backend/app/reporting/dashboard.py backend/app/routes/stats.py backend/app/deps.py backend/app/errors.py backend/tests/test_demo_mode.py backend/tests/test_guest_decisions_api.py`, check the staged stat (9 files), then
`git commit -m "feat(api): demo approvals are checked, not recorded, and shown only to the guest"`.

**REVIEW CHECKPOINT 7.**

---

### Task 8: Frontend labels for demo decisions, and the guest's demo postings

**Files:**
- Create: `frontend/src/components/DemoPostings.tsx`
- Modify: `frontend/src/api.ts`, `frontend/src/components/ApprovalCard.tsx`, `frontend/src/screens/Ledger.tsx`, `frontend/src/components/workspace/LedgerTimeline.tsx`

**Interfaces:**
- Consumes: `DecisionOut.recorded`, timeline `detail.recorded` (Task 7); `useDemoMode` (Task 2).

- [ ] **Step 1: Types** — in `frontend/src/api.ts`: add `recorded: boolean;` to `export interface ToolDecisionDto` (after `posting_id`); in `TimelineItemDto`, change the `detail` type to
  `detail: { entries?: { account: string; direction: 'debit' | 'credit'; amount_minor: number; currency: string }[]; recorded?: boolean } & Record<string, unknown>;`

- [ ] **Step 2: Approval card** — in `frontend/src/components/ApprovalCard.tsx`: import `useDemoMode` from `'../lib/useDemoMode'`; add `const demoMode = useDemoMode();` as the first line of `ApprovalCard`; in the undecided branch change the approve button label to `{demoMode ? 'Approve (demo, not recorded)' : 'Approve and post'}` and the help text to `{demoMode ? 'The ledger checks these entries; in the public demo nothing is written.' : 'Approving posts exactly these entries to the ledger, once.'}`; replace the decided branch

```tsx
        ) : decision.posting_id ? (
          <span className="tool-card__posted">
            Posted · <Link to={`/ledger?posting=${decision.posting_id}`}>View in ledger →</Link>
          </span>
        ) : (
          <span className="tool-card__help">Rejected by {decision.decided_by}. Nothing was posted.</span>
        )}
```

  with

```tsx
        ) : decision.posting_id ? (
          <span className="tool-card__posted">
            Posted · <Link to={`/ledger?posting=${decision.posting_id}`}>View in ledger →</Link>
          </span>
        ) : decision.decision === 'approved' && !decision.recorded ? (
          <span className="tool-card__help">Demo posting, not recorded. The ledger checked these entries; nothing was written.</span>
        ) : (
          <span className="tool-card__help">Rejected by {decision.decided_by}. Nothing was posted.</span>
        )}
```

- [ ] **Step 3: The guest's demo postings** — create `frontend/src/components/DemoPostings.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { type ToolInvocationDto, listToolInvocations } from '../api';
import { formatMinor } from '../lib/money';
import { formatUtc } from '../lib/time';
import { toolLabel } from '../lib/toolLabels';

/** Public demo: this guest's approved AI postings, checked by the ledger but never recorded (spec P2+P9, D3). */
export function DemoPostings() {
  const [approved, setApproved] = useState<ToolInvocationDto[]>([]);

  useEffect(() => {
    let cancelled = false;
    listToolInvocations({ pending: false, limit: 200 })
      .then((rows) => {
        if (!cancelled) setApproved(rows.filter((i) => i.decision?.decision === 'approved' && !i.decision.recorded));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  if (approved.length === 0) return null;
  return (
    <section className="panel ledger__demo-postings" aria-label="Your demo postings">
      <div className="ledger__detail-section-head">
        <span>Your demo postings (not recorded)</span>
      </div>
      <p className="ledger__help">
        The ledger checked these entries when you approved them. In the public demo nothing is written, and only you see them.
      </p>
      {approved.map((invocation) => (
        <table key={invocation.id} className="ledger__journal">
          <caption>
            {toolLabel(invocation.tool_name)} · approved {invocation.decision ? formatUtc(invocation.decision.decided_at) : ''}
          </caption>
          <thead>
            <tr>
              <th>Account</th>
              <th className="num">Debit</th>
              <th className="num">Credit</th>
            </tr>
          </thead>
          <tbody>
            {(invocation.proposed_entries ?? []).map((entry, index) => (
              <tr key={index}>
                <td>{entry.account_name}</td>
                <td className="num mono">{entry.direction === 'debit' ? formatMinor(entry.amount, entry.currency) : '—'}</td>
                <td className="num mono">{entry.direction === 'credit' ? formatMinor(entry.amount, entry.currency) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ))}
    </section>
  );
}
```

  In `frontend/src/screens/Ledger.tsx`: import `DemoPostings` from `'../components/DemoPostings'`, and render `{demoMode && <DemoPostings />}` directly after the closing `</div>` of the `ledger__header` block. In `frontend/src/screens/Ledger.css`, append:

```css
.ledger__demo-postings { padding: var(--space-4); margin-bottom: var(--space-4); }
.ledger__demo-postings caption { text-align: left; padding: var(--space-2) 0; }
```

  (If `--space-2` or `--space-4` is not defined in `frontend/src/index.css`, use the nearest existing `--space-*` tokens instead; do not invent new ones.)

- [ ] **Step 4: Timeline label** — in `frontend/src/components/workspace/LedgerTimeline.tsx`, directly after the `<div className="ws-reason">{new Date(item.at).toLocaleString()}</div>` line, add:

```tsx
            {item.kind === 'decided' && item.detail.recorded === false && (
              <div className="ws-reason">Demo decision, not recorded</div>
            )}
```

- [ ] **Step 5: Verify** — from `frontend/`: `npm test` (only the known pre-existing failure), `npm run build`, `npm run lint` (no new warnings or errors).

- [ ] **Step 6: Commit** — `git add frontend/src/api.ts frontend/src/components/ApprovalCard.tsx frontend/src/components/DemoPostings.tsx frontend/src/screens/Ledger.tsx frontend/src/screens/Ledger.css frontend/src/components/workspace/LedgerTimeline.tsx`, check the staged stat, then
`git commit -m "feat(frontend): label demo decisions and list the guest's demo postings"`.

**REVIEW CHECKPOINT 8.**

---

## M5 — Purge

### Task 9: The 24-hour overlay purge

**Files:**
- Create: `backend/app/assistant/overlays.py`, `backend/tests/test_overlay_purge.py`
- Modify: `backend/app/assistant/dao.py`, `backend/app/contracts/dao.py`, `backend/app/governance/dao.py`, `backend/app/routes/guests.py`

**Interfaces:**
- Produces: `assistant.dao.stale_guest_ids(session, tenant_id, *, before: datetime) -> list[uuid.UUID]`; `contracts.dao.purge_guest_reviews(session, guest_ids) -> None`; `governance.dao.purge_guest_decisions(session, guest_ids) -> None`; `assistant.overlays.purge_stale_overlays(session, tenant_id, now) -> None`; `assistant.overlays.OVERLAY_TTL = timedelta(hours=24)`.

- [ ] **Step 1: Write the failing test** — create `backend/tests/test_overlay_purge.py`:

```python
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.assistant import dao as assistant_dao
from app.assistant.models import Guest
from app.contracts import dao as contracts_dao
from app.contracts.models import GuestFieldReview
from app.contracts.types import ReviewDecision
from app.governance.dao import decide
from app.governance.models import GuestToolDecision
from app.governance.types import ToolDecision
from tests.test_governance import accounts  # noqa: F401  (accounts is a fixture)
from tests.test_guest_decisions import _propose
from tests.test_reviews_api import _run


def _decide_everything(db_session, tenant_id, accounts, run, guest):
    contracts_dao.record_review(db_session, tenant_id=tenant_id, run_id=run.id, field_path="fee_method",
                                decision=ReviewDecision.rejected, corrected_value=None, reason=None,
                                decided_by="x", overlay_guest=guest)
    invocation = _propose(db_session, tenant_id, accounts, guest)
    decide(db_session, tenant_id=tenant_id, invocation_id=invocation.id, decision=ToolDecision.rejected,
           decided_by="x", reason=None, overlay_guest=guest)


def test_a_new_guest_purges_the_overlays_of_guests_idle_for_24_hours(client, db_session, tenant_id, accounts):
    _, run = _run(db_session, tenant_id)
    idle = assistant_dao.register_guest(db_session, tenant_id, None)
    active = assistant_dao.register_guest(db_session, tenant_id, None)
    _decide_everything(db_session, tenant_id, accounts, run, idle)
    _decide_everything(db_session, tenant_id, accounts, run, active)
    now = datetime.now(timezone.utc)
    db_session.execute(update(Guest).where(Guest.id == idle).values(last_seen_at=now - timedelta(hours=25)))
    db_session.execute(update(Guest).where(Guest.id == active).values(last_seen_at=now - timedelta(hours=1)))
    db_session.commit()

    assert client.post("/guests").status_code == 201

    reviewers = set(db_session.scalars(select(GuestFieldReview.guest_id).where(GuestFieldReview.run_id == run.id)))
    deciders = set(db_session.scalars(select(GuestToolDecision.guest_id).where(GuestToolDecision.guest_id.in_([idle, active]))))
    assert reviewers == {active} and deciders == {active}
    assert db_session.get(Guest, idle) is not None  # the guest row stays: chat turns reference it
```

- [ ] **Step 2: Run it and confirm it fails** — `/home/niki/Documents/workenv/pydev/bin/pytest tests/test_overlay_purge.py -q`. Expected: assertion failure (the idle guest's rows are still there).

- [ ] **Step 3: The three DAO functions.**
  - `backend/app/assistant/dao.py`, append:

```python


def stale_guest_ids(session: Session, tenant_id: uuid.UUID, *, before: datetime) -> list[uuid.UUID]:
    """Guests not seen since `before`. Their overlay decisions are purged; the guest rows stay (chat turns reference them)."""
    return list(session.scalars(select(Guest.id).where(Guest.tenant_id == tenant_id, Guest.last_seen_at < before)))
```

  - `backend/app/contracts/dao.py`: add `delete` to the `from sqlalchemy import func, select` line, and append:

```python


def purge_guest_reviews(session: Session, guest_ids: Sequence[uuid.UUID]) -> None:
    """Delete these guests' overlay reviews (the 24-hour purge). The caller commits."""
    session.execute(delete(GuestFieldReview).where(GuestFieldReview.guest_id.in_(guest_ids)))
```

  - `backend/app/governance/dao.py`: add `delete` to the `from sqlalchemy import ColumnElement, func, select` line, add `from collections.abc import Mapping, Sequence` (extend the existing `Mapping` import), and append:

```python


def purge_guest_decisions(session: Session, guest_ids: Sequence[uuid.UUID]) -> None:
    """Delete these guests' overlay decisions (the 24-hour purge). The caller commits."""
    session.execute(delete(GuestToolDecision).where(GuestToolDecision.guest_id.in_(guest_ids)))
```

- [ ] **Step 4: The purge** — create `backend/app/assistant/overlays.py`:

```python
"""The 24-hour purge of demo guests' overlay decisions (spec P2+P9, D4).

Timing only reclaims storage: overlay rows are invisible to every other guest whenever they are deleted.
It runs when a new guest arrives, so there is no scheduler to deploy or watch."""
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.assistant import dao as assistant_dao
from app.contracts import dao as contracts_dao
from app.governance import dao as governance_dao

OVERLAY_TTL = timedelta(hours=24)


def purge_stale_overlays(session: Session, tenant_id: uuid.UUID, now: datetime) -> None:
    stale = assistant_dao.stale_guest_ids(session, tenant_id, before=now - OVERLAY_TTL)
    if stale:
        contracts_dao.purge_guest_reviews(session, stale)
        governance_dao.purge_guest_decisions(session, stale)
        session.commit()
```

- [ ] **Step 5: Run it on guest registration** — in `backend/app/routes/guests.py`: import `from datetime import datetime, timezone` and `from app.assistant.overlays import purge_stale_overlays`; in `register_guest`, before the `return`, add `purge_stale_overlays(session, tenant_id, datetime.now(timezone.utc))`.

- [ ] **Step 6: Run the tests** — `/home/niki/Documents/workenv/pydev/bin/pytest tests/test_overlay_purge.py tests/test_guests.py -q` → all pass; full suite `/home/niki/Documents/workenv/pydev/bin/pytest -q` → no failures. Then refresh the knowledge graph: from the repository root, `graphify update .`.

- [ ] **Step 7: Commit** — `git add backend/app/assistant/overlays.py backend/app/assistant/dao.py backend/app/contracts/dao.py backend/app/governance/dao.py backend/app/routes/guests.py backend/tests/test_overlay_purge.py` (plus `graphify-out/` files only if `graphify update` changed tracked files; report them), check the staged stat, then
`git commit -m "feat(assistant): purge demo guests' overlay decisions after 24 hours of inactivity"`.

**REVIEW CHECKPOINT 9.**

---

### Task 10: Operator rollout and deployed smoke test (the user, not Gemini)

Run after Claude has reviewed and pushed Tasks 1–9. Order matters (spec §9).

- [ ] **After Task 1–2 are deployed:** Railway API service → Variables: `DEMO_MODE=1`. Check: `curl -s -o /dev/null -w "%{http_code}\n" -X POST https://ledger-lens-production-f77a.up.railway.app/postings -H "Content-Type: application/json" -d '{}'` prints `405`, and `.../fee-runs` prints `404`.
- [ ] **After Task 3 is deployed:** as the Railway superuser (`railway connect postgres`): `CREATE ROLE ledger_demo LOGIN PASSWORD '<strong password>';` (store it in Infisical and `backend/.env.demo` as `LEDGER_DEMO_PASSWORD`). Then run the migration as `ledger_owner` through the public proxy: `cd backend && ALEMBIC_DATABASE_URL='postgresql+psycopg://ledger_owner:<owner-pw>@tokaido.proxy.rlwy.net:54230/railway' $PYDEV/bin/alembic upgrade head`. `DATABASE_URL` stays on `ledger_app` for now.
- [ ] **After Task 9 is deployed:** switch Railway `DATABASE_URL` to `postgresql+psycopg://ledger_demo:<pw>@postgres.railway.internal:5432/railway`. Check `/health/db` is ok.
- [ ] **Deployed smoke test:**
  - two guests with opposite decisions on the same field (browser windows A and B, or `curl` with two `X-Guest-Id` values from `POST /guests`): A confirms, B rejects; `GET /documents/<id>/terms` differs between them; neither sees the other's decision in the review queue;
  - `docker exec -i -e PGPASSWORD='<ledger_demo pw>' fintech-ledger-db psql -h tokaido.proxy.rlwy.net -p 54230 -U ledger_demo -d railway -c "INSERT INTO postings DEFAULT VALUES"` → `permission denied for table postings`;
  - browser on `https://ledgerlens.nknext.dev`: upload is hidden; the Ledger shows no reversal button and the note; ask the Tremblay question, approve the proposal → "Demo posting, not recorded"; the Ledger shows "Your demo postings (not recorded)"; the document timeline shows "Demo decision, not recorded"; the dashboard's pending counts are your own.
- [ ] **Rollback if needed:** `DATABASE_URL` back to `ledger_app`, or `DEMO_MODE` removed. The migration only adds, so it never needs reverting.
- [ ] **Changelog:** tick the P2, P9 phase 1 and P9 phase 2 lines with a dated note (Claude does this after the smoke test passes).

## Definition of done

- Tasks 1–9 committed, each reviewed at its checkpoint; the full backend suite and the frontend build/lint pass after every task.
- Task 10's smoke test passes on the deployed pair, with Railway running as `ledger_demo` and `DEMO_MODE=1`.
