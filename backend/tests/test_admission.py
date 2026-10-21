"""X3: admission control for chat turns. DB-free: the turn itself is faked, so these run on any FastAPI version
(the shared env and the load image differ). Every test ends with no slot held: a leaked slot is the failure that
matters, since a process that leaks them ends up refusing every turn."""
import asyncio
import contextlib
import json
import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from app import config, deps
from app.assistant import admission
from app.assistant import dao as assistant_dao
from app.assistant.service import TurnEvent
from app.documents import dao as documents_dao
from app.rate_limit import SlidingWindowLimiter

BODY = {"session_id": "s-x3", "message": "How often are fees billed?"}
BUSY_DETAIL = "The assistant is busy right now; try again in {n} seconds."


async def _answers(**_: object) -> AsyncIterator[TurnEvent]:
    yield TurnEvent("answer", {"text": "Quarterly.", "citations": [], "turn_id": "t-1"})


async def _raises_after_one_event(**_: object) -> AsyncIterator[TurnEvent]:
    yield TurnEvent("progress", {"step": "search"})
    raise RuntimeError("model failed mid-turn")


async def _blocks_after_one_event(**_: object) -> AsyncIterator[TurnEvent]:
    yield TurnEvent("progress", {"step": "search"})
    await asyncio.Event().wait()  # a turn still running when the client goes away
    yield TurnEvent("answer", {"text": "never", "citations": [], "turn_id": "t-2"})


@pytest.fixture
def app(monkeypatch):
    from app.main import app
    from app.routes import chat
    monkeypatch.setitem(app.dependency_overrides, chat.get_assistant_runtime, lambda: None)
    monkeypatch.setattr(chat, "run_turn", _answers)
    monkeypatch.setattr(config, "CHAT_MAX_IN_FLIGHT", 1)
    yield app
    assert admission.in_flight() == 0, "a slot leaked"


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def held_slot():
    """The one slot of a limit-1 process, already taken by another turn."""
    slot = admission.admit(1)
    yield slot
    slot.release()


@pytest.fixture
def known_guest(monkeypatch):
    guest = uuid.uuid4()
    touched: list[uuid.UUID] = []

    def touch(session, tenant_id, guest_id):
        touched.append(guest_id)
        return guest_id

    monkeypatch.setattr(assistant_dao, "touch_guest", touch)
    monkeypatch.setattr(config, "DEMO_MODE", True)
    return guest, touched


def _final_event(text: str) -> str:
    return [line[7:] for line in text.splitlines() if line.startswith("event: ")][-1]


# --- the counter -------------------------------------------------------------------------------------------------

def test_admit_counts_up_to_the_limit_then_refuses():
    first, second = admission.admit(2), admission.admit(2)
    assert admission.in_flight() == 2
    with pytest.raises(admission.Busy):
        admission.admit(2)
    first.release()
    third = admission.admit(2)
    second.release()
    third.release()
    assert admission.in_flight() == 0


def test_release_twice_frees_one_slot():
    other = admission.admit(0)
    slot = admission.admit(0)
    slot.release()
    slot.release()
    assert admission.in_flight() == 1
    other.release()
    assert admission.in_flight() == 0


def test_limit_zero_admits_everything():
    slots = [admission.admit(0) for _ in range(100)]
    assert admission.in_flight() == 100
    for slot in slots:
        slot.release()
    assert admission.in_flight() == 0


def test_retry_after_adds_up_to_two_seconds_of_jitter():
    assert admission.retry_after_seconds(3, rng=lambda: 0.0) == 3
    assert admission.retry_after_seconds(3, rng=lambda: 0.999) == 5


# --- the route ---------------------------------------------------------------------------------------------------

def test_a_busy_turn_is_a_fast_503_with_retry_after(client, held_slot):
    response = client.post("/chat", json=BODY)
    assert response.status_code == 503
    problem = response.json()
    assert problem["type"] == "/problems/busy" and problem["title"] == "Assistant busy"
    assert 3 <= problem["retry_after"] <= 5
    assert response.headers["Retry-After"] == str(problem["retry_after"])
    assert problem["detail"] == BUSY_DETAIL.format(n=problem["retry_after"])
    assert admission.in_flight() == 1  # only the held slot


