# Demo-ready UI, round 2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the real logo in the app chrome; give the dashboard its stat tiles and corpus telemetry back from a cached `/stats` + `/config` API; add one in-app PDF viewer (pdf.js), opened on demand from Documents and always shown in a new two-pane, paginated Review screen.

**Architecture:** Backend: one aggregated `GET /stats`, built from each package's own DAO and served from a per-process TTL cache that writes invalidate, with an ETag so an unchanged payload is a 304; a static `GET /config`, built once and cached by browsers for an hour; and immutable cache headers on original PDFs, since a version never changes. Frontend: a single `DocumentViewer` component, code-split with `React.lazy`, so pdf.js and its worker are only downloaded by screens that render it. Each screen owns *what* is shown, as props; Documents mounts the viewer in a side sheet only while it is open, and Review keeps it mounted in its right pane.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, pytest; React 19 + TypeScript + Vite 8; Vitest; **pdfjs-dist** (new dependency).

**Spec:** the owner's round-2 notes, reproduced as [Findings](#findings) (R1–R5). Earlier round: `docs/superpowers/plans/2026-09-26-demo-ready-ui.md`.

## Findings

| ID | Request | Task |
|---|---|---|
| R1 | Show the real ledger logo (`frontend/public/favicon.svg`) at the top of the landing nav and the app's sidebar | 1 |
| R2 | Dashboard: bring back the top tiles (documents indexed + chunk count, needs review, golden-set eval score, confidence drop-rate shown greyed with no value) and corpus telemetry, all from real data, through stats/config endpoints designed for load, caching and TTFB | 2, 3, 4 |
| R3 | One reusable pdf.js viewer component, injected only on the screens that display a document | 5 |
| R4 | Documents: the side overview has no way to view the PDF; add a "View document" action that opens the viewer, and a close button that removes it entirely | 6 |
| R5 | Review: content is stacked on the left leaving the right blank; make it two panes (list on the left, viewer on the right, first item's document loaded by default), paginate long lists, and show the discrepancy's page in the right pane instead of opening a new browser window | 7 |

**Correction to the request:** pdf.js is *not* currently installed in the frontend. "Open page" hands the PDF to the browser's own viewer. Task 5 adds `pdfjs-dist`.

## Global Constraints

- Branch `feat/demo-ready`; never commit to `preview` or `main`; never push or open a PR.
- Conventional commits, **no `Co-Authored-By` and no AI attribution** of any kind.
- Stage files explicitly; never `git add -A` / `git add .`. Check `git status` and `git diff --staged --stat` before every commit. **Commit each task immediately when its steps are done, before starting the next.**
- Backend runs with `$PYDEV/bin/...` from `backend/`; never create a `.venv`. Routes stay thin; DB access only inside each package's own `dao.py`; the ledger package imports no other package; no new Python dependency; no migration.
- Frontend: no `any`; a named props `interface` for every component; colours only through `index.css` custom properties; shadows ≤ 8px blur; motion 150–200 ms, with a reduced-motion fallback. New npm packages allowed in this plan: **`pdfjs-dist` only** (record it in the PR summary).
- **"Replace the file" means the whole file.** After any full-file replacement, run the check the task gives (for example, the old class names must be gone).
- Keep green at the end of every task: `$PYDEV/bin/pytest`; `npm test && npm run lint && npm run build` (lint must report **0 warnings**).
- Run `graphify update .` from the repo root before each commit.
- Browser checks: if you can't open a browser, say so. Never mark a browser check passed without having looked; include screenshot paths in the report.

## Review Focus

1. **Stale dashboard after a decision.** Approving a correction or reviewing a field must be reflected by `/stats` immediately, not after the cache TTL. Pinned by `test_writes_invalidate_the_cached_stats` (Task 3).
2. **Switching documents fast in the viewer.** Clicking through Review items or Documents rows must never paint page N of the previous PDF, or throw because a destroyed document is still rendering. The viewer keys its loaded document by URL and cancels in-flight renders; pinned by the manual check in Task 7 and by the `clampPage` tests (Task 5).
3. **Page out of range.** A field whose page is `null`, 0, or beyond the page count opens a valid page (1 or the last). Pinned by the `clampPage` tests.
4. **Pagination after the list shrinks.** Deciding the last item on the last page must land on a valid page, not an empty one. Pinned by the `paginate` clamp test (Task 7).
5. **No eval report for the running configuration.** The tile shows "—" greyed with an explanation, not 0% and not a crash. Pinned by the `eval_summary` test (Task 3) and the `evalScore` tests (Task 4).

---

### Task 1: Real logo in the landing nav and the sidebar (R1)

**Files:**
- Create: `frontend/src/components/BrandMark.tsx`
- Modify: `frontend/src/components/Sidebar.tsx`, `frontend/src/components/Sidebar.css`
- Modify: `frontend/src/screens/Landing.tsx`, `frontend/src/screens/Landing.css`

**Interfaces:**
- Produces: `BrandMark({ size?: number; className?: string })`, which renders `/favicon.svg`.

- [ ] **Step 1: Create the component**

`frontend/src/components/BrandMark.tsx`:

```tsx
interface BrandMarkProps {
  size?: number;
  className?: string;
}

// The ledger mark (a balanced "=" on the accent disc); decorative — the product name is always next to it.
export function BrandMark({ size = 24, className }: BrandMarkProps) {
  return <img src="/favicon.svg" width={size} height={size} alt="" className={className} />;
}
```

- [ ] **Step 2: Use it**

- `Sidebar.tsx`: import `{ BrandMark } from './BrandMark'` and replace `<span className="sidebar__brand-mark" aria-hidden="true" />` with `<BrandMark size={24} />`.
- `Landing.tsx`: import `{ BrandMark } from '../components/BrandMark'` and replace **both** `<span className="landing__brand-mark" aria-hidden="true" />` (nav and footer) with `<BrandMark size={24} />`.
- Delete the `.sidebar__brand-mark` rule from `Sidebar.css` and the `.landing__brand-mark` rule from `Landing.css`.

Check: `grep -rn "brand-mark" frontend/src` prints nothing.

- [ ] **Step 3: Verify and commit**

Run `cd frontend && npm test && npm run lint && npm run build`. In the browser, `/` and `/dashboard` show the blue disc with two white bars next to "Ledger Assistant".

```bash
graphify update .
git add frontend/src/components/BrandMark.tsx frontend/src/components/Sidebar.tsx frontend/src/components/Sidebar.css frontend/src/screens/Landing.tsx frontend/src/screens/Landing.css
git commit -m "feat(frontend): show the ledger logo in the landing nav and the sidebar"
```

---

### Task 2: Immutable cache headers on original PDFs (for R3–R5 load time)

**Files:**
- Modify: `backend/app/routes/documents.py` (`get_original_file`)
- Test: `backend/tests/test_documents_api.py`

**Interfaces:**
- Produces: `GET /documents/{id}/versions/{n}/file` responds with `Cache-Control: private, max-age=31536000, immutable`. A version's bytes never change (content-addressed and append-only), so the viewer reopens a PDF from the browser cache.

- [ ] **Step 1: Write the failing test** (append to `backend/tests/test_documents_api.py`)

```python
def test_original_file_is_cached_as_immutable(client):
    body = _post(client).json()
    response = client.get(f"/documents/{body['document_id']}/versions/1/file")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, max-age=31536000, immutable"
```

- [ ] **Step 2: Run it — expect FAIL** (`KeyError: 'cache-control'`)

`cd backend && $PYDEV/bin/pytest tests/test_documents_api.py::test_original_file_is_cached_as_immutable -v`

- [ ] **Step 3: Implement**

In `backend/app/routes/documents.py` add a module constant and pass it through:

```python
# A version's bytes never change (content-addressed, append-only), so browsers may keep it for good.
ORIGINAL_FILE_CACHE_CONTROL = "private, max-age=31536000, immutable"
```

```python
    return FileResponse(
        store.original_path(config.DOCUMENT_STORE_DIR, row.file_sha256),
        media_type="application/pdf",
        headers={"Cache-Control": ORIGINAL_FILE_CACHE_CONTROL},
    )
```

- [ ] **Step 4: Run it — expect PASS**, then the full suite: `$PYDEV/bin/pytest`.

- [ ] **Step 5: Commit**

```bash
graphify update .
git add backend/app/routes/documents.py backend/tests/test_documents_api.py
git commit -m "perf(api): cache original PDFs as immutable"
```

---

### Task 3: `/stats` and `/config` endpoints (R2, backend)

**Files:**
- Modify: `backend/app/assistant/graph.py` (add `eval_config_hash`)
- Modify: `backend/tests/eval/test_golden.py` (use it)
- Modify: `backend/app/assistant/dao.py` (`LatencySummary`, `latency_summary`)
- Modify: `backend/app/documents/dao.py` (`last_event_at`)
- Modify: `backend/app/retrieval/dao.py` (`indexed_chunk_count`)
- Modify: `backend/app/governance/dao.py` (`count_pending`)
- Create: `backend/app/reporting/dashboard.py`
- Create: `backend/app/routes/stats.py`
- Modify: `backend/app/main.py`, `backend/app/routes/reviews.py`, `backend/app/routes/tool_invocations.py`, `backend/app/routes/documents.py` (invalidate on writes)
- Test: `backend/tests/test_stats_api.py`

**Interfaces:**
- Produces:
  - `GET /stats` → `{documents: {total, indexed, processing, failed, indexed_chunks}, reviews_pending, approvals_pending, last_ingestion_at, chat: {turns_7d, latency_p50_ms, latency_p95_ms}, eval: {config_hash, chat_model, cases, numbers_ok, refusal_ok, citation_hit} | null, confidence_drop_rate: null, generated_at}`, with `Cache-Control: private, no-cache` and an `ETag`; a matching `If-None-Match` gets a 304.
  - `GET /config` → `{chat_model, extraction_model, embedding_model, embedding_dimensions, parser, pii, vector_store, retrieval: {search_candidates, min_dense_similarity}, eval_config_hash}`, with `Cache-Control: public, max-age=3600` and an `ETag`; a matching `If-None-Match` gets a 304.
  - `app.reporting.dashboard.invalidate_dashboard_stats(tenant_id: uuid.UUID) -> None`.

**Why this shape (TTFB and load):** the stats are ~8 small aggregate queries, computed at most once per 15 s per tenant and served from memory in between. The review, decision and upload routes invalidate the cache, so the UI never shows a stale count after an action. `no-cache` + ETag makes the browser revalidate every time but download the body only when it changed. `/config` only changes on deploy, so browsers keep it for an hour.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_stats_api.py`:

```python
import json

import pytest

from app.assistant.models import ChatOutcome, ChatTurn
from app.reporting import dashboard
from tests.test_retrieval_index import parsed_version
from tests.test_reviews_api import _decide, _run


@pytest.fixture(autouse=True)
def fresh_stats_cache():
    dashboard._cache.clear()
    yield
    dashboard._cache.clear()


def _turn(tenant_id, latency_ms):
    return ChatTurn(tenant_id=tenant_id, session_id="s", question_redacted="q", answer_redacted="a", citations=[],
                    retrieved=[], outcome=ChatOutcome.answered, model_id="m", prompt_version="p", graph_version="g",
                    input_tokens=0, output_tokens=0, latency_ms=latency_ms)


def test_stats_count_documents_and_answer_latency(client, db_session, tenant_id):
    parsed_version(db_session, tenant_id)
    db_session.add_all([_turn(tenant_id, ms) for ms in (100, 200, 300, 400, 1000)])
    db_session.commit()
    response = client.get("/stats")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-cache"
    body = response.json()
    assert body["documents"]["total"] == 1 and body["documents"]["indexed_chunks"] == 0
    assert body["chat"] == {"turns_7d": 5, "latency_p50_ms": 300, "latency_p95_ms": 880}
    assert body["confidence_drop_rate"] is None
    assert body["last_ingestion_at"] is not None


def test_unchanged_stats_revalidate_with_304(client):
    first = client.get("/stats")
    again = client.get("/stats", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304


def test_writes_invalidate_the_cached_stats(client, db_session, tenant_id):
    _, run = _run(db_session, tenant_id)
    assert client.get("/stats").json()["reviews_pending"] == 2
    assert _decide(client, run, "fee_method", "confirmed").status_code == 201
    assert client.get("/stats").json()["reviews_pending"] == 1


def test_stats_are_cached_for_the_ttl(db_session, tenant_id):
    now = [100.0]
    first = dashboard.cached_dashboard_stats(db_session, tenant_id, clock=lambda: now[0])
    parsed_version(db_session, tenant_id)
    assert dashboard.cached_dashboard_stats(db_session, tenant_id, clock=lambda: now[0]).documents_total == first.documents_total
    now[0] += dashboard.STATS_TTL_SECONDS
    assert dashboard.cached_dashboard_stats(db_session, tenant_id, clock=lambda: now[0]).documents_total == first.documents_total + 1


def test_eval_summary_reads_only_the_report_for_the_running_config(tmp_path):
    (tmp_path / "eval-abc123.json").write_text(json.dumps({
        "config_hash": "abc123", "chat_model": "gpt-x",
        "metrics": {"numbers_ok": 1.0, "refusal_ok": 0.875, "citation_hit": 0.875}, "results": [{}] * 8,
    }))
    summary = dashboard.eval_summary(tmp_path, "abc123")
    assert (summary.cases, summary.numbers_ok, summary.refusal_ok, summary.citation_hit) == (8, 1.0, 0.875, 0.875)
    assert dashboard.eval_summary(tmp_path, "other") is None


def test_config_is_cacheable_and_revalidates(client):
    response = client.get("/config")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=3600"
    body = response.json()
    assert body["embedding_model"] and body["embedding_dimensions"] > 0
    assert body["retrieval"]["search_candidates"] > 0
    again = client.get("/config", headers={"If-None-Match": response.headers["etag"]})
    assert again.status_code == 304
```

- [ ] **Step 2: Run them — expect FAIL** (`ModuleNotFoundError: app.reporting.dashboard`)

`cd backend && $PYDEV/bin/pytest tests/test_stats_api.py -v`

- [ ] **Step 3: Share the eval config hash**

In `backend/app/assistant/graph.py` (import `from app import config` if not already imported):

```python
def eval_config_hash() -> str:
    """Identifies the chat configuration a golden-set report was produced with (see tests/eval/test_golden.py)."""
    return hashlib.sha256(f"{config.CHAT_MODEL}|{prompt_version()}|{config.EMBEDDING_MODEL}".encode()).hexdigest()[:12]
```

In `backend/tests/eval/test_golden.py`, import `eval_config_hash` from `app.assistant.graph` and replace the inline `hashlib.sha256(...)` line with `config_hash = eval_config_hash()`. Remove the `hashlib` import if it's now unused.

- [ ] **Step 4: Add the DAO queries** (add the imports each one needs: `func`, `dataclass`, `datetime`, models)

`backend/app/assistant/dao.py`:

```python
@dataclass(frozen=True)
class LatencySummary:
    turns: int
    p50_ms: int | None
    p95_ms: int | None


def latency_summary(session: Session, tenant_id: uuid.UUID, since: datetime) -> LatencySummary:
    turns, p50, p95 = session.execute(
        select(
            func.count(),
            func.percentile_cont(0.5).within_group(ChatTurn.latency_ms),
            func.percentile_cont(0.95).within_group(ChatTurn.latency_ms),
        ).where(ChatTurn.tenant_id == tenant_id, ChatTurn.created_at >= since)
    ).one()
    return LatencySummary(turns, None if p50 is None else round(p50), None if p95 is None else round(p95))
```

`backend/app/documents/dao.py`:

```python
def last_event_at(session: Session, tenant_id: uuid.UUID) -> datetime | None:
    return session.scalar(
        select(func.max(VersionEvent.created_at))
        .join(DocumentVersion, DocumentVersion.id == VersionEvent.version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(Document.tenant_id == tenant_id)
    )
```

`backend/app/retrieval/dao.py`:

```python
def indexed_chunk_count(session: Session, tenant_id: uuid.UUID) -> int:
    return session.scalar(select(func.count()).select_from(ElementSearch).where(ElementSearch.tenant_id == tenant_id)) or 0
```

`backend/app/governance/dao.py`:

```python
def count_pending(session: Session, tenant_id: uuid.UUID) -> int:
    return session.scalar(
        select(func.count())
        .select_from(ToolInvocation)
        .outerjoin(ToolInvocationDecision, ToolInvocationDecision.invocation_id == ToolInvocation.id)
        .where(
            ToolInvocation.tenant_id == tenant_id,
            ToolInvocation.approval_required.is_(True),
            ToolInvocationDecision.invocation_id.is_(None),
        )
    ) or 0
```

- [ ] **Step 5: Create `backend/app/reporting/dashboard.py`**

```python
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from app import config
from app.assistant import dao as assistant_dao
from app.assistant.graph import eval_config_hash
from app.contracts import dao as contracts_dao
from app.documents import dao as documents_dao
from app.governance import dao as governance_dao
from app.ingestion_pipeline import PIPELINE, version_status
from app.retrieval import dao as retrieval_dao

REPORTS_DIR = config.BACKEND_DIR / "reports"
LATENCY_WINDOW = timedelta(days=7)
STATS_TTL_SECONDS = 15.0


@dataclass(frozen=True)
class EvalSummary:
    config_hash: str
    chat_model: str
    cases: int
    numbers_ok: float
    refusal_ok: float
    citation_hit: float


@dataclass(frozen=True)
class DashboardStats:
    documents_total: int
    documents_indexed: int
    documents_processing: int
    documents_failed: int
    indexed_chunks: int
    reviews_pending: int
    approvals_pending: int
    last_ingestion_at: datetime | None
    chat_turns_7d: int
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    eval: EvalSummary | None
    generated_at: datetime


@lru_cache(maxsize=8)
def _read_eval(path: Path, mtime_ns: int) -> EvalSummary:  # mtime is in the key, so a new golden-set run is picked up
    data = json.loads(path.read_text())
    metrics = data["metrics"]
    return EvalSummary(data["config_hash"], data["chat_model"], len(data["results"]),
                       metrics["numbers_ok"], metrics["refusal_ok"], metrics["citation_hit"])


def eval_summary(reports_dir: Path, config_hash: str) -> EvalSummary | None:
    """The golden-set report for exactly this configuration; a report for another model or prompt doesn't count."""
    path = reports_dir / f"eval-{config_hash}.json"
    if not path.is_file():
        return None
    return _read_eval(path, path.stat().st_mtime_ns)


def dashboard_stats(session: Session, tenant_id: uuid.UUID, *, now: datetime) -> DashboardStats:
    rows = documents_dao.list_documents(session, tenant_id)
    states = [version_status(PIPELINE, row.events).state for row in rows]
    latency = assistant_dao.latency_summary(session, tenant_id, since=now - LATENCY_WINDOW)
    return DashboardStats(
        documents_total=len(rows),
        documents_indexed=states.count("ready"),
        documents_processing=states.count("processing"),
        documents_failed=states.count("failed"),
        indexed_chunks=retrieval_dao.indexed_chunk_count(session, tenant_id),
        reviews_pending=len(contracts_dao.pending_reviews(session, tenant_id)),
        approvals_pending=governance_dao.count_pending(session, tenant_id),
        last_ingestion_at=documents_dao.last_event_at(session, tenant_id),
        chat_turns_7d=latency.turns,
        latency_p50_ms=latency.p50_ms,
        latency_p95_ms=latency.p95_ms,
        eval=eval_summary(REPORTS_DIR, eval_config_hash()),
        generated_at=now,
    )


# ponytail: per-process TTL cache — one API process in the demo; a shared cache (e.g. Redis) once there are several
_cache: dict[uuid.UUID, tuple[float, DashboardStats]] = {}


def cached_dashboard_stats(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    clock: Callable[[], float] = time.monotonic,
    ttl: float = STATS_TTL_SECONDS,
) -> DashboardStats:
    hit = _cache.get(tenant_id)
    if hit is not None and clock() - hit[0] < ttl:
        return hit[1]
    stats = dashboard_stats(session, tenant_id, now=datetime.now(timezone.utc))
    _cache[tenant_id] = (clock(), stats)
    return stats


def invalidate_dashboard_stats(tenant_id: uuid.UUID) -> None:
    _cache.pop(tenant_id, None)
```

- [ ] **Step 6: Create `backend/app/routes/stats.py`**

```python
import hashlib
import uuid
from datetime import datetime
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import config
from app.assistant.graph import eval_config_hash
from app.deps import get_session, get_tenant_id
from app.reporting.dashboard import cached_dashboard_stats

router = APIRouter(tags=["stats"])
SessionDep = Annotated[Session, Depends(get_session)]
TenantDep = Annotated[uuid.UUID, Depends(get_tenant_id)]
IfNoneMatch = Annotated[str | None, Header()]

STATS_CACHE_CONTROL = "private, no-cache"  # always revalidate; the ETag makes an unchanged payload a 304
CONFIG_CACHE_CONTROL = "public, max-age=3600"  # changes only on deploy


class DocumentStatsOut(BaseModel):
    total: int
    indexed: int
    processing: int
    failed: int
    indexed_chunks: int


class ChatStatsOut(BaseModel):
    turns_7d: int
    latency_p50_ms: int | None
    latency_p95_ms: int | None


class EvalOut(BaseModel):
    config_hash: str
    chat_model: str
    cases: int
    numbers_ok: float
    refusal_ok: float
    citation_hit: float


class StatsOut(BaseModel):
    documents: DocumentStatsOut
    reviews_pending: int
    approvals_pending: int
    last_ingestion_at: datetime | None
    chat: ChatStatsOut
    eval: EvalOut | None
    confidence_drop_rate: float | None  # rolling 7-day window; not tracked yet, so always null
    generated_at: datetime


class RetrievalConfigOut(BaseModel):
    search_candidates: int
    min_dense_similarity: float


class ConfigOut(BaseModel):
    chat_model: str
    extraction_model: str
    embedding_model: str
    embedding_dimensions: int
    parser: str
    pii: str
    vector_store: str
    retrieval: RetrievalConfigOut
    eval_config_hash: str


def _etag(body: BaseModel, exclude: set[str] | None = None) -> str:
    return '"' + hashlib.sha256(body.model_dump_json(exclude=exclude).encode()).hexdigest()[:16] + '"'


def _not_modified(etag: str, cache_control: str) -> Response:
    return Response(status_code=304, headers={"ETag": etag, "Cache-Control": cache_control})


@router.get("/stats", response_model=StatsOut)
def get_stats(response: Response, session: SessionDep, tenant_id: TenantDep, if_none_match: IfNoneMatch = None):
    s = cached_dashboard_stats(session, tenant_id)
    body = StatsOut(
        documents=DocumentStatsOut(total=s.documents_total, indexed=s.documents_indexed,
                                   processing=s.documents_processing, failed=s.documents_failed,
                                   indexed_chunks=s.indexed_chunks),
        reviews_pending=s.reviews_pending,
        approvals_pending=s.approvals_pending,
        last_ingestion_at=s.last_ingestion_at,
        chat=ChatStatsOut(turns_7d=s.chat_turns_7d, latency_p50_ms=s.latency_p50_ms, latency_p95_ms=s.latency_p95_ms),
        eval=None if s.eval is None else EvalOut(**s.eval.__dict__),
        confidence_drop_rate=None,
        generated_at=s.generated_at,
    )
    etag = _etag(body, exclude={"generated_at"})
    if if_none_match == etag:
        return _not_modified(etag, STATS_CACHE_CONTROL)
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = STATS_CACHE_CONTROL
    return body


@lru_cache(maxsize=1)
def _config_out() -> ConfigOut:
    return ConfigOut(
        chat_model=config.CHAT_MODEL,
        extraction_model=config.EXTRACTION_MODEL,
        embedding_model=config.EMBEDDING_MODEL,
        embedding_dimensions=config.EMBEDDING_DIMENSIONS,
        parser="Docling (local)",
        pii="Presidio tokens (local)",
        vector_store="Pinecone + Postgres full-text",
        retrieval=RetrievalConfigOut(search_candidates=config.SEARCH_CANDIDATES,
                                     min_dense_similarity=config.MIN_DENSE_SIMILARITY),
        eval_config_hash=eval_config_hash(),
    )


@router.get("/config", response_model=ConfigOut)
def get_config(response: Response, if_none_match: IfNoneMatch = None):
    body = _config_out()
    etag = _etag(body)
    if if_none_match == etag:
        return _not_modified(etag, CONFIG_CACHE_CONTROL)
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = CONFIG_CACHE_CONTROL
    return body
```

Register it in `backend/app/main.py`: add `stats` to the `from app.routes import ...` line and `app.include_router(stats.router)`.

- [ ] **Step 7: Invalidate on writes**

Import `from app.reporting.dashboard import invalidate_dashboard_stats` and call `invalidate_dashboard_stats(tenant_id)` right after the successful write in:
- `backend/app/routes/reviews.py` → `submit_review`, after `record_review(...)` returns.
- `backend/app/routes/tool_invocations.py` → `decide_tool_invocation`, after `decide(...)` returns.
- `backend/app/routes/documents.py` → `upload_document`, after `register_upload(...)` returns.

(The ingestion worker runs in another process and can't invalidate the cache; the 15 s TTL covers it.)

- [ ] **Step 8: Run the tests — expect PASS**

`$PYDEV/bin/pytest tests/test_stats_api.py -v`, then the full suite `$PYDEV/bin/pytest`. If `percentile_cont ... within_group` is rejected by the installed SQLAlchemy, **stop and report**.

- [ ] **Step 9: Commit**

```bash
graphify update .
git add backend/app/assistant/graph.py backend/tests/eval/test_golden.py backend/app/assistant/dao.py backend/app/documents/dao.py backend/app/retrieval/dao.py backend/app/governance/dao.py backend/app/reporting/dashboard.py backend/app/routes/stats.py backend/app/main.py backend/app/routes/reviews.py backend/app/routes/tool_invocations.py backend/app/routes/documents.py backend/tests/test_stats_api.py
git commit -m "feat(api): serve cached dashboard stats and deployment config"
```

---

### Task 4: Dashboard tiles and corpus telemetry on `/stats` + `/config` (R2, frontend)

**Files:**
- Modify: `frontend/src/api.ts`, `frontend/src/api.test.ts`
- Create: `frontend/src/lib/stats.ts`, `frontend/src/lib/stats.test.ts`
- Modify: `frontend/src/screens/Dashboard.tsx` (full replacement below), `frontend/src/screens/Dashboard.css`

**Interfaces:**
- Consumes: Task 3 endpoints.
- Produces: `getStats(): Promise<StatsDto>`, `getConfig(): Promise<ConfigDto>` (memoised for the page's lifetime; a failed request isn't memoised), types `StatsDto`, `ConfigDto`, `EvalDto`; `formatPercent(ratio: number): string`, `evalScore(evaluation: EvalDto): number`, `formatMs(ms: number | null): string`, `formatAgo(iso: string, now: number): string`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/lib/stats.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import type { EvalDto } from '../api';
import { evalScore, formatAgo, formatMs, formatPercent } from './stats';

const EVAL: EvalDto = { config_hash: 'abc', chat_model: 'm', cases: 8, numbers_ok: 1, refusal_ok: 0.875, citation_hit: 0.875 };

describe('stats formatting', () => {
  it('formats ratios as percentages with at most one decimal', () => {
    expect(formatPercent(0.875)).toBe('87.5%');
    expect(formatPercent(1)).toBe('100%');
  });

  it('scores the golden set as the mean of its three checks', () => {
    expect(evalScore(EVAL)).toBeCloseTo(0.9167, 3);
  });

  it('formats latency and shows a dash when there is none', () => {
    expect(formatMs(412)).toBe('412 ms');
    expect(formatMs(1830)).toBe('1.8 s');
    expect(formatMs(null)).toBe('—');
  });

  it('describes how long ago something happened', () => {
    const now = Date.parse('2026-09-26T12:00:00Z');
    expect(formatAgo('2026-09-26T11:59:30Z', now)).toBe('just now');
    expect(formatAgo('2026-09-26T11:43:00Z', now)).toBe('17 min ago');
    expect(formatAgo('2026-09-26T09:00:00Z', now)).toBe('3 h ago');
    expect(formatAgo('2026-09-24T12:00:00Z', now)).toBe('2 d ago');
  });
});
```

Append to `frontend/src/api.test.ts` (add `getConfig` to its import):

```ts
it('fetches the deployment config once and retries after a failure', async () => {
  vi.stubGlobal('fetch', () => Promise.reject(new TypeError('Failed to fetch')));
  await expect(getConfig()).rejects.toThrow();
  const calls = respondWith({ chat_model: 'm' });
  await getConfig();
  await getConfig();
  expect(calls).toHaveLength(1);
});
```

- [ ] **Step 2: Run — expect FAIL** (`npm test`: missing `./stats` and `getConfig`)

- [ ] **Step 3: Implement**

Append to `frontend/src/api.ts`:

```ts
export interface EvalDto {
  config_hash: string;
  chat_model: string;
  cases: number;
  numbers_ok: number;
  refusal_ok: number;
  citation_hit: number;
}

export interface StatsDto {
  documents: { total: number; indexed: number; processing: number; failed: number; indexed_chunks: number };
  reviews_pending: number;
  approvals_pending: number;
  last_ingestion_at: string | null;
  chat: { turns_7d: number; latency_p50_ms: number | null; latency_p95_ms: number | null };
  eval: EvalDto | null;
  confidence_drop_rate: number | null;
  generated_at: string;
}

export interface ConfigDto {
  chat_model: string;
  extraction_model: string;
  embedding_model: string;
  embedding_dimensions: number;
  parser: string;
  pii: string;
  vector_store: string;
  retrieval: { search_candidates: number; min_dense_similarity: number };
  eval_config_hash: string;
}

export function getStats(): Promise<StatsDto> {
  return fetch(`${API_BASE}/stats`).then((r) => json<StatsDto>(r));
}

let configRequest: Promise<ConfigDto> | null = null;

// The config only changes on deploy: one request per page load, and the HTTP cache covers reloads.
export function getConfig(): Promise<ConfigDto> {
  configRequest ??= fetch(`${API_BASE}/config`)
    .then((r) => json<ConfigDto>(r))
    .catch((error: unknown) => {
      configRequest = null;
      throw error;
    });
  return configRequest;
}
```

`frontend/src/lib/stats.ts`:

```ts
import type { EvalDto } from '../api';

export function formatPercent(ratio: number): string {
  return `${Number((ratio * 100).toFixed(1))}%`;
}

export function evalScore(evaluation: EvalDto): number {
  return (evaluation.numbers_ok + evaluation.refusal_ok + evaluation.citation_hit) / 3;
}

export function formatMs(ms: number | null): string {
  if (ms === null) return '—';
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function formatAgo(iso: string, now: number): string {
  const minutes = Math.floor((now - Date.parse(iso)) / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  return hours < 24 ? `${hours} h ago` : `${Math.floor(hours / 24)} d ago`;
}
```

- [ ] **Step 4: Run — expect PASS** (`npm test`).

- [ ] **Step 5: Replace `frontend/src/screens/Dashboard.tsx`**

```tsx
import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { type ConfigDto, type DocumentSummary, type StatsDto, getConfig, getStats, listDocuments, listPostings } from '../api';
import { StatusPill } from '../components/StatusPill';
import { type PostingView, toPostingView } from '../lib/postings';
import { evalScore, formatAgo, formatMs, formatPercent } from '../lib/stats';
import { formatUtc } from '../lib/time';
import './Dashboard.css';

const RECENT_POSTINGS = 5;
const CONTRACTS_SHOWN = 6;

interface DashboardData {
  stats: StatsDto;
  config: ConfigDto;
  documents: DocumentSummary[];
  postings: PostingView[];
}

interface StatTileProps {
  label: string;
  value: string;
  detail: string;
  tone?: 'warning';
  muted?: boolean;
  to?: string;
}

function StatTile({ label, value, detail, tone, muted, to }: StatTileProps) {
  const body = (
    <>
      <span className="stat-tile__label">{label}</span>
      <span className={`stat-tile__value mono${tone ? ` stat-tile__value--${tone}` : ''}`}>{value}</span>
      <span className="stat-tile__detail">{detail}</span>
    </>
  );
  const className = `stat-tile${muted ? ' stat-tile--muted' : ''}`;
  return to ? (
    <Link to={to} className={`${className} stat-tile--link`}>
      {body}
    </Link>
  ) : (
    <div className={className} aria-disabled={muted || undefined}>
      {body}
    </div>
  );
}

interface QueueRowProps {
  count: number;
  label: string;
  detail: string;
  to: string;
  action: string;
}

function QueueRow({ count, label, detail, to, action }: QueueRowProps) {
  return (
    <li className="queue__row">
      <span className={`queue__count mono${count === 0 ? ' queue__count--zero' : ''}`}>{count}</span>
      <div className="queue__text">
        <span className="queue__label">{label}</span>
        <span className="queue__detail">{detail}</span>
      </div>
      <Link to={to} className="queue__action">
        {action} →
      </Link>
    </li>
  );
}

interface TelemetryRowProps {
  label: string;
  value: string;
  note?: string;
}

function TelemetryRow({ label, value, note }: TelemetryRowProps) {
  return (
    <div className="telemetry__row">
      <dt>{label}</dt>
      <dd>
        <span className="mono">{value}</span>
        {note && <span className="telemetry__note">{note}</span>}
      </dd>
    </div>
  );
}

const DOC_STATUS: Record<DocumentSummary['status'], { variant: 'success' | 'accent' | 'warning'; label: string }> = {
  ready: { variant: 'success', label: 'Indexed' },
  processing: { variant: 'accent', label: 'Processing' },
  failed: { variant: 'warning', label: 'Failed' },
};

export function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getStats(), getConfig(), listDocuments(), listPostings({ limit: RECENT_POSTINGS })])
      .then(([stats, config, documents, page]) => {
        if (!cancelled) setData({ stats, config, documents, postings: page.items.map(toPostingView) });
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const now = Date.now();

  return (
    <div className="dashboard">
      <div className="dashboard__topbar">
        <span className="dashboard__breadcrumb">Dashboard</span>
      </div>

      <div className="dashboard__body">
        <div className="dashboard__header">
          <div>
            <h1 className="dashboard__title">Dashboard</h1>
            <p className="dashboard__subtitle">What needs a person, how the corpus looks, and what posted recently.</p>
          </div>
          <Link to="/chat" className="btn btn-primary">
            Ask the assistant
          </Link>
        </div>

        {error && (
          <div className="panel dashboard__error" role="alert">
            <strong>Couldn't reach the API.</strong> {error}. Start the backend with{' '}
            <code className="mono">uvicorn app.main:app</code> and reload.
          </div>
        )}

        {!error && data === null && <p className="dashboard__loading">Loading…</p>}

        {data && (
          <>
            <div className="dashboard__stats">
              <StatTile
                label="Documents indexed"
                value={`${data.stats.documents.indexed} / ${data.stats.documents.total}`}
                detail={`${data.stats.documents.indexed_chunks.toLocaleString('en-US')} chunks indexed`}
              />
              <StatTile
                label="Needs review"
                value={String(data.stats.reviews_pending + data.stats.approvals_pending)}
                detail={`${data.stats.reviews_pending} fields · ${data.stats.approvals_pending} corrections`}
                tone={data.stats.reviews_pending + data.stats.approvals_pending > 0 ? 'warning' : undefined}
                to="/review"
              />
              <StatTile label="Confidence drop-rate" value="—" detail="Rolling 7-day window · not tracked in this demo" muted />
              <StatTile
                label="Golden-set eval"
                value={data.stats.eval ? formatPercent(evalScore(data.stats.eval)) : '—'}
                detail={
                  data.stats.eval
                    ? `${data.stats.eval.cases} cases · numbers ${formatPercent(data.stats.eval.numbers_ok)} · refusals ${formatPercent(data.stats.eval.refusal_ok)} · citations ${formatPercent(data.stats.eval.citation_hit)}`
                    : 'No golden-set run for the running configuration'
                }
                muted={!data.stats.eval}
              />
            </div>

            <div className="dashboard__grid">
              <div className="dashboard__col">
                <section className="panel">
                  <div className="panel__head">
                    <h2 className="panel__title">Needs a person</h2>
                  </div>
                  <ul className="queue">
                    <QueueRow
                      count={data.stats.reviews_pending}
                      label="extracted fields to review"
                      detail="Held back because the quote couldn't be grounded, a validator failed, or the page was hard to read."
                      to="/review"
                      action="Review fields"
                    />
                    <QueueRow
                      count={data.stats.approvals_pending}
                      label="fee corrections to approve"
                      detail="Proposed by the assistant. Nothing posts to the ledger until someone approves it."
                      to="/review#approvals"
                      action="Review corrections"
                    />
                    <QueueRow
                      count={data.stats.documents.failed}
                      label="documents failed ingestion"
                      detail="Usually a scanned PDF without a text layer."
                      to="/documents"
                      action="Open documents"
                    />
                  </ul>
                </section>

                <section className="panel">
                  <div className="panel__head">
                    <h2 className="panel__title">Recent postings</h2>
                  </div>
                  {data.postings.length === 0 ? (
                    <p className="dashboard__empty">No postings yet. Approved corrections and fee runs will appear here.</p>
                  ) : (
                    <div className="scroll-x">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>Created</th>
                            <th>Description</th>
                            <th>Source</th>
                            <th style={{ textAlign: 'right' }}>Amount</th>
                          </tr>
                        </thead>
                        <tbody>
                          {data.postings.map((p) => (
                            <tr key={p.id}>
                              <td className="mono">{formatUtc(p.createdAt)}</td>
                              <td>
                                <Link to={`/ledger?posting=${p.id}`}>{p.description}</Link>
                              </td>
                              <td className="mono">{p.source}</td>
                              <td className="num">{p.amount}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  <Link className="panel__footer-link" to="/ledger">
                    Open the ledger →
                  </Link>
                </section>
              </div>

              <div className="dashboard__col">
                <section className="panel">
                  <div className="panel__head">
                    <h2 className="panel__title">Corpus &amp; telemetry</h2>
                  </div>
                  <dl className="telemetry">
                    <TelemetryRow
                      label="Documents"
                      value={`${data.stats.documents.total}`}
                      note={`${data.stats.documents.processing} processing · ${data.stats.documents.failed} failed`}
                    />
                    <TelemetryRow
                      label="Indexed chunks"
                      value={data.stats.documents.indexed_chunks.toLocaleString('en-US')}
                      note={data.config.vector_store}
                    />
                    <TelemetryRow
                      label="Embeddings"
                      value={data.config.embedding_model}
                      note={`${data.config.embedding_dimensions} dimensions`}
                    />
                    <TelemetryRow label="Chat model" value={data.config.chat_model} />
                    <TelemetryRow
                      label="Last ingestion"
                      value={data.stats.last_ingestion_at ? formatUtc(data.stats.last_ingestion_at) : '—'}
                      note={data.stats.last_ingestion_at ? formatAgo(data.stats.last_ingestion_at, now) : undefined}
                    />
                    <TelemetryRow
                      label="Answer latency (7 d)"
                      value={`p50 ${formatMs(data.stats.chat.latency_p50_ms)} · p95 ${formatMs(data.stats.chat.latency_p95_ms)}`}
                      note={`${data.stats.chat.turns_7d} chat turns`}
                    />
                    <TelemetryRow
                      label="Citation coverage"
                      value={data.stats.eval ? formatPercent(data.stats.eval.citation_hit) : '—'}
                      note="golden set"
                    />
                  </dl>
                </section>

                <section className="panel">
                  <div className="panel__head">
                    <h2 className="panel__title">Contracts</h2>
                  </div>
                  {data.documents.length === 0 ? (
                    <p className="dashboard__empty">
                      No contracts yet. <Link to="/documents">Upload one</Link> to start.
                    </p>
                  ) : (
                    <ul className="contract-list">
                      {data.documents.slice(0, CONTRACTS_SHOWN).map((doc) => (
                        <li key={doc.id} className="contract-list__row">
                          <span className="contract-list__title" title={doc.title}>
                            {doc.title}
                          </span>
                          <StatusPill variant={DOC_STATUS[doc.status].variant}>{DOC_STATUS[doc.status].label}</StatusPill>
                        </li>
                      ))}
                    </ul>
                  )}
                  <Link className="panel__footer-link" to="/documents">
                    All documents →
                  </Link>
                </section>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Update `frontend/src/screens/Dashboard.css`**

Replace the `.dashboard__grid` and `.dashboard__wide` rules with the rules below, and add the tile and telemetry rules. Keep every other existing rule.

```css
.dashboard__stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.stat-tile {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  background: var(--color-surface);
  color: var(--color-text-primary);
}

.stat-tile--link:hover {
  border-color: var(--color-accent);
  color: var(--color-text-primary);
}

.stat-tile--muted {
  background: var(--color-bg-subtle);
}

.stat-tile--muted .stat-tile__value,
.stat-tile--muted .stat-tile__label {
  color: var(--color-text-secondary);
}

.stat-tile__label {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-secondary);
}

.stat-tile__value {
  font-size: 26px;
  font-weight: 600;
  line-height: 1.2;
}

.stat-tile__value--warning {
  color: var(--color-warning);
}

.stat-tile__detail {
  font-size: 12px;
  color: var(--color-text-secondary);
}

.dashboard__grid {
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
  gap: var(--space-3);
  align-items: start;
}

.dashboard__col {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.telemetry {
  margin: 0;
}

.telemetry__row {
  display: grid;
  grid-template-columns: 140px 1fr;
  gap: var(--space-2);
  padding: 10px 0;
  border-top: 1px solid var(--color-border);
  font-size: 13px;
}

.telemetry__row:first-child {
  border-top: none;
  padding-top: 0;
}

.telemetry__row dt {
  color: var(--color-text-secondary);
}

.telemetry__row dd {
  margin: 0;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow-wrap: anywhere;
}

.telemetry__note {
  font-size: 12px;
  color: var(--color-text-secondary);
}

@media (max-width: 1080px) {
  .dashboard__stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .dashboard__stats {
    grid-template-columns: 1fr;
  }
}
```

(The existing `@media (max-width: 1080px) { .dashboard__grid { grid-template-columns: 1fr; } }` rule stays.)

Check: `grep -n "dashboard__wide" frontend/src/screens/Dashboard.*` prints nothing.

- [ ] **Step 7: Verify and commit**

`npm test && npm run lint && npm run build`. In the browser: the four tiles show real numbers; "Confidence drop-rate" is greyed with "—"; the golden-set tile shows a score if `backend/reports/eval-<hash>.json` matches the running config, and is greyed otherwise; the telemetry values match `/stats` and `/config` (compare with `curl localhost:8000/stats`). In DevTools → Network, reloading the dashboard shows `/config` served from cache and `/stats` answered with 304 while nothing changed.

```bash
graphify update .
git add frontend/src/api.ts frontend/src/api.test.ts frontend/src/lib/stats.ts frontend/src/lib/stats.test.ts frontend/src/screens/Dashboard.tsx frontend/src/screens/Dashboard.css
git commit -m "feat(frontend): bring back dashboard tiles and corpus telemetry on real stats"
```

---

### Task 5: The `DocumentViewer` component (pdf.js, code-split) (R3)

**Files:**
- Modify: `frontend/package.json`, `frontend/package-lock.json` (add `pdfjs-dist`)
- Create: `frontend/src/lib/viewer.ts`, `frontend/src/lib/viewer.test.ts`
- Create: `frontend/src/components/DocumentViewer/DocumentViewer.tsx`
- Create: `frontend/src/components/DocumentViewer/DocumentViewer.css`
- Create: `frontend/src/components/DocumentViewer/index.ts`

**Interfaces:**
- Consumes: `documentPageUrl(documentId, version, page)` (existing, in `api.ts`).
- Produces: `DocumentViewer` (a lazy component; render it inside `<Suspense>`) with props `DocumentViewerProps { documentId: string; version: number; page?: number | null; title?: string; onClose?: () => void }`. When `page` changes, the viewer jumps to it; when `documentId`/`version` change, it loads the other PDF. It fills its parent's height.
- Produces: `clampPage(page: number | null | undefined, numPages: number): number`, `nextZoom(current: number, direction: 1 | -1): number`, `ZOOM_STEPS`.

**React pattern (for the record):** one presentational, *controlled* component. The screen owns which document and page to show, and passes them as props. The viewer owns only viewing state (current page, zoom). It is code-split with `React.lazy`, so pdf.js (~1 MB with its worker) is downloaded only when a screen renders it. Screens decide its lifetime: Documents mounts it conditionally, so closing unmounts it and frees the PDF and the worker. Review keeps it mounted. No context provider and no portal: only two screens use it, and props are enough.

- [ ] **Step 1: Install pdf.js**

`cd frontend && npm install pdfjs-dist`

- [ ] **Step 2: Write the failing tests** — `frontend/src/lib/viewer.test.ts`

```ts
import { describe, expect, it } from 'vitest';
import { clampPage, nextZoom } from './viewer';

describe('clampPage', () => {
  it('keeps a valid page', () => {
    expect(clampPage(3, 10)).toBe(3);
  });

  it('opens page 1 for a missing or non-positive page', () => {
    expect(clampPage(null, 10)).toBe(1);
    expect(clampPage(undefined, 10)).toBe(1);
    expect(clampPage(0, 10)).toBe(1);
  });

  it('opens the last page for a page beyond the end', () => {
    expect(clampPage(42, 10)).toBe(10);
  });
});

describe('nextZoom', () => {
  it('steps through the zoom levels and stops at the ends', () => {
    expect(nextZoom(1, 1)).toBe(1.25);
    expect(nextZoom(1, -1)).toBe(0.75);
    expect(nextZoom(2, 1)).toBe(2);
    expect(nextZoom(0.5, -1)).toBe(0.5);
  });

  it('restarts from 100% for an unknown level', () => {
    expect(nextZoom(1.1, 1)).toBe(1.25);
  });
});
```

- [ ] **Step 3: Run — expect FAIL**, then implement `frontend/src/lib/viewer.ts`

```ts
export const ZOOM_STEPS = [0.5, 0.75, 1, 1.25, 1.5, 2] as const;

export function clampPage(page: number | null | undefined, numPages: number): number {
  const wanted = Math.trunc(page ?? 1) || 1;
  return Math.min(Math.max(1, wanted), Math.max(1, numPages));
}

export function nextZoom(current: number, direction: 1 | -1): number {
  const index = ZOOM_STEPS.findIndex((step) => step === current);
  const from = index === -1 ? ZOOM_STEPS.indexOf(1) : index;
  return ZOOM_STEPS[Math.min(Math.max(from + direction, 0), ZOOM_STEPS.length - 1)];
}
```

Run `npm test` — expect PASS.

- [ ] **Step 4: Create `frontend/src/components/DocumentViewer/DocumentViewer.tsx`**

```tsx
import { useEffect, useRef, useState } from 'react';
import { GlobalWorkerOptions, type PDFDocumentProxy, type RenderTask, getDocument } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { documentPageUrl } from '../../api';
import { clampPage, nextZoom } from '../../lib/viewer';
import './DocumentViewer.css';

GlobalWorkerOptions.workerSrc = workerUrl;

export interface DocumentViewerProps {
  documentId: string;
  version: number;
  page?: number | null;
  title?: string;
  onClose?: () => void;
}

type Loaded = { url: string; doc: PDFDocumentProxy };
type Failure = { url: string; message: string };

export default function DocumentViewer({ documentId, version, page, title, onClose }: DocumentViewerProps) {
  const url = documentPageUrl(documentId, version, null);
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [current, setCurrent] = useState(page ?? 1);
  const [zoom, setZoom] = useState(1);

  // Follow the page the screen asks for (React's "adjust state when a prop changes" pattern, no effect needed).
  const target = `${url}#${page ?? 1}`;
  const [lastTarget, setLastTarget] = useState(target);
  if (target !== lastTarget) {
    setLastTarget(target);
    setCurrent(page ?? 1);
  }

  // Only ever render the document that belongs to the current URL, never the previous one mid-switch.
  const doc = loaded?.url === url ? loaded.doc : null;
  const error = failure?.url === url ? failure.message : null;
  const pageNumber = doc ? clampPage(current, doc.numPages) : 1;

  useEffect(() => {
    const task = getDocument({ url });
    let cancelled = false;
    task.promise
      .then((pdf) => {
        if (!cancelled) setLoaded({ url, doc: pdf });
      })
      .catch((e: unknown) => {
        if (!cancelled) setFailure({ url, message: e instanceof Error ? e.message : 'Could not open the PDF' });
      });
    return () => {
      cancelled = true;
      void task.destroy();
    };
  }, [url]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!doc || !canvas || !container) return;
    let cancelled = false;
    let render: RenderTask | null = null;
    doc.getPage(pageNumber).then((pdfPage) => {
      if (cancelled) return;
      // ponytail: fit-to-width is measured once per render; a window resize applies on the next page or zoom change
      const fit = (container.clientWidth - 32) / pdfPage.getViewport({ scale: 1 }).width;
      const viewport = pdfPage.getViewport({ scale: Math.max(fit, 0.1) * zoom });
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.floor(viewport.width * ratio);
      canvas.height = Math.floor(viewport.height * ratio);
      canvas.style.width = `${Math.floor(viewport.width)}px`;
      canvas.style.height = `${Math.floor(viewport.height)}px`;
      render = pdfPage.render({ canvas, viewport, transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0] });
      render.promise.catch(() => undefined); // a cancelled render rejects; nothing to report
    });
    return () => {
      cancelled = true;
      render?.cancel();
    };
  }, [doc, pageNumber, zoom]);

  return (
    <section className="doc-viewer" aria-label={title ? `${title}, page ${pageNumber}` : 'Document viewer'}>
      <header className="doc-viewer__toolbar">
        <span className="doc-viewer__title" title={title}>
          {title ?? 'Document'}
        </span>
        <div className="doc-viewer__controls">
          <button type="button" className="doc-viewer__btn" aria-label="Previous page" disabled={!doc || pageNumber <= 1} onClick={() => setCurrent(pageNumber - 1)}>
            ‹
          </button>
          <span className="doc-viewer__page mono">
            {doc ? `${pageNumber} / ${doc.numPages}` : '…'}
          </span>
          <button type="button" className="doc-viewer__btn" aria-label="Next page" disabled={!doc || pageNumber >= doc.numPages} onClick={() => setCurrent(pageNumber + 1)}>
            ›
          </button>
          <button type="button" className="doc-viewer__btn" aria-label="Zoom out" onClick={() => setZoom((z) => nextZoom(z, -1))}>
            −
          </button>
          <span className="doc-viewer__page mono">{Math.round(zoom * 100)}%</span>
          <button type="button" className="doc-viewer__btn" aria-label="Zoom in" onClick={() => setZoom((z) => nextZoom(z, 1))}>
            +
          </button>
          <a className="doc-viewer__link" href={documentPageUrl(documentId, version, pageNumber)} target="_blank" rel="noreferrer">
            New tab ↗
          </a>
          {onClose && (
            <button type="button" className="doc-viewer__btn doc-viewer__close" aria-label="Close viewer" onClick={onClose}>
              ✕
            </button>
          )}
        </div>
      </header>
      <div className="doc-viewer__canvas-wrap" ref={containerRef}>
        {error ? (
          <p className="doc-viewer__message" role="alert">
            {error}
          </p>
        ) : (
          <>
            {!doc && <p className="doc-viewer__message">Loading document…</p>}
            <canvas ref={canvasRef} className="doc-viewer__canvas" hidden={!doc} />
          </>
        )}
      </div>
    </section>
  );
}
```

If `tsc` rejects the `render({ canvas, viewport, transform })` parameters for the installed pdfjs-dist version, add `canvasContext: canvas.getContext('2d')` and nothing else. If it still fails, **stop and report the type error**.

- [ ] **Step 5: Create `frontend/src/components/DocumentViewer/DocumentViewer.css`**

```css
.doc-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--color-bg-subtle);
}

