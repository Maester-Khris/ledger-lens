import json

from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.assistant.graph import Answer
from app.assistant.models import ChatOutcome, ChatTurn
from app.assistant.service import AssistantRuntime
from app.assistant.tools import default_tools
from app.retrieval.index import index_version
from app.retrieval.search import search
from app.retrieval.vector_index import InMemoryVectorIndex
from tests.fakes import RecordingEmbeddings, ScriptedChatModel
from tests.test_retrieval_index import parsed_version


def _events(response) -> list[tuple[str, dict]]:
    events = []
    for block in response.text.strip().split("\n\n"):
        if not block: continue
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def _runtime(model, embeddings, index):
    return AssistantRuntime(chat_model=model, embeddings=embeddings, vector_index=index, tools=default_tools())


def _override(client, runtime, session_factory):
    from app.main import app
    from app.routes.chat import get_assistant_runtime, get_session_factory
    app.dependency_overrides[get_assistant_runtime] = lambda: runtime
    app.dependency_overrides[get_session_factory] = lambda: session_factory


def test_stream_has_progress_then_one_verified_answer(client, session_factory, db_session, tenant_id):
    embeddings, index = RecordingEmbeddings(), InMemoryVectorIndex()
    version = parsed_version(db_session, tenant_id, texts=("Fees are billed quarterly in arrears.",))
    index_version(db_session, version.id, embeddings=embeddings, vector_index=index)
    element_id = str(search(db_session, tenant_id=tenant_id, query="quarterly", embeddings=embeddings, vector_index=index)[0].element_id)
    model = ScriptedChatModel(replies=[
        AIMessage(content="", tool_calls=[{"name": "search_contracts", "args": {"query": "quarterly"}, "id": "c1"}]),
        AIMessage(content="done"),
        Answer(text="Fees are billed quarterly in arrears.", citations=[element_id], refused=False),
    ])
    _override(client, _runtime(model, embeddings, index), session_factory)
    response = client.post("/chat", json={"session_id": "s-1", "message": "How often are fees billed?"})
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response)
    kinds = [kind for kind, _ in events]
    assert kinds[-1] == "answer" and kinds.count("answer") == 1 and "progress" in kinds
    answer = events[-1][1]
    assert answer["citations"][0]["page"] == 1 and answer["citations"][0]["file_url"].endswith("#page=1")
    turn = db_session.scalars(select(ChatTurn).where(ChatTurn.session_id == "s-1")).one()
    assert turn.outcome is ChatOutcome.answered and turn.retrieved[0]["id"] == element_id


def test_refusal_is_its_own_event(client, session_factory, tenant_id):
    model = ScriptedChatModel(replies=[
        AIMessage(content="", tool_calls=[{"name": "search_contracts", "args": {"query": "donations"}, "id": "c1"}]),
        AIMessage(content="done"),
    ])
    _override(client, _runtime(model, RecordingEmbeddings(), InMemoryVectorIndex()), session_factory)
    events = _events(client.post("/chat", json={"session_id": "s-2", "message": "Donations?"}))
    assert events[-1][0] == "refused"


def test_model_failure_is_an_error_event_and_recorded(client, session_factory, db_session, tenant_id):
    model = ScriptedChatModel(replies=[])  # runs out immediately -> AssertionError inside the graph
    _override(client, _runtime(model, RecordingEmbeddings(), InMemoryVectorIndex()), session_factory)
    events = _events(client.post("/chat", json={"session_id": "s-3", "message": "Anything?"}))
    assert events[-1][0] == "error"
    turn = db_session.scalars(select(ChatTurn).where(ChatTurn.session_id == "s-3")).one()
    assert turn.outcome is ChatOutcome.error


def test_disconnect_records_cancelled(session_factory, db_session, tenant_id):
    import asyncio
    from app import config
    from app.assistant.service import run_turn

    slow_model = ScriptedChatModel(replies=[
        AIMessage(content="", tool_calls=[{"name": "search_contracts", "args": {"query": "x"}, "id": "c1"}]),
        AIMessage(content="done"),
    ])

    async def consume_one_then_close():
        stream = run_turn(session_factory=session_factory, runtime=_runtime(slow_model, RecordingEmbeddings(), InMemoryVectorIndex()),
                          tenant_id=tenant_id, session_id="s-4", message="x",
                          hmac_key=config.PII_HMAC_KEY, vault_key=config.PII_VAULT_KEY)
        await stream.__anext__()  # first progress event
        await stream.aclose()  # what a client disconnect does to the generator

    asyncio.run(consume_one_then_close())
    turn = db_session.scalars(select(ChatTurn).where(ChatTurn.session_id == "s-4")).one()
    assert turn.outcome is ChatOutcome.cancelled

