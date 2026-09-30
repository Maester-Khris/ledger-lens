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
