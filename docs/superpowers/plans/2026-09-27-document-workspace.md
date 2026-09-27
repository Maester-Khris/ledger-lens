# Document Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **This project:** Gemini executes the tasks in order; Claude reviews at each **REVIEW CHECKPOINT** before the next task starts. Stop at every checkpoint and hand over: commits, test counts, `git status`.

**Goal:** A chat-centred document workspace: guest attribution (N19), chat optionally scoped to one document (N12), a contract profile (N17), disclosure of unconfirmed fields and the not-comparable notice (N11), a per-session audit trail (N13) and a per-document ledger timeline (N14).

**Architecture:** One read endpoint per panel, each owned by one package (`contracts` for terms, `reporting` for the timeline, `governance` for invocations); scoping enforced inside the agent's tools; the chat stream gains one `unvalidated` event and a `system` citation; the React Chat screen becomes a layout with document cards, a scope chip and a tabbed right panel.

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy 2.0 / Alembic / LangGraph; PostgreSQL 18; pytest; React (Vite) + TypeScript.

**Spec:** `docs/superpowers/specs/2026-09-27-document-workspace-design.md` — read it before Task 1.

## Global Constraints

- Read `CLAUDE.md` and `CLAUDE.local.md` first. Backend commands: `/home/niki/Documents/workenv/pydev/bin/<tool>` (below: `$PY`, `$PYTEST`), run from `backend/`. Never create a `.venv`.
- Branch `feat/demo-ready`. Never commit to `main`/`preview`. Stage files explicitly (never `git add -A`/`.`). Conventional commits. **No AI co-author line.** Do not push.
- Layering: routes stay thin (parse → call a package function → return); DB access only in each package's `dao.py`; dependencies point toward `ledger`; the ledger imports no other package.
- Type hints on every Python signature; dataclasses for DTOs; no explicit `session.begin()`.
- TypeScript: no `any`; a props interface for every component; `noUnusedLocals`/`noUnusedParameters` must pass (`npm run build`).
- No new Python dependency, no new npm package.
- Guest id = **attribution, not authentication**: never gate access on it.
- Working labels (from the reframing glossary): "Audit trail", "Awaiting review", "Billing reconciliation", "Every number traced to its source page", "Coming soon".
- Full backend suite after every task: `$PYTEST -q -m "not stress"`. It may rewrite `backend/reports/eval-*.json`; run `git restore backend/reports/eval-*.json` before committing. Run `graphify update .` from the repo root after each task's code changes.
- Existing tests must keep passing unchanged unless a step says otherwise.

## Review Focus

Inputs the spec implies but its tests don't cover; each has a test in the owning task:

1. **Stale guest id after the database is cleared** (Phase 4 re-ingests from an empty DB): the browser still holds an old id → `POST /guests` with that id must return a *new* id, not keep attributing to nothing (Task 1).
2. **An answered turn that also hit "not comparable"**: the system notice must only replace a *refusal*, never a valid answer (Task 6).
3. **Fee bands 10+ sort after band 2**: `field_path` string order puts `fee_tiers[10]` before `fee_tiers[2]`; the profile must order numerically (Task 4).
4. **A rejected AI proposal** appears in the timeline as `decided` with no `posted` item and no crash (Task 10).
5. **Documents still processing or failed** are not offered as scope cards (Task 3); a blocked cross-document tool call still shows in the audit trail (Task 2 asserts it is recorded).

## File Map

Backend
- `alembic/versions/0012_guests_and_turn_scope.py` — create: `guests`, `chat_turns.guest_id`, `chat_turns.document_id`, column-level UPDATE grant.
- `app/assistant/models.py` — modify: `Guest`; `ChatTurn.guest_id`, `ChatTurn.document_id`.
- `app/assistant/dao.py` — modify: `register_guest`, `touch_guest`, `trace_ids`.
- `app/deps.py` — modify: `get_guest_id`, `decided_by`.
- `app/routes/guests.py` — create: `POST /guests`.
- `app/routes/chat.py` — modify: `document_id`, guest, 404.
- `app/assistant/service.py` — modify: guest/document on the turn, turn id, `unvalidated` event, system notice.
- `app/assistant/tools.py` — modify: `ToolContext.document_id`, `ToolOutcome.unvalidated_document_id` / `system_notice`, scope enforcement.
- `app/assistant/contract_tools.py` — modify: scope checks, outcome flags.
- `app/assistant/graph.py` — modify: collect `unvalidated` and `system_notices` in state.
- `app/contracts/terms.py` — create: pure status/reason/label/group logic.
- `app/contracts/dao.py` — modify: `served_fields` reuses `field_status`; `terms_view`; `runs_with_reviews`.
- `app/billing/dao.py` — modify: `find_household`.
- `app/routes/contract_terms.py` — create: `GET /documents/{id}/terms`.
- `app/governance/dao.py` — modify: `session_id` filter; `invocations_for_document`.
- `app/routes/tool_invocations.py` — modify: `session_id` query, `trace_id`, `decided_by`.
- `app/routes/reviews.py` — modify: `decided_by`.
- `app/documents/dao.py` — modify: `version_events_for_document`.
- `app/reporting/timeline.py` — create: `build_timeline` (pure) + `document_timeline`.
- `app/routes/document_timeline.py` — create: `GET /documents/{id}/timeline`.
- `app/main.py` — modify: register the three new routers.
- `tests/eval/golden.json`, `tests/eval/test_golden.py` — modify: `expect_system_notice`, `score_case`.

Tests (create): `tests/test_guests.py`, `tests/test_assistant_scope.py`, `tests/test_contract_terms.py`, `tests/test_unvalidated_and_notice.py`, `tests/test_golden_scoring.py`, `tests/test_audit_trail.py`, `tests/test_document_timeline.py`.

Frontend (`frontend/src/`)
- `api.ts` — modify: guest id, headers, `streamChat` options, new types and clients.
- `components/workspace/Workspace.css` — create.
- `components/workspace/DocumentCards.tsx`, `ScopeChip.tsx`, `DocumentPanel.tsx`, `ContractProfile.tsx`, `UnvalidatedNotice.tsx`, `AuditLog.tsx`, `LedgerTimeline.tsx`, `RefreshButton.tsx` — create.
- `screens/Chat.tsx`, `screens/Chat.css` — modify: layout, scope, panel, notices.
- `screens/Documents.tsx` — modify: "Ask about this document".

---

### Task 1: Guests and turn scope columns (N19)

**Files:**
- Create: `backend/alembic/versions/0012_guests_and_turn_scope.py`, `backend/app/routes/guests.py`, `backend/tests/test_guests.py`
- Modify: `backend/app/assistant/models.py`, `backend/app/assistant/dao.py`, `backend/app/deps.py`, `backend/app/routes/chat.py`, `backend/app/routes/reviews.py`, `backend/app/routes/tool_invocations.py`, `backend/app/main.py`, `backend/app/assistant/service.py`

**Interfaces:**
- Produces: `Guest` model; `ChatTurn.guest_id: uuid.UUID | None`, `ChatTurn.document_id: uuid.UUID | None`; `assistant_dao.register_guest(session, tenant_id, known_id) -> uuid.UUID`; `assistant_dao.touch_guest(session, tenant_id, guest_id) -> uuid.UUID | None`; `deps.get_guest_id(...) -> uuid.UUID | None`; `deps.decided_by(guest_id) -> str`; `run_turn(..., guest_id: uuid.UUID | None = None, document_id: uuid.UUID | None = None)`.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_guests.py`

```python
import uuid

from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.assistant.models import ChatTurn, Guest
from app.contracts.models import ExtractionRun
from app.contracts.types import FieldRouting
from app.deps import DECIDED_BY, decided_by
from app.retrieval.vector_index import InMemoryVectorIndex
from tests.fakes import RecordingEmbeddings, ScriptedChatModel
from tests.test_api_chat import _override, _runtime
from tests.test_contracts_compare import _contract


def _refusing_model() -> ScriptedChatModel:
    return ScriptedChatModel(replies=[
        AIMessage(content="", tool_calls=[{"name": "search_contracts", "args": {"query": "x"}, "id": "c1"}]),
        AIMessage(content="done"),
    ])


def test_post_guests_creates_a_guest(client, db_session, tenant_id):
    response = client.post("/guests")
    assert response.status_code == 201
    guest = db_session.get(Guest, uuid.UUID(response.json()["id"]))
    assert guest is not None and guest.tenant_id == tenant_id


def test_post_guests_keeps_a_known_id(client):
    first = client.post("/guests").json()["id"]
    assert client.post("/guests", headers={"X-Guest-Id": first}).json()["id"] == first


def test_post_guests_replaces_a_stale_id(client):
    # Review Focus 1: the DB was cleared but the browser still holds the old id
    stale = str(uuid.uuid4())
    assert client.post("/guests", headers={"X-Guest-Id": stale}).json()["id"] != stale


def test_chat_records_a_known_guest_and_touches_last_seen(client, session_factory, db_session, tenant_id):
    guest_id = uuid.UUID(client.post("/guests").json()["id"])
    before = db_session.get(Guest, guest_id).last_seen_at
    _override(client, _runtime(_refusing_model(), RecordingEmbeddings(), InMemoryVectorIndex()), session_factory)
    client.post("/chat", json={"session_id": "g-1", "message": "hi"}, headers={"X-Guest-Id": str(guest_id)})
    db_session.expire_all()
    turn = db_session.scalars(select(ChatTurn).where(ChatTurn.session_id == "g-1")).one()
    assert turn.guest_id == guest_id
    assert db_session.get(Guest, guest_id).last_seen_at >= before


def test_unknown_or_malformed_guest_is_null_not_an_error(client, session_factory, db_session):
    _override(client, _runtime(_refusing_model(), RecordingEmbeddings(), InMemoryVectorIndex()), session_factory)
    for session_id, header in (("g-2", str(uuid.uuid4())), ("g-3", "not-a-uuid")):
        response = client.post("/chat", json={"session_id": session_id, "message": "hi"}, headers={"X-Guest-Id": header})
        assert response.status_code == 200
        turn = db_session.scalars(select(ChatTurn).where(ChatTurn.session_id == session_id)).one()
        assert turn.guest_id is None


def test_decided_by_uses_the_guest_prefix():
    guest_id = uuid.UUID("1234abcd-0000-0000-0000-000000000000")
    assert decided_by(guest_id) == "guest:1234abcd"
    assert decided_by(None) == DECIDED_BY


def test_review_decision_records_the_guest(client, db_session, tenant_id):
    document_id = _contract(db_session, tenant_id, None, tier_routing=FieldRouting.needs_review, key="guest-review")
    run_id = db_session.scalars(select(ExtractionRun.id).order_by(ExtractionRun.created_at.desc())).first()  # the run _contract just made
    guest_id = client.post("/guests").json()["id"]
    response = client.post("/reviews", json={"run_id": str(run_id), "field_path": "fee_tiers[0]", "decision": "confirmed"},
                           headers={"X-Guest-Id": guest_id})
    assert response.status_code == 201
    assert response.json()["decided_by"] == f"guest:{guest_id[:8]}"
