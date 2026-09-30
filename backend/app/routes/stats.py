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
