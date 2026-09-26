import uuid

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.assistant.models import ChatTurn


def save_turn(session: Session, turn: ChatTurn) -> None:
    session.add(turn)
    session.commit()


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
