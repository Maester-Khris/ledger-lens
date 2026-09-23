import uuid

from sqlalchemy import select
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