```

- [ ] **Step 2: Run to verify they fail**

Run: `$PYTEST tests/test_guests.py -v`
Expected: FAIL — `ImportError: cannot import name 'Guest'`.

- [ ] **Step 3: Migration** — `backend/alembic/versions/0012_guests_and_turn_scope.py`

```python
"""guests, and the guest and document scope of a chat turn

Revision ID: 0012_guests_and_turn_scope
Revises: 0011_chat_trace_id
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0012_guests_and_turn_scope"
down_revision: Union[str, Sequence[str], None] = "0011_chat_trace_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "guests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    # SELECT, INSERT come from the default privileges (0003). Attribution needs one updatable column, nothing else.
    op.execute("GRANT UPDATE (last_seen_at) ON guests TO ledger_app")
    op.add_column("chat_turns", sa.Column("guest_id", UUID(as_uuid=True), sa.ForeignKey("guests.id"), nullable=True))
    op.add_column("chat_turns", sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_turns", "document_id")
    op.drop_column("chat_turns", "guest_id")
    op.drop_table("guests")
```

- [ ] **Step 4: Models** — in `backend/app/assistant/models.py` add, after `ChatOutcome`:

```python
class Guest(Base):
    """A browser visitor. Attribution, not authentication: a guest id never grants access."""
    __tablename__ = "guests"
    __mapper_args__ = {"eager_defaults": True}
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
```

and in `ChatTurn`, after `trace_id`:

```python
    guest_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("guests.id"), nullable=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True)
```

- [ ] **Step 5: DAO** — append to `backend/app/assistant/dao.py` (add `update` to the `sqlalchemy` import and `Guest` to the models import):

```python
def touch_guest(session: Session, tenant_id: uuid.UUID, guest_id: uuid.UUID) -> uuid.UUID | None:
    """Known guest → bump last_seen_at and return its id; unknown → None. Commits."""
    found = session.execute(
        update(Guest).where(Guest.id == guest_id, Guest.tenant_id == tenant_id)
        .values(last_seen_at=func.now()).returning(Guest.id)
    ).scalar_one_or_none()
    session.commit()
    return found


def register_guest(session: Session, tenant_id: uuid.UUID, known_id: uuid.UUID | None) -> uuid.UUID:
    """Reuse a known guest; otherwise (none, or stale after a DB reset) create a new one."""
    if known_id is not None and (found := touch_guest(session, tenant_id, known_id)) is not None:
        return found
    guest = Guest(tenant_id=tenant_id)
    session.add(guest)
    session.commit()
    return guest.id
```

- [ ] **Step 6: Dependencies** — in `backend/app/deps.py` add (imports: `from typing import Annotated`, `from fastapi import Depends, Header`, `from app.assistant import dao as assistant_dao`):

```python
def parse_guest_header(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


def get_guest_id(
    session: Annotated[Session, Depends(get_session)],
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    x_guest_id: Annotated[str | None, Header()] = None,
) -> uuid.UUID | None:
    """Attribution only: a missing, malformed or unknown id resolves to None, never an error."""
    guest_id = parse_guest_header(x_guest_id)
    return None if guest_id is None else assistant_dao.touch_guest(session, tenant_id, guest_id)


def decided_by(guest_id: uuid.UUID | None) -> str:
    return f"guest:{str(guest_id)[:8]}" if guest_id is not None else DECIDED_BY
```

- [ ] **Step 7: Route** — `backend/app/routes/guests.py`

```python
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.assistant import dao as assistant_dao
from app.deps import get_session, get_tenant_id, parse_guest_header

router = APIRouter(prefix="/guests", tags=["assistant"])


class GuestOut(BaseModel):
    id: uuid.UUID


@router.post("", status_code=201, response_model=GuestOut)
def register_guest(
    session: Annotated[Session, Depends(get_session)],
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    x_guest_id: Annotated[str | None, Header()] = None,
) -> GuestOut:
    return GuestOut(id=assistant_dao.register_guest(session, tenant_id, parse_guest_header(x_guest_id)))
```

Register it in `backend/app/main.py`: add `guests` to the `from app.routes import ...` line and `app.include_router(guests.router)` next to the others.

- [ ] **Step 8: Chat, reviews, tool invocations**

`backend/app/routes/chat.py` — add `guest_id: Annotated[uuid.UUID | None, Depends(get_guest_id)]` to `chat(...)` (import `get_guest_id` from `app.deps`) and pass `guest_id=guest_id` to `run_turn`. (`document_id` comes in Task 2.)

`backend/app/assistant/service.py` — `run_turn` gains keyword params `guest_id: uuid.UUID | None = None, document_id: uuid.UUID | None = None`; add `guest_id=guest_id, document_id=document_id` to the `record = dict(...)`.

`backend/app/routes/reviews.py` — `submit_review` gains `guest_id: Annotated[uuid.UUID | None, Depends(get_guest_id)]` and uses `decided_by=decided_by(guest_id)` (import both from `app.deps`; drop the now-unused `DECIDED_BY` import).

`backend/app/routes/tool_invocations.py` — same change in `decide_tool_invocation`.

- [ ] **Step 9: Migrate and run the tests**

Run from the repo root: `./backend/scripts/db_up.sh` — migrates `ledger_dev` and `ledger_test`; both must report `0012_guests_and_turn_scope (head)` via `$PY -m alembic current`.
Run: `$PYTEST tests/test_guests.py -v` → all PASS. Then `$PYTEST -q -m "not stress"` → all PASS.

- [ ] **Step 10: Commit**

```bash
git add backend/alembic/versions/0012_guests_and_turn_scope.py backend/app/assistant/models.py backend/app/assistant/dao.py \
  backend/app/deps.py backend/app/routes/guests.py backend/app/routes/chat.py backend/app/routes/reviews.py \
  backend/app/routes/tool_invocations.py backend/app/main.py backend/app/assistant/service.py backend/tests/test_guests.py
git commit -m "feat(assistant): attribute chats and decisions to a guest"
```

---

### Task 2: Scoped chat in the backend (N12)

**Files:**
- Create: `backend/tests/test_assistant_scope.py`
- Modify: `backend/app/assistant/tools.py`, `backend/app/assistant/contract_tools.py`, `backend/app/assistant/service.py`, `backend/app/routes/chat.py`

**Interfaces:**
- Consumes: `run_turn(..., document_id=...)` (Task 1).
- Produces: `ToolContext.document_id: uuid.UUID | None = None`; `tools.scope_violation(ctx, document_id) -> ToolOutcome | None`; `ChatIn.document_id: uuid.UUID | None`.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_assistant_scope.py`

```python
import json
import uuid

from langchain_core.messages import AIMessage
from sqlalchemy import select

from app import config
from app.assistant.contract_tools import contract_tools
from app.assistant.models import ChatTurn
from app.assistant.tools import ToolContext, default_tools, execute
from app.governance.dao import ModelConfig
from app.governance.models import ToolInvocation
from app.retrieval.index import index_version
from app.retrieval.vector_index import InMemoryVectorIndex
from tests.fakes import RecordingEmbeddings, ScriptedChatModel
from tests.test_api_chat import _override, _runtime
from tests.test_retrieval_index import parsed_version

TOOLS = {spec.name: spec for spec in default_tools() + contract_tools()}


def _ctx(db_session, tenant_id, embeddings, index, document_id):
    return ToolContext(session=db_session, tenant_id=tenant_id, session_id="scope", turn_id=uuid.uuid4(),
                       embeddings=embeddings, vector_index=index, model=ModelConfig("fake", "scripted", "p", 0),
                       hmac_key=config.PII_HMAC_KEY, vault_key=config.PII_VAULT_KEY, document_id=document_id)


def _two_documents(db_session, tenant_id, embeddings, index):
    a = parsed_version(db_session, tenant_id, key="scope-a", texts=("Fees are billed quarterly.",))
    b = parsed_version(db_session, tenant_id, key="scope-b", texts=("Fees are billed quarterly too.",))
    for version in (a, b):
        index_version(db_session, version.id, embeddings=embeddings, vector_index=index)
    return a.document_id, b.document_id


def test_scoped_search_ignores_other_document_ids(db_session, tenant_id):
    embeddings, index = RecordingEmbeddings(), InMemoryVectorIndex()
    a, b = _two_documents(db_session, tenant_id, embeddings, index)
    outcome = execute(TOOLS["search_contracts"], _ctx(db_session, tenant_id, embeddings, index, a),
                      {"query": "billed quarterly", "document_ids": [str(b)]})
    assert outcome.citations and {c["document_id"] for c in outcome.citations.values()} == {str(a)}


def test_scoped_list_documents_returns_only_the_scope(db_session, tenant_id):
    embeddings, index = RecordingEmbeddings(), InMemoryVectorIndex()
    a, _ = _two_documents(db_session, tenant_id, embeddings, index)
    outcome = execute(TOOLS["list_documents"], _ctx(db_session, tenant_id, embeddings, index, a), {})
    assert [row["document_id"] for row in json.loads(outcome.content)] == [str(a)]


def test_contract_tool_for_another_document_is_refused_and_still_audited(db_session, tenant_id):
    embeddings, index = RecordingEmbeddings(), InMemoryVectorIndex()
    a, b = _two_documents(db_session, tenant_id, embeddings, index)
    outcome = execute(TOOLS["get_contract_fields"], _ctx(db_session, tenant_id, embeddings, index, a), {"document_id": str(b)})
    assert "This chat is scoped to" in json.loads(outcome.content)["error"]
    # Review Focus 5: the blocked call is recorded, so the audit trail shows it
    assert db_session.scalars(select(ToolInvocation).where(ToolInvocation.session_id == "scope")).first() is not None


def test_chat_with_unknown_document_is_404(client, session_factory):
    _override(client, _runtime(ScriptedChatModel(replies=[]), RecordingEmbeddings(), InMemoryVectorIndex()), session_factory)
    response = client.post("/chat", json={"session_id": "s-404", "message": "hi", "document_id": str(uuid.uuid4())})
    assert response.status_code == 404


def test_scoped_chat_records_the_document_on_the_turn(client, session_factory, db_session, tenant_id):
    embeddings, index = RecordingEmbeddings(), InMemoryVectorIndex()
    a, _ = _two_documents(db_session, tenant_id, embeddings, index)
    model = ScriptedChatModel(replies=[
        AIMessage(content="", tool_calls=[{"name": "search_contracts", "args": {"query": "nothing"}, "id": "c1"}]),
        AIMessage(content="done"),
    ])
    _override(client, _runtime(model, embeddings, index), session_factory)
    client.post("/chat", json={"session_id": "s-scoped", "message": "hi", "document_id": str(a)})
    turn = db_session.scalars(select(ChatTurn).where(ChatTurn.session_id == "s-scoped")).one()
    assert turn.document_id == a
```

- [ ] **Step 2: Run to verify they fail**

Run: `$PYTEST tests/test_assistant_scope.py -v`
Expected: FAIL — `TypeError: ToolContext.__init__() got an unexpected keyword argument 'document_id'`.

- [ ] **Step 3: Tools** — in `backend/app/assistant/tools.py`:

Add to `ToolContext` as the last field: `document_id: uuid.UUID | None = None  # set = the chat is scoped to this document`.

Add after `evidence_citation`:

```python
def scope_violation(ctx: ToolContext, document_id: uuid.UUID) -> ToolOutcome | None:
    """A scoped chat may only touch its own document; the model can't widen the scope."""
    if ctx.document_id is None or document_id == ctx.document_id:
        return None
    scoped = documents_dao.find_document(ctx.session, ctx.tenant_id, ctx.document_id)
    title = scoped.title if scoped is not None else str(ctx.document_id)
    return ToolOutcome(json.dumps({"error": f"This chat is scoped to {title}."}))
```

In `_list_documents`, filter the rows: `rows = [r for r in documents_dao.list_documents(ctx.session, ctx.tenant_id) if ctx.document_id is None or r.document.id == ctx.document_id]`.

In `_search_contracts`, pass `document_ids=[ctx.document_id] if ctx.document_id is not None else args.document_ids`.

- [ ] **Step 4: Contract tools** — in `backend/app/assistant/contract_tools.py`, import `scope_violation` from `app.assistant.tools` and make the first line after each `assert isinstance(...)` in `_get_contract_fields` and `_compare`:

```python
    if (blocked := scope_violation(ctx, args.document_id)) is not None:
        return blocked
```

- [ ] **Step 5: Service and route**

`backend/app/assistant/service.py`: pass `document_id=document_id` when building `ToolContext`.

`backend/app/routes/chat.py`: add `document_id: uuid.UUID | None = None` to `ChatIn`; before defining `stream()`:

```python
    if body.document_id is not None:
        with session_factory() as session:
            if documents_dao.find_document(session, tenant_id, body.document_id) is None:
                raise DocumentNotFound(f"Document {body.document_id} does not exist.")
```

(imports: `from app.documents import dao as documents_dao`, `from app.documents.errors import DocumentNotFound`) and pass `document_id=body.document_id` to `run_turn`.

- [ ] **Step 6: Run tests** — `$PYTEST tests/test_assistant_scope.py -v` → PASS; full suite → PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/assistant/tools.py backend/app/assistant/contract_tools.py backend/app/assistant/service.py \
  backend/app/routes/chat.py backend/tests/test_assistant_scope.py
git commit -m "feat(assistant): scope a chat to one document inside the tools"
```

