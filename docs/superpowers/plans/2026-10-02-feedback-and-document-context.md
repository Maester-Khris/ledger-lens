# Answer Feedback and Document Context (P5 + P8) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Status 2026-10-02:** Part A is done (commits `d912986`, `cd6641b`, `f4bfa4f`, `d992d22`, `5b84509`); see "Part A outcome" below. The executor starts at Task 3.
>
> **This project:** Claude runs Tasks 1–2 and Task 11. The executor (Gemini) does Tasks 3–10 in order and stops at each **REVIEW CHECKPOINT** with: the commit hash, the exact test/build/lint output, `git status`, and any deviation from the task. Do not start the next task until the checkpoint is approved.

**Goal:** A demo guest can rate and comment on any reply, sees what each document is, gets starter questions that match the document they picked, and opens a citation inside the app.

**Architecture:** One additive migration (an insert-only `chat_feedback` table and an insert-only `document_descriptions` table). The chat stream's final event gains the turn id, a thin feedback route calls one function in `app/assistant/feedback.py`, and the frontend adds one component and two small pure modules. Before that, a fix so the contract-fields tool stops handing the model numbers the contract text doesn't contain, and a scoped pass in the eval harness.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2.0 / Alembic / PostgreSQL 18 / pytest; React (Vite) + TypeScript / vitest; Playwright.

**Spec:** `docs/superpowers/specs/2026-10-02-feedback-and-document-context-design.md` — read it in full first. § numbers refer to it.

## Deviations from the spec (found while mapping the code; the spec is amended to match)

1. **Citations already carry `document_id`** (`assistant/tools.py`, `assistant/contract_tools.py`). D11 needs only the frontend type.
2. **No component unit tests.** The frontend has no DOM test setup (vitest runs pure `lib/` tests only) and no new npm package is allowed. Logic lives in pure functions with vitest tests (`lib/starters.ts`, `lib/viewer.ts`, `api.ts`); the component behaviour is covered by the Playwright test.
3. **The comment column allows 4000 characters; the API accepts 1000.** Tokenising replaces a short value with a longer token, so a 1000-character comment can grow.
4. **Starters live in `frontend/src/lib/starters.json`**, so a backend test can check them against `golden.json` without parsing TypeScript.
5. **Two tasks precede the feature work** (found by the starter pre-check, 2026-10-02): the contract-fields tool gave the model `rate_bps`, the model sometimes wrote "55 basis points", the output check rejected the number and the turn ended in a refusal. Task 1 fixes it; Task 2 makes the eval gate ask the starters scoped to their document as well.

## Global Constraints

- Branch `feat/pre-launch-demo`. Never commit to `main`/`preview`. Stage files explicitly (never `git add -A`/`.`). Conventional commits; use the commit message each task gives, verbatim. **No AI co-author line, no "Generated with" line.** Do not push.
- Backend commands from `backend/` as `/home/niki/Documents/workenv/pydev/bin/<tool>`; never create a `.venv`. Frontend commands from `frontend/`.
- No new Python dependency, no new npm package.
- Python: type hints on every signature; dataclasses for input DTOs; no `session.begin()`. TypeScript: no `any`, a props interface per component.
- Routes stay thin; DB access only in a package's `dao.py`.
- The normal backend suite (`/home/niki/Documents/workenv/pydev/bin/pytest -q`) must pass after every backend task and must never call a real LLM. The `eval`-marked golden test is **not** run by the executor.
- The frontend checks after every frontend task: `npm test`, `npm run build`, `npm run lint`.
- Only edit existing tests where a task says so. Never print or commit `backend/.env*`, `backend/script.demo.sh` or `backend/script.demo.md`.
- Copy every user-facing string exactly as written here.

## Review Focus

Conditions the spec implies that are most likely to bite a guest. Each has a test in the task named.

1. **A thumb clicked before the turn row is saved** (the row is written after the final event): the API answers 404 and the control must stay usable and say so. Backend test in Task 6; the control's failure state in Task 10.
2. **A comment that is only spaces**: stored as NULL, not as an empty string. Task 6.
3. **A document with no description or no starters** (anything uploaded outside the demo corpus): nothing is rendered, no empty line or empty chip row. Tasks 7 and 8.
4. **A citation with no page** (system and tool citations): no "Open page" button. Task 9.
5. **A second click while a save is in flight**: the buttons are disabled while saving, so one click makes one row. Task 10 (Playwright asserts a single "Feedback saved").

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `backend/app/assistant/contract_tools.py` | the fields tool sends only what the contract says | 1 |
| `backend/tests/eval/test_golden.py`, `golden.json` | scoped pass; starter cases | 2 |
| `frontend/src/api.test.ts` | stale reversal test | 3 |
| `backend/alembic/versions/0015_feedback_descriptions.py` | both tables, the grant, the four descriptions | 4 |
| `backend/app/assistant/models.py`, `backend/app/documents/models.py` | `ChatFeedback`, `FeedbackRating`, `DocumentDescription` | 4 |
| `backend/app/assistant/service.py` | `turn_id` on final events | 5 |
| `backend/app/assistant/feedback.py` (new), `dao.py`, `backend/app/errors.py`, `backend/app/routes/chat.py` | record feedback | 6 |
| `backend/app/documents/dao.py`, `backend/app/routes/documents.py` | description in the document list | 7 |
| `frontend/src/lib/starters.json`, `starters.ts` (new) | starter questions | 8 |
| `frontend/src/lib/viewer.ts` | `citationTarget` | 9 |
| `frontend/src/components/FeedbackControl.tsx`, `.css` (new) | the control | 10 |
| `frontend/src/screens/Chat.tsx`, `frontend/src/api.ts` | wiring | 5, 8, 9, 10 |

---

# Part A — run by Claude before the executor starts

### Task 1: The contract-fields tool sends no derived numbers

**Files:**
- Modify: `backend/app/assistant/contract_tools.py`
- Test: `backend/tests/test_assistant_contract_tools.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_assistant_contract_tools.py`)

```python
def test_fields_tool_hides_numbers_the_contract_text_does_not_contain(db_session, tenant_id):
    """rate_bps and up_to_minor are derived by extraction; an answer repeating one fails the citation check."""
    scenario = build_fee_scenario(db_session, tenant_id)
    document_id = _contract(db_session, tenant_id, scenario.household_id)
    outcome = execute(TOOLS["get_contract_fields"], _ctx(db_session, tenant_id), {"document_id": str(document_id)})
    tier = json.loads(outcome.content)["fields"]["fee_tiers[1]"]
    assert set(tier) == {"band_text", "rate_text"}
```

- [ ] **Step 2: Run it and see it fail**

Run: `/home/niki/Documents/workenv/pydev/bin/pytest tests/test_assistant_contract_tools.py -q`
Expected: 1 failed (the set also holds `rate_bps` and `up_to_minor`).

- [ ] **Step 3: Implement** — in `contract_tools.py`, above `_get_contract_fields`:

```python
# Derived by extraction for calculations. The contract's text never contains them, so the chat model must not see
# them: an answer that repeats one ("55 basis points") fails the every-number-is-cited check and ends in a refusal.
DERIVED_KEYS = frozenset({"rate_bps", "up_to_minor"})


def _as_written(value: object) -> object:
    return {k: v for k, v in value.items() if k not in DERIVED_KEYS} if isinstance(value, dict) else value
```

and in `_get_contract_fields` change the `fields` line to:

```python
        "fields": {path: _as_written(f.value) for path, f in served.fields.items()},
```

- [ ] **Step 4: Run the suite**

Run: `/home/niki/Documents/workenv/pydev/bin/pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/assistant/contract_tools.py backend/tests/test_assistant_contract_tools.py
git commit -m "fix(assistant): the contract-fields tool sends only what the contract text says"
```

### Task 2: Scoped pass in the eval harness, and the starter cases

**Files:**
- Modify: `backend/tests/eval/test_golden.py`, `backend/tests/eval/golden.json`
- Test: `backend/tests/test_golden_scoring.py`

