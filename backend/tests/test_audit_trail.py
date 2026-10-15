from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.assistant.models import ChatTurn
from app.governance.models import ToolInvocation
from app.retrieval.vector_index import InMemoryVectorIndex
from tests.fakes import RecordingEmbeddings, ScriptedChatModel
from tests.test_api_chat import _override, _runtime


def _chat(client, session_factory, session_id):
    model = ScriptedChatModel(replies=[
        AIMessage(content="", tool_calls=[{"name": "search_contracts", "args": {"query": "x"}, "id": "c1"}]),
        AIMessage(content="done"),
    ])
    _override(client, _runtime(model, RecordingEmbeddings(), InMemoryVectorIndex()), session_factory)
    client.post("/chat", json={"session_id": session_id, "message": "hi"})


def test_turn_id_matches_the_invocations_turn_id(client, session_factory, db_session):
    _chat(client, session_factory, "a-1")
    turn = db_session.scalars(select(ChatTurn).where(ChatTurn.session_id == "a-1")).one()
    invocation = db_session.scalars(select(ToolInvocation).where(ToolInvocation.session_id == "a-1")).one()
    assert invocation.input["turn_id"] == str(turn.id)


def test_session_filter_returns_only_that_session(client, session_factory):
    _chat(client, session_factory, "a-2")
    _chat(client, session_factory, "a-3")
    rows = client.get("/tool-invocations", params={"session_id": "a-2"}).json()
    assert rows and {r["session_id"] for r in rows} == {"a-2"}
    assert "trace_id" in rows[0]
