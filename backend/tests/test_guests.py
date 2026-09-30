import uuid

from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.assistant.models import ChatTurn, Guest
from app.contracts.models import ExtractionRun
from app.contracts.types import FieldRouting
from app.deps import DECIDED_BY, decided_by
from app.retrieval.vector_index import InMemoryVectorIndex
from tests.fakes import RecordingEmbeddings, ScriptedChatModel
from tests.test_api_chat import _override, _runtime
from tests.test_contracts_compare import _contract


def _refusing_model() -> ScriptedChatModel:
    return ScriptedChatModel(replies=[
        AIMessage(content="", tool_calls=[{"name": "search_contracts", "args": {"query": "x"}, "id": "c1"}]),
        AIMessage(content="done"),
    ])


def test_post_guests_creates_a_guest(client, db_session, tenant_id):
    response = client.post("/guests")
    assert response.status_code == 201
    guest = db_session.get(Guest, uuid.UUID(response.json()["id"]))
    assert guest is not None and guest.tenant_id == tenant_id


def test_post_guests_keeps_a_known_id(client):
    first = client.post("/guests").json()["id"]
    assert client.post("/guests", headers={"X-Guest-Id": first}).json()["id"] == first


def test_post_guests_replaces_a_stale_id(client):
    # Review Focus 1: the DB was cleared but the browser still holds the old id
    stale = str(uuid.uuid4())
    assert client.post("/guests", headers={"X-Guest-Id": stale}).json()["id"] != stale


def test_chat_records_a_known_guest_and_touches_last_seen(client, session_factory, db_session, tenant_id):
    guest_id = uuid.UUID(client.post("/guests").json()["id"])
    before = db_session.get(Guest, guest_id).last_seen_at
    _override(client, _runtime(_refusing_model(), RecordingEmbeddings(), InMemoryVectorIndex()), session_factory)
    client.post("/chat", json={"session_id": "g-1", "message": "hi"}, headers={"X-Guest-Id": str(guest_id)})
    db_session.expire_all()
    turn = db_session.scalars(select(ChatTurn).where(ChatTurn.session_id == "g-1")).one()
    assert turn.guest_id == guest_id
    assert db_session.get(Guest, guest_id).last_seen_at >= before


def test_unknown_or_malformed_guest_is_null_not_an_error(client, session_factory, db_session):
    _override(client, _runtime(_refusing_model(), RecordingEmbeddings(), InMemoryVectorIndex()), session_factory)
    for session_id, header in (("g-2", str(uuid.uuid4())), ("g-3", "not-a-uuid")):
        response = client.post("/chat", json={"session_id": session_id, "message": "hi"}, headers={"X-Guest-Id": header})
        assert response.status_code == 200
        turn = db_session.scalars(select(ChatTurn).where(ChatTurn.session_id == session_id)).one()
        assert turn.guest_id is None


def test_decided_by_uses_the_guest_prefix():
    guest_id = uuid.UUID("1234abcd-0000-0000-0000-000000000000")
    assert decided_by(guest_id) == "guest:1234abcd"
    assert decided_by(None) == DECIDED_BY


def test_review_decision_records_the_guest(client, db_session, tenant_id):
    document_id = _contract(db_session, tenant_id, None, tier_routing=FieldRouting.needs_review, key="guest-review")
    run_id = db_session.scalars(select(ExtractionRun.id).order_by(ExtractionRun.created_at.desc())).first()  # the run _contract just made
    guest_id = client.post("/guests").json()["id"]
    response = client.post("/reviews", json={"run_id": str(run_id), "field_path": "fee_tiers[0]", "decision": "confirmed"},
                           headers={"X-Guest-Id": guest_id})
    assert response.status_code == 201
    assert response.json()["decided_by"] == f"guest:{guest_id[:8]}"