**Interfaces:**
- Produces: a golden case may carry `"scoped": true`; the harness then also asks it with `document_id` set to the document whose key is `expect_document`, and reports it as `<id>@scoped` in category `answerable`. The report format is unchanged (more rows in `results`), so `app/reporting/dashboard.py` needs no change.

- [ ] **Step 1: Write the failing test** (append to `tests/test_golden_scoring.py`; add `expand` to its import from `tests.eval.test_golden`)

```python
def test_a_scoped_case_is_asked_twice_the_second_time_limited_to_its_document():
    plain = _case("answerable", "answer")
    scoped = _case("answerable", "answer", scoped=True, expect_document="tremblay-ima") | {"id": "fee"}
    assert [(c["id"], c.get("document_key")) for c in expand([plain, scoped])] == [
        ("answerable-answer", None), ("fee", None), ("fee@scoped", "tremblay-ima")]
```

- [ ] **Step 2: Run it and see it fail** — `pytest tests/test_golden_scoring.py -q` → ImportError on `expand`.

- [ ] **Step 3: Implement** in `tests/eval/test_golden.py`:

```python
def expand(cases: list[dict]) -> list[dict]:
    """Every case as written, then the ones marked "scoped" again with the chat limited to their document:
    a guest who picked a document card asks that way, and the unscoped run never exercises it."""
    return [*cases, *(c | {"id": f"{c['id']}@scoped", "document_key": c["expect_document"]} for c in cases if c.get("scoped"))]


def _document_ids() -> dict[str, uuid.UUID]:
    with SessionLocal() as session:
        return {row.document.document_key: row.document.id for row in documents_dao.list_documents(session, DEMO_TENANT_ID)}
```

with `from app.documents import dao as documents_dao` added to the imports. `_run(case)` becomes `_run(case, document_ids)` and passes `document_id=document_ids[case["document_key"]] if "document_key" in case else None` to `run_turn`. `test_golden_set` loads `document_ids = _document_ids()` once and iterates `expand(CASES)`.

- [ ] **Step 4: Add the starter cases to `golden.json`.** Set `"scoped": true` on the existing `fee-schedule`, `termination`, `governing-law`, `calamos-top-tier` and `aim-first-tier`, and append:

```json
{"id": "calamos-first-tier", "category": "answerable", "expect": "answer", "retrieval": true, "scoped": true,
 "question": "What rate applies to the first $500 million of the Calamos Emerging Market Equity Fund's assets?",
 "expect_document": "calamos-emerging-market-equity", "expect_page": 1, "expect_numbers": ["1.10", "500"]},
{"id": "calamos-fee-basis", "category": "answerable", "expect": "answer", "retrieval": true, "scoped": true,
 "question": "What are the Calamos Emerging Market Equity Fund's fees calculated on?",
 "expect_document": "calamos-emerging-market-equity", "expect_page": 1, "expect_numbers": []},
{"id": "aim-termination", "category": "answerable", "expect": "answer", "retrieval": true, "scoped": true,
 "question": "How many days of notice are needed to terminate the AIM Global Trends Fund agreement?",
 "expect_document": "aim-global-trends-advisory", "expect_page": 5, "expect_numbers": ["60"]},
{"id": "aim-fee-schedule", "category": "answerable", "expect": "answer", "retrieval": true, "scoped": true,
 "question": "What is the full fee schedule for AIM Global Trends Fund?",
 "expect_document": "aim-global-trends-advisory", "expect_page": 7, "expect_numbers": ["0.975", "0.95", "0.925", "0.90"]},
{"id": "nomura-fee-schedule", "category": "answerable", "expect": "answer", "retrieval": true, "scoped": true,
 "question": "What is the fee schedule for the Nomura Tax-Free Colorado Fund?",
 "expect_document": "nomura-tax-free-colorado-ima", "expect_page": 4, "expect_numbers": ["0.55", "0.50", "0.45", "0.425"]},
{"id": "nomura-top-tier", "category": "answerable", "expect": "answer", "retrieval": true, "scoped": true,
 "question": "What rate applies to the Nomura Tax-Free Colorado Fund's assets in excess of $2.5 billion?",
 "expect_document": "nomura-tax-free-colorado-ima", "expect_page": 4, "expect_numbers": ["0.425", "2.5"]},
{"id": "nomura-billing-frequency", "category": "answerable", "expect": "answer", "retrieval": true, "scoped": true,
 "question": "How often is the management fee paid for the Nomura Tax-Free Colorado Fund?",
 "expect_document": "nomura-tax-free-colorado-ima", "expect_page": 2, "expect_numbers": []}
```

- [ ] **Step 5: Run the normal suite** — `pytest -q` → all pass.

- [ ] **Step 6: Run the gate twice** (49 turns each, a few cents)

Run: `ENV_FILE=.env.demo /home/niki/Documents/workenv/pydev/bin/pytest -m eval tests/eval/test_golden.py -s`
Expected: the "eval target" line says `ledger_demo` / `contract-demo`; the gate passes; every `@scoped` row is an `answer`.

- [ ] **Step 7: Repeat the three questions that were flaky**, five times each, unscoped and scoped, with the tool and verification trace on (the scratch script from the diagnosis). If any attempt is refused: find the cause from the trace before going on; a starter that cannot be made reliable is replaced here, in `golden.json` and in Task 8's `starters.json`, and the user is told.

- [ ] **Step 8: Commit**

```bash
git add backend/tests/eval/test_golden.py backend/tests/eval/golden.json backend/tests/test_golden_scoring.py backend/reports
git commit -m "test(eval): ask the starter questions scoped to their document, and add the new starters"
```

---

## Part A outcome (2026-10-02)

Tasks 1 and 2 are committed. The gate runs found two more causes of refused answerables, fixed in Part A as well:
search now scores passages against the guest's question as well as the model's query (`cd6641b`), and a multi-contract
answer is a list of per-contract sections, with verified sections kept when one fails (`f4bfa4f`, `d992d22`). Gate
under configuration `5bfdd62942f4`: 48 of 49, then 49 of 49. Step 7 of Task 2 was not run: the user decided to stop
tuning; an occasional refusal of an answerable question is known and accepted (changelog, backlog X5). All 12 starters
stay as written.

---

# Part B — run by the executor, one REVIEW CHECKPOINT per task

### Task 3: Fix the stale reversal test

`reversePosting` awaits `guestHeaders()`, which first POSTs `/guests`, so the reversal is no longer `calls[0]`.

**Files:**
- Modify: `frontend/src/api.test.ts`

- [ ] **Step 1: Confirm the failure** — `cd frontend && npm test` → exactly one failing test, "reverses with a key derived from the posting id so a retry replays".

- [ ] **Step 2: Replace that test's body** with:

```ts
it('reverses with a key derived from the posting id so a retry replays', async () => {
  const calls = respondWith({ id: 'p2' }, 201);
  await reversePosting('p1');
  const reversal = calls.find((call) => call.url === `${API_BASE}/postings/p1/reversal`);
  expect(reversal).toBeDefined();
  expect(new Headers(reversal?.init?.headers).get('Idempotency-Key')).toBe('reverse:p1');
});
```

- [ ] **Step 3: Run** — `npm test` → all pass. `npm run build` and `npm run lint` → clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api.test.ts
git commit -m "test(frontend): find the reversal call by its URL, not its position"
```

**REVIEW CHECKPOINT 3.**

### Task 4: Migration 0015 and the models

**Files:**
- Create: `backend/alembic/versions/0015_feedback_descriptions.py`
- Modify: `backend/app/assistant/models.py`, `backend/app/documents/models.py`
- Test: `backend/tests/test_demo_role.py`

**Interfaces:**
- Produces: `app.assistant.models.FeedbackRating` (`up`, `down`), `app.assistant.models.ChatFeedback` (`id`, `tenant_id`, `turn_id`, `guest_id`, `rating`, `comment_redacted`, `created_at`), `app.documents.models.DocumentDescription` (`document_id`, `description`, `created_at`).

- [ ] **Step 1: Write the failing test** (append to `tests/test_demo_role.py`)

```python
def test_feedback_is_insert_only_and_descriptions_are_read_only_for_the_demo_role(owner_session):
    assert _can(owner_session, "ledger_demo", "chat_feedback", "SELECT")
    assert _can(owner_session, "ledger_demo", "chat_feedback", "INSERT")
    for role in ("ledger_demo", "ledger_app"):
        for privilege in ("UPDATE", "DELETE"):
            assert not _can(owner_session, role, "chat_feedback", privilege), (role, privilege)
    assert _can(owner_session, "ledger_demo", "document_descriptions", "SELECT")
    for privilege in ("INSERT", "UPDATE", "DELETE"):
        assert not _can(owner_session, "ledger_demo", "document_descriptions", privilege), privilege