from langchain_core.callbacks.base import BaseCallbackHandler
from unittest.mock import patch
import pytest
from app import config
from app.documents import dao as documents_dao

def test_tracing_disabled_handler_is_none(client, session_factory, db_session, tenant_id):
    embeddings, index = RecordingEmbeddings(), InMemoryVectorIndex()
    version = parsed_version(db_session, tenant_id, texts=("x",))
    index_version(db_session, version.id, embeddings=embeddings, vector_index=index)
    element_id = str(search(db_session, tenant_id=tenant_id, query="x", embeddings=embeddings, vector_index=index)[0].element_id)

    model = ScriptedChatModel(replies=[
        AIMessage(content="", tool_calls=[{"name": "search_contracts", "args": {"query": "x"}, "id": "c1"}]),
        AIMessage(content="done"),
        Answer(text="Found x", citations=[element_id], refused=False),
    ])
    _override(client, _runtime(model, embeddings, index), session_factory)
    
    # Force get_tracing_handler to return None explicitly for this test
    with patch("app.assistant.service.get_tracing_handler", return_value=None):
        response = client.post("/chat", json={"session_id": "s-trace-off", "message": "hello"})
        assert _events(response)[-1][0] == "answer"
    
        turn = db_session.scalars(select(ChatTurn).where(ChatTurn.session_id == "s-trace-off")).one()
        assert turn.trace_id is None

@pytest.mark.enable_tracing
def test_tracing_enabled_and_no_pii_leakage(client, session_factory, db_session, tenant_id):
    from app.documents.dao import tokenize_known_values
    
    # Let tokenize_known_values run its regexes and return the tokenised string
    msg = "Email bob@example.com about 123 Main Street"
    tokenised_msg = tokenize_known_values(db_session, tenant_id, msg, config.PII_HMAC_KEY, config.PII_VAULT_KEY)
    
    # extract the tokens
    import re
    tokens = re.findall(r"<[A-Z_]+_[a-f0-9]{12}>", tokenised_msg)
    t_email = next(t for t in tokens if "EMAIL" in t)
    t_loc = next(t for t in tokens if "STREET" in t)
    
    embeddings, index = RecordingEmbeddings(), InMemoryVectorIndex()
    version = parsed_version(db_session, tenant_id, texts=("x",))
    index_version(db_session, version.id, embeddings=embeddings, vector_index=index)
    
    element_id = str(search(db_session, tenant_id=tenant_id, query="x", embeddings=embeddings, vector_index=index)[0].element_id)
    
    model = ScriptedChatModel(replies=[
        AIMessage(content="", tool_calls=[{"name": "search_contracts", "args": {"query": "x"}, "id": "c1"}]),
        AIMessage(content="done"),
        Answer(text=f"Found {t_email} at {t_loc}", citations=[element_id], refused=False),
    ])
    
    class CapturingHandler(BaseCallbackHandler):
        def __init__(self):
            super().__init__()
            self.captured = []
            self.last_trace_id = "trace-123"
            
        def on_chain_start(self, serialized, inputs, **kwargs):
            self.captured.append(str(inputs))
            
        def on_chain_end(self, outputs, **kwargs):
            self.captured.append(str(outputs))
            
        def on_chat_model_start(self, serialized, messages, **kwargs):
            self.captured.append(str(messages))
            
        def on_llm_end(self, response, **kwargs):
            self.captured.append(str(response))
            
        def on_tool_start(self, serialized, input_str, **kwargs):
            self.captured.append(str(input_str))
            
        def on_tool_end(self, output, **kwargs):
            self.captured.append(str(output))

    handler = CapturingHandler()
    
    with patch("app.assistant.service.get_tracing_handler", return_value=handler):
        _override(client, _runtime(model, embeddings, index), session_factory)
        
        response = client.post("/chat", json={"session_id": "s-5", "message": msg})
        
        events = _events(response)
        assert events[-1][0] == "answer"
        
        turn = db_session.scalars(select(ChatTurn).where(ChatTurn.session_id == "s-5")).one()
        assert turn.trace_id == "trace-123"
        
        for inp in handler.captured:
            assert "bob@example.com" not in inp
            assert "123 Main Street" not in inp
