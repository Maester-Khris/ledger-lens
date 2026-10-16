"""The load-test provider mock (scripts/load/mock_openai.py) must drive the real agent graph to a verified, cited answer,
or a load test would only ever exercise the refusal path."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_openai import ChatOpenAI

from app import config
from app.assistant.service import AssistantRuntime, run_turn
from app.assistant.tools import default_tools
from app.documents import dao as documents_dao
from app.documents.ingest import parse_and_redact
from app.documents.parse import parse_pdf
from app.documents.redact import PiiDetector
from app.documents.sniff import PdfFacts
from app.retrieval.index import index_version
from app.retrieval.vector_index import InMemoryVectorIndex, StubVectorIndex
from scripts.load import mock_openai
from tests.fakes import RecordingEmbeddings

FIXTURE = Path(__file__).parent / "fixtures" / "documents" / "client_agreement.pdf"


def test_agent_searches_first_then_stops():
    question = [{"role": "user", "content": "What is the fee?"}]
    first = mock_openai.reply({"messages": question, "tool_choice": "auto"})
    assert first["tool_calls"][0]["function"]["name"] == "search_contracts"
    searched = question + [first, {"role": "tool", "content": json.dumps([{"id": "e1", "text": "Fee 0.5%"}])}]
    assert "tool_calls" not in mock_openai.reply({"messages": searched, "tool_choice": "auto"})


def test_forced_tool_is_called():
    choice = {"type": "function", "function": {"name": "list_documents"}}
    reply = mock_openai.reply({"messages": [{"role": "user", "content": "q"}], "tool_choice": choice})
    assert reply["tool_calls"][0]["function"]["name"] == "list_documents"


def test_answer_quotes_and_cites_the_first_passage_or_refuses():
    hit = [{"role": "user", "content": "q"},
           {"role": "tool", "content": json.dumps({"sections": {"S1": {"document": "d", "section": "s", "text": "Fee 0.5%"}},
                                                   "hits": [{"id": "e1", "section": "S1", "page": 1, "text": "Fee 0.5%"}]})}]
    answer = json.loads(mock_openai.reply({"messages": hit, "response_format": {"type": "json_schema"}})["content"])
    assert answer["citations"] == ["e1"] and "0.5%" in answer["text"] and not answer["refused"]
    empty = json.loads(mock_openai.reply({"messages": hit[:1], "response_format": {"type": "json_schema"}})["content"])
    assert empty["refused"]


def test_stub_index_serves_current_passages_of_the_namespace():
    index = StubVectorIndex([("t", "v#0", "d1"), ("t", "v#1", "d1"), ("t", "w#0", "d2"), ("x", "z#0", "d3")])
    assert {m.id for m in index.query("t", [0.1] * 8, 10, None)} == {"v#0", "v#1", "w#0"}
    assert [m.id for m in index.query("t", [0.1] * 8, 10, ["d2"])] == ["w#0"]
    assert index.query("t", [0.3] * 8, 2, None) == index.query("t", [0.3] * 8, 2, None)


@pytest.mark.slow
def test_real_graph_reaches_a_verified_cited_answer(session_factory, db_session, tenant_id, monkeypatch):
    monkeypatch.setenv("MOCK_DELAY_SCALE", "0")
    data = FIXTURE.read_bytes()
    version = documents_dao.register_upload(
        db_session, tenant_id=tenant_id, document_key="tremblay-ima", title="IMA", source_url=None, data=data,
        facts=PdfFacts(2, len(data)), uploaded_by="test", store_root=config.DOCUMENT_STORE_DIR,
    ).version
    parse_and_redact(db_session, version.id, parser=parse_pdf, detector=PiiDetector(), store_root=config.DOCUMENT_STORE_DIR,
                     hmac_key=config.PII_HMAC_KEY, vault_key=config.PII_VAULT_KEY)
    embeddings, index = RecordingEmbeddings(), InMemoryVectorIndex()
    index_version(db_session, version.id, embeddings=embeddings, vector_index=index)
    model = ChatOpenAI(model="mock", api_key="mock", base_url="http://testserver/v1", max_retries=0,
                       http_client=TestClient(mock_openai.app),  # sync path
                       http_async_client=httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_openai.app)))
    runtime = AssistantRuntime(chat_model=model, embeddings=embeddings, vector_index=index, tools=default_tools())

    async def ask():
        return [e async for e in run_turn(session_factory=session_factory, runtime=runtime, tenant_id=tenant_id,
                                          session_id="mock", message="What does the agreement say about fees?",
                                          hmac_key=config.PII_HMAC_KEY, vault_key=config.PII_VAULT_KEY)]

    final = asyncio.run(ask())[-1]
    assert final.type == "answer", final
    assert final.data["citations"]