```

- [ ] **Step 2: Run it and see it fail** — `pytest tests/test_demo_role.py -q` → fails with `relation "chat_feedback" does not exist`.

- [ ] **Step 3: Create the migration** `backend/alembic/versions/0015_feedback_descriptions.py`:

```python
"""answer feedback and document descriptions (P5 + P8)

Revision ID: 0015_feedback_descriptions
Revises: 0014_chat_outcome_clarified
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015_feedback_descriptions"
down_revision: Union[str, Sequence[str], None] = "0014_chat_outcome_clarified"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# One line per demo document, matched by document_key. A database without these documents gets no rows.
DESCRIPTIONS = (
    ("tremblay-ima", "Synthetic household agreement: a graduated advisory fee in CAD, billed quarterly. "
                     "The only contract with billing records to compare against."),
    ("calamos-emerging-market-equity", "Notice amending a fund management agreement: an eight-tier fee on average "
                                       "daily net assets, down to 0.90% above $26 billion."),
    ("aim-global-trends-advisory", "Master advisory agreement from 2001: a four-tier fee starting at 0.975%, with a "
                                   "60-day termination notice."),
    ("nomura-tax-free-colorado-ima", "2025 management agreement for the Nomura Tax-Free Colorado Fund: a four-tier "
                                     "fee starting at 0.55%, paid monthly."),
)


def upgrade() -> None:
    for statement in (
        "CREATE TYPE feedback_rating AS ENUM ('up', 'down')",
        # A guest's opinion of one reply (spec P5). Append-only by privilege: nobody is granted UPDATE or DELETE, and
        # the latest row per guest and turn is the guest's feedback. The API caps a comment at 1000 characters;
        # tokenising can lengthen it, hence the wider limit here.
        "CREATE TABLE chat_feedback ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " tenant_id uuid NOT NULL REFERENCES tenants(id),"
        " turn_id uuid NOT NULL REFERENCES chat_turns(id),"
        " guest_id uuid NOT NULL REFERENCES guests(id),"
        " rating feedback_rating NOT NULL,"
        " comment_redacted text NULL CONSTRAINT ck_chat_feedback_comment_length CHECK (char_length(comment_redacted) <= 4000),"
        " created_at timestamptz NOT NULL DEFAULT now())",
        "CREATE INDEX ix_chat_feedback_turn ON chat_feedback (turn_id, created_at DESC)",
        # ledger_app gets SELECT and INSERT from 0003's default privileges, ledger_demo SELECT from 0013's.
        "GRANT INSERT ON chat_feedback TO ledger_demo",
        # documents is append-only (its trigger rejects UPDATE), so the one-line description lives beside it (spec D9).
        "CREATE TABLE document_descriptions ("
        " document_id uuid PRIMARY KEY REFERENCES documents(id),"
        " description text NOT NULL CONSTRAINT ck_document_descriptions_length CHECK (char_length(description) BETWEEN 1 AND 200),"
        " created_at timestamptz NOT NULL DEFAULT now())",
    ):
        op.execute(statement)
    insert = sa.text("INSERT INTO document_descriptions (document_id, description) "
                     "SELECT id, :description FROM documents WHERE document_key = :document_key")
    for document_key, description in DESCRIPTIONS:
        op.get_bind().execute(insert, {"document_key": document_key, "description": description})


def downgrade() -> None:
    op.execute("DROP TABLE document_descriptions")
    op.execute("DROP TABLE chat_feedback")
    op.execute("DROP TYPE feedback_rating")
```

- [ ] **Step 4: Add the models.** In `app/assistant/models.py`, after `ChatOutcome`:

```python
class FeedbackRating(str, enum.Enum):
    up = "up"
    down = "down"
```

and at the end of the file:

```python
class ChatFeedback(Base):
    """A guest's opinion of one reply. Insert-only: the latest row per guest and turn wins (spec P5 D1)."""
    __tablename__ = "chat_feedback"
    __mapper_args__ = {"eager_defaults": True}
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    turn_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chat_turns.id"), nullable=False)
    guest_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("guests.id"), nullable=False)
    rating: Mapped[FeedbackRating] = mapped_column(SAEnum(FeedbackRating, name="feedback_rating", native_enum=True), nullable=False)
    comment_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
```

In `app/documents/models.py`, at the end of the file (reuse the file's existing imports and its `_created_at()` helper):

```python
class DocumentDescription(Base):
    """One line saying what a document is. Beside documents, not on it: documents is append-only (spec P8 D9)."""
    __tablename__ = "document_descriptions"
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"), primary_key=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()
```

- [ ] **Step 5: Migrate the local databases** — `./scripts/db_up.sh` (from `backend/`). Expected: ends without error; `ledger_dev` and `ledger_test` are at `0015_feedback_descriptions`.

- [ ] **Step 6: Run the suite** — `pytest -q` → all pass, including `tests/test_migrations.py` (upgrade, downgrade, upgrade) and the new test.

- [ ] **Step 7: Commit**

```bash
git add backend/alembic/versions/0015_feedback_descriptions.py backend/app/assistant/models.py backend/app/documents/models.py backend/tests/test_demo_role.py
git commit -m "feat(db): chat_feedback and document_descriptions tables (migration 0015)"
```

**REVIEW CHECKPOINT 4.**

### Task 5: The final chat event carries the turn id

**Files:**
- Modify: `backend/app/assistant/service.py`, `frontend/src/api.ts`, `frontend/src/screens/Chat.tsx`
- Test: `backend/tests/test_api_chat.py`

**Interfaces:**
- Produces: every `answer`, `refused` and `clarify` event's data has `"turn_id": "<uuid>"`, the id of the `chat_turns` row saved for that turn. `progress`, `unvalidated` and `error` are unchanged. Frontend: `Turn.turnId: string | null`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_api_chat.py`)

```python
def test_the_final_event_names_the_saved_turn(client, session_factory, db_session, tenant_id):
    model = ScriptedChatModel(replies=[
        AIMessage(content="", tool_calls=[{"name": "search_contracts", "args": {"query": "donations"}, "id": "c1"}]),
        AIMessage(content="done"),
        Answer(text="", citations=[], refused=True),
    ])
    _override(client, _runtime(model, RecordingEmbeddings(), InMemoryVectorIndex()), session_factory)
    kind, data = _events(client.post("/chat", json={"session_id": "s-turn-id", "message": "Donations?"}))[-1]
    turn = db_session.scalars(select(ChatTurn).where(ChatTurn.session_id == "s-turn-id")).one()
    assert kind == "refused" and data["turn_id"] == str(turn.id)
```

- [ ] **Step 2: Run it and see it fail** — `pytest tests/test_api_chat.py -q` → `KeyError: 'turn_id'`.

- [ ] **Step 3: Implement.** In `run_turn` (`app/assistant/service.py`), directly after the line `record["id"] = turn_id`, add:

```python
        def final(kind: Literal["answer", "refused", "clarify"], text: str, citations: list[dict]) -> TurnEvent:
            """The event that ends a turn. It names the turn so the client can attach feedback to it (spec P5 D5)."""
            return TurnEvent(kind, {"text": text, "citations": citations, "turn_id": str(turn_id)})
```

Then replace each of the six final `yield` statements, keeping everything around them:

| Today | Replace with |
|---|---|
| `yield TurnEvent("refused", {"text": NOT_COMPARABLE_TEXT.format(reason=notices[-1]), "citations": [citation]})` | `yield final("refused", NOT_COMPARABLE_TEXT.format(reason=notices[-1]), [citation])` |
| `yield TurnEvent("refused", {"text": text, "citations": [citation]})` | `yield final("refused", text, [citation])` |
| `yield TurnEvent("clarify", {"text": text, "citations": []})` | `yield final("clarify", text, [])` |
| `yield TurnEvent("answer", {"text": text, "citations": shown})` | `yield final("answer", text, shown)` |
| the timeout `yield TurnEvent("refused", {"text": "That took too long; please try a narrower question.", "citations": record["citations"]})` | `yield final("refused", "That took too long; please try a narrower question.", record["citations"])` |
| the step-limit `yield TurnEvent("refused", {"text": "I couldn't settle on an answer within my step limit.", "citations": record["citations"]})` | `yield final("refused", "I couldn't settle on an answer within my step limit.", record["citations"])` |

Leave the `error` event as it is.

- [ ] **Step 4: Run the backend suite** — `pytest -q`. One existing test compares a whole final-event dict; if a test fails only because `turn_id` is now present, change that assertion to compare `data["text"]` and `data["citations"]` and report it at the checkpoint. Expected: all pass.

- [ ] **Step 5: Frontend types.** In `frontend/src/api.ts` change the final-event line of `ChatEvent` to:

```ts
  | { type: 'answer' | 'refused' | 'clarify'; data: { text: string; citations: Citation[]; turn_id: string } }
```

In `frontend/src/screens/Chat.tsx`: add `turnId: string | null;` to the `Turn` type; add `turnId: null` to the object pushed in `ask`; and change the last branch of `onEvent` to:

```ts
      else updateLast({ outcome: event.type, text: event.data.text, citations: event.data.citations, turnId: event.data.turn_id });
```

- [ ] **Step 6: Frontend checks** — `npm test`, `npm run build`, `npm run lint` → clean.

- [ ] **Step 7: Commit**

```bash
git add backend/app/assistant/service.py backend/tests/test_api_chat.py frontend/src/api.ts frontend/src/screens/Chat.tsx
git commit -m "feat(assistant): the final chat event names the saved turn"
```

**REVIEW CHECKPOINT 5.**

### Task 6: Record feedback

**Files:**
- Create: `backend/app/assistant/feedback.py`, `backend/tests/test_chat_feedback.py`
- Modify: `backend/app/assistant/dao.py`, `backend/app/errors.py`, `backend/app/routes/chat.py`

**Interfaces:**
- Consumes: `ChatFeedback`, `FeedbackRating` (Task 4).
- Produces: `POST /chat/turns/{turn_id}/feedback`, body `{"rating": "up" | "down", "comment"?: string up to 1000}`, answering 201 `{"id": "<uuid>"}`; 400 without a known guest; 404 for an unknown turn or another guest's turn; 429 at the sixth row for one guest and turn; 422 for a bad body.

- [ ] **Step 1: Write the failing tests** — create `backend/tests/test_chat_feedback.py`:

```python
import uuid

import psycopg
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from app import config
from app.assistant.models import ChatFeedback, ChatOutcome, ChatTurn, FeedbackRating
from app.ledger.db import make_session_factory


def _guest(client) -> dict[str, str]:
    return {"X-Guest-Id": client.post("/guests").json()["id"]}


def _turn(db_session, tenant_id, headers: dict[str, str]) -> uuid.UUID:
    turn = ChatTurn(tenant_id=tenant_id, session_id=f"s-{uuid.uuid4().hex[:8]}", question_redacted="q", answer_redacted="a",
                    citations=[], retrieved=[], outcome=ChatOutcome.answered, model_id="m", prompt_version="p",
                    graph_version="v2", guest_id=uuid.UUID(headers["X-Guest-Id"]), input_tokens=0, output_tokens=0, latency_ms=1)
    db_session.add(turn)
    db_session.commit()
    return turn.id


def _rows(db_session, turn_id: uuid.UUID) -> list[ChatFeedback]:
    return list(db_session.scalars(select(ChatFeedback).where(ChatFeedback.turn_id == turn_id).order_by(ChatFeedback.created_at)))


def test_a_thumb_is_saved_at_once_and_the_latest_row_wins(client, db_session, tenant_id):
    guest = _guest(client)
    turn_id = _turn(db_session, tenant_id, guest)
    first = client.post(f"/chat/turns/{turn_id}/feedback", headers=guest, json={"rating": "up"})
    assert first.status_code == 201 and uuid.UUID(first.json()["id"])
    assert client.post(f"/chat/turns/{turn_id}/feedback", headers=guest, json={"rating": "down", "comment": "Wrong tier."}).status_code == 201
    rows = _rows(db_session, turn_id)
    assert [(r.rating, r.comment_redacted) for r in rows] == [(FeedbackRating.up, None), (FeedbackRating.down, "Wrong tier.")]
    assert rows[-1].guest_id == uuid.UUID(guest["X-Guest-Id"]) and rows[-1].tenant_id == tenant_id


def test_feedback_needs_a_known_guest(client, db_session, tenant_id):
    turn_id = _turn(db_session, tenant_id, _guest(client))
    assert client.post(f"/chat/turns/{turn_id}/feedback", json={"rating": "up"}).status_code == 400
    assert client.post(f"/chat/turns/{turn_id}/feedback", headers={"X-Guest-Id": str(uuid.uuid4())}, json={"rating": "up"}).status_code == 400


def test_an_unknown_turn_or_another_guests_turn_is_not_found(client, db_session, tenant_id):
    owner, other = _guest(client), _guest(client)
    turn_id = _turn(db_session, tenant_id, owner)
    assert client.post(f"/chat/turns/{uuid.uuid4()}/feedback", headers=owner, json={"rating": "up"}).status_code == 404
    assert client.post(f"/chat/turns/{turn_id}/feedback", headers=other, json={"rating": "up"}).status_code == 404
    assert _rows(db_session, turn_id) == []


def test_the_sixth_row_for_one_turn_is_refused(client, db_session, tenant_id):
    guest = _guest(client)
    turn_id = _turn(db_session, tenant_id, guest)
    codes = [client.post(f"/chat/turns/{turn_id}/feedback", headers=guest, json={"rating": "up"}).status_code for _ in range(6)]
    assert codes == [201] * 5 + [429]
    assert len(_rows(db_session, turn_id)) == 5


def test_a_comment_is_tokenised_and_a_blank_one_is_stored_as_null(client, db_session, tenant_id):
    guest = _guest(client)
    turn_id = _turn(db_session, tenant_id, guest)
    client.post(f"/chat/turns/{turn_id}/feedback", headers=guest, json={"rating": "down", "comment": "Mail me at bob@example.com"})
    client.post(f"/chat/turns/{turn_id}/feedback", headers=guest, json={"rating": "down", "comment": "   "})
    tokenised, blank = _rows(db_session, turn_id)
    assert "bob@example.com" not in tokenised.comment_redacted and "<EMAIL_ADDRESS_" in tokenised.comment_redacted
    assert blank.comment_redacted is None


@pytest.mark.parametrize("body", [
    {"rating": "meh"}, {}, {"rating": "up", "comment": "x" * 1001}, {"rating": "up", "extra": 1},
])
def test_a_bad_body_is_rejected(client, db_session, tenant_id, body):
    guest = _guest(client)
    turn_id = _turn(db_session, tenant_id, guest)
    assert client.post(f"/chat/turns/{turn_id}/feedback", headers=guest, json=body).status_code == 422


def test_the_demo_role_can_insert_feedback_but_not_change_it(client, db_session, tenant_id, migrated_test_database):
    guest = _guest(client)
    turn_id = _turn(db_session, tenant_id, guest)
    demo = make_session_factory(config.TEST_DEMO_DATABASE_URL)()
    try:
        demo.add(ChatFeedback(tenant_id=tenant_id, turn_id=turn_id, guest_id=uuid.UUID(guest["X-Guest-Id"]), rating=FeedbackRating.up))
        demo.commit()
        with pytest.raises(ProgrammingError) as caught:
            demo.execute(text("UPDATE chat_feedback SET rating = 'down' WHERE turn_id = :t"), {"t": turn_id})
        assert isinstance(caught.value.orig, psycopg.errors.InsufficientPrivilege)
    finally:
        demo.rollback()
        demo.close()
```