.doc-viewer__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-1);
  padding: 8px 12px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
  flex-wrap: wrap;
}

.doc-viewer__title {
  font-size: 13px;
  font-weight: 600;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.doc-viewer__controls {
  display: flex;
  align-items: center;
  gap: 4px;
}

.doc-viewer__btn {
  min-width: 32px;
  height: 32px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-surface);
  font-size: 15px;
  line-height: 1;
}

.doc-viewer__btn:hover:not(:disabled) {
  border-color: var(--color-text-secondary);
}

.doc-viewer__btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.doc-viewer__page {
  font-size: 12px;
  min-width: 52px;
  text-align: center;
  color: var(--color-text-secondary);
}

.doc-viewer__link {
  font-size: 12px;
  margin: 0 6px;
}

.doc-viewer__canvas-wrap {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: var(--space-2);
  display: flex;
  justify-content: center;
  align-items: flex-start;
}

.doc-viewer__canvas {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
}

.doc-viewer__message {
  font-size: 13px;
  color: var(--color-text-secondary);
  margin-top: var(--space-4);
}
```

- [ ] **Step 6: Create `frontend/src/components/DocumentViewer/index.ts`**

```ts
import { lazy } from 'react';

export type { DocumentViewerProps } from './DocumentViewer';

// Code-split: pdf.js and its worker are fetched only by screens that actually render a document.
export const DocumentViewer = lazy(() => import('./DocumentViewer'));
```

- [ ] **Step 7: Verify and commit**

`npm test && npm run lint && npm run build`. The build output must list a **separate chunk** for the viewer, plus a `pdf.worker` asset; the main `index-*.js` must not grow by the size of pdf.js. Record the before/after main-chunk size in the report.

```bash
graphify update .
git add frontend/package.json frontend/package-lock.json frontend/src/lib/viewer.ts frontend/src/lib/viewer.test.ts frontend/src/components/DocumentViewer
git commit -m "feat(frontend): add a code-split pdf.js document viewer"
```

---

### Task 6: "View document" on Documents (R4)

**Files:**
- Modify: `frontend/src/screens/Documents.tsx`, `frontend/src/screens/Documents.css`
- Modify: `frontend/src/index.css` (z-index scale)

**Interfaces:**
- Consumes: `DocumentViewer` (Task 5).

- [ ] **Step 1: Add a z-index scale** to `:root` in `frontend/src/index.css`:

```css
  --z-sticky: 10;
  --z-sheet: 20;