---

### Task 3: Guest client, document cards, scope chip and panel shell (N19 + N12 frontend)

**Files:**
- Create: `frontend/src/components/workspace/Workspace.css`, `DocumentCards.tsx`, `ScopeChip.tsx`, `DocumentPanel.tsx`, `RefreshButton.tsx`
- Modify: `frontend/src/api.ts`, `frontend/src/screens/Chat.tsx`, `frontend/src/screens/Chat.css`

**Interfaces:**
- Consumes: `POST /guests`, `/chat` `document_id`.
- Produces: `guestHeaders(): Promise<Record<string, string>>`; `streamChat(sessionId, message, onEvent, options?: { documentId?: string })`; `DocumentPanel` props `{ tabs: PanelTab[] }` with `PanelTab = { id: string; label: string; content: ReactNode }`; `RefreshButton` props `{ onClick(): void; busy: boolean }`.

- [ ] **Step 1: `api.ts` guest id and headers** — add near the top:

```ts
const GUEST_KEY = 'ledgerlens.guest';
let guestPromise: Promise<string> | null = null;

function storedGuest(): string | null {
  try { return localStorage.getItem(GUEST_KEY); } catch { return null; }
}

function storeGuest(id: string): void {
  try { localStorage.setItem(GUEST_KEY, id); } catch { /* storage blocked: the id lives for this tab only */ }
}

/** Registers once per page load; the server replaces an id it no longer knows (e.g. after a DB reset). */
export function guestId(): Promise<string> {
  guestPromise ??= (async () => {
    const known = storedGuest();
    const response = await fetch(`${API_BASE}/guests`, { method: 'POST', headers: known ? { 'X-Guest-Id': known } : {} });
    const { id } = await json<{ id: string }>(response);
    storeGuest(id);
    return id;
  })();
  return guestPromise;
}

export async function guestHeaders(): Promise<Record<string, string>> {
  try { return { 'X-Guest-Id': await guestId() }; } catch { return {}; }
}
```

Change `streamChat` to:

```ts
export interface StreamChatOptions { documentId?: string }

export async function streamChat(
  sessionId: string, message: string, onEvent: (event: ChatEvent) => void, options: StreamChatOptions = {},
): Promise<void> {
  const response = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await guestHeaders()) },
    body: JSON.stringify({ session_id: sessionId, message, ...(options.documentId ? { document_id: options.documentId } : {}) }),
  });
  // … the rest of the existing body unchanged
```

Make the shared `postJson` helper send the guest header on every POST (that covers `decideToolInvocation` and `submitReview`):

```ts
async function postJson(url: string, body: unknown, headers: Record<string, string> = {}): Promise<Response> {
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await guestHeaders()), ...headers },
    body: JSON.stringify(body),
  });
}
```

- [ ] **Step 2: `RefreshButton.tsx`**

```tsx
interface RefreshButtonProps {
  onClick(): void;
  busy: boolean;
}

export function RefreshButton({ onClick, busy }: RefreshButtonProps) {
  return (
    <button type="button" className="ws-refresh" onClick={onClick} disabled={busy} aria-label="Refresh">
      {busy ? 'Refreshing…' : 'Refresh'}
    </button>
  );
}
```

- [ ] **Step 3: `DocumentCards.tsx`** (only `ready` documents are offered — Review Focus 5)

```tsx
import type { DocumentSummary } from '../../api';

interface DocumentCardsProps {
  documents: DocumentSummary[];
  selectedId: string | null;
  onSelect(id: string | null): void;
}

export function DocumentCards({ documents, selectedId, onSelect }: DocumentCardsProps) {
  const ready = documents.filter((d) => d.status === 'ready');
  if (ready.length === 0) return <p className="ws-empty">No indexed contracts yet.</p>;
  return (
    <div className="ws-cards" role="list" aria-label="Choose a contract to ask about">
      {ready.map((d) => {
        const selected = d.id === selectedId;
        return (
          <button key={d.id} type="button" role="listitem" aria-pressed={selected}
                  className={`ws-card${selected ? ' ws-card--selected' : ''}`}
                  onClick={() => onSelect(selected ? null : d.id)}>
            <span className="ws-card__title">{d.title}</span>
            <span className="ws-card__meta">{d.page_count} pages · v{d.version}</span>
          </button>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 4: `ScopeChip.tsx`**

```tsx
interface ScopeChipProps {
  title: string | null;
  onOpen(): void;
  onClear(): void;
}

export function ScopeChip({ title, onOpen, onClear }: ScopeChipProps) {
  return (
    <div className="ws-chip">
      <button type="button" className="ws-chip__label" onClick={onOpen}>
        {title ? <>Scoped to: <strong>{title}</strong></> : 'All documents'}
      </button>
      {title && (
        <button type="button" className="ws-chip__clear" onClick={onClear} aria-label="Clear the document scope">✕</button>
      )}
    </div>
  );
}
```

- [ ] **Step 5: `DocumentPanel.tsx`** (accessible tabs; renders nothing when there are no tabs)

```tsx
import { type KeyboardEvent, type ReactNode, useState } from 'react';

export interface PanelTab {
  id: string;
  label: string;
  content: ReactNode;
}

interface DocumentPanelProps {
  tabs: PanelTab[];
}

export function DocumentPanel({ tabs }: DocumentPanelProps) {
  const [activeId, setActiveId] = useState<string | null>(null);
  if (tabs.length === 0) return null;
  const active = tabs.find((t) => t.id === activeId) ?? tabs[0];
  const move = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
    const index = tabs.indexOf(active);
    const next = tabs[(index + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
    setActiveId(next.id);
    document.getElementById(`ws-tab-${next.id}`)?.focus();
  };
  return (
    <aside className="ws-panel" aria-label="Document details">
      <div className="ws-tabs" role="tablist" onKeyDown={move}>
        {tabs.map((t) => (
          <button key={t.id} id={`ws-tab-${t.id}`} type="button" role="tab" aria-selected={t.id === active.id}
                  aria-controls={`ws-pane-${t.id}`} tabIndex={t.id === active.id ? 0 : -1}
                  className="ws-tab" onClick={() => setActiveId(t.id)}>
            {t.label}
          </button>
        ))}
      </div>
      <div id={`ws-pane-${active.id}`} role="tabpanel" aria-labelledby={`ws-tab-${active.id}`} className="ws-pane">
        {active.content}
      </div>
    </aside>
  );
}
```

- [ ] **Step 6: `Workspace.css`** (existing design tokens only)

```css
.ws-layout { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-3); min-height: 0; }
@media (min-width: 1100px) { .ws-layout--with-panel { grid-template-columns: minmax(0, 1fr) 380px; } }
.ws-cards { display: flex; gap: var(--space-2); overflow-x: auto; padding-bottom: var(--space-1); }
.ws-card { flex: 0 0 220px; text-align: left; padding: var(--space-2) var(--space-3); border: 1px solid var(--color-border);
  border-radius: var(--radius-card); background: var(--color-surface); color: var(--color-text-primary); cursor: pointer; }
.ws-card--selected { border-color: var(--color-accent); box-shadow: 0 0 0 1px var(--color-accent); }
.ws-card__title { display: block; font-weight: 600; }
.ws-card__meta { display: block; color: var(--color-text-secondary); font-size: 0.85em; }
.ws-chip { display: inline-flex; align-items: center; gap: var(--space-1); border: 1px solid var(--color-border);
  border-radius: var(--radius-pill); padding: 0 var(--space-1) 0 var(--space-2); background: var(--color-bg-subtle); }
.ws-chip__label, .ws-chip__clear { background: none; border: 0; color: var(--color-text-primary); cursor: pointer; padding: var(--space-1); }
.ws-panel { border: 1px solid var(--color-border); border-radius: var(--radius-card); background: var(--color-surface);
  display: flex; flex-direction: column; min-height: 0; }
@media (max-width: 1099px) { .ws-panel { position: fixed; inset: 0 0 0 auto; width: min(420px, 100vw); z-index: 20; } }
.ws-tabs { display: flex; border-bottom: 1px solid var(--color-border); }
.ws-tab { flex: 1; background: none; border: 0; padding: var(--space-2); color: var(--color-text-secondary); cursor: pointer; }
.ws-tab[aria-selected='true'] { color: var(--color-text-primary); box-shadow: inset 0 -2px 0 var(--color-accent); }
.ws-pane { overflow-y: auto; padding: var(--space-3); }
.ws-pane__head { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-2); }
.ws-refresh { background: none; border: 1px solid var(--color-border); border-radius: var(--radius-control);
  padding: 0 var(--space-2); color: var(--color-text-secondary); cursor: pointer; }
.ws-empty, .ws-error { color: var(--color-text-secondary); }
.ws-muted { opacity: 0.55; }
.ws-badge { font-size: 0.75em; border-radius: var(--radius-pill); padding: 0 var(--space-1); border: 1px solid var(--color-border); }
```

On narrow screens the panel is a fixed sheet: `Chat.tsx` shows it only while `panelOpen` is true (Step 7).

- [ ] **Step 7: `Chat.tsx` integration**

1. Imports: `useSearchParams` from `react-router`; `DocumentCards`, `ScopeChip`, `DocumentPanel`, `type PanelTab` from `../components/workspace/...`; `'../components/workspace/Workspace.css'`; `type DocumentSummary` from `../api`.
2. State (replace the `indexedCount` effect so one `listDocuments()` call feeds both):

```tsx
  const [searchParams] = useSearchParams();
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [scopeId, setScopeId] = useState<string | null>(searchParams.get('document'));
  const [cardsOpen, setCardsOpen] = useState(true);
  const [panelOpen, setPanelOpen] = useState(false);
  const scoped = documents.find((d) => d.id === scopeId) ?? null;
  const tabs: PanelTab[] = [];  // Tasks 5, 9 and 11 add Profile, Audit trail and Ledger

  useEffect(() => {
    listDocuments()
      .then((docs) => { setDocuments(docs); setIndexedCount(docs.filter((d) => d.status === 'ready').length); })
      .catch(() => setIndexedCount(null));
  }, []);
```

3. A helper that starts a fresh conversation, used by "+ New session" and by a scope change:

```tsx
  const startConversation = (nextScope: string | null) => {
    setScopeId(nextScope);
    setSessionId(newSessionId());
    setTurns([]);
    setApprovals([]);
    setCardsOpen(true);
  };
```

   The "+ New session" button calls `startConversation(scopeId)`.
4. In `ask`: before `setTurns`, add `setCardsOpen(false);`; call `streamChat(sessionId, question, onEvent, { documentId: scopeId ?? undefined })`.
5. Render: wrap `chat__scroll` and `chat__composer` in `<div className={`ws-layout${tabs.length ? ' ws-layout--with-panel' : ''}`}><div className="chat__column">…</div>{(panelOpen || window.matchMedia('(min-width: 1100px)').matches) && <DocumentPanel tabs={tabs} />}</div>`. Above the thread: `cardsOpen ? <DocumentCards documents={documents} selectedId={scopeId} onSelect={(id) => id !== scopeId && startConversation(id)} /> : <ScopeChip title={scoped?.title ?? null} onOpen={() => { setCardsOpen(true); setPanelOpen(true); }} onClear={() => startConversation(null)} />`.
6. `Chat.css`: `.chat__column { display: flex; flex-direction: column; min-height: 0; }`.

- [ ] **Step 8: Verify** — `cd frontend && npm run build` → no errors. Run the app; confirm: cards show only ready documents; selecting one and asking collapses to the chip; ✕ returns to "All documents" with a new session id; `/chat?document=<id>` preselects.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/api.ts frontend/src/screens/Chat.tsx frontend/src/screens/Chat.css frontend/src/components/workspace/
git commit -m "feat(frontend): guest id, document cards, scope chip and the workspace panel shell"
```

**REVIEW CHECKPOINT A** (spec build steps 1–2) — stop and hand over to Claude.

---

### Task 4: `GET /documents/{id}/terms` (N17 backend)

**Files:**
- Create: `backend/app/contracts/terms.py`, `backend/app/routes/contract_terms.py`, `backend/tests/test_contract_terms.py`
- Modify: `backend/app/contracts/dao.py`, `backend/app/billing/dao.py`, `backend/app/main.py`