- [ ] **Step 2: Run them and see them fail** — `pytest tests/test_chat_feedback.py -q` → every request answers 404 or 405 (no route yet).

- [ ] **Step 3: Errors.** Append to `app/errors.py`:

```python
class TurnNotFound(DomainError):
    """The chat turn does not exist, or belongs to another guest: both look the same to the caller."""

    status = 404
    type_slug = "turn-not-found"
    title = "Chat turn not found"


class FeedbackLimitReached(DomainError):
    """One guest may leave a few rows per reply (a thumb, a comment, a change of mind), not an unbounded number."""

    status = 429
    type_slug = "feedback-limit"
    title = "Too much feedback on one answer"

    def __init__(self) -> None:
        super().__init__("This answer already has the maximum number of feedback entries.")
```

- [ ] **Step 4: DAO.** Add to `app/assistant/dao.py` (extend the models import to `from app.assistant.models import ChatFeedback, ChatTurn, Guest`):

```python
def find_turn(session: Session, tenant_id: uuid.UUID, turn_id: uuid.UUID) -> ChatTurn | None:
    turn = session.get(ChatTurn, turn_id)
    return turn if turn is not None and turn.tenant_id == tenant_id else None


def count_feedback(session: Session, guest_id: uuid.UUID, turn_id: uuid.UUID) -> int:
    return session.scalar(select(func.count()).select_from(ChatFeedback).where(
        ChatFeedback.guest_id == guest_id, ChatFeedback.turn_id == turn_id))


def add_feedback(session: Session, feedback: ChatFeedback) -> uuid.UUID:
    session.add(feedback)
    session.commit()
    return feedback.id
```

- [ ] **Step 5: The function.** Create `app/assistant/feedback.py`:

```python
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.assistant import dao
from app.assistant.models import ChatFeedback, FeedbackRating
from app.documents import dao as documents_dao
from app.errors import FeedbackLimitReached, TurnNotFound

MAX_COMMENT_LENGTH = 1000
# A thumb, a comment and a change of mind fit; chat itself is rate-limited, so this bounds what one guest can write.
MAX_FEEDBACK_PER_TURN = 5


@dataclass(frozen=True)
class FeedbackInput:
    tenant_id: uuid.UUID
    guest_id: uuid.UUID
    turn_id: uuid.UUID
    rating: FeedbackRating
    comment: str | None = None


def record_feedback(session: Session, feedback: FeedbackInput, hmac_key: str, vault_key: str) -> uuid.UUID:
    """Append one feedback row for the guest's own turn. Rows are never changed: the latest one wins (spec P5 D1)."""
    turn = dao.find_turn(session, feedback.tenant_id, feedback.turn_id)
    if turn is None or turn.guest_id != feedback.guest_id:
        raise TurnNotFound(f"Chat turn {feedback.turn_id} does not exist.")
    if dao.count_feedback(session, feedback.guest_id, feedback.turn_id) >= MAX_FEEDBACK_PER_TURN:
        raise FeedbackLimitReached()
    comment = (feedback.comment or "").strip()
    redacted = documents_dao.tokenize_known_values(session, feedback.tenant_id, comment, hmac_key, vault_key) if comment else None
    return dao.add_feedback(session, ChatFeedback(
        tenant_id=feedback.tenant_id, turn_id=feedback.turn_id, guest_id=feedback.guest_id,
        rating=feedback.rating, comment_redacted=redacted))
```

- [ ] **Step 6: The route.** In `app/routes/chat.py` add the imports

```python
from sqlalchemy.orm import Session, sessionmaker

from app.assistant.feedback import MAX_COMMENT_LENGTH, FeedbackInput, record_feedback
from app.assistant.models import FeedbackRating
from app.deps import get_guest_id, get_overlay_guest, get_session, get_tenant_id, limit_chat
from app.errors import GuestRequired
```

(replacing the two existing lines they extend) and append:

```python
class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: FeedbackRating
    comment: Annotated[str, StringConstraints(max_length=MAX_COMMENT_LENGTH)] | None = None


class FeedbackOut(BaseModel):
    id: uuid.UUID


@router.post("/turns/{turn_id}/feedback", status_code=201, response_model=FeedbackOut)
def give_feedback(
    turn_id: uuid.UUID,
    body: FeedbackIn,
    session: Annotated[Session, Depends(get_session)],
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    guest_id: Annotated[uuid.UUID | None, Depends(get_guest_id)],
) -> FeedbackOut:
    if guest_id is None:
        raise GuestRequired("Send the X-Guest-Id of a known guest (POST /guests) to give feedback.")
    feedback = FeedbackInput(tenant_id=tenant_id, guest_id=guest_id, turn_id=turn_id, rating=body.rating, comment=body.comment)
    return FeedbackOut(id=record_feedback(session, feedback, config.require("PII_HMAC_KEY"), config.require("PII_VAULT_KEY")))
```

- [ ] **Step 7: Run** — `pytest tests/test_chat_feedback.py -q` → all pass; then `pytest -q` → all pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/assistant/feedback.py backend/app/assistant/dao.py backend/app/errors.py backend/app/routes/chat.py backend/tests/test_chat_feedback.py
git commit -m "feat(assistant): record a guest's feedback on a chat turn"
```

**REVIEW CHECKPOINT 6.**

### Task 7: Document descriptions in the list

**Files:**
- Modify: `backend/app/documents/dao.py`, `backend/app/routes/documents.py`, `frontend/src/api.ts`, `frontend/src/components/workspace/DocumentCards.tsx`, `frontend/src/components/workspace/Workspace.css`, `frontend/src/screens/Documents.tsx`, `frontend/src/screens/Documents.css`
- Test: `backend/tests/test_documents_api.py`

**Interfaces:**
- Consumes: `DocumentDescription` (Task 4).
- Produces: `GET /documents` and `GET /documents/{id}` items gain `description: string | null`. Frontend: `DocumentSummary.description: string | null`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_documents_api.py`)

```python
def test_the_list_and_the_detail_carry_the_description_when_there_is_one(client, db_session):
    from app.documents.models import DocumentDescription
    document_id = _post(client).json()["document_id"]
    assert client.get("/documents").json()[0]["description"] is None
    db_session.add(DocumentDescription(document_id=uuid.UUID(document_id), description="A household agreement."))
    db_session.commit()
    assert client.get("/documents").json()[0]["description"] == "A household agreement."
    assert client.get(f"/documents/{document_id}").json()["description"] == "A household agreement."
```

- [ ] **Step 2: Run it and see it fail** — `pytest tests/test_documents_api.py -q` → `KeyError: 'description'`.

- [ ] **Step 3: Backend.** In `app/documents/dao.py` add `DocumentDescription` to the models import, add a last field to `DocumentRow`:

```python
    description: str | None = None
```

and replace the last line of `_row` with:

```python
    description = session.scalar(select(DocumentDescription.description).where(DocumentDescription.document_id == document.id))
    return DocumentRow(document, version, version_events(session, version.id), count, description)
```

In `app/routes/documents.py` add `description: str | None` to `DocumentOut` (after `status_note`) and `description=row.description,` to the dict in `_out`.

- [ ] **Step 4: Run** — `pytest -q` → all pass.

- [ ] **Step 5: Frontend.** In `frontend/src/api.ts` add to `DocumentSummary`, after `status_note`:

```ts
  description: string | null;
```

In `DocumentCards.tsx`, between the title span and the meta span:

```tsx
            {d.description && <span className="ws-card__description">{d.description}</span>}
```

In `Workspace.css`, change `flex: 0 0 220px` in `.ws-card` to `flex: 0 0 260px` and add after `.ws-card__title`:

```css
.ws-card__description { display: block; margin: 2px 0 4px; color: var(--color-text-secondary); font-size: 0.85em; line-height: 1.35; }
```

In `Documents.tsx`, directly after the `documents__name` div (the one with `title={doc.title}`):

```tsx
                        {doc.description && <div className="documents__description">{doc.description}</div>}
```

In `Documents.css`, after the `.documents__name` rule:

```css
.documents__description {
  font-size: 12px;
  color: var(--color-text-secondary);
  white-space: normal;
  max-width: 60ch;
}
```

- [ ] **Step 6: Frontend checks** — `npm test`, `npm run build`, `npm run lint` → clean. If `npm run build` reports an object literal of type `DocumentSummary` missing `description` (a test fixture), add `description: null` to that literal and report it.

- [ ] **Step 7: Commit**

```bash
git add backend/app/documents/dao.py backend/app/routes/documents.py backend/tests/test_documents_api.py frontend/src/api.ts frontend/src/components/workspace/DocumentCards.tsx frontend/src/components/workspace/Workspace.css frontend/src/screens/Documents.tsx frontend/src/screens/Documents.css
git commit -m "feat(documents): a one-line description per document in the list and on the cards"
```

**REVIEW CHECKPOINT 7.**

### Task 8: Starter questions follow the selected document

**Files:**
- Create: `frontend/src/lib/starters.json`, `frontend/src/lib/starters.ts`, `frontend/src/lib/starters.test.ts`, `backend/tests/test_starters_are_golden.py`
- Modify: `frontend/src/screens/Chat.tsx`

**Interfaces:**
- Produces: `startersFor(documents: DocumentSummary[], scopeId: string | null): string[]`.

- [ ] **Step 1: The data.** Create `frontend/src/lib/starters.json` (keys are `document_key`; the first question of each list is the one shown when no document is selected):

```json
{
  "tremblay-ima": [
    "What is the fee schedule in the Tremblay agreement?",
    "How many days of notice are needed to terminate the Tremblay agreement?",
    "Which law governs the Tremblay agreement?"
  ],
  "calamos-emerging-market-equity": [
    "What is the Calamos Emerging Market Equity Fund's rate in excess of $26 billion?",
    "What rate applies to the first $500 million of the Calamos Emerging Market Equity Fund's assets?",
    "What are the Calamos Emerging Market Equity Fund's fees calculated on?"
  ],
  "aim-global-trends-advisory": [
    "What annual rate applies to the first $500 million for AIM Global Trends Fund?",
    "How many days of notice are needed to terminate the AIM Global Trends Fund agreement?",
    "What is the full fee schedule for AIM Global Trends Fund?"
  ],
  "nomura-tax-free-colorado-ima": [
    "What is the fee schedule for the Nomura Tax-Free Colorado Fund?",
    "What rate applies to the Nomura Tax-Free Colorado Fund's assets in excess of $2.5 billion?",
    "How often is the management fee paid for the Nomura Tax-Free Colorado Fund?"
  ]
}
```

- [ ] **Step 2: Write the failing tests.** Create `frontend/src/lib/starters.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import type { DocumentSummary } from '../api';
import { STARTERS, startersFor } from './starters';

function doc(id: string, key: string, status: DocumentSummary['status'] = 'ready'): DocumentSummary {
  return {
    id, document_key: key, title: key, source_url: null, version: 1, version_id: `v-${id}`, page_count: 2, byte_size: 1,
    file_sha256: 'x', uploaded_at: '2026-10-01T00:00:00Z', element_count: 1, status, status_note: null, description: null,
    events: [],
  };
}

const DOCS = [doc('1', 'tremblay-ima'), doc('2', 'calamos-emerging-market-equity'), doc('3', 'unknown-key'), doc('4', 'aim-global-trends-advisory', 'processing')];

describe('startersFor', () => {
  it('shows the first question of each ready document when none is selected', () => {
    expect(startersFor(DOCS, null)).toEqual([STARTERS['tremblay-ima'][0], STARTERS['calamos-emerging-market-equity'][0]]);
  });

  it("shows the selected document's own questions", () => {
    expect(startersFor(DOCS, '2')).toEqual(STARTERS['calamos-emerging-market-equity']);
  });

  it('shows nothing for a selected document without starters', () => {
    expect(startersFor(DOCS, '3')).toEqual([]);
  });

  it('shows at most four when no document is selected', () => {
    const many = ['a', 'b', 'c', 'd', 'e'].map((id) => doc(id, 'tremblay-ima'));
    expect(startersFor(many, null)).toHaveLength(4);
  });

  it('shows nothing before the documents have loaded', () => {
    expect(startersFor([], '2')).toEqual([]);
  });
});
```

Create `backend/tests/test_starters_are_golden.py`:

```python
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_every_starter_question_is_an_answerable_scoped_golden_case():
    """A starter is a promise that the demo answers it, so each one is measured by the eval gate, scoped too."""
    starters = json.loads((ROOT / "frontend/src/lib/starters.json").read_text())
    golden = {case["question"]: case for case in json.loads((ROOT / "backend/tests/eval/golden.json").read_text())}
    for document_key, questions in starters.items():
        for question in questions:
            case = golden.get(question)
            assert case is not None, f"not in golden.json: {question}"
            assert (case["category"], case["expect"], case.get("retrieval"), case.get("scoped")) == ("answerable", "answer", True, True), question
            assert case["expect_document"] == document_key, question
```

- [ ] **Step 3: Run and see the frontend test fail** — `npm test` → cannot resolve `./starters`. The backend test passes already (Task 2 added the cases): `pytest tests/test_starters_are_golden.py -q` → 1 passed.

- [ ] **Step 4: Implement** `frontend/src/lib/starters.ts`:

```ts
import type { DocumentSummary } from '../api';
import starters from './starters.json';

// Every question here is an answerable case in backend/tests/eval/golden.json (backend test_starters_are_golden).
export const STARTERS: Record<string, string[]> = starters;
const MAX_UNSCOPED = 4;

/** The selected document's questions, or one per ready document when none is selected. */
export function startersFor(documents: DocumentSummary[], scopeId: string | null): string[] {
  const ready = documents.filter((d) => d.status === 'ready');
  if (scopeId !== null) return STARTERS[ready.find((d) => d.id === scopeId)?.document_key ?? ''] ?? [];
  return ready.flatMap((d) => (STARTERS[d.document_key] ?? []).slice(0, 1)).slice(0, MAX_UNSCOPED);
}
```

If `npm run build` rejects the JSON import, add `"resolveJsonModule": true` to `compilerOptions` in `frontend/tsconfig.app.json` and report it.

- [ ] **Step 5: Wire it into `Chat.tsx`.** Delete the `SUGGESTED_QUESTIONS` constant. Add `import { startersFor } from '../lib/starters';`. After the line `const scoped = documents.find(...)` add:

```ts
  const starters = startersFor(documents, scopeId);
```

Change the condition `{turns.length === 0 && (` to `{turns.length === 0 && starters.length > 0 && (` and `SUGGESTED_QUESTIONS.map` to `starters.map`.

