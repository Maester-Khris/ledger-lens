import json

from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.assistant.graph import Answer, FAILED_VERIFICATION_MESSAGE, NO_EVIDENCE_MESSAGE
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


def test_refusal_is_its_own_event_with_fixed_text_and_a_system_reason(client, session_factory, tenant_id):
    model = ScriptedChatModel(replies=[
        AIMessage(content="", tool_calls=[{"name": "search_contracts", "args": {"query": "donations"}, "id": "c1"}]),
        AIMessage(content="done"),
        Answer(text="Nothing about donations here, sorry!", citations=[], refused=True),
    ])
    _override(client, _runtime(model, RecordingEmbeddings(), InMemoryVectorIndex()), session_factory)
    kind, data = _events(client.post("/chat", json={"session_id": "s-2", "message": "Donations?"}))[-1]
    assert kind == "refused" and data["text"] == NO_EVIDENCE_MESSAGE
    assert data["citations"] == [{"id": "system", "kind": "system", "source": "indexed contracts",
                                  "detail": "No passage in the indexed contracts supports an answer to this question."}]


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
        
        # the handler saw the tokenised question, so the loop below isn't checking an empty capture
        assert any(t_email in inp and t_loc in inp for inp in handler.captured)
        for inp in handler.captured:
            assert "bob@example.com" not in inp
            assert "123 Main Street" not in inp


def test_a_model_refusal_is_shown_as_the_fixed_text_with_a_system_reason(client, session_factory, db_session, tenant_id):
    embeddings, index = RecordingEmbeddings(), InMemoryVectorIndex()
    version = parsed_version(db_session, tenant_id, texts=("Fees are billed quarterly in arrears.",))
    index_version(db_session, version.id, embeddings=embeddings, vector_index=index)
    model = ScriptedChatModel(replies=[
        AIMessage(content="", tool_calls=[{"name": "search_contracts", "args": {"query": "quarterly"}, "id": "c1"}]),
        AIMessage(content="done"),
        Answer(text="I'd rather not say.", citations=[], refused=True),
    ])
    _override(client, _runtime(model, embeddings, index), session_factory)
    kind, data = _events(client.post("/chat", json={"session_id": "s-r", "message": "Is there a fee waiver?"}))[-1]
    assert kind == "refused" and data["text"] == NO_EVIDENCE_MESSAGE and data["citations"][0]["kind"] == "system"
    turn = db_session.scalars(select(ChatTurn).where(ChatTurn.session_id == "s-r")).one()
    assert turn.answer_redacted == NO_EVIDENCE_MESSAGE  # the model's own wording is never stored as the answer


def test_a_clarifying_question_streams_clarify_and_is_stored_as_clarified(client, session_factory, db_session, tenant_id):
    model = ScriptedChatModel(replies=[
        AIMessage(content="no tool needed"),
        Answer(text="Which contract do you mean: Tremblay or Calamos?", citations=[], refused=False, clarification=True),
    ])
    _override(client, _runtime(model, RecordingEmbeddings(), InMemoryVectorIndex()), session_factory)
    kind, data = _events(client.post("/chat", json={"session_id": "s-c", "message": "Is it allowed?"}))[-1]
    assert kind == "clarify" and data["citations"] == []
    assert data["text"].startswith("I need a little more to go on.")
    assert "Which contract do you mean: Tremblay or Calamos?" not in data["text"]  # the wording is the service's
    turn = db_session.scalars(select(ChatTurn).where(ChatTurn.session_id == "s-c")).one()
    assert turn.outcome is ChatOutcome.clarified and turn.answer_redacted == data["text"]


def test_the_models_clarification_text_is_never_shown(client, session_factory, tenant_id):
    model = ScriptedChatModel(replies=[
        AIMessage(content="no tool needed"),
        Answer(text="Do you mean the 30-day notice?", citations=[], refused=False, clarification=True),
    ])
    _override(client, _runtime(model, RecordingEmbeddings(), InMemoryVectorIndex()), session_factory)
    kind, data = _events(client.post("/chat", json={"session_id": "s-f", "message": "Is it allowed?"}))[-1]
    assert kind == "clarify" and "30" not in data["text"]