**Interfaces:**
- Produces: `terms.field_status(routing, decision) -> FieldStatus`; `terms.SERVED_STATUSES`; `terms.field_reason(...)`, `terms.field_label(path)`, `terms.field_group(path)`, `terms.field_sort_key(path)`; `contracts_dao.terms_view(session, tenant_id, document_id, on: date) -> TermsView | None`; `TermsView`, `TermField`, `ScheduleView` dataclasses; `billing_dao.find_household(session, tenant_id, household_id) -> Household | None`.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_contract_terms.py`

```python
import uuid
from datetime import date

from sqlalchemy import select

from app.contracts import dao as contracts_dao
from app.contracts.models import ExtractionRun
from app.contracts.terms import field_label, field_sort_key, field_status
from app.contracts.types import FieldRouting, ReviewDecision
from tests.support import build_fee_scenario
from tests.test_contracts_compare import _contract

ON = date(2026, 9, 30)


def test_field_status_covers_every_case():
    assert field_status(FieldRouting.accepted, None) == "accepted"
    assert field_status(FieldRouting.needs_review, None) == "needs_review"
    assert field_status(FieldRouting.needs_review, ReviewDecision.confirmed) == "confirmed"
    assert field_status(FieldRouting.needs_review, ReviewDecision.corrected) == "corrected"
    assert field_status(FieldRouting.accepted, ReviewDecision.rejected) == "rejected"


def test_bands_sort_numerically_and_have_labels():
    # Review Focus 3
    paths = ["fee_tiers[10]", "fee_tiers[2]", "currency"]
    assert sorted(paths, key=field_sort_key) == ["currency", "fee_tiers[2]", "fee_tiers[10]"]
    assert field_label("fee_tiers[0]") == "Fee band 1"


def test_terms_with_household_and_schedule(db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    document_id = _contract(db_session, tenant_id, scenario.household_id)
    view = contracts_dao.terms_view(db_session, tenant_id, document_id, ON)
    by_path = {f.path: f for f in view.fields}
    assert by_path["currency"].status == "accepted" and by_path["currency"].group == "fee_schedule"
    assert view.household is not None and view.schedule is not None and view.schedule.tiers


def test_needs_review_then_confirmed_and_corrected(db_session, tenant_id):
    document_id = _contract(db_session, tenant_id, None, tier_routing=FieldRouting.needs_review, key="terms-review")
    view = contracts_dao.terms_view(db_session, tenant_id, document_id, ON)
    tier = next(f for f in view.fields if f.path == "fee_tiers[0]")
    assert tier.status == "needs_review" and tier.reason == "not grounded in the cited text"
    run_id = db_session.scalars(select(ExtractionRun.id).order_by(ExtractionRun.created_at.desc())).first()
    contracts_dao.record_review(db_session, tenant_id=tenant_id, run_id=run_id, field_path="fee_tiers[0]",
                                decision=ReviewDecision.confirmed, corrected_value=None, reason=None, decided_by="t")
    contracts_dao.record_review(db_session, tenant_id=tenant_id, run_id=run_id, field_path="fee_tiers[1]",
                                decision=ReviewDecision.corrected, corrected_value={"rate_text": "0.90%"}, reason="typo", decided_by="t")
    db_session.commit()
    by_path = {f.path: f for f in contracts_dao.terms_view(db_session, tenant_id, document_id, ON).fields}
    assert by_path["fee_tiers[0]"].status == "confirmed" and by_path["fee_tiers[0]"].reason is None
    assert by_path["fee_tiers[1]"].status == "corrected" and by_path["fee_tiers[1]"].value == {"rate_text": "0.90%"}


def test_no_household_means_null_household_and_schedule(db_session, tenant_id):
    document_id = _contract(db_session, tenant_id, None, key="terms-fund")
    view = contracts_dao.terms_view(db_session, tenant_id, document_id, ON)
    assert view.household is None and view.schedule is None


def test_api_404_and_not_extracted(client, db_session, tenant_id):
    assert client.get(f"/documents/{uuid.uuid4()}/terms").status_code == 404
    document_id = _contract(db_session, tenant_id, None, key="terms-api")
    body = client.get(f"/documents/{document_id}/terms").json()
    assert body["extraction"]["fields"] and body["coming_soon"][0] == "fee_schedule_history"
```

- [ ] **Step 2: Run to verify they fail** — `$PYTEST tests/test_contract_terms.py -v` → FAIL (`ModuleNotFoundError: app.contracts.terms`).

- [ ] **Step 3: `backend/app/contracts/terms.py`** (pure, no DB)

```python
"""What a reviewer sees for each extracted field: its status, why it isn't confirmed, and where it belongs."""
import re
from typing import Literal

from app.contracts.types import FieldRouting, ReviewDecision

FieldStatus = Literal["accepted", "confirmed", "corrected", "rejected", "needs_review"]
SERVED_STATUSES: frozenset[str] = frozenset({"accepted", "confirmed", "corrected"})
COMING_SOON = ("fee_schedule_history", "client_type", "exceptions", "referral_arrangements", "expense_allocation")

_GROUPS = {
    "fund_or_account": "parties", "adviser": "parties", "client": "parties", "signatories": "parties",
    "fee_basis": "fee_schedule", "fee_method": "fee_schedule", "currency": "fee_schedule", "fee_tiers": "fee_schedule",
    "billing_frequency": "billing_terms", "payment_timing": "billing_terms",
    "agreement_date": "term_and_law", "effective_date": "term_and_law",
    "termination_notice_days": "term_and_law", "governing_law": "term_and_law",
}
_LABELS = {
    "fund_or_account": "Fund or account", "adviser": "Adviser", "client": "Client", "signatories": "Signatory",
    "fee_basis": "Fee basis", "fee_method": "Fee method", "currency": "Currency", "fee_tiers": "Fee band",
    "billing_frequency": "Billing frequency", "payment_timing": "Payment timing",
    "agreement_date": "Agreement date", "effective_date": "Effective date",
    "termination_notice_days": "Termination notice (days)", "governing_law": "Governing law",
}
_INDEXED = re.compile(r"^(?P<base>[a-z_]+)(?:\[(?P<index>\d+)\])?$")


def field_status(routing: FieldRouting, decision: ReviewDecision | None) -> FieldStatus:
    """The one definition of a field's status; served_fields serves exactly SERVED_STATUSES."""
    if decision is ReviewDecision.corrected:
        return "corrected"
    if decision is ReviewDecision.confirmed:
        return "confirmed"
    if decision is ReviewDecision.rejected:
        return "rejected"
    return "accepted" if routing is FieldRouting.accepted else "needs_review"


def field_reason(status: FieldStatus, grounded: bool, validator_errors: list[str], page_grade: str,
                 review_reason: str | None) -> str | None:
    if status == "rejected":
        return review_reason or "rejected by a reviewer"
    if status != "needs_review":
        return None
    if not grounded:
        return "not grounded in the cited text"
    if validator_errors:
        return validator_errors[0]
    if page_grade != "GOOD":
        return f"low page quality ({page_grade})"
    return "awaiting review"


def _split(path: str) -> tuple[str, int | None]:
    match = _INDEXED.match(path)
    if match is None:
        return path, None
    index = match.group("index")
    return match.group("base"), None if index is None else int(index)


def field_group(path: str) -> str:
    return _GROUPS.get(_split(path)[0], "other")


def field_label(path: str) -> str:
    base, index = _split(path)
    label = _LABELS.get(base, base.replace("_", " ").capitalize())
    return label if index is None else f"{label} {index + 1}"


def field_sort_key(path: str) -> tuple[str, int]:
    base, index = _split(path)
    return base, -1 if index is None else index
```

- [ ] **Step 4: `contracts/dao.py`** — refactor `served_fields` to use `field_status` (same behaviour), and add `terms_view`:

```python
# imports to add
from datetime import date
from app.billing import dao as billing_dao
from app.billing.errors import NoScheduleAssigned
from app.contracts.terms import (COMING_SOON, SERVED_STATUSES, FieldStatus, field_group, field_label, field_reason,
                                 field_sort_key, field_status)
```

Inside `served_fields`, replace the `if/elif/else` in the loop with:

```python
        review = reviews.get(field.field_path)
        status = field_status(field.routing, None if review is None else review.decision)
        if status in SERVED_STATUSES:
            value = review.corrected_value if status == "corrected" else field.value
            served[field.field_path] = ServedField(field.field_path, value, field.element_ids, field.quote)
        else:
            unserved.append(field.field_path)
```

Append:

```python
@dataclass(frozen=True)
class TermField:
    path: str
    label: str
    group: str
    value: object
    status: FieldStatus
    reason: str | None
    page: int | None
    quote: str  # tokenised; the route reveals it for display


@dataclass(frozen=True)
class ScheduleView:
    version: int
    method: str
    tiers: list[dict]
    valid_from: date | None


@dataclass(frozen=True)
class TermsView:
    document_id: uuid.UUID
    title: str
    version: int
    run_id: uuid.UUID | None
    extracted_at: datetime | None
    fields: list[TermField]
    household: tuple[uuid.UUID, str] | None
    schedule: ScheduleView | None
    coming_soon: tuple[str, ...] = COMING_SOON


def _schedule_in_effect(session: Session, household_id: uuid.UUID, on: date) -> ScheduleView | None:
    try:
        _schedule, version, tiers = billing_dao.schedule_in_effect(session, household_id, on)
    except NoScheduleAssigned:
        return None
    return ScheduleView(version.version, version.method.value,
                        [{"up_to_minor": t.up_to_minor, "rate_bps": str(t.rate_bps)} for t in tiers],
                        version.valid_during.lower)


def terms_view(session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID, on: date) -> TermsView | None:
    """None = unknown document. A document without an extraction yet has run_id None and no fields."""
    document = documents_dao.find_document(session, tenant_id, document_id)
    if document is None:
        return None
    version_id = documents_dao.current_version_id(session, document_id)
    version_no = documents_dao.version_number(session, version_id)
    household = None
    schedule = None
    if document.household_id is not None and (row := billing_dao.find_household(session, tenant_id, document.household_id)):
        household = (row.id, row.name)
        schedule = _schedule_in_effect(session, row.id, on)
    run = _latest_run(session, version_id)
    if run is None:
        return TermsView(document_id, document.title, version_no, None, None, [], household, schedule)
    reviews = {r.field_path: r for r in session.scalars(select(FieldReview).where(FieldReview.run_id == run.id))}
    fields = []
    for f in sorted(session.scalars(select(ExtractedField).where(ExtractedField.run_id == run.id)),
                    key=lambda f: field_sort_key(f.field_path)):
        review = reviews.get(f.field_path)
        status = field_status(f.routing, None if review is None else review.decision)
        fields.append(TermField(
            path=f.field_path, label=field_label(f.field_path), group=field_group(f.field_path),
            value=review.corrected_value if status == "corrected" else f.value, status=status,
            reason=field_reason(status, f.grounded, list(f.validator_errors), f.page_grade,
                                None if review is None else review.reason),
            page=documents_dao.first_page(session, f.element_ids), quote=f.quote,
        ))
    return TermsView(document_id, document.title, version_no, run.id, run.created_at, fields, household, schedule)
```

(Add `from datetime import datetime` alongside the `date` import.) Add to `app/documents/dao.py`:

```python
def version_number(session: Session, version_id: uuid.UUID) -> int:
    return session.get(DocumentVersion, version_id).version
```

- [ ] **Step 5: `billing/dao.py`** — append:

```python
def find_household(session: Session, tenant_id: uuid.UUID, household_id: uuid.UUID) -> Household | None:
    household = session.get(Household, household_id)
    return household if household is not None and household.tenant_id == tenant_id else None
```

(`Household` is already imported from `app.billing.models`; add it to the import if not.)

- [ ] **Step 6: Route** — `backend/app/routes/contract_terms.py`

```python
import uuid
from dataclasses import asdict
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import config
from app.contracts import dao as contracts_dao
from app.deps import get_session, get_tenant_id
from app.documents import dao as documents_dao
from app.documents.errors import DocumentNotFound

router = APIRouter(prefix="/documents", tags=["contracts"])


class TermFieldOut(BaseModel):
    path: str
    label: str
    group: str
    value: object
    status: str
    reason: str | None
    page: int | None
    quote: str


class ExtractionOut(BaseModel):
    run_id: uuid.UUID
    extracted_at: datetime
    fields: list[TermFieldOut]


class HouseholdOut(BaseModel):
    id: uuid.UUID
    name: str


class ScheduleOut(BaseModel):
    version: int
    method: str
    tiers: list[dict]
    valid_from: date | None


class TermsOut(BaseModel):
    document_id: uuid.UUID
    title: str
    version: int
    extraction: ExtractionOut | None
    household: HouseholdOut | None
    billing_schedule: ScheduleOut | None
    coming_soon: list[str]


@router.get("/{document_id}/terms", response_model=TermsOut)
def get_terms(document_id: uuid.UUID, session: Annotated[Session, Depends(get_session)],
              tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)]) -> TermsOut:
    view = contracts_dao.terms_view(session, tenant_id, document_id, date.today())
    if view is None:
        raise DocumentNotFound(f"Document {document_id} does not exist.")
    # ponytail: detokenises for the single demo user, like the document preview; gate on permissions once auth exists
    quotes = documents_dao.reveal(session, tenant_id, [f.quote for f in view.fields], config.require("PII_VAULT_KEY"))
    fields = [TermFieldOut(**(asdict(f) | {"quote": q})) for f, q in zip(view.fields, quotes)]
    return TermsOut(
        document_id=view.document_id, title=view.title, version=view.version,
        extraction=None if view.run_id is None else ExtractionOut(run_id=view.run_id, extracted_at=view.extracted_at, fields=fields),
        household=None if view.household is None else HouseholdOut(id=view.household[0], name=view.household[1]),
        billing_schedule=None if view.schedule is None else ScheduleOut(**asdict(view.schedule)),
        coming_soon=list(view.coming_soon),
    )
