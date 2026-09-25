import uuid
from pathlib import Path

from sqlalchemy import select

from app import config
from app.documents import dao as documents_dao
from app.documents.models import DocumentElement
from app.documents.sniff import PdfFacts
from app.documents.types import ElementKind, VersionStage
from app.retrieval.index import index_version
from app.retrieval.models import ElementSearch
from app.retrieval.vector_index import InMemoryVectorIndex, vector_id
from tests.fakes import RecordingEmbeddings

FIXTURE = Path(__file__).parent / "fixtures" / "documents" / "client_agreement.pdf"


def parsed_version(db_session, tenant_id, *, key="tremblay-ima", data=None, texts=("Fees are billed quarterly in arrears.",)):
    """Register a version and give it parsed elements without Docling (a heading plus the given paragraphs)."""
    data = data if data is not None else FIXTURE.read_bytes()
    version = documents_dao.register_upload(
        db_session, tenant_id=tenant_id, document_key=key, title="Tremblay IMA", source_url=None,
        data=data, facts=PdfFacts(2, len(data)), uploaded_by="test", store_root=config.DOCUMENT_STORE_DIR,
    ).version
    db_session.add(DocumentElement(version_id=version.id, ordinal=0, kind=ElementKind.heading, section_path=["3. Fees"],
                                   page_start=1, page_end=1, text_redacted="3. Fees", parser_version="t"))
    for ordinal, text in enumerate(texts, start=1):
        db_session.add(DocumentElement(version_id=version.id, ordinal=ordinal, kind=ElementKind.paragraph,
                                       section_path=["3. Fees"], page_start=1, page_end=1, text_redacted=text,
                                       parser_version="t"))
    documents_dao.append_event(db_session, version.id, VersionStage.parsed, {"page_grades": {"1": "GOOD"}})
    db_session.commit()
    return version


def test_index_writes_search_rows_vectors_and_event(db_session, tenant_id):
    version = parsed_version(db_session, tenant_id)
    embeddings, index = RecordingEmbeddings(), InMemoryVectorIndex()
    index_version(db_session, version.id, embeddings=embeddings, vector_index=index)
    rows = db_session.scalars(select(ElementSearch).where(ElementSearch.version_id == version.id)).all()
    assert len(rows) == 1  # the heading is folded into the breadcrumb, not indexed on its own
    assert embeddings.seen == ["3. Fees\nFees are billed quarterly in arrears."]
    assert [m.id for m in index.query(str(tenant_id), embeddings.embed_query("x"), 5, None)] == [vector_id(version.id, 1)]
    assert documents_dao.version_events(db_session, version.id)[-1].stage is VersionStage.indexed


def test_indexing_v2_replaces_v1_search_rows_and_vectors(db_session, tenant_id):
    index = InMemoryVectorIndex()
    v1 = parsed_version(db_session, tenant_id)
    index_version(db_session, v1.id, embeddings=RecordingEmbeddings(), vector_index=index)
    v2 = parsed_version(db_session, tenant_id, data=FIXTURE.read_bytes() + b"\n% v2\n", texts=("Fees are billed monthly.",))
    index_version(db_session, v2.id, embeddings=RecordingEmbeddings(), vector_index=index)
    versions = set(db_session.scalars(select(ElementSearch.version_id).where(ElementSearch.tenant_id == tenant_id)))
    assert versions == {v2.id}
    ids = [m.id for m in index.query(str(tenant_id), [1.0] * 8, 10, None)]
    assert vector_id(v1.id, 1) not in ids and vector_id(v2.id, 1) in ids


def test_superseded_version_is_marked_indexed_without_indexing(db_session, tenant_id):
    v1 = parsed_version(db_session, tenant_id)
    parsed_version(db_session, tenant_id, data=FIXTURE.read_bytes() + b"\n% v2\n")
    index_version(db_session, v1.id, embeddings=RecordingEmbeddings(), vector_index=InMemoryVectorIndex())
    last = documents_dao.version_events(db_session, v1.id)[-1]
    assert last.stage is VersionStage.indexed and last.detail == {"skipped": "superseded"}