- [ ] **Step 6: Checks** — `npm test`, `npm run build`, `npm run lint` → clean; `pytest -q` → all pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/starters.json frontend/src/lib/starters.ts frontend/src/lib/starters.test.ts frontend/src/screens/Chat.tsx backend/tests/test_starters_are_golden.py
git commit -m "feat(chat): starter questions follow the selected document"
```

(Add `frontend/tsconfig.app.json` to the commit only if Step 4 needed it.)

**REVIEW CHECKPOINT 8.**

### Task 9: A citation opens the in-app viewer

**Files:**
- Modify: `frontend/src/lib/viewer.ts`, `frontend/src/lib/viewer.test.ts`, `frontend/src/api.ts`, `frontend/src/screens/Chat.tsx`, `frontend/src/screens/Chat.css`

**Interfaces:**
- Produces: `ViewerTarget { documentId: string; version: number; page: number; title: string }` and `citationTarget(citation: Citation): ViewerTarget | null` in `lib/viewer.ts`.

- [ ] **Step 1: Write the failing tests** (append to `viewer.test.ts`; add `citationTarget` to its import)

```ts
describe('citationTarget', () => {
  const element = { id: 'e1', kind: 'element' as const, document_id: 'd1', document_title: 'Tremblay IMA', version: 2, page: 3 };

  it('points at the cited page of the cited version', () => {
    expect(citationTarget(element)).toEqual({ documentId: 'd1', version: 2, page: 3, title: 'Tremblay IMA' });
  });

  it('has no target for a citation without a page (system and tool citations)', () => {
    expect(citationTarget({ id: 'system', kind: 'system', source: 'indexed contracts' })).toBeNull();
    expect(citationTarget({ ...element, page: undefined })).toBeNull();
    expect(citationTarget({ ...element, document_id: undefined })).toBeNull();
  });

  it('falls back to a generic title', () => {
    expect(citationTarget({ ...element, document_title: undefined })?.title).toBe('Document');
  });
});
```

- [ ] **Step 2: Run and see them fail** — `npm test` → `citationTarget` is not exported.

- [ ] **Step 3: Implement.** In `frontend/src/api.ts` add to `Citation`, after `kind`:

```ts
  document_id?: string;
```

Append to `frontend/src/lib/viewer.ts` (add `import type { Citation } from '../api';` at the top):

```ts
export interface ViewerTarget {
  documentId: string;
  version: number;
  page: number;
  title: string;
}

/** Where "Open page" goes. Null for a citation that names no page (system reasons, tool results). */
export function citationTarget(citation: Citation): ViewerTarget | null {
  if (!citation.document_id || citation.version === undefined || citation.page === undefined) return null;
  return { documentId: citation.document_id, version: citation.version, page: citation.page, title: citation.document_title ?? 'Document' };
}
```

- [ ] **Step 4: Wire `CitationCard` in `Chat.tsx`.** Add `import { citationTarget, type ViewerTarget } from '../lib/viewer';` and remove `fileUrl` from the `'../api'` import. Replace the props interface and the top and foot of `CitationCard`:

```tsx
interface CitationCardProps {
  citation: Citation;
  onOpen(target: ViewerTarget): void;
}

function CitationCard({ citation, onOpen }: CitationCardProps) {
  const target = citationTarget(citation);
```

```tsx
      <div className="citation-card__foot">
        <span className="mono">{citation.id}</span>
        {target && (
          <button type="button" className="citation-card__open" onClick={() => onOpen(target)}>
            Open page →
          </button>
        )}
      </div>
```

Change the `viewer` state's type to `ViewerTarget | null` (`useState<ViewerTarget | null>(null)`), and pass `onOpen={setViewer}` to both `<CitationCard ... />` usages.

In `Chat.css` replace the `.citation-card__foot a` rule with:

```css
.citation-card__open {
  border: 0;
  background: none;
  padding: 0;
  font-size: 12px;
  font-weight: 500;
  color: var(--color-accent);
  cursor: pointer;
}

.citation-card__open:hover {
  color: var(--color-accent-hover);
}
```

- [ ] **Step 5: Checks** — `npm test`, `npm run build`, `npm run lint` → clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/viewer.ts frontend/src/lib/viewer.test.ts frontend/src/api.ts frontend/src/screens/Chat.tsx frontend/src/screens/Chat.css
git commit -m "feat(chat): a citation opens its page in the in-app viewer"
```

**REVIEW CHECKPOINT 9.**

### Task 10: The feedback control

**Files:**
- Create: `frontend/src/components/FeedbackControl.tsx`, `frontend/src/components/FeedbackControl.css`, `frontend/e2e/demo-feedback.e2e.ts`
- Modify: `frontend/src/api.ts`, `frontend/src/api.test.ts`, `frontend/src/components/Icons.tsx`, `frontend/src/screens/Chat.tsx`

**Interfaces:**
- Consumes: `Turn.turnId` (Task 5); `POST /chat/turns/{turn_id}/feedback` (Task 6).
- Produces: `sendFeedback(turnId: string, rating: FeedbackRating, comment?: string): Promise<{ id: string }>`; `<FeedbackControl turnId={string} />`.

- [ ] **Step 1: Write the failing API tests** (append to `api.test.ts`; add `sendFeedback` to its import)

```ts
it('posts a rating, and the comment only when there is one', async () => {
  const calls = respondWith({ id: 'f1' }, 201);
  await sendFeedback('t1', 'up');
  await sendFeedback('t1', 'down', 'Wrong tier.');
  const posts = calls.filter((call) => call.url === `${API_BASE}/chat/turns/t1/feedback`);
  expect(posts.map((call) => JSON.parse(String(call.init?.body)))).toEqual([{ rating: 'up' }, { rating: 'down', comment: 'Wrong tier.' }]);
  expect(posts[0].init?.method).toBe('POST');
});

it('rejects when the feedback is refused', async () => {
  respondWith({ detail: 'Chat turn t1 does not exist.' }, 404);
  await expect(sendFeedback('t1', 'up')).rejects.toThrow('does not exist');
});
```

- [ ] **Step 2: Run and see them fail** — `npm test` → `sendFeedback` is not exported.

- [ ] **Step 3: API.** Add to `frontend/src/api.ts`, after `streamChat`:

```ts
export type FeedbackRating = 'up' | 'down';

/** One row per call: a thumb, then optionally the same thumb with a comment. The latest row is the guest's feedback. */
export async function sendFeedback(turnId: string, rating: FeedbackRating, comment?: string): Promise<{ id: string }> {
  const response = await fetch(`${API_BASE}/chat/turns/${turnId}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await guestHeaders()) },
    body: JSON.stringify(comment ? { rating, comment } : { rating }),
  });
  return json<{ id: string }>(response);
}
```

- [ ] **Step 4: Icons.** Append to `frontend/src/components/Icons.tsx`:

```tsx
export function ThumbUpIcon({ size = 16, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M7 10v12" />
      <path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z" />
    </svg>
  );
}

export function ThumbDownIcon({ size = 16, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M17 14V2" />
      <path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z" />
    </svg>
  );
}
```

- [ ] **Step 5: The component.** Create `frontend/src/components/FeedbackControl.tsx`:

```tsx
import { useState, type FormEvent } from 'react';
import { type FeedbackRating, sendFeedback } from '../api';
import { ThumbDownIcon, ThumbUpIcon } from './Icons';
import './FeedbackControl.css';

const MAX_COMMENT_LENGTH = 1000; // same cap as the API

interface FeedbackControlProps {
  turnId: string;
}

type Status = 'idle' | 'saving' | 'saved' | 'comment-saved' | 'failed';

const MESSAGES: Partial<Record<Status, string>> = {
  saved: 'Feedback saved',
  'comment-saved': 'Comment saved',
  failed: "Couldn't save your feedback. Try again.",
};

