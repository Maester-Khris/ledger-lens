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
