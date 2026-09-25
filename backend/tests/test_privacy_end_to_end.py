import asyncio
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from app import config
from app.assistant.graph import Answer
from app.assistant.service import AssistantRuntime, run_turn
from app.assistant.tools import default_tools
from app.documents import dao as documents_dao
from app.documents.ingest import parse_and_redact
from app.documents.parse import parse_pdf
from app.documents.redact import PiiDetector
from app.documents.sniff import PdfFacts
from app.retrieval.index import index_version
from app.retrieval.vector_index import InMemoryVectorIndex
from tests.fakes import RecordingEmbeddings, ScriptedChatModel

FIXTURE = Path(__file__).parent / "fixtures" / "documents" / "client_agreement.pdf"
RAW_PII = ("Marie Tremblay", "Tremblay", "130 692 544", "marie.tremblay@example.com", "514-555-0142")


@pytest.mark.slow
def test_no_raw_pii_reaches_embeddings_or_the_model(session_factory, db_session, tenant_id):
    data = FIXTURE.read_bytes()
    version = documents_dao.register_upload(
        db_session, tenant_id=tenant_id, document_key="tremblay-ima", title="IMA", source_url=None, data=data,
        facts=PdfFacts(2, len(data)), uploaded_by="test", store_root=config.DOCUMENT_STORE_DIR,
    ).version
    parse_and_redact(db_session, version.id, parser=parse_pdf, detector=PiiDetector(), store_root=config.DOCUMENT_STORE_DIR,
                     hmac_key=config.PII_HMAC_KEY, vault_key=config.PII_VAULT_KEY)
    embeddings, index = RecordingEmbeddings(), InMemoryVectorIndex()
    index_version(db_session, version.id, embeddings=embeddings, vector_index=index)

    model = ScriptedChatModel(replies=[
        AIMessage(content="", tool_calls=[{"name": "search_contracts", "args": {"query": "Marie Tremblay fees"}, "id": "c1"}]),
        AIMessage(content="done"),
        Answer(text="I can't find that.", citations=[], refused=True),
    ])
    runtime = AssistantRuntime(chat_model=model, embeddings=embeddings, vector_index=index, tools=default_tools())

    async def ask():
        return [e async for e in run_turn(session_factory=session_factory, runtime=runtime, tenant_id=tenant_id,
                                          session_id="privacy", message="What fees does Marie Tremblay pay?",
                                          hmac_key=config.PII_HMAC_KEY, vault_key=config.PII_VAULT_KEY)]

    asyncio.run(ask())
    seen = "\n".join(embeddings.seen + model.prompts)
    for value in RAW_PII:
        assert value not in seen, f"raw PII {value!r} reached an external model"
