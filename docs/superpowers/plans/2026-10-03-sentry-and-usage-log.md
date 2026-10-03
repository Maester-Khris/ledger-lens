# Sentry error reporting and chat usage log (P6 + P7) Implementation Plan

> **For agentic workers:** The executor is Gemini. Planner and reviewer are Claude. Work one checkpoint at a time. Do not start a checkpoint until the previous one's review has passed. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send backend and browser errors to Sentry without chat text, and record one client-measured time-to-first-byte (TTFB) per chat turn, so the launch metric can be read from the database.

**Architecture:** The API initialises Sentry only when `SENTRY_DSN` is set and scrubs every event before it leaves the process. The browser initialises `@sentry/react` only when `VITE_SENTRY_DSN` is set. The chat stream measures TTFB in the browser and posts it to a new insert-only table, `chat_turn_timing`, keyed by turn. A SQL view, `chat_usage_daily`, computes the cited-answer share and the TTFB figures.

**Tech Stack:** Python 3.11+ / FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL 18, pytest; React + Vite + TypeScript, vitest; `sentry-sdk[fastapi]==2.60.0`, `@sentry/react` (new npm package).

**Spec:** `docs/superpowers/specs/2026-10-03-sentry-and-usage-log-design.md` (amended in commit `4e54ea8`). Where this plan and the spec disagree, the spec wins; stop and report the disagreement.

## Global Constraints

- Branch: `feat/pre-launch-demo`. Never commit to `main` or `preview`. Check with `git branch --show-current` before every commit.
- Stage files explicitly with `git add <file> ...`. Never `git add -A` or `git add .`.
- Commit messages: conventional commits. Do **not** add any `Co-Authored-By` or AI attribution line.
- Python: type hints on every function signature. Dataclasses for input DTOs. SQLAlchemy 2.0: never call `session.begin()`.
- Layering: routes stay thin (parse, call a package function, return). Only `app/assistant/dao.py` touches the database for chat tables. Pure logic in framework-free files.
- Backend tests run with `/home/niki/Documents/workenv/pydev/bin/pytest` from `backend/`. Never create a repo-local `.venv`.
- A new npm package (`@sentry/react`) must be named in the commit body and the PR summary.
- Every new backend dependency goes in `backend/requirements.txt`.
- Do not change the `chat_outcome` enum. Do not change `chat_turns` in any way.
- Do not commit `backend/.env.local`, `frontend/.env.local`, `backend/.env.demo`, `backend/script.demo.sh`, or `backend/script.demo.md`. All are git-ignored.

## Review Focus

These are the inputs most likely to break in use. Each one has a test in the task that owns it.

1. A guest posts timing for another guest's turn → 404, no row written. (Task 4)
2. A second timing post for the same turn → 200, the first value is kept. (Task 4)
3. `ttfb_ms` negative, above 60 000, or not an integer → 422, no row written. (Task 4)
4. A timing post without `X-Guest-Id` → 400 with a problem response, no row written. (Task 4)
5. A chat event with `text` or a question in it never appears in a Sentry event. (Task 2)
6. A turn that ends in an `error` event has no `turn_id`, so the client posts no timing. (Task 7)
7. An aborted stream leaves no timing row and throws no error to the guest. (Task 7)
8. With `SENTRY_DSN` or `VITE_SENTRY_DSN` unset, nothing is initialised and the tests still pass. (Tasks 1, 5)

---

## Checkpoint 0: Baseline

Nothing is changed in this checkpoint. Its only output is a recorded baseline.

- [ ] **Step 1: Confirm branch and clean state**

Run: `cd /home/niki/Documents/saas/fintech-prod && git branch --show-current && git status --short`
Expected: `feat/pre-launch-demo`. Modified files: `backend/app/config.py`, `backend/app/main.py`, `backend/app/routes/health.py`, `backend/requirements.txt`. Nothing else.

- [ ] **Step 2: Record backend baseline**

Run: `cd backend && /home/niki/Documents/workenv/pydev/bin/pytest -q 2>&1 | tail -5`
Expected: all tests pass. Write the pass/fail counts in the checkpoint report. If anything fails before any change, stop and report it.

- [ ] **Step 3: Record frontend baseline**

Run: `cd frontend && npx vitest run 2>&1 | tail -5`
Expected: all tests pass. Record the counts.

