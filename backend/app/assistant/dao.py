import uuid

from dataclasses import dataclass
from datetime import datetime

from collections.abc import Iterable
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.assistant.models import ChatTurn, Guest


def save_turn(session: Session, turn: ChatTurn) -> None:
    session.add(turn)
    session.commit()


def trace_ids(session: Session, tenant_id: uuid.UUID, turn_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str | None]:
    ids = list(turn_ids)
    if not ids:
        return {}
    rows = session.execute(select(ChatTurn.id, ChatTurn.trace_id).where(ChatTurn.tenant_id == tenant_id, ChatTurn.id.in_(ids)))
    return {turn_id: trace_id for turn_id, trace_id in rows}


def recent_turns(session: Session, tenant_id: uuid.UUID, session_id: str, limit: int) -> list[ChatTurn]:
    rows = session.scalars(
        select(ChatTurn).where(ChatTurn.tenant_id == tenant_id, ChatTurn.session_id == session_id)
        .order_by(ChatTurn.created_at.desc()).limit(limit)
    )
    return list(reversed(list(rows)))

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
