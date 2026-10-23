"""N8 S6 (OWASP LLM02): no raw PII value leaves in any request body to the provider, chat completions or embeddings.
The real graph and tools run against the provider mock (scripts/load/mock_openai.py) over ASGITransport; an event hook
records every request body, from indexing through two chat turns in one session (the second carries the history)."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app import config
from app.assistant.contract_tools import contract_tools
from app.assistant.service import AssistantRuntime, run_turn
from app.assistant.tools import default_tools
from app.documents import dao as documents_dao
from app.documents.ingest import parse_and_redact
from app.documents.parse import parse_pdf
from app.documents.redact import PiiDetector
from app.documents.sniff import PdfFacts
from app.retrieval.index import index_version
from app.retrieval.vector_index import InMemoryVectorIndex
from scripts.load import mock_openai

FIXTURE = Path(__file__).parent / "fixtures" / "documents" / "client_agreement.pdf"
RAW_PII = ("Marie Tremblay", "Tremblay", "130 692 544", "marie.tremblay@example.com", "514-555-0142")
QUESTIONS = (
    "What fees does Marie Tremblay pay? Her SIN is 130 692 544.",
    "Email the answer to marie.tremblay@example.com or call 514-555-0142.",
)


def _text(request: httpx.Request) -> str:
    """The body as the provider reads it: JSON-decoded, so an escaped value (\\u00e9) is still found."""
    body = request.content.decode()
    try:
        return json.dumps(json.loads(body), ensure_ascii=False)
    except ValueError:
        return body


@pytest.mark.slow
def test_no_raw_pii_in_any_provider_request(session_factory, db_session, tenant_id, monkeypatch):
    monkeypatch.setenv("MOCK_DELAY_SCALE", "0")
    bodies: list[tuple[str, str]] = []

    def record(request: httpx.Request) -> None:
        bodies.append((request.url.path, _text(request)))

    async def record_async(request: httpx.Request) -> None:
        record(request)

    sync_client = TestClient(mock_openai.app)
    sync_client.event_hooks = {"request": [record]}
    async_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_openai.app), event_hooks={"request": [record_async]})
    provider = {"api_key": "mock", "base_url": "http://testserver/v1", "max_retries": 0,
                "http_client": sync_client, "http_async_client": async_client}
    # Text, not token ids: the production default sends tiktoken ids, which a string scan cannot read.
    embeddings = OpenAIEmbeddings(model=config.EMBEDDING_MODEL, check_embedding_ctx_length=False, **provider)
    model = ChatOpenAI(model="mock", temperature=0, **provider)

    data = FIXTURE.read_bytes()
    version = documents_dao.register_upload(
        db_session, tenant_id=tenant_id, document_key="s6-ima", title="IMA", source_url=None, data=data,
        facts=PdfFacts(2, len(data)), uploaded_by="test", store_root=config.DOCUMENT_STORE_DIR,
    ).version
    parse_and_redact(db_session, version.id, parser=parse_pdf, detector=PiiDetector(), store_root=config.DOCUMENT_STORE_DIR,
                     hmac_key=config.PII_HMAC_KEY, vault_key=config.PII_VAULT_KEY)
    index = InMemoryVectorIndex()
    index_version(db_session, version.id, embeddings=embeddings, vector_index=index)
    runtime = AssistantRuntime(chat_model=model, embeddings=embeddings, vector_index=index,
                               tools=default_tools() + contract_tools())

    async def ask(message: str) -> list:
        return [e async for e in run_turn(session_factory=session_factory, runtime=runtime, tenant_id=tenant_id,
                                          session_id="s6-egress", message=message,
                                          hmac_key=config.PII_HMAC_KEY, vault_key=config.PII_VAULT_KEY)]

    finals = [asyncio.run(ask(q))[-1] for q in QUESTIONS]

    paths = [path for path, _ in bodies]
    assert "/v1/chat/completions" in paths and "/v1/embeddings" in paths, paths  # the scan saw both endpoints
    assert finals[0].type == "answer", finals[0]  # the turn reached the answer call, not an early refusal
    leaks = [(path, value) for path, text in bodies for value in RAW_PII if value.casefold() in text.casefold()]
    assert not leaks, f"raw PII reached the provider: {leaks}"