**REVIEW CHECKPOINT 0:** Claude confirms both baselines in writing before Task 1 begins.

---

## Task 1: API Sentry init and temporary ping removal

**Files:**
- Modify: `backend/app/config.py` (already contains `SENTRY_DSN` and `SENTRY_ENVIRONMENT`; keep as is)
- Modify: `backend/app/main.py` (already contains the init; keep as is)
- Modify: `backend/app/routes/health.py` (remove the temporary line and the `sentry_sdk` import)
- Modify: `backend/requirements.txt` (already contains `sentry-sdk[fastapi]==2.60.0`; keep as is)
- Test: `backend/tests/test_sentry_init.py`

**Interfaces:**
- Consumes: `config.SENTRY_DSN: str | None`, `config.SENTRY_ENVIRONMENT: str`.
- Produces: nothing new. The API either has Sentry initialised (DSN set) or not (DSN unset).

- [ ] **Step 1: Remove the temporary ping**

In `backend/app/routes/health.py`, delete the line that calls `sentry_sdk.capture_message("SENTRY TEST: ...")` (it has a `# TEMP` comment). Delete the now-unused `import sentry_sdk` line at the top of the same file. The function body must be exactly:

```python
@router.get("/health")
def health() -> dict[str, str]:
    """Liveness only, so a database blip never fails the deploy check or restarts the container."""
    return {"status": "ok"}
```

- [ ] **Step 2: Write the test**

Create `backend/tests/test_sentry_init.py`:

```python
import importlib

import pytest


def test_health_sends_nothing_to_sentry(monkeypatch):
    # The temporary dashboard ping must not exist in committed code.
    import app.routes.health as health_module
    source = open(health_module.__file__, encoding="utf-8").read()
    assert "capture_message" not in source
    assert "SENTRY TEST" not in source


def test_sentry_off_without_dsn(monkeypatch):
    import sentry_sdk
    monkeypatch.setattr("app.config.SENTRY_DSN", None)
    calls = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: calls.append(kw))
    import app.main as main_module
    importlib.reload(main_module)
    assert calls == []
```

- [ ] **Step 3: Run the test and confirm it fails**

Run: `cd backend && /home/niki/Documents/workenv/pydev/bin/pytest tests/test_sentry_init.py -v`
Expected: `test_health_sends_nothing_to_sentry` FAILS if Step 1 was skipped. After Step 1 it PASSES.

- [ ] **Step 4: Run it to pass**

Run: `cd backend && /home/niki/Documents/workenv/pydev/bin/pytest tests/test_sentry_init.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && /home/niki/Documents/workenv/pydev/bin/pytest -q`
Expected: same pass count as Checkpoint 0, plus the two new tests.

- [ ] **Step 6: Commit**

```bash
cd /home/niki/Documents/saas/fintech-prod
git add backend/app/config.py backend/app/main.py backend/app/routes/health.py backend/requirements.txt backend/tests/test_sentry_init.py
git commit -m "feat(ops): report API errors to Sentry when SENTRY_DSN is set"
```

**REVIEW CHECKPOINT 1:** Claude checks: the diff in `health.py` has no `sentry_sdk` import left; `main.py` init is gated on the DSN; `requirements.txt` pins `2.60.0`.

---

## Task 2: Scrubbing hook for API events

**Files:**
- Create: `backend/app/sentry_scrub.py`
- Modify: `backend/app/main.py` (pass `before_send` to `sentry_sdk.init`)
- Test: `backend/tests/test_sentry_scrub.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `scrub_event(event: dict, hint: dict) -> dict` — returns the event with request data removed and message text removed. Never returns `None` (we never drop whole events).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_sentry_scrub.py`:

```python
from app.sentry_scrub import scrub_event


def test_request_body_is_removed():
    event = {"request": {"data": {"message": "What is the fee?"}, "url": "/chat"}}
    out = scrub_event(event, {})
    assert "data" not in out["request"]
    assert out["request"]["url"] == "/chat"


def test_message_text_is_removed():
    event = {"message": "Q: what is the fee for Tremblay?"}
    out = scrub_event(event, {})
    assert out["message"] == "[Filtered]"


def test_exception_value_is_removed():
    event = {"exception": {"values": [{"type": "ValueError", "value": "bad input: John Tremblay"}]}}
    out = scrub_event(event, {})
    assert out["exception"]["values"][0]["value"] == "[Filtered]"
    assert out["exception"]["values"][0]["type"] == "ValueError"


def test_event_without_sensitive_parts_is_unchanged():
    event = {"level": "error", "environment": "demo"}
    assert scrub_event(event, {}) == event
```