```

Register in `app/main.py` (`contract_terms` import + `include_router`).

- [ ] **Step 7: Run tests** — `$PYTEST tests/test_contract_terms.py tests/test_contracts_dao.py tests/test_assistant_contract_tools.py -v` → PASS (the `served_fields` refactor must not change behaviour); then the full suite.

- [ ] **Step 8: Commit**

```bash
git add backend/app/contracts/terms.py backend/app/contracts/dao.py backend/app/billing/dao.py backend/app/documents/dao.py \
  backend/app/routes/contract_terms.py backend/app/main.py backend/tests/test_contract_terms.py
git commit -m "feat(contracts): serve a contract's terms with their review status"
```

---

### Task 5: Profile tab (N17 frontend)

**Files:**
- Create: `frontend/src/components/workspace/ContractProfile.tsx`
- Modify: `frontend/src/api.ts`, `frontend/src/screens/Chat.tsx`

**Interfaces:**
- Consumes: `GET /documents/{id}/terms` (Task 4).
- Produces: `getTerms(id): Promise<TermsDto>`; `TermsDto`, `TermFieldDto`; `ContractProfile` props `{ documentId: string }`.

- [ ] **Step 1: `api.ts` types and client**

```ts
export type FieldStatus = 'accepted' | 'confirmed' | 'corrected' | 'rejected' | 'needs_review';

export interface TermFieldDto {
  path: string; label: string; group: string; value: unknown;
  status: FieldStatus; reason: string | null; page: number | null; quote: string;
}

export interface TermsDto {
  document_id: string; title: string; version: number;
  extraction: { run_id: string; extracted_at: string; fields: TermFieldDto[] } | null;
  household: { id: string; name: string } | null;
  billing_schedule: { version: number; method: string; tiers: { up_to_minor: number | null; rate_bps: string }[]; valid_from: string | null } | null;
  coming_soon: string[];
}

export function getTerms(documentId: string): Promise<TermsDto> {
  return fetch(`${API_BASE}/documents/${documentId}/terms`).then((r) => json<TermsDto>(r));
}
```

- [ ] **Step 2: `ContractProfile.tsx`**

```tsx
import { useEffect, useState } from 'react';
import { type TermFieldDto, type TermsDto, documentPageUrl, getTerms } from '../../api';

const GROUPS: { id: string; label: string }[] = [
  { id: 'parties', label: 'Parties' },
  { id: 'fee_schedule', label: 'Fee schedule' },
  { id: 'billing_terms', label: 'Billing terms' },
  { id: 'term_and_law', label: 'Term and governing law' },
  { id: 'other', label: 'Other' },
];
const STATUS_LABEL: Record<TermFieldDto['status'], string> = {
  accepted: 'Accepted', confirmed: 'Confirmed', corrected: 'Corrected', rejected: 'Rejected', needs_review: 'Awaiting review',
};
const COMING_SOON_LABEL: Record<string, string> = {
  fee_schedule_history: 'Fee schedule version history', client_type: 'Client type', exceptions: 'Exceptions',
  referral_arrangements: 'Referral arrangements', expense_allocation: 'Expense allocation',
};

interface ContractProfileProps {
  documentId: string;
}

function display(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'object') {
    const band = value as { band_text?: string; rate_text?: string };
    if (band.band_text || band.rate_text) return [band.band_text, band.rate_text].filter(Boolean).join(' · ');
    return JSON.stringify(value);
  }
  return String(value);
}

function percent(bps: string): string {
  return `${(Number(bps) / 100).toFixed(2)}%`;
}

