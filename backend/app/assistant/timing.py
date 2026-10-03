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