- [ ] **Step 2: Run and confirm it fails**

Run: `cd backend && /home/niki/Documents/workenv/pydev/bin/pytest tests/test_sentry_scrub.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.sentry_scrub'`.

- [ ] **Step 3: Implement**

Create `backend/app/sentry_scrub.py`:

```python
"""Removes user text from Sentry events before they leave the process (spec P6, section 1).

The dashboard scrubber is a second layer; this runs first and is the one that is tested."""
from typing import Any

FILTERED = "[Filtered]"


def scrub_event(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)
        request.pop("query_string", None)
        request.pop("cookies", None)
    if "message" in event:
        event["message"] = FILTERED
    for exc in (event.get("exception") or {}).get("values", []):
        if "value" in exc:
            exc["value"] = FILTERED
    return event
```

- [ ] **Step 4: Wire it into the API init**

In `backend/app/main.py`, change the init call to:

```python
sentry_sdk.init(
    dsn=config.SENTRY_DSN,
    environment=config.SENTRY_ENVIRONMENT,
    send_default_pii=False,
    before_send=scrub_event,
)
```

and add `from app.sentry_scrub import scrub_event` to the imports.

- [ ] **Step 5: Run and confirm it passes**

Run: `cd backend && /home/niki/Documents/workenv/pydev/bin/pytest tests/test_sentry_scrub.py tests/test_sentry_init.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/sentry_scrub.py backend/app/main.py backend/tests/test_sentry_scrub.py
git commit -m "feat(ops): scrub request bodies and message text from Sentry events"
```

**REVIEW CHECKPOINT 2:** Claude checks that `scrub_event` never returns `None`, and that no test depends on the real Sentry client.

---

## Task 3: Browser Sentry init

**Files:**
- Modify: `frontend/package.json` (add `@sentry/react`)
- Create: `frontend/src/lib/sentry.ts`
- Modify: `frontend/src/main.tsx` (call the init, wrap the app in the error boundary)
- Test: `frontend/src/lib/sentry.test.ts`

**Interfaces:**
- Consumes: `import.meta.env.VITE_SENTRY_DSN: string | undefined`.
- Produces: `initSentry(dsn: string | undefined): boolean` — returns `true` when initialised, `false` when the DSN is empty.

- [ ] **Step 1: Install the package**

Run: `cd frontend && npm install @sentry/react`
Expected: `package.json` gains `@sentry/react`. Record the version in the commit body.

- [ ] **Step 2: Write the failing test**

Create `frontend/src/lib/sentry.test.ts`:

```ts
import { describe, expect, it, vi } from 'vitest';

vi.mock('@sentry/react', () => ({ init: vi.fn() }));
import * as Sentry from '@sentry/react';
import { initSentry } from './sentry';

describe('initSentry', () => {
  it('does nothing without a DSN', () => {
    expect(initSentry(undefined)).toBe(false);
    expect(initSentry('')).toBe(false);
    expect(Sentry.init).not.toHaveBeenCalled();
  });

  it('initialises with the DSN, no PII and no traces', () => {
    const dsn = 'https://key@example.ingest.us.sentry.io/1';
    expect(initSentry(dsn)).toBe(true);
    expect(Sentry.init).toHaveBeenCalledWith(expect.objectContaining({
      dsn, sendDefaultPii: false, tracesSampleRate: 0,
    }));
  });
});
```

- [ ] **Step 3: Run and confirm it fails**

Run: `cd frontend && npx vitest run src/lib/sentry.test.ts`
Expected: FAIL with `Cannot find module './sentry'`.

- [ ] **Step 4: Implement**

Create `frontend/src/lib/sentry.ts`:

```ts
import * as Sentry from '@sentry/react';

/** Drops chat request bodies and every fetch or XHR breadcrumb that calls /chat (spec P6, section 2). */
function scrubEvent<T extends Sentry.ErrorEvent>(event: T): T {
  if (event.request) delete event.request.data;
  event.breadcrumbs = event.breadcrumbs?.filter((b) => !((b.category === 'fetch' || b.category === 'xhr') && String(b.data?.url ?? '').includes('/chat')));
  return event;
}

/** Initialises Sentry only when a DSN is configured. Returns whether it did. */
export function initSentry(dsn: string | undefined): boolean {
  if (!dsn) return false;
  Sentry.init({ dsn, sendDefaultPii: false, tracesSampleRate: 0, beforeSend: scrubEvent });
  return true;
}
```

- [ ] **Step 5: Wire it into the app**

In `frontend/src/main.tsx`, before rendering: `initSentry(import.meta.env.VITE_SENTRY_DSN);`. Wrap the existing root component in `<Sentry.ErrorBoundary fallback={<p role="alert">Something went wrong. Reload the page.</p>}>` from `@sentry/react`. Keep the existing render call otherwise unchanged.

- [ ] **Step 6: Run and confirm it passes**

Run: `cd frontend && npx vitest run src/lib/sentry.test.ts && npm run build`
Expected: the test PASSES; `npm run build` completes with no type errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/lib/sentry.ts frontend/src/lib/sentry.test.ts frontend/src/main.tsx
git commit -m "feat(ops): report browser errors to Sentry when VITE_SENTRY_DSN is set

