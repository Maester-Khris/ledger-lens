import uuid

import psycopg
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from app import config
from app.assistant.models import ChatFeedback, ChatOutcome, ChatTurn, FeedbackRating
from app.ledger.db import make_session_factory


def _guest(client) -> dict[str, str]:
    return {"X-Guest-Id": client.post("/guests").json()["id"]}


def _turn(db_session, tenant_id, headers: dict[str, str]) -> uuid.UUID:
    turn = ChatTurn(tenant_id=tenant_id, session_id=f"s-{uuid.uuid4().hex[:8]}", question_redacted="q", answer_redacted="a",
                    citations=[], retrieved=[], outcome=ChatOutcome.answered, model_id="m", prompt_version="p",
                    graph_version="v2", guest_id=uuid.UUID(headers["X-Guest-Id"]), input_tokens=0, output_tokens=0, latency_ms=1)
    db_session.add(turn)
    db_session.commit()
    return turn.id


def _rows(db_session, turn_id: uuid.UUID) -> list[ChatFeedback]:
    return list(db_session.scalars(select(ChatFeedback).where(ChatFeedback.turn_id == turn_id).order_by(ChatFeedback.created_at)))


def test_a_thumb_is_saved_at_once_and_the_latest_row_wins(client, db_session, tenant_id):
    guest = _guest(client)
    turn_id = _turn(db_session, tenant_id, guest)
    first = client.post(f"/chat/turns/{turn_id}/feedback", headers=guest, json={"rating": "up"})
    assert first.status_code == 201 and uuid.UUID(first.json()["id"])
    assert client.post(f"/chat/turns/{turn_id}/feedback", headers=guest, json={"rating": "down", "comment": "Wrong tier."}).status_code == 201
    rows = _rows(db_session, turn_id)
    assert [(r.rating, r.comment_redacted) for r in rows] == [(FeedbackRating.up, None), (FeedbackRating.down, "Wrong tier.")]
    assert rows[-1].guest_id == uuid.UUID(guest["X-Guest-Id"]) and rows[-1].tenant_id == tenant_id


def test_feedback_needs_a_known_guest(client, db_session, tenant_id):
    turn_id = _turn(db_session, tenant_id, _guest(client))
    assert client.post(f"/chat/turns/{turn_id}/feedback", json={"rating": "up"}).status_code == 400
    assert client.post(f"/chat/turns/{turn_id}/feedback", headers={"X-Guest-Id": str(uuid.uuid4())}, json={"rating": "up"}).status_code == 400


def test_an_unknown_turn_or_another_guests_turn_is_not_found(client, db_session, tenant_id):
    owner, other = _guest(client), _guest(client)
    turn_id = _turn(db_session, tenant_id, owner)
    assert client.post(f"/chat/turns/{uuid.uuid4()}/feedback", headers=owner, json={"rating": "up"}).status_code == 404
    assert client.post(f"/chat/turns/{turn_id}/feedback", headers=other, json={"rating": "up"}).status_code == 404
    assert _rows(db_session, turn_id) == []


def test_the_sixth_row_for_one_turn_is_refused(client, db_session, tenant_id):
    guest = _guest(client)
    turn_id = _turn(db_session, tenant_id, guest)
    codes = [client.post(f"/chat/turns/{turn_id}/feedback", headers=guest, json={"rating": "up"}).status_code for _ in range(6)]
    assert codes == [201] * 5 + [429]
    assert len(_rows(db_session, turn_id)) == 5


def test_a_comment_is_tokenised_and_a_blank_one_is_stored_as_null(client, db_session, tenant_id):
    guest = _guest(client)
    turn_id = _turn(db_session, tenant_id, guest)
    client.post(f"/chat/turns/{turn_id}/feedback", headers=guest, json={"rating": "down", "comment": "Mail me at bob@example.com"})
    client.post(f"/chat/turns/{turn_id}/feedback", headers=guest, json={"rating": "down", "comment": "   "})
    tokenised, blank = _rows(db_session, turn_id)
    assert "bob@example.com" not in tokenised.comment_redacted and "<EMAIL_ADDRESS_" in tokenised.comment_redacted
    assert blank.comment_redacted is None


@pytest.mark.parametrize("body", [
    {"rating": "meh"}, {}, {"rating": "up", "comment": "x" * 1001}, {"rating": "up", "extra": 1},
])
def test_a_bad_body_is_rejected(client, db_session, tenant_id, body):
    guest = _guest(client)
    turn_id = _turn(db_session, tenant_id, guest)
    assert client.post(f"/chat/turns/{turn_id}/feedback", headers=guest, json=body).status_code == 422


def test_the_demo_role_can_insert_feedback_but_not_change_it(client, db_session, tenant_id, migrated_test_database):
    guest = _guest(client)
    turn_id = _turn(db_session, tenant_id, guest)
    demo = make_session_factory(config.TEST_DEMO_DATABASE_URL)()
    try:
        demo.add(ChatFeedback(tenant_id=tenant_id, turn_id=turn_id, guest_id=uuid.UUID(guest["X-Guest-Id"]), rating=FeedbackRating.up))
        demo.commit()
        with pytest.raises(ProgrammingError) as caught:
            demo.execute(text("UPDATE chat_feedback SET rating = 'down' WHERE turn_id = :t"), {"t": turn_id})
        assert isinstance(caught.value.orig, psycopg.errors.InsufficientPrivilege)
    finally:
        demo.rollback()
        demo.close()