export function ContractProfile({ documentId }: ContractProfileProps) {
  const [terms, setTerms] = useState<TermsDto | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setTerms(null);
    setError(null);
    getTerms(documentId).then(setTerms).catch((e: unknown) => setError(e instanceof Error ? e.message : 'Could not load the terms'));
  }, [documentId]);

  if (error) return <p className="ws-error">{error}</p>;
  if (!terms) return <p className="ws-empty">Loading the contract profile…</p>;
  if (!terms.extraction) return <p className="ws-empty">Not extracted yet.</p>;
  const fields = terms.extraction.fields;
  return (
    <div className="ws-profile">
      {GROUPS.map((group) => {
        const rows = fields.filter((f) => f.group === group.id);
        if (rows.length === 0) return null;
        return (
          <section key={group.id}>
            <h3>{group.label}</h3>
            <dl>
              {rows.map((f) => (
                <div key={f.path} className="ws-field">
                  <dt>{f.label} <span className="ws-badge">{STATUS_LABEL[f.status]}</span></dt>
                  <dd>
                    {display(f.value)}
                    {f.reason && <div className="ws-reason">{f.reason}</div>}
                    {f.page !== null && (
                      <a href={documentPageUrl(terms.document_id, terms.version, f.page)} target="_blank" rel="noreferrer">
                        Page {f.page} →
                      </a>
                    )}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        );
      })}
      <section>
        <h3>Billing reconciliation</h3>
        {terms.household ? (
          <p>
            Household <strong>{terms.household.name}</strong>
            {terms.billing_schedule
              ? <> — billed on schedule v{terms.billing_schedule.version} ({terms.billing_schedule.method}):{' '}
                  {terms.billing_schedule.tiers.map((t) => percent(t.rate_bps)).join(' / ')}</>
              : ' — no billing schedule in effect today.'}
          </p>
        ) : <p className="ws-empty">Not linked to a billing household.</p>}
      </section>
      <section className="ws-muted" aria-disabled="true">
        <h3>Coming soon</h3>
        <ul>
          {terms.coming_soon.map((id) => (
            <li key={id}>{COMING_SOON_LABEL[id] ?? id} <span className="ws-badge">Coming soon</span></li>
          ))}
        </ul>
      </section>
    </div>
  );
}
```

Add to `Workspace.css`: `.ws-field { display: grid; gap: 2px; margin-bottom: var(--space-2); } .ws-reason { color: var(--color-text-secondary); font-size: 0.85em; }`.

- [ ] **Step 3: Wire the tab** — in `Chat.tsx` replace `const tabs: PanelTab[] = [];` with:

```tsx
  const tabs: PanelTab[] = [
    ...(scopeId ? [{ id: 'profile', label: 'Profile', content: <ContractProfile documentId={scopeId} /> }] : []),
  ];
```

- [ ] **Step 4: Verify** — `npm run build` passes; scoping the Tremblay contract shows grouped fields, statuses, page links, the household and schedule, and the greyed "Coming soon" list.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.ts frontend/src/screens/Chat.tsx frontend/src/components/workspace/ContractProfile.tsx frontend/src/components/workspace/Workspace.css
git commit -m "feat(frontend): contract profile tab with review status and coming-soon slots"
```

**REVIEW CHECKPOINT B** (spec build step 3).

---

### Task 6: Unvalidated-field event and the not-comparable notice (N11 backend + eval)

**Files:**
- Create: `backend/tests/test_unvalidated_and_notice.py`, `backend/tests/test_golden_scoring.py`
- Modify: `backend/app/assistant/tools.py`, `backend/app/assistant/contract_tools.py`, `backend/app/assistant/graph.py`, `backend/app/assistant/service.py`, `backend/tests/eval/golden.json`, `backend/tests/eval/test_golden.py`

**Interfaces:**
- Consumes: `contracts_dao.terms_view` (Task 4).
- Produces: `ToolOutcome.unvalidated_document_id: uuid.UUID | None`, `ToolOutcome.system_notice: str | None`; `TurnState.unvalidated: list[str]`, `TurnState.system_notices: list[str]`; SSE event `unvalidated {document_id, title, fields: [{path, label, reason}]}`; citation `{"id": "system", "kind": "system", "source": "billing records", "detail": str}`; `test_golden.score_case(case, event_type, data) -> dict`.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_unvalidated_and_notice.py`

```python
from langchain_core.messages import AIMessage

from app.assistant.contract_tools import contract_tools
from app.assistant.graph import Answer
from app.assistant.service import AssistantRuntime
from app.assistant.tools import default_tools
from app.contracts.types import FieldRouting
from app.retrieval.index import index_version
from app.retrieval.search import search
from app.retrieval.vector_index import InMemoryVectorIndex
from tests.fakes import RecordingEmbeddings, ScriptedChatModel
from tests.test_api_chat import _events, _override
from tests.test_contracts_compare import _contract
from tests.test_retrieval_index import parsed_version


def _runtime(model, embeddings=None, index=None):
    return AssistantRuntime(chat_model=model, embeddings=embeddings or RecordingEmbeddings(),
                            vector_index=index or InMemoryVectorIndex(), tools=default_tools() + contract_tools())


def test_unconfirmed_fields_are_announced_before_the_final_event(client, session_factory, db_session, tenant_id):
    document_id = _contract(db_session, tenant_id, None, tier_routing=FieldRouting.needs_review, key="uv-1")
    model = ScriptedChatModel(replies=[
        AIMessage(content="", tool_calls=[{"name": "get_contract_fields", "args": {"document_id": str(document_id)}, "id": "c1"}]),
        AIMessage(content="done"),
    ])
    _override(client, _runtime(model), session_factory)
    events = _events(client.post("/chat", json={"session_id": "uv-1", "message": "What are the fees?"}))
    kinds = [k for k, _ in events]
    assert kinds.count("unvalidated") == 1 and kinds.index("unvalidated") < len(kinds) - 1
    notice = dict(events)["unvalidated"]
    assert notice["document_id"] == str(document_id)
    assert {f["path"] for f in notice["fields"]} >= {"fee_tiers[0]"} and notice["fields"][0]["reason"]


def test_not_comparable_refusal_becomes_a_system_notice(client, session_factory, db_session, tenant_id):
    document_id = _contract(db_session, tenant_id, None, key="uv-fund")
    model = ScriptedChatModel(replies=[
        AIMessage(content="", tool_calls=[{"name": "list_documents", "args": {}, "id": "c0"}]),
        AIMessage(content="", tool_calls=[{"name": "compare_contract_to_billing", "args": {"document_id": str(document_id)}, "id": "c1"}]),
        AIMessage(content="done"),
    ])
    _override(client, _runtime(model), session_factory)
    kind, data = _events(client.post("/chat", json={"session_id": "uv-2", "message": "Compare this contract with billing"}))[-1]
    assert kind == "refused"
    assert "not linked to a billing household" in data["text"]
    assert data["citations"] == [{"id": "system", "kind": "system", "source": "billing records",
                                  "detail": "This contract is not linked to a billing household (fund-level agreement)."}]


def test_notice_never_replaces_a_valid_answer(client, session_factory, db_session, tenant_id):
    # Review Focus 2
    fund = _contract(db_session, tenant_id, None, key="uv-fund-2")
    embeddings, index = RecordingEmbeddings(), InMemoryVectorIndex()
    version = parsed_version(db_session, tenant_id, key="uv-text", texts=("Fees are billed quarterly in arrears.",))
    index_version(db_session, version.id, embeddings=embeddings, vector_index=index)
    element_id = str(search(db_session, tenant_id=tenant_id, query="quarterly", embeddings=embeddings, vector_index=index)[0].element_id)
    model = ScriptedChatModel(replies=[
        AIMessage(content="", tool_calls=[
            {"name": "compare_contract_to_billing", "args": {"document_id": str(fund)}, "id": "c1"},
            {"name": "search_contracts", "args": {"query": "quarterly"}, "id": "c2"},
        ]),
        AIMessage(content="done"),
        Answer(text="Fees are billed quarterly in arrears.", citations=[element_id], refused=False),
    ])
    _override(client, _runtime(model, embeddings, index), session_factory)
    kind, data = _events(client.post("/chat", json={"session_id": "uv-3", "message": "How often are fees billed?"}))[-1]
    assert kind == "answer" and data["citations"][0]["kind"] == "element"
```

(The question contains "compare", so `route` forces `list_documents` then `compare_contract_to_billing`; the scripted replies follow that order. In the third test the question has no calculation keyword, so no tool is forced.)

`backend/tests/test_golden_scoring.py`:

```python
from tests.eval.test_golden import score_case

CASE = {"id": "fund-not-comparable", "expect_page": None, "expect_numbers": [], "expect_refusal": False,
        "expect_system_notice": True}


def test_system_notice_case_passes_only_with_a_system_citation():
    with_notice = score_case(CASE, "refused", {"text": "x", "citations": [{"kind": "system", "detail": "d"}]})
    assert with_notice["refusal_ok"] and with_notice["citation_hit"]
    generic = score_case(CASE, "refused", {"text": "I can't find that", "citations": []})
    assert not generic["refusal_ok"] and not generic["citation_hit"]


def test_ordinary_cases_are_scored_as_before():
    case = {"id": "c", "expect_page": 2, "expect_numbers": ["0.85"], "expect_refusal": False}
    result = score_case(case, "answer", {"text": "0.85%", "citations": [{"kind": "element", "page": 2}]})
    assert result["refusal_ok"] and result["citation_hit"] and result["numbers_ok"]
```

- [ ] **Step 2: Run to verify they fail** — `$PYTEST tests/test_unvalidated_and_notice.py tests/test_golden_scoring.py -v` → FAIL.

- [ ] **Step 3: `ToolOutcome` and `execute`** — in `tools.py` add two fields to `ToolOutcome`:

```python
    unvalidated_document_id: uuid.UUID | None = None  # this document has fields the agent may not use
    system_notice: str | None = None  # a fixed, non-generated reason (e.g. not comparable with billing)
```

In `execute`, pass both through in the final `ToolOutcome(...)`: `unvalidated_document_id=outcome.unvalidated_document_id, system_notice=outcome.system_notice`.

- [ ] **Step 4: Contract tools** — `_get_contract_fields` returns `ToolOutcome(json.dumps(body), sources=sources, citations=citations, unvalidated_document_id=args.document_id if served.unserved else None)`. In `_compare`, the `except ContractNotComparable as exc:` branch returns `ToolOutcome(json.dumps({"error": exc.detail}), system_notice=exc.detail)`.

- [ ] **Step 5: Graph state** — in `graph.py` add to `TurnState`:

```python
    unvalidated: Annotated[list[str], operator.add]  # document ids with fields the agent may not use
    system_notices: Annotated[list[str], operator.add]
```

In `run_tools`, collect `unvalidated += [str(outcome.unvalidated_document_id)] if outcome.unvalidated_document_id else []` and `notices += [outcome.system_notice] if outcome.system_notice else []` (initialise both lists next to `messages, sources, ...`) and return them as `"unvalidated": unvalidated, "system_notices": notices`.

- [ ] **Step 6: Service** — in `service.py`:

```python
# module level
SYSTEM_CITATION_ID = "system"
NOT_COMPARABLE_TEXT = "I can't compare this contract with billing: {reason}"


def _unvalidated_events(session: Session, tenant_id: uuid.UUID, document_ids: list[str]) -> list[TurnEvent]:
    events = []
    for document_id in dict.fromkeys(document_ids):  # once per document, in order
        view = contracts_dao.terms_view(session, tenant_id, uuid.UUID(document_id), date.today())
        if view is None:
            continue
        fields = [{"path": f.path, "label": f.label, "reason": f.reason} for f in view.fields if f.status in ("needs_review", "rejected")]
        if fields:
            events.append(TurnEvent("unvalidated", {"document_id": document_id, "title": view.title, "fields": fields}))
    return events
```

(imports: `from datetime import date`, `from sqlalchemy.orm import Session`, `from app.contracts import dao as contracts_dao`; add `"unvalidated"` to the `TurnEvent.type` Literal.)

In `run_turn`, right after `answer = state["answer"]`:

```python
            for event in _unvalidated_events(session, tenant_id, state.get("unvalidated", [])):
                yield event
            notices = state.get("system_notices", [])
            if answer.refused and notices:
                citation = {"id": SYSTEM_CITATION_ID, "kind": "system", "source": "billing records", "detail": notices[-1]}
                record.update(answer_redacted=NOT_COMPARABLE_TEXT.format(reason=notices[-1]), citations=[citation],
                              retrieved=state.get("retrieved", []))
                record["input_tokens"], record["output_tokens"] = _usage(state.get("messages", []))
                outcome = ChatOutcome.refused
                yield TurnEvent("refused", {"text": NOT_COMPARABLE_TEXT.format(reason=notices[-1]), "citations": [citation]})
                return
```

(`return` inside the `try` still runs the `finally` that saves the turn.)

- [ ] **Step 7: Eval** — in `golden.json`, add `"expect_system_notice": true` to the `fund-not-comparable` case only. In `test_golden.py`, move the scoring out of `_run` into:

```python
def score_case(case: dict, event_type: str, data: dict) -> dict:
    """Pure scoring, unit-tested in tests/test_golden_scoring.py without OpenAI."""
    citations = data.get("citations", [])
    found = numbers_in(data.get("text", ""))
    refusal_ok = (event_type == "refused") == case["expect_refusal"]
    citation_hit = case["expect_refusal"] or any(
        case["expect_page"] is None or c.get("page") == case["expect_page"] for c in citations
    )
    if case.get("expect_system_notice"):  # explained abstention: only a system citation counts
        refusal_ok = citation_hit = any(c.get("kind") == "system" for c in citations)
    return {"id": case["id"], "event": event_type, "refusal_ok": refusal_ok, "citation_hit": citation_hit,
            "numbers_ok": {_normal(n) for n in case["expect_numbers"]} <= found}
```

and have `_run` call `score_case(case, final.type, final.data)` and merge any extra keys it returned before (keep the report format unchanged).

- [ ] **Step 8: Run tests** — the two new files → PASS; full suite → PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/assistant/tools.py backend/app/assistant/contract_tools.py backend/app/assistant/graph.py \
  backend/app/assistant/service.py backend/tests/eval/golden.json backend/tests/eval/test_golden.py \
  backend/tests/test_unvalidated_and_notice.py backend/tests/test_golden_scoring.py
git commit -m "feat(assistant): disclose unconfirmed fields and explain a not-comparable contract"
```

---

### Task 7: Notices in the conversation (N11 frontend)

**Files:**
- Create: `frontend/src/components/workspace/UnvalidatedNotice.tsx`
- Modify: `frontend/src/api.ts`, `frontend/src/screens/Chat.tsx`

**Interfaces:**
- Consumes: SSE `unvalidated`; `kind: "system"` citations (Task 6).
- Produces: `UnvalidatedDto`; `Turn.unvalidated: UnvalidatedDto[]`.

- [ ] **Step 1: `api.ts`** — extend `Citation.kind` to `'element' | 'tool' | 'system'` and add `source?: string; detail?: string;`. Add:

```ts
export interface UnvalidatedDto {
  document_id: string;
  title: string;
  fields: { path: string; label: string; reason: string | null }[];
}
```

and the union member `| { type: 'unvalidated'; data: UnvalidatedDto }` to `ChatEvent`.

- [ ] **Step 2: `UnvalidatedNotice.tsx`**

```tsx
import { Link } from 'react-router';
import type { UnvalidatedDto } from '../../api';

interface UnvalidatedNoticeProps {
  notice: UnvalidatedDto;
}

export function UnvalidatedNotice({ notice }: UnvalidatedNoticeProps) {
  return (
    <div className="ws-notice" role="note">
      <strong>Not confirmed, awaiting review</strong> in {notice.title}:{' '}
      {notice.fields.map((f) => f.label).join(', ')}.{' '}
      <Link to="/review">Review →</Link>
    </div>
  );
}
```

CSS: `.ws-notice { border-left: 3px solid var(--color-accent); padding: var(--space-2); background: var(--color-bg-subtle); margin-top: var(--space-2); }`.

- [ ] **Step 3: `Chat.tsx`** — add `unvalidated: UnvalidatedDto[]` to the `Turn` type (initialise `[]` where turns are created). In `onEvent`, handle `unvalidated` before the generic branch:

```tsx
      else if (event.type === 'unvalidated')
        setTurns((all) => all.map((t, i) => (i === all.length - 1 ? { ...t, unvalidated: [...t.unvalidated, event.data] } : t)));
```

Render `{turn.unvalidated.map((n) => <UnvalidatedNotice key={n.document_id} notice={n} />)}` under the answer and under a refusal. In `CitationCard`, when `citation.kind === 'system'`, render `System · {citation.source}` and `citation.detail` instead of a page link. Show citations for refusals too when present.

- [ ] **Step 4: Verify** — `npm run build` passes; asking "Compare the Calamos fund agreement with billing" shows the fixed notice with "System · billing records"; asking about a contract with fields awaiting review shows the notice under the answer.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.ts frontend/src/screens/Chat.tsx frontend/src/components/workspace/UnvalidatedNotice.tsx frontend/src/components/workspace/Workspace.css
git commit -m "feat(frontend): show unconfirmed fields and system notices in the conversation"
```

**REVIEW CHECKPOINT C** (spec build step 4).

---

### Task 8: Audit trail endpoint (N13 backend)

**Files:**
- Create: `backend/tests/test_audit_trail.py`
- Modify: `backend/app/assistant/service.py`, `backend/app/assistant/dao.py`, `backend/app/governance/dao.py`, `backend/app/routes/tool_invocations.py`

**Interfaces:**
- Produces: `chat_turns.id == ToolContext.turn_id` (= `tool_invocations.input["turn_id"]`); `list_invocations(..., session_id: str | None = None)`; `assistant_dao.trace_ids(session, tenant_id, turn_ids) -> dict[uuid.UUID, str | None]`; `InvocationOut.trace_id: str | None`; `GET /tool-invocations?session_id=`.

> Deviation from the spec (better): the spec joined traces by "nearest turn in time". Instead the turn row takes
> the id already written into every invocation's `input.turn_id`, so the join is exact.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_audit_trail.py`

```python
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.assistant.models import ChatTurn
from app.governance.models import ToolInvocation
from app.retrieval.vector_index import InMemoryVectorIndex
from tests.fakes import RecordingEmbeddings, ScriptedChatModel
from tests.test_api_chat import _override, _runtime


def _chat(client, session_factory, session_id):
    model = ScriptedChatModel(replies=[
        AIMessage(content="", tool_calls=[{"name": "search_contracts", "args": {"query": "x"}, "id": "c1"}]),
        AIMessage(content="done"),
    ])
    _override(client, _runtime(model, RecordingEmbeddings(), InMemoryVectorIndex()), session_factory)
    client.post("/chat", json={"session_id": session_id, "message": "hi"})


def test_turn_id_matches_the_invocations_turn_id(client, session_factory, db_session):
    _chat(client, session_factory, "a-1")
    turn = db_session.scalars(select(ChatTurn).where(ChatTurn.session_id == "a-1")).one()
    invocation = db_session.scalars(select(ToolInvocation).where(ToolInvocation.session_id == "a-1")).one()
    assert invocation.input["turn_id"] == str(turn.id)


def test_session_filter_returns_only_that_session(client, session_factory):
    _chat(client, session_factory, "a-2")
    _chat(client, session_factory, "a-3")
    rows = client.get("/tool-invocations", params={"session_id": "a-2"}).json()
    assert rows and {r["session_id"] for r in rows} == {"a-2"}
    assert "trace_id" in rows[0]
```

- [ ] **Step 2: Run to verify they fail** — `$PYTEST tests/test_audit_trail.py -v` → FAIL.

- [ ] **Step 3: Turn id** — in `service.run_turn`, create `turn_id = uuid.uuid4()` once, use it for `ToolContext(turn_id=turn_id, ...)` and add `id=turn_id` to `record`.

- [ ] **Step 4: DAO filters** — `governance/dao.py` `list_invocations` gains `session_id: str | None = None` and `if session_id is not None: query = query.where(ToolInvocation.session_id == session_id)`. `assistant/dao.py` gains:

```python
def trace_ids(session: Session, tenant_id: uuid.UUID, turn_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str | None]:
    ids = list(turn_ids)
    if not ids:
        return {}
    rows = session.execute(select(ChatTurn.id, ChatTurn.trace_id).where(ChatTurn.tenant_id == tenant_id, ChatTurn.id.in_(ids)))
    return {turn_id: trace_id for turn_id, trace_id in rows}
```

(import `Iterable` from `collections.abc`).

- [ ] **Step 5: Route** — `routes/tool_invocations.py`: add `trace_id: str | None = None` to `InvocationOut`; `list_tool_invocations` gains `session_id: str | None = None`, passes it to `list_invocations`, then:

```python
    turn_ids = {uuid.UUID(i.input["turn_id"]) for i, _ in rows if i.input.get("turn_id")}
    traces = assistant_dao.trace_ids(session, tenant_id, turn_ids)
    return [
        _invocation_out(session, invocation, decision).model_copy(update={
            "trace_id": traces.get(uuid.UUID(invocation.input["turn_id"])) if invocation.input.get("turn_id") else None,
        })
        for invocation, decision in rows
    ]
```

(import `from app.assistant import dao as assistant_dao`.)

- [ ] **Step 6: Run tests** — PASS; full suite → PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/assistant/service.py backend/app/assistant/dao.py backend/app/governance/dao.py \
  backend/app/routes/tool_invocations.py backend/tests/test_audit_trail.py
git commit -m "feat(governance): list a conversation's tool calls with their trace"
```

---

### Task 9: Audit trail tab (N13 frontend)

**Files:**
- Create: `frontend/src/components/workspace/AuditLog.tsx`
- Modify: `frontend/src/api.ts`, `frontend/src/screens/Chat.tsx`

**Interfaces:**
- Consumes: `GET /tool-invocations?session_id=` (Task 8); `RefreshButton` (Task 3).
- Produces: `ListInvocationsOptions.sessionId?: string`; `ToolInvocationDto.trace_id: string | null`; `AuditLog` props `{ sessionId: string; refreshKey: number }`.

- [ ] **Step 1: `api.ts`** — add `sessionId?: string` to `ListInvocationsOptions` and `session_id: options.sessionId` to the `withQuery` object in `listToolInvocations`; add `trace_id: string | null;` to `ToolInvocationDto`; add `export const LANGFUSE_URL: string | undefined = import.meta.env.VITE_LANGFUSE_URL;`.

- [ ] **Step 2: `AuditLog.tsx`**

```tsx
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router';
import { LANGFUSE_URL, type ToolInvocationDto, listToolInvocations } from '../../api';
import { RefreshButton } from './RefreshButton';

interface AuditLogProps {
  sessionId: string;
  refreshKey: number;  // bumped by Chat after every finished turn
}

export function AuditLog({ sessionId, refreshKey }: AuditLogProps) {
  const [rows, setRows] = useState<ToolInvocationDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setBusy(true);
    listToolInvocations({ sessionId, limit: 200 })
      .then((r) => { setRows(r); setError(null); })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Could not load the audit trail'))
      .finally(() => setBusy(false));
  }, [sessionId]);

  useEffect(load, [load, refreshKey]);

  return (
    <div>
      <div className="ws-pane__head"><h3>Audit trail</h3><RefreshButton onClick={load} busy={busy} /></div>
      {error && <p className="ws-error">{error}</p>}
      {!error && rows === null && <p className="ws-empty">Loading…</p>}
      {rows?.length === 0 && <p className="ws-empty">No AI decisions in this conversation yet.</p>}
      <ol className="ws-audit">
        {rows?.map((r) => (
          <li key={r.id}>
            <div><strong>{r.tool_name}</strong> · {new Date(r.created_at).toLocaleTimeString()}</div>
            <div className="ws-reason">{r.model_id} · prompt {r.prompt_version}</div>
            <pre className="ws-input">{JSON.stringify(Object.fromEntries(Object.entries(r.input).filter(([k]) => k !== 'turn_id')), null, 1)}</pre>
            {r.decision
              ? <div>{r.decision.decision} by {r.decision.decided_by}
                  {r.decision.posting_id && <> · <Link to={`/ledger?posting=${r.decision.posting_id}`}>View posting →</Link></>}</div>
              : r.approval_required && <Link to="/review#approvals">Awaiting approval →</Link>}
            {r.trace_id && LANGFUSE_URL && (
              <a href={`${LANGFUSE_URL}/trace/${r.trace_id}`} target="_blank" rel="noreferrer">View trace →</a>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
```

CSS: `.ws-audit { list-style: none; padding: 0; display: grid; gap: var(--space-2); } .ws-input { font-size: 0.8em; white-space: pre-wrap; margin: 0; }`.

Add `VITE_LANGFUSE_URL=` (empty) to `frontend/.env.example` if that file exists, with a comment "project URL, e.g. https://us.cloud.langfuse.com/project/<id>".

- [ ] **Step 3: `Chat.tsx`** — add `const [auditKey, setAuditKey] = useState(0);`; in `ask`'s `finally` add `setAuditKey((k) => k + 1);`; append to `tabs` (always present):

```tsx
    { id: 'audit', label: 'Audit trail', content: <AuditLog sessionId={sessionId} refreshKey={auditKey} /> },
```

- [ ] **Step 4: Verify** — `npm run build`; ask two questions: the tab refreshes after each; the Refresh button reloads; an approval shows "View posting →".

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.ts frontend/src/screens/Chat.tsx frontend/src/components/workspace/AuditLog.tsx frontend/src/components/workspace/Workspace.css
git commit -m "feat(frontend): audit trail tab with refresh"
```

(Add `frontend/.env.example` to the `git add` if you changed it.)

**REVIEW CHECKPOINT D** (spec build step 5).

---

### Task 10: `GET /documents/{id}/timeline` (N14 backend)

**Files:**
- Create: `backend/app/reporting/timeline.py`, `backend/app/routes/document_timeline.py`, `backend/tests/test_document_timeline.py`
- Modify: `backend/app/documents/dao.py`, `backend/app/contracts/dao.py`, `backend/app/governance/dao.py`, `backend/app/main.py`

**Interfaces:**
- Produces: `documents_dao.version_events_for_document(session, document_id) -> list[tuple[int, VersionEvent]]`; `contracts_dao.runs_with_reviews(session, document_id) -> list[tuple[ExtractionRun, list[FieldReview]]]`; `contracts_dao.accepted_count(session, run_id) -> int`; `governance_dao.invocations_for_document(session, tenant_id, document_id) -> list[tuple[ToolInvocation, ToolInvocationDecision | None]]`; `timeline.TimelineItem`; `timeline.build_timeline(...) -> list[TimelineItem]`; `timeline.document_timeline(session, tenant_id, document_id) -> list[TimelineItem] | None`.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_document_timeline.py`

```python
import uuid
from datetime import datetime, timedelta, timezone

from app.reporting.timeline import TimelineItem, build_timeline, document_timeline
from app.assistant.contract_tools import contract_tools
from tests.support import build_fee_scenario
from tests.test_assistant_contract_tools import _ctx
from tests.test_contracts_compare import _contract
from app.assistant.tools import execute

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


def test_build_timeline_sorts_and_keeps_kinds():
    items = [TimelineItem(T0 + timedelta(minutes=2), "decided", "Approved", {}, {}),
             TimelineItem(T0, "ingested", "Stored", {}, {})]
    assert [i.kind for i in build_timeline(items)] == ["ingested", "decided"]


def test_document_timeline_from_ingestion_to_posting(client, db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    document_id = _contract(db_session, tenant_id, scenario.household_id)
    other = _contract(db_session, tenant_id, None, key="timeline-other")
    compare = {s.name: s for s in contract_tools()}["compare_contract_to_billing"]
    execute(compare, _ctx(db_session, tenant_id), {"document_id": str(document_id), "as_of": "2026-09-30"})
    execute(compare, _ctx(db_session, tenant_id), {"document_id": str(other)})
    db_session.commit()
    invocation_id = client.get("/tool-invocations", params={"pending": True}).json()[0]["id"]
    assert client.post(f"/tool-invocations/{invocation_id}/decision", json={"decision": "approved"}).status_code == 201
    items = client.get(f"/documents/{document_id}/timeline").json()
    kinds = [i["kind"] for i in items]
    assert kinds.index("ingested") < kinds.index("extracted") < kinds.index("ai_proposed") < kinds.index("decided") < kinds.index("posted")
    posted = next(i for i in items if i["kind"] == "posted")
    assert {e["direction"] for e in posted["detail"]["entries"]} == {"debit", "credit"}
    assert all(i["detail"].get("document_id") in (None, str(document_id)) for i in items)


def test_rejected_proposal_is_decided_without_a_posting(client, db_session, tenant_id):
    # Review Focus 4
    scenario = build_fee_scenario(db_session, tenant_id)
    document_id = _contract(db_session, tenant_id, scenario.household_id, key="timeline-rejected")
    compare = {s.name: s for s in contract_tools()}["compare_contract_to_billing"]
    execute(compare, _ctx(db_session, tenant_id), {"document_id": str(document_id), "as_of": "2026-09-30"})
    db_session.commit()
    invocation_id = client.get("/tool-invocations", params={"pending": True}).json()[0]["id"]
    client.post(f"/tool-invocations/{invocation_id}/decision", json={"decision": "rejected", "reason": "not now"})
    kinds = [i["kind"] for i in client.get(f"/documents/{document_id}/timeline").json()]
    assert "decided" in kinds and "posted" not in kinds


def test_unknown_document_is_404(client):
    assert client.get(f"/documents/{uuid.uuid4()}/timeline").status_code == 404
```



- [ ] **Step 2: Run to verify they fail** — FAIL (`ModuleNotFoundError: app.reporting.timeline`).

- [ ] **Step 3: Package reads**

`documents/dao.py`:

```python
def version_events_for_document(session: Session, document_id: uuid.UUID) -> list[tuple[int, VersionEvent]]:
    rows = session.execute(
        select(DocumentVersion.version, VersionEvent).join(VersionEvent, VersionEvent.version_id == DocumentVersion.id)
        .where(DocumentVersion.document_id == document_id).order_by(VersionEvent.id)
    )
    return [(version, event) for version, event in rows]
```

(`VersionEvent` has `id` (identity), `version_id`, `stage`, `detail`, `created_at`.)

`contracts/dao.py`:

```python
def runs_with_reviews(session: Session, document_id: uuid.UUID) -> list[tuple[ExtractionRun, list[FieldReview]]]:
    runs = session.scalars(
        select(ExtractionRun).join(DocumentVersion, DocumentVersion.id == ExtractionRun.version_id)
        .where(DocumentVersion.document_id == document_id).order_by(ExtractionRun.created_at)
    ).all()
    return [(run, list(session.scalars(select(FieldReview).where(FieldReview.run_id == run.id)))) for run in runs]


def accepted_count(session: Session, run_id: uuid.UUID) -> int:
    return session.scalar(select(func.count()).select_from(ExtractedField).where(
        ExtractedField.run_id == run_id, ExtractedField.routing == FieldRouting.accepted))
```

(add `func` to the `sqlalchemy` import.)

(import `DocumentVersion` from `app.documents.models`.)

`governance/dao.py`:

```python
def invocations_for_document(session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID
                             ) -> list[tuple[ToolInvocation, ToolInvocationDecision | None]]:
    # ponytail: scans tool_invocations by JSONB; add an index on (tenant_id, (input->>'document_id')) when volume grows
    query = (
        select(ToolInvocation, ToolInvocationDecision)
        .outerjoin(ToolInvocationDecision, ToolInvocationDecision.invocation_id == ToolInvocation.id)
        .where(ToolInvocation.tenant_id == tenant_id, ToolInvocation.input["document_id"].astext == str(document_id))
        .order_by(ToolInvocation.created_at)
    )
    return [(i, d) for i, d in session.execute(query)]
```

- [ ] **Step 4: `reporting/timeline.py`**

```python
"""A document's history as one ordered list: how a contract became ledger entries. Read-only."""
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.contracts import dao as contracts_dao
from app.documents import dao as documents_dao
from app.governance import dao as governance_dao
from app.ledger import dao as ledger_dao


@dataclass(frozen=True)
class TimelineItem:
    at: datetime
    kind: str  # ingested | extracted | reviewed | ai_proposed | decided | posted
    title: str
    detail: dict = field(default_factory=dict)
    links: dict = field(default_factory=dict)


def build_timeline(items: list[TimelineItem]) -> list[TimelineItem]:
    return sorted(items, key=lambda item: item.at)


def document_timeline(session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID) -> list[TimelineItem] | None:
    if documents_dao.find_document(session, tenant_id, document_id) is None:
        return None
    items = [
        TimelineItem(event.created_at, "ingested", f"v{version} · {event.stage.value}", {"stage": event.stage.value})
        for version, event in documents_dao.version_events_for_document(session, document_id)
    ]
    for run, reviews in contracts_dao.runs_with_reviews(session, document_id):
        accepted = contracts_dao.accepted_count(session, run.id)
        items.append(TimelineItem(run.created_at, "extracted", "Terms extracted", {"run_id": str(run.id), "accepted": accepted}))
        items += [TimelineItem(r.decided_at, "reviewed", f"{r.field_path} {r.decision.value}",
                               {"field_path": r.field_path, "decided_by": r.decided_by}) for r in reviews]
    for invocation, decision in governance_dao.invocations_for_document(session, tenant_id, document_id):
        items.append(TimelineItem(invocation.created_at, "ai_proposed", invocation.tool_name, {
            "document_id": str(document_id), "amount_minor": invocation.result_amount_minor,
            "currency": invocation.result_currency, "invocation_id": str(invocation.id)}))
        if decision is None:
            continue
        items.append(TimelineItem(decision.decided_at, "decided", f"{decision.decision.value} by {decision.decided_by}",
                                  {"reason": decision.reason}))
        if decision.posting_id is not None:
            posting = ledger_dao.get_posting(session, tenant_id=tenant_id, posting_id=decision.posting_id)
            labels = ledger_dao.account_labels(session, (e.account_id for e in posting.entries))
            items.append(TimelineItem(posting.created_at, "posted", posting.description or "Posting", {
                "posting_id": str(posting.id),
                "entries": [{"account": labels[e.account_id].name, "direction": e.direction.value, "amount_minor": e.amount,
                             "currency": labels[e.account_id].currency} for e in posting.entries],
            }, {"ledger": f"/ledger?posting={posting.id}"}))
    return build_timeline(items)
```



- [ ] **Step 5: Route** — `backend/app/routes/document_timeline.py`

```python
import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.deps import get_session, get_tenant_id
from app.documents.errors import DocumentNotFound
from app.reporting.timeline import document_timeline

router = APIRouter(prefix="/documents", tags=["reporting"])


class TimelineItemOut(BaseModel):
    at: datetime
    kind: str
    title: str
    detail: dict
    links: dict


@router.get("/{document_id}/timeline", response_model=list[TimelineItemOut])
def get_timeline(document_id: uuid.UUID, session: Annotated[Session, Depends(get_session)],
                 tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)]) -> list[TimelineItemOut]:
    items = document_timeline(session, tenant_id, document_id)
    if items is None:
        raise DocumentNotFound(f"Document {document_id} does not exist.")
    return [TimelineItemOut(**asdict(item)) for item in items]
```

Register in `app/main.py`.

- [ ] **Step 6: Run tests** — PASS; full suite → PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/reporting/timeline.py backend/app/routes/document_timeline.py backend/app/documents/dao.py \
  backend/app/contracts/dao.py backend/app/governance/dao.py backend/app/main.py backend/tests/test_document_timeline.py
git commit -m "feat(reporting): a document's timeline from ingestion to ledger postings"
```

---

### Task 11: Ledger tab and "Ask about this document" (N14 frontend)

**Files:**
- Create: `frontend/src/components/workspace/LedgerTimeline.tsx`
- Modify: `frontend/src/api.ts`, `frontend/src/screens/Chat.tsx`, `frontend/src/screens/Documents.tsx`

**Interfaces:**
- Consumes: `GET /documents/{id}/timeline` (Task 10); `RefreshButton`.
- Produces: `TimelineItemDto`, `getTimeline(id)`; `LedgerTimeline` props `{ documentId: string; refreshKey: number }`.

- [ ] **Step 1: `api.ts`**

```ts
export interface TimelineItemDto {
  at: string;
  kind: 'ingested' | 'extracted' | 'reviewed' | 'ai_proposed' | 'decided' | 'posted';
  title: string;
  detail: { entries?: { account: string; direction: 'debit' | 'credit'; amount_minor: number; currency: string }[] } & Record<string, unknown>;
  links: { ledger?: string };
}

export function getTimeline(documentId: string): Promise<TimelineItemDto[]> {
  return fetch(`${API_BASE}/documents/${documentId}/timeline`).then((r) => json<TimelineItemDto[]>(r));
}
```

- [ ] **Step 2: `LedgerTimeline.tsx`**

```tsx
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router';
import { type TimelineItemDto, getTimeline } from '../../api';
import { RefreshButton } from './RefreshButton';

const KIND_LABEL: Record<TimelineItemDto['kind'], string> = {
  ingested: 'Ingested', extracted: 'Extracted', reviewed: 'Reviewed',
  ai_proposed: 'AI proposed', decided: 'Decided', posted: 'Posted',
};

interface LedgerTimelineProps {
  documentId: string;
  refreshKey: number;
}

function money(minor: number, currency: string): string {
  return new Intl.NumberFormat('en-CA', { style: 'currency', currency }).format(minor / 100);
}

export function LedgerTimeline({ documentId, refreshKey }: LedgerTimelineProps) {
  const [items, setItems] = useState<TimelineItemDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setBusy(true);
    getTimeline(documentId)
      .then((r) => { setItems(r); setError(null); })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Could not load the timeline'))
      .finally(() => setBusy(false));
  }, [documentId]);

  useEffect(load, [load, refreshKey]);

  return (
    <div>
      <div className="ws-pane__head"><h3>From contract to ledger</h3><RefreshButton onClick={load} busy={busy} /></div>
      {error && <p className="ws-error">{error}</p>}
      {!error && items === null && <p className="ws-empty">Loading…</p>}
      {items?.length === 0 && <p className="ws-empty">Nothing has happened to this document yet.</p>}
      <ol className="ws-timeline">
        {items?.map((item, index) => (
          <li key={`${item.at}-${index}`} className={`ws-timeline__item ws-timeline__item--${item.kind}`}>
            <div><span className="ws-badge">{KIND_LABEL[item.kind]}</span> {item.title}</div>
            <div className="ws-reason">{new Date(item.at).toLocaleString()}</div>
            {item.detail.entries && (
              <details>
                <summary>Entries</summary>
                <ul>
                  {item.detail.entries.map((e, i) => (
                    <li key={i}>{e.direction === 'debit' ? 'Dr' : 'Cr'} {e.account} {money(e.amount_minor, e.currency)}</li>
                  ))}
                </ul>
              </details>
            )}
            {item.links.ledger && <Link to={item.links.ledger}>View in ledger →</Link>}
          </li>
        ))}
      </ol>
    </div>
  );
}
```

CSS: `.ws-timeline { list-style: none; padding: 0 0 0 var(--space-3); border-left: 2px solid var(--color-border); display: grid; gap: var(--space-2); }`.

- [ ] **Step 3: `Chat.tsx`** — add `const [ledgerKey, setLedgerKey] = useState(0);`; bump it when an approval completes: pass `onDecided={() => { refreshApprovals(sessionId); setLedgerKey((k) => k + 1); setAuditKey((k) => k + 1); }}` to each `ApprovalCard` (the prop already exists); add to the scoped tabs after Profile:

```tsx
      { id: 'ledger', label: 'Ledger', content: <LedgerTimeline documentId={scopeId} refreshKey={ledgerKey} /> },
```

Final tab order: Profile, Audit trail, Ledger (Audit trail only when unscoped).

- [ ] **Step 4: `Documents.tsx`** — in the detail pane, next to the existing actions:

```tsx
<Link className="btn btn-secondary" to={`/chat?document=${detail.id}`}>Ask about this document</Link>
```

- [ ] **Step 5: Verify** — `npm run build`; on Tremblay: ask the comparison question → approve in chat → Ledger tab shows `posted` with Dr/Cr entries in CAD; Refresh reloads; the Documents button opens a scoped chat.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api.ts frontend/src/screens/Chat.tsx frontend/src/screens/Documents.tsx \
  frontend/src/components/workspace/LedgerTimeline.tsx frontend/src/components/workspace/Workspace.css
git commit -m "feat(frontend): ledger timeline tab and ask about a document"
```

---

### Task 12: End-to-end check and records

- [ ] **Step 1:** Backend: `$PYTEST -q -m "not stress"` and `$PYTEST -q -m slow` → all PASS; restore `backend/reports/eval-*.json`.
- [ ] **Step 2:** Frontend: `npm run build` → PASS.
- [ ] **Step 3:** Playwright walk-through (`playwright-cli`, app running locally): open `/documents` → "Ask about this document" on Tremblay → cards collapse on the first question → Profile shows statuses → ask "Compare the Tremblay agreement with billing" → Audit trail lists the calls → approve → Ledger shows the posting after Refresh. Save screenshots under `.playwright-cli/` (gitignored).
- [ ] **Step 4:** `graphify update .` from the repo root.
- [ ] **Step 5:** `CHANGELOG.md` (current sprint): tick nothing that needs Phase 4; add under Scope one line per shipped item (N19, N12, N17, N11, N13, N14) with `→ **Not epic-tracked** (fintech reframing, backlog N-id)`; tick the "behaviour under uncertainty" and "real-time audit log" scope items only if they are fully covered (the audit log is refresh-based, so leave "real-time" unticked with a note pointing to D6). `artifacts/product-backlog.md`: tick N19 (add it to the "Now" list if missing), N12, N17, N11, N13, N14.
- [ ] **Step 6: Commit**

```bash
git add CHANGELOG.md artifacts/product-backlog.md
git commit -m "docs(changelog): record the document workspace"
```

**REVIEW CHECKPOINT E** (spec build step 6 + whole-phase review).

---

## Skills that informed this plan

- **clean-architecture / pragmatic-programmer** — one owning package per endpoint; `field_status` is the single definition of "served" (Task 4 refactors `served_fields` onto it); scope enforced at the tool boundary.
- **domain-driven-design** — guest vs conversation; glossary labels.
- **ddia-systems** — exact join on `turn_id` instead of time proximity (Task 8); FKs for guest/document; the JSONB-scan ceiling written next to the query.
- **clean-code / test-driven-development** — failing test first in every backend task; pure functions (`terms.py`, `build_timeline`, `score_case`) tested without the DB or OpenAI.
- **supabase-postgres-best-practices** — column-level UPDATE grant; index plan for the timeline query.