New npm package: @sentry/react (version as installed; see package.json)."
```

**REVIEW CHECKPOINT 3:** Claude checks that `initSentry` is the only call to `Sentry.init`, that `package-lock.json` changed only by the new package, and that the build passes.

---

## Task 4: Migration 0016, model, DAO, and timing endpoint

**Files:**
- Create: `backend/alembic/versions/0016_chat_turn_timing.py`
- Modify: `backend/app/assistant/models.py` (add `ChatTurnTiming`)
- Modify: `backend/app/assistant/dao.py` (add `add_timing`)
- Create: `backend/app/assistant/timing.py` (framework-free input dataclass and `record_timing`)
- Modify: `backend/app/routes/chat.py` (add the route; thin)
- Test: `backend/tests/test_chat_timing.py`
- Test: `backend/tests/test_migrations.py` (extend, do not replace)

**Interfaces:**
- Consumes: `dao.find_turn(session, tenant_id, turn_id) -> ChatTurn | None` (existing); `errors.TurnNotFound`, `errors.GuestRequired` (existing).
- Produces:
  - `TimingInput(tenant_id: uuid.UUID, guest_id: uuid.UUID, turn_id: uuid.UUID, ttfb_ms: int)` (frozen dataclass)
  - `record_timing(session: Session, timing: TimingInput) -> bool` — `True` if a row was written, `False` if one already existed. Raises `TurnNotFound` when the turn is missing or belongs to another guest.
  - `dao.add_timing(session: Session, row: ChatTurnTiming) -> bool` — `INSERT ... ON CONFLICT (turn_id) DO NOTHING`, returns whether a row was inserted.
  - HTTP: `POST /chat/turns/{turn_id}/timing`, body `{"ttfb_ms": int}` with `ge=0`, `le=60000`, response `200 {"recorded": bool}`.

- [ ] **Step 1: Write the migration**

Create `backend/alembic/versions/0016_chat_turn_timing.py`:

```python
"""chat turn timing and the usage view (P7)

Revision ID: 0016_chat_turn_timing
Revises: 0015_feedback_descriptions
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0016_chat_turn_timing"
down_revision: Union[str, Sequence[str], None] = "0015_feedback_descriptions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for statement in (
        # One client-measured TTFB per chat turn. Insert-only, like every other chat table: the unique key on turn_id
        # makes a second write a no-op, and the first value wins (spec P7 section 3).
        "CREATE TABLE chat_turn_timing ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " tenant_id uuid NOT NULL REFERENCES tenants(id),"
        " turn_id uuid NOT NULL UNIQUE REFERENCES chat_turns(id),"
        " guest_id uuid NOT NULL REFERENCES guests(id),"
        " ttfb_ms integer NOT NULL CONSTRAINT ck_chat_turn_timing_range CHECK (ttfb_ms BETWEEN 0 AND 60000),"
        " created_at timestamptz NOT NULL DEFAULT now())",
        "CREATE TRIGGER trg_chat_turn_timing_append_only BEFORE UPDATE OR DELETE ON chat_turn_timing "
        "FOR EACH ROW EXECUTE FUNCTION forbid_mutation()",
        "CREATE TRIGGER trg_chat_turn_timing_no_truncate BEFORE TRUNCATE ON chat_turn_timing "
        "FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()",
        # ledger_app gets SELECT and INSERT from the 0003 default privileges; the demo role needs an explicit grant.
        "GRANT INSERT, SELECT ON chat_turn_timing TO ledger_demo",
        # Cited-answer share and TTFB per day. A session reached a cited answer when any of its turns that day was
        # 'answered' with at least one citation. Averages skip turns that have no timing row.
        """
        CREATE VIEW chat_usage_daily AS
        WITH sessions AS (
          SELECT date_trunc('day', created_at) AS day, session_id,
                 bool_or(outcome = 'answered' AND jsonb_array_length(citations) > 0) AS reached_cited
          FROM chat_turns GROUP BY 1, 2
        ), timing AS (
          SELECT date_trunc('day', t.created_at) AS day, tt.ttfb_ms
          FROM chat_turn_timing tt JOIN chat_turns t ON t.id = tt.turn_id
        )
        SELECT s.day,
               count(*) AS sessions,
               count(*) FILTER (WHERE s.reached_cited) AS cited_sessions,
               round(100.0 * count(*) FILTER (WHERE s.reached_cited) / count(*), 1) AS cited_pct,
               (SELECT count(*) FROM timing ti WHERE ti.day = s.day) AS timed_turns,
               (SELECT round(avg(ti.ttfb_ms)) FROM timing ti WHERE ti.day = s.day) AS avg_ttfb_ms
        FROM sessions s GROUP BY s.day ORDER BY s.day
        """,
        "GRANT SELECT ON chat_usage_daily TO ledger_app",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP VIEW chat_usage_daily")
    op.execute("DROP TABLE chat_turn_timing")
```

- [ ] **Step 2: Extend the migration test**

In `backend/tests/test_migrations.py`, add a test that checks: after `upgrade head`, `chat_turn_timing` exists; an `UPDATE` on it raises `restrict_violation`; a `DELETE` on it raises `restrict_violation`; an `UPDATE` on `chat_turns` still raises (the existing append-only rule). Follow the style of the existing tests in that file. Run it:

Run: `cd backend && /home/niki/Documents/workenv/pydev/bin/pytest tests/test_migrations.py -v`
Expected: the new test FAILS before Step 1 and PASSES after.

- [ ] **Step 3: Add the model**

In `backend/app/assistant/models.py`, add after `ChatFeedback`:

```python
class ChatTurnTiming(Base):
    __tablename__ = "chat_turn_timing"
    __mapper_args__ = {"eager_defaults": True}
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    turn_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chat_turns.id"), nullable=False, unique=True)
    guest_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("guests.id"), nullable=False)
    ttfb_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
```

- [ ] **Step 4: Write the failing endpoint test**

Create `backend/tests/test_chat_timing.py`. Copy the helpers `_guest` and `_turn` and the fixtures `client`, `db_session`, `tenant_id` from `backend/tests/test_chat_feedback.py` (same names, same signatures; `_turn` returns the turn id). The file must contain these cases:

```python
import uuid

from sqlalchemy import select

from app.assistant.models import ChatTurnTiming


def _guest(client) -> dict[str, str]:  # copied from test_chat_feedback.py
    return {"X-Guest-Id": client.post("/guests").json()["id"]}


def _timings(db_session, turn_id: uuid.UUID) -> list[ChatTurnTiming]:
    return list(db_session.scalars(select(ChatTurnTiming).where(ChatTurnTiming.turn_id == turn_id)))


def test_first_timing_is_recorded(client, db_session, tenant_id):
    guest = _guest(client)
    turn_id = _turn(db_session, tenant_id, guest)
    r = client.post(f"/chat/turns/{turn_id}/timing", json={"ttfb_ms": 850}, headers=guest)
    assert r.status_code == 200
    assert r.json() == {"recorded": True}
    assert [t.ttfb_ms for t in _timings(db_session, turn_id)] == [850]


def test_second_timing_keeps_the_first(client, db_session, tenant_id):
    guest = _guest(client)
    turn_id = _turn(db_session, tenant_id, guest)
    client.post(f"/chat/turns/{turn_id}/timing", json={"ttfb_ms": 850}, headers=guest)
    r = client.post(f"/chat/turns/{turn_id}/timing", json={"ttfb_ms": 9000}, headers=guest)
    assert r.status_code == 200
    assert r.json() == {"recorded": False}
    assert [t.ttfb_ms for t in _timings(db_session, turn_id)] == [850]


def test_another_guests_turn_is_not_found(client, db_session, tenant_id):
    owner, other = _guest(client), _guest(client)
    turn_id = _turn(db_session, tenant_id, owner)
    r = client.post(f"/chat/turns/{turn_id}/timing", json={"ttfb_ms": 850}, headers=other)
    assert r.status_code == 404
    assert _timings(db_session, turn_id) == []


def test_missing_guest_header_gets_400(client, db_session, tenant_id):
    turn_id = _turn(db_session, tenant_id, _guest(client))
    r = client.post(f"/chat/turns/{turn_id}/timing", json={"ttfb_ms": 850})
    assert r.status_code == 400


def test_out_of_range_values_get_422(client, db_session, tenant_id):
    guest = _guest(client)
    turn_id = _turn(db_session, tenant_id, guest)
    for bad in (-1, 60001, "fast", 1.5):
        r = client.post(f"/chat/turns/{turn_id}/timing", json={"ttfb_ms": bad}, headers=guest)
        assert r.status_code == 422, bad
    assert _timings(db_session, turn_id) == []
```

- [ ] **Step 5: Run and confirm it fails**

Run: `cd backend && /home/niki/Documents/workenv/pydev/bin/pytest tests/test_chat_timing.py -v`
Expected: FAIL with 404 on the route (the route does not exist yet).

- [ ] **Step 6: Implement the DAO function**

In `backend/app/assistant/dao.py`, add:

```python
def add_timing(session: Session, row: ChatTurnTiming) -> bool:
    result = session.execute(
        insert(ChatTurnTiming)
        .values(tenant_id=row.tenant_id, turn_id=row.turn_id, guest_id=row.guest_id, ttfb_ms=row.ttfb_ms)
        .on_conflict_do_nothing(index_elements=["turn_id"])
        .returning(ChatTurnTiming.id)
    )
    inserted = result.first() is not None
    session.commit()  # the session dependency only closes; every DAO write commits itself, as add_feedback does
    return inserted
```

Add `from sqlalchemy.dialects.postgresql import insert` and `ChatTurnTiming` to the imports if they are not there.

- [ ] **Step 7: Implement the service function**

Create `backend/app/assistant/timing.py`:

```python
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.assistant import dao
from app.assistant.models import ChatTurnTiming
from app.errors import TurnNotFound


@dataclass(frozen=True)
class TimingInput:
    tenant_id: uuid.UUID
    guest_id: uuid.UUID
    turn_id: uuid.UUID
    ttfb_ms: int


def record_timing(session: Session, timing: TimingInput) -> bool:
    """Record the guest's TTFB for their own turn. The first value wins; returns False when one already exists."""
    turn = dao.find_turn(session, timing.tenant_id, timing.turn_id)
    if turn is None or turn.guest_id != timing.guest_id:
        raise TurnNotFound(f"Chat turn {timing.turn_id} does not exist.")
    return dao.add_timing(session, ChatTurnTiming(
        tenant_id=timing.tenant_id, turn_id=timing.turn_id, guest_id=timing.guest_id, ttfb_ms=timing.ttfb_ms))