def test_a_scoped_clarification_names_only_that_contract(client, session_factory, db_session, tenant_id):
    from app.assistant.service import CLARIFY_SCOPED
    version = parsed_version(db_session, tenant_id, key="scoped-a")
    parsed_version(db_session, tenant_id, key="scoped-b")  # a second contract that must not be named
    model = ScriptedChatModel(replies=[
        AIMessage(content="no tool needed"),
        Answer(text="", citations=[], refused=False, clarification=True),
    ])
    _override(client, _runtime(model, RecordingEmbeddings(), InMemoryVectorIndex()), session_factory)
    body = {"session_id": "s-sc", "message": "Is it allowed?", "document_id": str(version.document_id)}
    kind, data = _events(client.post("/chat", json=body))[-1]
    assert kind == "clarify" and data["text"] == CLARIFY_SCOPED.format(title="Tremblay IMA")


SYSTEM_REASON = {"id": "system", "kind": "system", "source": "indexed contracts",
                 "detail": "No passage in the indexed contracts supports an answer to this question."}


def test_step_limit_and_timeout_refusals_carry_the_system_reason(client, session_factory, db_session, tenant_id, monkeypatch):
    model = ScriptedChatModel(replies=[AIMessage(content="no tool needed")])
    _override(client, _runtime(model, RecordingEmbeddings(), InMemoryVectorIndex()), session_factory)
    monkeypatch.setattr("app.assistant.service.RECURSION_LIMIT", 1)
    kind, data = _events(client.post("/chat", json={"session_id": "s-limit", "message": "Anything?"}))[-1]
    assert kind == "refused" and "step limit" in data["text"] and data["citations"] == [SYSTEM_REASON]
    assert db_session.scalars(select(ChatTurn).where(ChatTurn.session_id == "s-limit")).one().citations == [SYSTEM_REASON]
    monkeypatch.setattr(config, "CHAT_TURN_TIMEOUT_SECONDS", 0)
    kind, data = _events(client.post("/chat", json={"session_id": "s-slow", "message": "Anything?"}))[-1]
    assert kind == "refused" and "too long" in data["text"] and data["citations"] == [SYSTEM_REASON]
    turn = db_session.scalars(select(ChatTurn).where(ChatTurn.session_id == "s-slow")).one()
    assert turn.outcome is ChatOutcome.timed_out and turn.citations == [SYSTEM_REASON]


def test_a_blank_message_is_rejected(client):
    assert client.post("/chat", json={"session_id": "s-b", "message": "   "}).status_code == 422


def test_search_is_scored_against_the_guests_question_not_only_the_models_query(client, session_factory, db_session, tenant_id, monkeypatch):
    """The model often searches with a terse rewrite ("fees") that falls under the relevance floor (P5+P8 finding)."""
    embeddings, index = RecordingEmbeddings(), InMemoryVectorIndex()
    version = parsed_version(db_session, tenant_id, texts=("Fees are calculated on average daily net assets.",))
    index_version(db_session, version.id, embeddings=embeddings, vector_index=index)
    score = lambda q: index.query(str(tenant_id), embeddings.embed_query(q), 1, None)[0].score
    (low, terse), (high, full) = sorted((score(q), q) for q in ("fees", "What are the fees calculated on?"))
    element_id = str(search(db_session, tenant_id=tenant_id, query=full, embeddings=embeddings, vector_index=index)[0].element_id)
    monkeypatch.setattr(config, "MIN_DENSE_SIMILARITY", (low + high) / 2)
    model = ScriptedChatModel(replies=[
        AIMessage(content="", tool_calls=[{"name": "search_contracts", "args": {"query": terse}, "id": "c1"}]),
        AIMessage(content="done"),
        Answer(text="Fees are calculated on average daily net assets.", citations=[element_id], refused=False),
    ])
    _override(client, _runtime(model, embeddings, index), session_factory)
    kind, data = _events(client.post("/chat", json={"session_id": "s-terse", "message": full}))[-1]
    assert kind == "answer" and data["citations"][0]["id"] == element_id
