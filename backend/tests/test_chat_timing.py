import uuid

from sqlalchemy import select

from app.assistant.models import ChatTurnTiming
from app.assistant.models import ChatOutcome, ChatTurn

def _guest(client) -> dict[str, str]:  # copied from test_chat_feedback.py
    return {"X-Guest-Id": client.post("/guests").json()["id"]}


def _turn(db_session, tenant_id, headers: dict[str, str]) -> uuid.UUID:
    turn = ChatTurn(tenant_id=tenant_id, session_id=f"s-{uuid.uuid4().hex[:8]}", question_redacted="q", answer_redacted="a",
                    citations=[], retrieved=[], outcome=ChatOutcome.answered, model_id="m", prompt_version="p",
                    graph_version="v2", guest_id=uuid.UUID(headers["X-Guest-Id"]), input_tokens=0, output_tokens=0, latency_ms=1)
    db_session.add(turn)
    db_session.commit()
    return turn.id


def _timings(db_session, turn_id: uuid.UUID) -> list[ChatTurnTiming]:
    return list(db_session.scalars(select(ChatTurnTiming).where(ChatTurnTiming.turn_id == turn_id)))


def test_first_timing_is_recorded(client, db_session, tenant_id):
    guest = _guest(client)
    turn_id = _turn(db_session, tenant_id, guest)
    r = client.post(f"/chat/turns/{turn_id}/timing", json={"ttfb_ms": 850}, headers=guest)
    assert r.status_code == 200
    assert r.json() == {"recorded": True}
    assert [t.ttfb_ms for t in _timings(db_session, turn_id)] == [850]


def test_second_timing_keeps_the_first(client, db_session, tenant_id):
    guest = _guest(client)
    turn_id = _turn(db_session, tenant_id, guest)
    client.post(f"/chat/turns/{turn_id}/timing", json={"ttfb_ms": 850}, headers=guest)
    r = client.post(f"/chat/turns/{turn_id}/timing", json={"ttfb_ms": 9000}, headers=guest)
    assert r.status_code == 200
    assert r.json() == {"recorded": False}
    assert [t.ttfb_ms for t in _timings(db_session, turn_id)] == [850]


def test_another_guests_turn_is_not_found(client, db_session, tenant_id):
    owner, other = _guest(client), _guest(client)
    turn_id = _turn(db_session, tenant_id, owner)
    r = client.post(f"/chat/turns/{turn_id}/timing", json={"ttfb_ms": 850}, headers=other)
    assert r.status_code == 404
    assert _timings(db_session, turn_id) == []


def test_missing_guest_header_gets_400(client, db_session, tenant_id):
    turn_id = _turn(db_session, tenant_id, _guest(client))
    r = client.post(f"/chat/turns/{turn_id}/timing", json={"ttfb_ms": 850})
    assert r.status_code == 400


def test_out_of_range_values_get_422(client, db_session, tenant_id):
    guest = _guest(client)
    turn_id = _turn(db_session, tenant_id, guest)
    for bad in (-1, 60001, "fast", 1.5):
        r = client.post(f"/chat/turns/{turn_id}/timing", json={"ttfb_ms": bad}, headers=guest)
        assert r.status_code == 422, bad
    assert _timings(db_session, turn_id) == []