```

- [ ] **Step 8: Implement the route**

In `backend/app/routes/chat.py`, add next to the feedback route. Mirror `give_feedback` exactly:

```python
class TimingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ttfb_ms: Annotated[int, Field(ge=0, le=60000)]


class TimingOut(BaseModel):
    recorded: bool


@router.post("/turns/{turn_id}/timing", response_model=TimingOut)
def give_timing(
    turn_id: uuid.UUID,
    body: TimingIn,
    session: Annotated[Session, Depends(get_session)],
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    guest_id: Annotated[uuid.UUID | None, Depends(get_guest_id)],
) -> TimingOut:
    if guest_id is None:
        raise GuestRequired("Send the X-Guest-Id of a known guest (POST /guests) to report timing.")
    recorded = record_timing(session, TimingInput(tenant_id=tenant_id, guest_id=guest_id, turn_id=turn_id, ttfb_ms=body.ttfb_ms))
    return TimingOut(recorded=recorded)
```

Add `from app.assistant.timing import TimingInput, record_timing` to the imports. Do **not** call `session.commit()` in the route. The commit happens in `dao.add_timing` (Step 6), as `add_feedback` does. `get_session` in `backend/app/deps.py` only closes the session; it never commits.

- [ ] **Step 9: Run and confirm it passes**

Run: `cd backend && /home/niki/Documents/workenv/pydev/bin/pytest tests/test_chat_timing.py tests/test_migrations.py -v`
Expected: all PASS.

- [ ] **Step 10: Run the full backend suite**

Run: `cd backend && /home/niki/Documents/workenv/pydev/bin/pytest -q`
Expected: same as Checkpoint 0, plus the new tests. No failures.

- [ ] **Step 11: Commit**

```bash
git add backend/alembic/versions/0016_chat_turn_timing.py backend/app/assistant/models.py backend/app/assistant/dao.py backend/app/assistant/timing.py backend/app/routes/chat.py backend/tests/test_chat_timing.py backend/tests/test_migrations.py
git commit -m "feat(assistant): record client TTFB per chat turn in an insert-only table (P7)"
```

**REVIEW CHECKPOINT 4:** Claude checks: the migration has no `ALTER` on `chat_turns`; the route has no SQL in it; the view is granted to `ledger_app` only; all five Review Focus tests for this task exist and pass.

---

## Task 5: Frontend TTFB measurement

**Files:**
- Modify: `frontend/src/api.ts` (`streamChat` measures and posts; add `sendTiming`)
- Test: `frontend/src/api.test.ts` (extend; the file already exists)

**Interfaces:**
- Consumes: the final `ChatEvent` types `answer | refused | clarify` carry `data.turn_id: string`. `error` carries no turn id.
- Produces: `sendTiming(turnId: string, ttfbMs: number): Promise<void>`, which posts to `/chat/turns/{turnId}/timing` and never throws to the caller. `streamChat`'s signature does not change.

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/api.test.ts` (use the existing fetch-mocking helpers in that file):