```

In `frontend/src/components/Sidebar.css`, replace `z-index: 10;` with `z-index: var(--z-sticky);`.

- [ ] **Step 2: Wire the viewer into `Documents.tsx`**

- Change the React import to `import { Suspense, useEffect, useRef, useState } from 'react';` and add `import { DocumentViewer } from '../components/DocumentViewer';`.
- Add state after the other `useState` calls: `const [viewerOpen, setViewerOpen] = useState(false);`
- Close on Escape (this sets state from an event, not synchronously in an effect):

```tsx
  useEffect(() => {
    if (!viewerOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setViewerOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [viewerOpen]);
```

- In the detail `<aside>`, directly under the `documents__detail-id` block, add:

```tsx
              <button type="button" className="btn btn-primary documents__view-btn" onClick={() => setViewerOpen(true)}>
                View document
              </button>
```

- As the last child of the root `<div className="documents">`:

```tsx
      {viewerOpen && current && (
        <div className="viewer-sheet" role="dialog" aria-modal="false" aria-label={`${current.title} viewer`}>
          <Suspense fallback={<p className="viewer-sheet__loading">Loading viewer…</p>}>
            <DocumentViewer
              documentId={current.id}
              version={current.version}
              title={current.title}
              onClose={() => setViewerOpen(false)}
            />
          </Suspense>
        </div>
      )}
```

(While the sheet is open, selecting another row switches the sheet to that document. Closing unmounts the viewer entirely.)

- [ ] **Step 3: Styles** — append to `frontend/src/screens/Documents.css`:

```css
.documents__view-btn {
  margin: var(--space-2) 0;
  width: 100%;
}

.viewer-sheet {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(760px, 100vw);
  z-index: var(--z-sheet);
  border-left: 1px solid var(--color-border);
  box-shadow: -4px 0 8px rgba(15, 20, 35, 0.08);
  background: var(--color-bg-subtle);
}

.viewer-sheet__loading {
  padding: var(--space-3);
  font-size: 13px;
  color: var(--color-text-secondary);
}

@media (prefers-reduced-motion: no-preference) {
  .viewer-sheet {
    animation: viewer-sheet-in 200ms cubic-bezier(0.22, 1, 0.36, 1);
  }

  @keyframes viewer-sheet-in {
    from {
      transform: translateX(24px);
      opacity: 0;
    }
    to {
      transform: none;
      opacity: 1;
    }
  }
}

@media (max-width: 860px) {
  .viewer-sheet {
    bottom: 64px;
  }
}
```

(`rgba(15, 20, 35, …)` is `--color-bg-dark` with alpha; if the colour grep from round 1 flags it, add `--color-shadow: rgba(15, 20, 35, 0.08);` to `:root` and use that.)

- [ ] **Step 4: Verify and commit**

`npm test && npm run lint && npm run build`. In the browser (backend running): on `/documents`, "View document" opens the sheet with page 1; next/prev and zoom work; selecting another row switches the document; ✕ and Escape remove the sheet. In DevTools → Network, the pdf.js chunk loads only on the first "View document", not when `/documents` loads.

```bash
graphify update .
git add frontend/src/screens/Documents.tsx frontend/src/screens/Documents.css frontend/src/index.css frontend/src/components/Sidebar.css
git commit -m "feat(frontend): view a document in a side sheet from the documents screen"
```

---

### Task 7: Two-pane, paginated Review with the viewer (R5)

**Files:**
- Create: `frontend/src/lib/paginate.ts`, `frontend/src/lib/paginate.test.ts`
- Modify: `frontend/src/lib/review.ts`, `frontend/src/lib/review.test.ts` (viewer targets)
- Create: `frontend/src/components/Pager.tsx`
- Modify: `frontend/src/screens/Review.tsx` (full replacement below), `frontend/src/screens/Review.css` (full replacement below)

**Interfaces:**
- Consumes: `DocumentViewer` (Task 5); `listReviews`, `listToolInvocations`, `listDocuments`, `submitReview`, `ReviewItemDto`, `ToolInvocationDto`, `DocumentSummary` (existing); `ApprovalCard`, `formatValue`, `parseCorrection`, `reviewReasons` (existing).
- Produces: `paginate<T>(items: T[], page: number, size: number): PageSlice<T>`; `ViewerTarget`, `fieldTarget(item)`, `approvalTarget(invocation, documents)`; `Pager({ page, pageCount, onChange, label })`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/lib/paginate.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { paginate } from './paginate';

const ITEMS = [1, 2, 3, 4, 5, 6, 7];

describe('paginate', () => {
  it('slices one page', () => {
    expect(paginate(ITEMS, 1, 5)).toEqual({ items: [1, 2, 3, 4, 5], page: 1, pageCount: 2 });
  });

  it('returns the partial last page', () => {
    expect(paginate(ITEMS, 2, 5)).toEqual({ items: [6, 7], page: 2, pageCount: 2 });
  });

  it('clamps a page that no longer exists after the list shrinks', () => {
    expect(paginate([1, 2], 3, 5)).toEqual({ items: [1, 2], page: 1, pageCount: 1 });
  });

  it('has one empty page for an empty list', () => {
    expect(paginate([], 1, 5)).toEqual({ items: [], page: 1, pageCount: 1 });
  });
});
```

Append to `frontend/src/lib/review.test.ts` (add `approvalTarget, fieldTarget` to the import; add `DocumentSummary, ToolInvocationDto` to the type import from `'../api'`):

```ts
describe('viewer targets', () => {
  const item: ReviewItemDto = {
    run_id: 'r1', field_path: 'fee_method', value: 'cliff', quote: 'q', grounded: false, validator_errors: [],
    page_grade: 'FAIR', document_id: 'd1', document_title: 'Tremblay IMA', version: 2, page: 3,
  };

  it('points a field at its document, version and page', () => {
    expect(fieldTarget(item)).toEqual({
      key: 'field:r1:fee_method', documentId: 'd1', version: 2, page: 3, title: 'Tremblay IMA',
    });
  });

  it('points a correction at the current version of the compared contract', () => {
    const invocation = { id: 'i1', input: { document_id: 'd1' } } as unknown as ToolInvocationDto;
    const documents = [{ id: 'd1', version: 4, title: 'Tremblay IMA' }] as unknown as DocumentSummary[];
    expect(approvalTarget(invocation, documents)).toEqual({
      key: 'approval:i1', documentId: 'd1', version: 4, page: null, title: 'Tremblay IMA',
    });
    expect(approvalTarget({ id: 'i2', input: {} } as unknown as ToolInvocationDto, documents)).toBeNull();
  });
});
```

- [ ] **Step 2: Run — expect FAIL**, then implement

`frontend/src/lib/paginate.ts`:

```ts
export interface PageSlice<T> {
  items: T[];
  page: number;
  pageCount: number;
}

export function paginate<T>(items: T[], page: number, size: number): PageSlice<T> {
  const pageCount = Math.max(1, Math.ceil(items.length / size));
  const current = Math.min(Math.max(1, page), pageCount);
  return { items: items.slice((current - 1) * size, current * size), page: current, pageCount };
}
```

Append to `frontend/src/lib/review.ts` (extend its type import from `'../api'` with `DocumentSummary, ToolInvocationDto`):

```ts
export interface ViewerTarget {
  key: string;
  documentId: string;
  version: number;
  page: number | null;
  title: string;
}

export function fieldTarget(item: ReviewItemDto): ViewerTarget {
  return {
    key: `field:${item.run_id}:${item.field_path}`,
    documentId: item.document_id,
    version: item.version,
    page: item.page,
    title: item.document_title,
  };
}

export function approvalTarget(invocation: ToolInvocationDto, documents: DocumentSummary[]): ViewerTarget | null {
  const documentId = invocation.input.document_id;
  const doc = typeof documentId === 'string' ? documents.find((d) => d.id === documentId) : undefined;
  if (!doc) return null;
  return { key: `approval:${invocation.id}`, documentId: doc.id, version: doc.version, page: null, title: doc.title };
}
```

Run `npm test` — expect PASS.

- [ ] **Step 3: Create `frontend/src/components/Pager.tsx`**

```tsx
interface PagerProps {
  page: number;
  pageCount: number;
  onChange: (page: number) => void;
  label: string;
}

export function Pager({ page, pageCount, onChange, label }: PagerProps) {
  if (pageCount <= 1) return null;
  return (
    <nav className="pager" aria-label={label}>
      <button type="button" className="btn btn-secondary pager__btn" disabled={page <= 1} onClick={() => onChange(page - 1)}>
        ← Previous
      </button>
      <span className="pager__status mono">
        Page {page} of {pageCount}
      </span>
      <button type="button" className="btn btn-secondary pager__btn" disabled={page >= pageCount} onClick={() => onChange(page + 1)}>
        Next →
      </button>
    </nav>
  );
}
```

- [ ] **Step 4: Replace `frontend/src/screens/Review.tsx`**

```tsx
import { Suspense, useCallback, useEffect, useState } from 'react';
import {
  type DocumentSummary,
  type ReviewDecision,
  type ReviewItemDto,
  type ToolInvocationDto,
  listDocuments,
  listReviews,
  listToolInvocations,
  submitReview,
} from '../api';
import { ApprovalCard } from '../components/ApprovalCard';
import { DocumentViewer } from '../components/DocumentViewer';
import { Pager } from '../components/Pager';
import { paginate } from '../lib/paginate';
import {
  type ViewerTarget,
  approvalTarget,
  fieldTarget,
  formatValue,
  parseCorrection,
  reviewReasons,
} from '../lib/review';
import './Review.css';

const PAGE_SIZE = 5;

interface FieldReviewCardProps {
  item: ReviewItemDto;
  selected: boolean;
  onSelect: () => void;
  onDone: () => void;
}

function FieldReviewCard({ item, selected, onSelect, onDone }: FieldReviewCardProps) {
  const [correcting, setCorrecting] = useState(false);
  const [draft, setDraft] = useState(formatValue(item.value));
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async (decision: ReviewDecision) => {
    const corrected = decision === 'corrected' ? parseCorrection(draft) : null;
    if (decision === 'corrected' && corrected === undefined) {
      setError('Enter the corrected value.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await submitReview({
        run_id: item.run_id,
        field_path: item.field_path,
        decision,
        corrected_value: corrected ?? null,
        reason: reason.trim() || null,
      });
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The decision was not recorded');
      setSubmitting(false);
    }
  };

  return (
    <article className={`field-card${selected ? ' field-card--selected' : ''}`}>
      <div className="field-card__head">
        <span className="field-card__path mono">{item.field_path}</span>
        <span className="field-card__doc">
          {item.document_title} · v{item.version}
          {item.page !== null && ` · p.${item.page}`}
        </span>
        <button type="button" className="field-card__show" aria-pressed={selected} onClick={onSelect}>
          {selected ? 'Showing' : `Show ${item.page !== null ? `page ${item.page}` : 'document'}`}
        </button>
      </div>
      <dl className="field-card__facts">
        <dt>Extracted value</dt>
        <dd className="mono">{formatValue(item.value)}</dd>
        <dt>Quote</dt>
        <dd className="field-card__quote">“{item.quote}”</dd>
      </dl>
      <ul className="field-card__reasons">
        {reviewReasons(item).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      {correcting && (
        <div className="field-card__correct">
          <label>
            Corrected value
            <input className="mono" value={draft} onChange={(event) => setDraft(event.target.value)} />
          </label>
          <label>
            Reason (optional)
            <input value={reason} onChange={(event) => setReason(event.target.value)} />
          </label>
        </div>
      )}
      <div className="field-card__actions">
        {correcting ? (
          <>
            <button type="button" className="btn btn-primary" disabled={submitting} onClick={() => void send('corrected')}>
              Save correction
            </button>
            <button type="button" className="btn btn-secondary" disabled={submitting} onClick={() => setCorrecting(false)}>
              Cancel
            </button>
          </>
        ) : (
          <>
            <button type="button" className="btn btn-primary" disabled={submitting} onClick={() => void send('confirmed')}>
              Confirm value
            </button>
            <button type="button" className="btn btn-secondary" disabled={submitting} onClick={() => setCorrecting(true)}>
              Correct
            </button>
            <button type="button" className="btn btn-secondary" disabled={submitting} onClick={() => void send('rejected')}>
              Reject
            </button>
          </>
        )}
        {error && (
          <span className="field-card__error" role="alert">
            {error}
          </span>
        )}
      </div>
    </article>
  );
}

export function Review() {
  const [items, setItems] = useState<ReviewItemDto[] | null>(null);
  const [approvals, setApprovals] = useState<ToolInvocationDto[] | null>(null);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [fieldPage, setFieldPage] = useState(1);
  const [approvalPage, setApprovalPage] = useState(1);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const load = useCallback(() => {
    Promise.all([listReviews(), listToolInvocations({ pending: true }), listDocuments()])
      .then(([reviewItems, pending, docs]) => {
        setItems(reviewItems);
        setApprovals(pending);
        setDocuments(docs);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const fields = paginate(items ?? [], fieldPage, PAGE_SIZE);
  const corrections = paginate(approvals ?? [], approvalPage, PAGE_SIZE);

  // Everything the viewer can show, in list order; the first one is shown until the reviewer picks another.
  const targets: ViewerTarget[] = [
    ...(items ?? []).map(fieldTarget),
    ...(approvals ?? []).flatMap((invocation) => approvalTarget(invocation, documents) ?? []),
  ];
  const selected = targets.find((t) => t.key === selectedKey) ?? targets[0] ?? null;

  return (
    <div className="review">
      <div className="review__topbar">
        <span>Review</span>
      </div>
      <div className="review__panes">
        <div className="review__list-pane">
          <h1 className="review__title">Review</h1>
          <p className="review__subtitle">
            Decisions are recorded append-only with your name and the time. Nothing here reaches the assistant or the
            ledger until someone decides.
          </p>
          {error && (
            <p className="review__error" role="alert">
              {error}
            </p>
          )}

          <section className="review__section">
            <h2 className="review__section-title">Extracted fields to review ({items?.length ?? '…'})</h2>
            <p className="review__hint">
              Held back because the quote couldn't be grounded, a validator failed, or the page was hard to read.
            </p>
            {items === null ? (
              <p className="review__empty">Loading…</p>
            ) : items.length === 0 ? (
              <p className="review__empty">No fields are waiting. Every extracted field is either accepted or decided.</p>
            ) : (
              <>
                <div className="review__list">
                  {fields.items.map((item) => {
                    const target = fieldTarget(item);
                    return (
                      <FieldReviewCard
                        key={target.key}
                        item={item}
                        selected={selected?.key === target.key}
                        onSelect={() => setSelectedKey(target.key)}
                        onDone={load}
                      />
                    );
                  })}
                </div>
                <Pager page={fields.page} pageCount={fields.pageCount} onChange={setFieldPage} label="Fields pages" />
              </>
            )}
          </section>

          <section className="review__section" id="approvals">
            <h2 className="review__section-title">Fee corrections to approve ({approvals?.length ?? '…'})</h2>
            <p className="review__hint">
              Proposed by the assistant when a contract and billing disagree. Approving posts exactly the entries shown.
            </p>
            {approvals === null ? (
              <p className="review__empty">Loading…</p>
            ) : approvals.length === 0 ? (
              <p className="review__empty">No corrections are waiting. Ask the assistant to compare a contract with billing.</p>
            ) : (
              <>
                <div className="review__list">
                  {corrections.items.map((invocation) => {
                    const target = approvalTarget(invocation, documents);
                    return (
                      <div
                        key={invocation.id}
                        className={`review__approval${target && selected?.key === target.key ? ' review__approval--selected' : ''}`}
                      >
                        {target && (
                          <button
                            type="button"
                            className="field-card__show review__approval-show"
                            aria-pressed={selected?.key === target.key}
                            onClick={() => setSelectedKey(target.key)}
                          >
                            {selected?.key === target.key ? 'Showing contract' : 'Show contract'}
                          </button>
                        )}
                        <ApprovalCard invocation={invocation} />
                      </div>
                    );
                  })}
                </div>
                <Pager
                  page={corrections.page}
                  pageCount={corrections.pageCount}
                  onChange={setApprovalPage}
                  label="Corrections pages"
                />
              </>
            )}
          </section>
        </div>

        <aside className="review__viewer-pane" aria-label="Document viewer">
          {selected ? (
            <Suspense fallback={<p className="review__empty review__viewer-empty">Loading viewer…</p>}>
              <DocumentViewer
                documentId={selected.documentId}
                version={selected.version}
                page={selected.page}
                title={selected.title}
              />
            </Suspense>
          ) : (
            <p className="review__empty review__viewer-empty">Nothing to show — the review queue is empty.</p>
          )}
        </aside>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Replace `frontend/src/screens/Review.css`**

```css
.review {
  display: flex;
  flex-direction: column;
  height: 100dvh;
}

.review__topbar {
  padding: 12px var(--space-3);
  border-bottom: 1px solid var(--color-border);
  font-size: 13px;
  color: var(--color-text-secondary);
}

.review__panes {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(380px, 5fr) minmax(0, 7fr);
}

.review__list-pane {
  overflow-y: auto;
  padding: var(--space-3);
  border-right: 1px solid var(--color-border);
}

.review__viewer-pane {
  min-height: 0;
  min-width: 0;
}

.review__viewer-empty {
  padding: var(--space-3);
}

.review__title {
  font-size: 24px;
  font-weight: 600;
}

.review__subtitle,
.review__hint {
  color: var(--color-text-secondary);
  font-size: 14px;
  margin-top: 4px;
  max-width: 72ch;
}

.review__error,
.field-card__error {
  color: var(--color-error);
  font-size: 13px;
}

.review__section {
  margin-top: var(--space-4);
}

.review__section-title {
  font-size: 16px;
  font-weight: 600;
}

.review__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.review__empty {
  margin-top: var(--space-2);
  font-size: 14px;
  color: var(--color-text-secondary);
}

.field-card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  padding: var(--space-2);
  background: var(--color-surface);
}

.field-card--selected,
.review__approval--selected .tool-card {
  border-color: var(--color-accent);
  box-shadow: 0 0 0 1px var(--color-accent);
}

.field-card__head {
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 13px;
}

.field-card__path {
  font-weight: 600;
  font-size: 14px;
}

.field-card__doc {
  color: var(--color-text-secondary);
  flex: 1;
}

.field-card__show {
  border: none;
  background: none;
  padding: 0;
  font-size: 13px;
  font-weight: 500;
  color: var(--color-accent);
}

.field-card__show[aria-pressed='true'] {
  color: var(--color-text-secondary);
}

.field-card__facts {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 6px var(--space-2);
  margin: 12px 0;
  font-size: 13px;
}

.field-card__facts dt {
  color: var(--color-text-secondary);
}

.field-card__facts dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.field-card__quote {
  font-style: italic;
}

.field-card__reasons {
  margin: 0 0 12px;
  padding-left: 18px;
  font-size: 12px;
  color: var(--color-warning);
}

.field-card__correct {
  display: grid;
  gap: var(--space-1);
  margin-bottom: 12px;
  font-size: 12px;
  color: var(--color-text-secondary);
}

.field-card__correct input {
  display: block;
  width: 100%;
  margin-top: 4px;
  padding: 8px 10px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  font-size: 13px;
  color: var(--color-text-primary);
}

.field-card__actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  flex-wrap: wrap;
}