/** Thumbs under a reply. A click saves at once; a comment or the other thumb saves a new row, and the latest wins. */
export function FeedbackControl({ turnId }: FeedbackControlProps) {
  const [rating, setRating] = useState<FeedbackRating | null>(null);
  const [comment, setComment] = useState('');
  const [status, setStatus] = useState<Status>('idle');
  const saving = status === 'saving';

  const save = async (next: FeedbackRating, text?: string) => {
    setStatus('saving');
    try {
      await sendFeedback(turnId, next, text);
      setRating(next);
      if (text) setComment('');
      setStatus(text ? 'comment-saved' : 'saved');
    } catch {
      setStatus('failed');
    }
  };

  const submitComment = (event: FormEvent) => {
    event.preventDefault();
    if (rating && comment.trim()) void save(rating, comment.trim());
  };

  return (
    <div className="feedback">
      <div className="feedback__row">
        <span className="feedback__label">Was this helpful?</span>
        <button type="button" className="feedback__thumb" aria-label="Good answer" aria-pressed={rating === 'up'} disabled={saving} onClick={() => void save('up')}>
          <ThumbUpIcon size={15} />
        </button>
        <button type="button" className="feedback__thumb" aria-label="Bad answer" aria-pressed={rating === 'down'} disabled={saving} onClick={() => void save('down')}>
          <ThumbDownIcon size={15} />
        </button>
        <span className={`feedback__status${status === 'failed' ? ' feedback__status--failed' : ''}`} role="status">
          {MESSAGES[status] ?? ''}
        </span>
      </div>
      {rating && (
        <form className="feedback__comment" onSubmit={submitComment}>
          <input
            type="text"
            className="feedback__input"
            aria-label="Add a comment (optional)"
            placeholder="Add a comment (optional)"
            maxLength={MAX_COMMENT_LENGTH}
            value={comment}
            onChange={(event) => setComment(event.target.value)}
          />
          <button type="submit" className="btn btn-secondary feedback__send" disabled={saving || !comment.trim()}>
            Send comment
          </button>
        </form>
      )}
    </div>
  );
}
```

Create `frontend/src/components/FeedbackControl.css`:

```css
.feedback { margin-top: var(--space-2); display: flex; flex-direction: column; gap: 6px; }
.feedback__row { display: flex; align-items: center; gap: 6px; }
.feedback__label, .feedback__status { font-size: 12px; color: var(--color-text-secondary); }
.feedback__status--failed { color: var(--color-text-primary); font-weight: 500; }
.feedback__thumb { display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px;
  border: 1px solid var(--color-border); border-radius: var(--radius-pill); background: var(--color-surface);
  color: var(--color-text-secondary); cursor: pointer; }
.feedback__thumb:hover:not(:disabled) { border-color: var(--color-accent); color: var(--color-accent); }
.feedback__thumb[aria-pressed='true'] { border-color: var(--color-accent); color: var(--color-accent); background: var(--color-accent-tint); }
.feedback__thumb:disabled { cursor: default; opacity: 0.6; }
.feedback__comment { display: flex; gap: 6px; max-width: 520px; }
.feedback__input { flex: 1; min-width: 0; padding: 6px 10px; border: 1px solid var(--color-border);
  border-radius: var(--radius-card); background: var(--color-surface); color: var(--color-text-primary); font-size: 12px; }
.feedback__send { font-size: 12px; }
```

- [ ] **Step 6: Wire it into `Chat.tsx`.** Add `import { FeedbackControl } from '../components/FeedbackControl';`. Directly before the closing `</div>` of the `chat__turn--assistant` block (after the `refused || error` fragment), add:

```tsx
                    {turn.turnId && <FeedbackControl key={turn.turnId} turnId={turn.turnId} />}
```

An `error` turn has no `turnId`, so it gets no control.

- [ ] **Step 7: The end-to-end test.** Create `frontend/e2e/demo-feedback.e2e.ts` (it runs against the deployed site, so do **not** run it; Claude runs it after the deploy):

```ts
import { expect, test } from '@playwright/test';

// Public demo (spec P5 + P8): the first-five-minutes journey. One real chat turn (OpenAI), so a run costs a few cents.
const STARTER = 'What is the fee schedule in the Tremblay agreement?';

test('a guest picks a starter, opens its citation in the app, and leaves feedback', async ({ page, context }) => {
  await page.goto('/chat');
  await expect(page.getByText('The only contract with billing records to compare against.')).toBeVisible();
  await page.getByRole('button', { name: STARTER }).click();
  await expect(page.getByText(/citation\(s\)/)).toBeVisible({ timeout: 120_000 });

  await page.getByRole('button', { name: 'Open page →' }).first().click();
  await expect(page.getByRole('dialog')).toBeVisible();
  expect(context.pages()).toHaveLength(1); // the page opened in the app, not in a new tab
  await page.getByRole('button', { name: 'Close viewer' }).click();

  await page.getByRole('button', { name: 'Good answer' }).click();
  await expect(page.getByText('Feedback saved')).toHaveCount(1);
  await expect(page.getByRole('button', { name: 'Good answer' })).toHaveAttribute('aria-pressed', 'true');
  await page.getByLabel('Add a comment (optional)').fill('Playwright check: the citation opened on the right page.');
  await page.getByRole('button', { name: 'Send comment' }).click();
  await expect(page.getByText('Comment saved')).toBeVisible();
});
```

- [ ] **Step 8: Checks** — `npm test`, `npm run build`, `npm run lint` → clean.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/FeedbackControl.tsx frontend/src/components/FeedbackControl.css frontend/src/components/Icons.tsx frontend/src/api.ts frontend/src/api.test.ts frontend/src/screens/Chat.tsx frontend/e2e/demo-feedback.e2e.ts
git commit -m "feat(chat): thumbs up/down and an optional comment on every reply"
```

**REVIEW CHECKPOINT 10.**

---

# Part C — run by Claude with the user

### Task 11: Rollout and verification

- [ ] **Step 1: Operator runbook (local files, never committed).** `backend/script.demo.md` gains a section "P5 + P8 (migration 0015)" with:
  - the migrate commands and the expected head `0015_feedback_descriptions`;
  - the check queries:
    ```sql
    SELECT to_regclass('public.chat_feedback'), to_regclass('public.document_descriptions');
    SELECT has_table_privilege('ledger_demo', 'chat_feedback', 'INSERT') AS demo_can_insert_feedback,  -- expect t
           has_table_privilege('ledger_demo', 'chat_feedback', 'UPDATE') AS demo_can_update_feedback;  -- expect f
    SELECT count(*) FROM document_descriptions;                                                        -- expect 4
    ```
  - the feedback read query:
    ```sql
    SELECT DISTINCT ON (f.guest_id, f.turn_id)
           f.created_at, left(f.guest_id::text, 8) AS guest, f.rating, f.comment_redacted,
           t.outcome, t.prompt_version, left(t.question_redacted, 80) AS question
    FROM chat_feedback f JOIN chat_turns t ON t.id = f.turn_id
    ORDER BY f.guest_id, f.turn_id, f.created_at DESC;
    ```
  `backend/script.demo.sh`: `check` also runs the three check queries; a new `feedback` subcommand runs the read query; the usage header lists it.
- [ ] **Step 2: Local demo database.** Migrate it (`ENV_FILE=.env.demo`, owner URL) and confirm `SELECT count(*) FROM document_descriptions` is 4.
- [ ] **Step 3: Full local checks.** `pytest -q`; `npm test`, `npm run build`, `npm run lint`; `graphify update .`.
- [ ] **Step 4: Local browser pass** with `E2E_BASE_URL` pointed at the local dev server: both Playwright files.
- [ ] **Step 5: Eval gate once** against the demo configuration, to confirm the final code. Nothing after Part A changes prompts or retrieval. One refused answerable is the known behaviour (backlog X5) and does not block the rollout; anything else does.
- [ ] **Step 6: The user** runs `./script.demo.sh migrate`, then `./script.demo.sh check`, then approves the push; Railway and Vercel deploy.
- [ ] **Step 7: Deployed verification.** curl the feedback route (201, 400 without a guest, 404 for an unknown turn); `npm run test:e2e` (three tests); `./script.demo.sh feedback` shows the Playwright rows. Report what was and was not checked.
- [ ] **Step 8: Changelog.** Tick P5, P8 and the stale-test chore with the results; add the backlog item "a retry that ends in a refusal after sources were found should say the answer couldn't be verified".

```bash
git add CHANGELOG.md artifacts/product-backlog.md
git commit -m "docs(changelog): close P5 + P8 after the deployed verification"
```

## Lenses applied

- **Postgres practice:** insert-only by privilege, one index for the one known join, CHECK constraints at the boundary (Task 4).
- **Data-systems thinking:** an append-only fact table with latest-wins derived at read time; derived values kept out of what the model reads (Tasks 1, 4, 6).
- **Clean architecture:** thin route, one function in `assistant/feedback.py`, DB access only in `dao.py`; UI logic in pure `lib/` functions (Tasks 6, 8, 9).
- **Frontend design:** the control names what it does and reports what happened, in the screen's existing visual language (Task 10).