```ts
it('posts TTFB after the first chunk and the final turn id', async () => {
  // Mock /chat to stream: one progress event, then an answer event naming turn "t-1".
  // Mock /chat/turns/t-1/timing to return 200 {"recorded": true}.
  // Call streamChat('s', 'q', () => {}).
  // Expect exactly one fetch call to '/chat/turns/t-1/timing' with body {"ttfb_ms": <number >= 0>}.
});

it('posts nothing when the stream ends in an error event (no turn id)', async () => {
  // Mock /chat to stream one error event only.
  // Expect no call to any URL containing '/timing'.
});

it('posts nothing and does not throw when the stream is aborted', async () => {
  // Mock /chat so the body reader rejects after the first chunk.
  // Expect streamChat to reject with the abort error, and no call to '/timing'.
});

it('a failed timing post never reaches the caller', async () => {
  // Mock /timing to return 500.
  // Expect streamChat to resolve normally.
});
```

Write each `// Mock` comment out as real mock code using the helpers already in `api.test.ts`. Do not leave the comments in the committed file.

- [ ] **Step 2: Run and confirm they fail**

Run: `cd frontend && npx vitest run src/api.test.ts`
Expected: the first test FAILS (no timing call is made).

- [ ] **Step 3: Implement `sendTiming`**

Add to `frontend/src/api.ts`, after `sendFeedback`:

```ts
/** Fire-and-forget: a lost timing row is acceptable, a visible error for the guest is not. */
export async function sendTiming(turnId: string, ttfbMs: number): Promise<void> {
  try {
    await fetch(`${API_BASE}/chat/turns/${turnId}/timing`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(await guestHeaders()) },
      body: JSON.stringify({ ttfb_ms: ttfbMs }),
    });
  } catch {
    // ignored on purpose: see the comment above
  }
}
```

- [ ] **Step 4: Implement the measurement in `streamChat`**

In `streamChat`, record `const t0 = performance.now();` immediately before the `fetch` call. After `const { value, done } = await reader.read();` succeeds with a non-empty `value` for the first time, set `let t1: number | undefined` (only the first time). Track `let turnId: string | undefined;` and set it when an event has `data.turn_id` (types `answer`, `refused`, `clarify`). When the loop ends (`done`), if `turnId` and `t1` are both set, call `void sendTiming(turnId, Math.round(t1 - t0));`. Do not await it. Do not change the thrown error path: if `reader.read()` rejects, the error propagates exactly as it does today.