.review__approval {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.review__approval-show {
  align-self: flex-end;
}

.pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-1);
  margin-top: var(--space-2);
}

.pager__btn {
  padding: 6px 12px;
  font-size: 13px;
}

.pager__status {
  font-size: 12px;
  color: var(--color-text-secondary);
}

@media (max-width: 1080px) {
  .review {
    height: auto;
  }

  .review__panes {
    grid-template-columns: 1fr;
  }

  .review__list-pane {
    overflow: visible;
    border-right: none;
  }

  .review__viewer-pane {
    height: 70dvh;
    border-top: 1px solid var(--color-border);
  }
}
```

Check: `grep -n "review__body" frontend/src/screens/Review.*` prints nothing (that's the old single-column wrapper that caused the empty right side).

- [ ] **Step 6: Verify and commit**

`npm test && npm run lint && npm run build`. In the browser at 1440×900: `/review` has a list on the left and the viewer on the right, filling the width; the first item's document opens by default on the item's page. "Show page N" moves the viewer to that page, and the card gets an accent outline. With more than 5 items, the pager shows and works. After confirming the last item on the last page, the list lands on a valid page. Clicking quickly through five items never shows the wrong document. At 390px the viewer sits below the list. Take screenshots at both widths.

```bash
graphify update .
git add frontend/src/lib/paginate.ts frontend/src/lib/paginate.test.ts frontend/src/lib/review.ts frontend/src/lib/review.test.ts frontend/src/components/Pager.tsx frontend/src/screens/Review.tsx frontend/src/screens/Review.css
git commit -m "feat(frontend): two-pane review with pagination and the in-app document viewer"
```

---

### Task 8: Verification and records

- [ ] **Step 1: Everything green**

```bash
cd backend && $PYDEV/bin/pytest
cd ../frontend && npm test && npm run lint && npm run build
```

Lint: 0 warnings. Record both test counts.

- [ ] **Step 2: Walk-through with screenshots** (1440×900 and 390×844 for each): `/`, `/dashboard`, `/documents` with the viewer open, `/review`. Also confirm in Network that pdf.js is not requested on `/`, `/dashboard` or `/ledger`.

- [ ] **Step 3: CHANGELOG** — under `## [Sprint — feat/demo-ready]` → `### Scope`, add:

```markdown
- [x] `frontend` — ledger logo in the app chrome; dashboard tiles and corpus telemetry on real stats; in-app pdf.js viewer on Documents and a two-pane, paginated Review → **Not epic-tracked** (UI review round 2, 2026-09-26)
- [x] `api` — cached `/stats` (TTL + invalidation + ETag) and `/config`; immutable caching for original PDFs → **Not epic-tracked** (UI review round 2, 2026-09-26)
```

- [ ] **Step 4: Commit**

```bash
graphify update .
git add CHANGELOG.md
git commit -m "docs(changelog): record the round-2 UI work"
```

- [ ] **Step 5: Report** — one line per task (hash + message); test counts; the main JS chunk size before and after Task 5, plus the viewer chunk size; screenshot paths; every deviation with its reason. Do not push.
