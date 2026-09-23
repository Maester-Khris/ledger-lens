"""Sequences ingestion stages across packages. It is the "main" wiring: documents, retrieval and
contracts never import each other; only this module knows the order."""
import logging
import uuid
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.documents import dao as documents_dao
from app.documents.types import VersionStage

logger = logging.getLogger(__name__)
MAX_STAGE_ATTEMPTS = 3
MAX_ERROR_MESSAGE_CHARS = 500
StageRunner = Callable[[Session, uuid.UUID], None]


@dataclass(frozen=True)
class StageSpec:
    name: str
    requires: VersionStage
    produces: VersionStage


PARSE_REDACT = StageSpec("parse_redact", VersionStage.stored, VersionStage.parsed)
INDEX = StageSpec("index", VersionStage.parsed, VersionStage.indexed)
PIPELINE: tuple[StageSpec, ...] = (PARSE_REDACT, INDEX)


class EventLike(Protocol):
    stage: VersionStage
    detail: dict


@dataclass(frozen=True)
class VersionStatus:
    state: Literal["processing", "ready", "failed"]
    note: str | None


def _failures(events: Sequence[EventLike]) -> Counter:
    return Counter(e.detail.get("stage") for e in events if e.stage is VersionStage.failed)


def next_stage(pipeline: Sequence[StageSpec], events: Sequence[EventLike]) -> StageSpec | None:
    reached = {e.stage for e in events}
    failures = _failures(events)
    for spec in pipeline:
        if spec.produces not in reached and spec.requires in reached and failures[spec.name] < MAX_STAGE_ATTEMPTS:
            return spec
    return None


def version_status(pipeline: Sequence[StageSpec], events: Sequence[EventLike]) -> VersionStatus:
    reached = {e.stage for e in events}
    failures = _failures(events)
    exhausted = [s for s in pipeline if s.produces not in reached and failures[s.name] >= MAX_STAGE_ATTEMPTS]
    if exhausted:
        last = next(e for e in reversed(events) if e.stage is VersionStage.failed and e.detail.get("stage") == exhausted[0].name)
        return VersionStatus("failed", f"{exhausted[0].name} failed: {last.detail.get('error_type')} {last.detail.get('message', '')}".strip())
    pending = [s for s in pipeline if s.produces not in reached]
    if pending:
        return VersionStatus("processing", f"waiting for {pending[0].name}")
    return VersionStatus("ready", None)


def _run_next(session_factory: sessionmaker, runners: Mapping[str, StageRunner], pipeline: Sequence[StageSpec], version_id: uuid.UUID) -> bool:
    lock = text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))")
    unlock = text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))")
    with session_factory.kw["bind"].connect() as lock_connection:  # the lease; separate from the work session
        if not lock_connection.execute(lock, {"key": str(version_id)}).scalar():
            return False  # another worker holds this version
        try:
            with session_factory() as session:
                spec = next_stage(pipeline, documents_dao.version_events(session, version_id))
                if spec is None or spec.name not in runners:
                    return False
                try:
                    runners[spec.name](session, version_id)
                except Exception as exc:  # every stage failure is recorded, whatever its type; nothing is lost silently
                    session.rollback()
                    logger.exception("stage %s failed for version %s", spec.name, version_id)
                    documents_dao.append_event(session, version_id, VersionStage.failed, {
                        "stage": spec.name, "error_type": type(exc).__name__, "message": str(exc)[:MAX_ERROR_MESSAGE_CHARS],
                    })
                    session.commit()
                return True
        finally:
            lock_connection.execute(unlock, {"key": str(version_id)})


def run_pending(session_factory: sessionmaker, runners: Mapping[str, StageRunner], pipeline: Sequence[StageSpec] = PIPELINE) -> int:
    """One pass over all versions, one stage each. Returns how many stages ran."""
    with session_factory() as session:
        version_ids = documents_dao.all_version_ids(session)
    return sum(_run_next(session_factory, runners, pipeline, version_id) for version_id in version_ids)
