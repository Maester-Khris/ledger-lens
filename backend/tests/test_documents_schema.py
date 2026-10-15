import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.documents.models import Document, DocumentElement, DocumentVersion, VersionEvent
from app.documents.types import DocumentType, ElementKind, VersionStage

SHA = "a" * 64


def _version(db_session, tenant_id, *, sha=SHA, version=1, key=None):
    document = Document(
        tenant_id=tenant_id, document_key=key or f"doc-{uuid.uuid4().hex[:8]}",
        doc_type=DocumentType.contract, title="IMA",
    )
    db_session.add(document)
    db_session.flush()
    row = DocumentVersion(
        document_id=document.id, version=version, file_sha256=sha, mime_type="application/pdf",
        byte_size=10, page_count=2, uploaded_by="test",
    )
    db_session.add(row)
    db_session.commit()
    return document, row


def test_version_numbers_and_file_hashes_are_unique_per_document(db_session, tenant_id):
    document, _ = _version(db_session, tenant_id)
    db_session.add(DocumentVersion(document_id=document.id, version=1, file_sha256="b" * 64,
                                   mime_type="application/pdf", byte_size=1, page_count=1, uploaded_by="t"))
    with pytest.raises(IntegrityError) as same_version:
        db_session.commit()
    assert same_version.value.orig.sqlstate == "23505"
    db_session.rollback()
    db_session.add(DocumentVersion(document_id=document.id, version=2, file_sha256=SHA,
                                   mime_type="application/pdf", byte_size=1, page_count=1, uploaded_by="t"))
    with pytest.raises(IntegrityError) as same_file:
        db_session.commit()
    assert same_file.value.orig.sqlstate == "23505"


def test_element_pages_must_be_ordered(db_session, tenant_id):
    _, version = _version(db_session, tenant_id)
    db_session.add(DocumentElement(version_id=version.id, ordinal=0, kind=ElementKind.paragraph,
                                   section_path=[], page_start=3, page_end=2, text_redacted="x", parser_version="t"))
    with pytest.raises(IntegrityError) as exc_info:
        db_session.commit()
    assert exc_info.value.orig.sqlstate == "23514"


@pytest.mark.parametrize("table", ["documents", "document_versions", "version_events", "document_elements", "pii_tokens"])
def test_record_tables_are_append_only(db_session, owner_session, tenant_id, table):
    _, version = _version(db_session, tenant_id)
    db_session.add(VersionEvent(version_id=version.id, stage=VersionStage.stored, detail={}))
    db_session.commit()
    statement = text(f"DELETE FROM {table}")
    with pytest.raises(ProgrammingError):  # the app role has no DELETE privilege
        db_session.execute(statement)
    db_session.rollback()
    if table in {"document_elements", "pii_tokens"}:
        return  # empty tables: a row trigger has nothing to fire on; the privilege check above is the guard
    with pytest.raises(IntegrityError) as exc_info:  # even the owner is stopped by forbid_mutation()
        owner_session.execute(statement)
    assert exc_info.value.orig.sqlstate == "23001"