def test_busy_touches_no_guest_and_records_no_rate_limit_hit(app, client, held_slot, known_guest, monkeypatch):
    guest, touched = known_guest
    monkeypatch.setattr(deps, "chat_limits", (SlidingWindowLimiter(1, 600), SlidingWindowLimiter(100, 600)))
    headers = {"X-Guest-Id": str(guest)}
    assert client.post("/chat", json=BODY, headers=headers).status_code == 503
    assert touched == []
    held_slot.release()
    response = client.post("/chat", json=BODY, headers=headers)
    assert response.status_code == 200  # the refusal used none of the guest's one-turn allowance
    assert _final_event(response.text) == "answer"


def test_a_finished_stream_frees_the_slot(client):
    response = client.post("/chat", json=BODY)
    assert response.status_code == 200 and _final_event(response.text) == "answer"
    assert json.loads(response.text.split("data: ", 1)[1].split("\n", 1)[0])["text"] == "Quarterly."
    assert admission.in_flight() == 0


def test_a_turn_that_raises_mid_stream_frees_the_slot(client, monkeypatch):
    from app.routes import chat
    monkeypatch.setattr(chat, "run_turn", _raises_after_one_event)
    with contextlib.suppress(Exception):
        client.post("/chat", json=BODY)
    assert admission.in_flight() == 0


def test_a_rate_limited_turn_frees_its_slot(client, known_guest, monkeypatch):
    guest, _ = known_guest
    by_guest = SlidingWindowLimiter(1, 600)
    by_guest.hit(f"guest:{guest}")
    monkeypatch.setattr(deps, "chat_limits", (by_guest, SlidingWindowLimiter(100, 600)))
    assert client.post("/chat", json=BODY, headers={"X-Guest-Id": str(guest)}).status_code == 429
    assert admission.in_flight() == 0


def test_an_unknown_document_frees_its_slot(client, monkeypatch):
    monkeypatch.setattr(documents_dao, "find_document", lambda session, tenant_id, document_id: None)
    response = client.post("/chat", json={**BODY, "document_id": str(uuid.uuid4())})
    assert response.status_code == 404
    assert admission.in_flight() == 0


# --- the client goes away (raw ASGI: TestClient cannot hang up mid-stream) ------------------------------------------

def _scope() -> dict:
    return {
        "type": "http", "http_version": "1.1", "method": "POST", "path": "/chat", "raw_path": b"/chat",
        "root_path": "", "scheme": "http", "query_string": b"", "client": ("127.0.0.1", 50000),
        "server": ("test", 80), "headers": [(b"host", b"test"), (b"content-type", b"application/json")],
    }


async def _call(app, receive, send) -> None:
    with contextlib.suppress(Exception):
        await asyncio.wait_for(app(_scope(), receive, send), timeout=2)


def test_a_client_disconnect_mid_stream_frees_the_slot(app, monkeypatch):
    from app.routes import chat
    monkeypatch.setattr(chat, "run_turn", _blocks_after_one_event)

    async def scenario() -> None:
        first_chunk_sent = asyncio.Event()
        requests = iter([{"type": "http.request", "body": json.dumps(BODY).encode(), "more_body": False}])

        async def receive() -> dict:
            with contextlib.suppress(StopIteration):
                return next(requests)
            await first_chunk_sent.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict) -> None:
            if message["type"] == "http.response.body" and message.get("body"):
                first_chunk_sent.set()

        await _call(app, receive, send)

    asyncio.run(scenario())
    assert admission.in_flight() == 0


def _failing_send_scenario(app, fail_on: str) -> None:
    async def scenario() -> None:
        requests = iter([{"type": "http.request", "body": json.dumps(BODY).encode(), "more_body": False}])

        async def receive() -> dict:
            with contextlib.suppress(StopIteration):
                return next(requests)
            await asyncio.Event().wait()  # the ASGI 2.4 path: no disconnect message, only a failing send
            return {"type": "http.disconnect"}

        async def send(message: dict) -> None:
            if message["type"] == fail_on and (fail_on == "http.response.start" or message.get("body")):
                raise OSError("client gone")

        await _call(app, receive, send)

    asyncio.run(scenario())


def test_a_send_that_fails_mid_stream_frees_the_slot(app, monkeypatch):
    from app.routes import chat
    monkeypatch.setattr(chat, "run_turn", _blocks_after_one_event)
    _failing_send_scenario(app, "http.response.body")
    assert admission.in_flight() == 0


def test_a_send_that_fails_before_the_first_chunk_frees_the_slot(app):
    _failing_send_scenario(app, "http.response.start")
    assert admission.in_flight() == 0