- [ ] **Step 5: Run and confirm they pass**

Run: `cd frontend && npx vitest run src/api.test.ts && npm run build`
Expected: all four tests PASS; build passes.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api.ts frontend/src/api.test.ts
git commit -m "feat(chat): report the time to first byte of each reply (P7)"
```

**REVIEW CHECKPOINT 5:** Claude checks: `streamChat`'s signature is unchanged; `sendTiming` cannot throw; `t1` is set only once; no `await` on `sendTiming`.

---

## Task 6: Operator scripts and runbook (local files, not committed)

**Files:**
- Modify: `backend/script.demo.sh` (already has `usage` and the 0016 `check` lines; verify, do not duplicate)
- Modify: `backend/script.demo.md` (already has the P6 + P7 section; verify, do not duplicate)

**Interfaces:** none.

- [ ] **Step 1: Verify the script**

Run: `cd backend && bash -n script.demo.sh && ./script.demo.sh 2>&1 | head -20`
Expected: no syntax error; the usage text lists `usage` and `feedback`.

- [ ] **Step 2: Verify the runbook**

Open `backend/script.demo.md`. Confirm the section `P6 + P7 (migration 0016)` names `0016_chat_turn_timing (head)` and the `check` expectations. Confirm no other section was altered.

- [ ] **Step 3: No commit**

These two files are git-ignored by design. Confirm with `git check-ignore -v backend/script.demo.sh backend/script.demo.md`. Do not stage them.

**REVIEW CHECKPOINT 6:** Claude confirms the two files are ignored and syntactically valid.

---

## Task 7: Deploy and smoke test (human steps, with Claude checking the results)

This task runs against the deployed environment. The executor must **stop** before each numbered step that says **HUMAN**, and wait for the user's go-ahead.

- [ ] **Step 1: HUMAN — run the migration on the Railway database**

Run: `cd backend && ./script.demo.sh migrate`
Then: `./script.demo.sh check`
Expected: `alembic current` prints `0016_chat_turn_timing (head)`; `demo_can_insert_timing = t`, `demo_can_update_timing = f`, `demo_can_update_turns = f`.

- [ ] **Step 2: HUMAN — set the browser DSN in Vercel**

Confirm `VITE_SENTRY_DSN` exists for the Vercel **Production** environment. The API DSN (`SENTRY_DSN`, `SENTRY_ENVIRONMENT=demo`) must already exist in Railway.

- [ ] **Step 3: HUMAN — push the branch and deploy**

Pushing is outward-facing. Wait for the user's explicit go-ahead before `git push`.

Push `feat/pre-launch-demo` and let Railway and Vercel build. Confirm both builds succeed.

- [ ] **Step 4: Forced API error**

Send one request to a route that is known to fail for a bad input, or temporarily call a route you control. Expected: one event appears in the `ledgerlens-api` Sentry project, environment `demo`, with no request body and no message text.

- [ ] **Step 5: Forced browser error**

Open the deployed site, and trigger an error boundary (or throw from the console with the Sentry test pattern the team agreed). Expected: one event in `ledgerlens-web`, with no `/chat` breadcrumb request body.

- [ ] **Step 6: One real chat turn with timing**

Ask one question on the deployed site and wait for the answer. Then run `./script.demo.sh usage`. Expected: a row for today with `timed_turns >= 1` and a non-null `avg_ttfb_ms`.

- [ ] **Step 7: Record the results**

Write the three results (Sentry API event, Sentry web event, usage row) into `CHANGELOG.md` under the P6 and P7 lines, following the existing "**Done <date>:**" convention. Commit that change on its own: `docs(changelog): P6 and P7 deployed verification`.

**REVIEW CHECKPOINT 7:** Claude reads the three results and compares them with the expectations above. Any mismatch stops the sprint and goes back to the user.

---

## Execution Notes for Gemini

- Work only inside the task you are on. Do not reorder checkpoints.
- Where a step says "copy from file X", open file X first and copy its exact names; do not guess.
- If a test you expect to pass fails for a reason outside this task, stop and report the output. Do not edit unrelated tests.
- Report at each checkpoint: the commands you ran, their final lines of output, and the commit hash.
