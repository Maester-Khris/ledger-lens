import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.documents import store
from app.documents.errors import VersionNotFound
from app.documents.models import Document, DocumentVersion, VersionEvent
from app.documents.sniff import PdfFacts
from app.documents.types import DocumentType, VersionStage

PDF_MIME = "application/pdf"


@dataclass(frozen=True)
class UploadResult:
    document: Document
    version: DocumentVersion
    created: bool


def _document(
    session: Session, tenant_id: uuid.UUID, document_key: str, title: str, source_url: str | None,
    household_id: uuid.UUID | None,
) -> Document:
    session.execute(
        insert(Document)
        .values(tenant_id=tenant_id, document_key=document_key, doc_type=DocumentType.contract,
                title=title, source_url=source_url, household_id=household_id)
        .on_conflict_do_nothing(constraint="uq_documents_tenant_key")
    )
    return session.scalars(
        select(Document).where(Document.tenant_id == tenant_id, Document.document_key == document_key)
    ).one()


def register_upload(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    document_key: str,
    title: str,
    source_url: str | None,
    data: bytes,
    facts: PdfFacts,
    uploaded_by: str,
    store_root: Path,
    household_id: uuid.UUID | None = None,
) -> UploadResult:
    """The first upload of a document_key sets its title, source and household; later versions keep them."""
    sha256 = store.save_original(store_root, data)
    for attempt in range(2):  # one retry: a concurrent upload may take the next version number first
        document = _document(session, tenant_id, document_key, title, source_url, household_id)
        existing = session.scalars(
            select(DocumentVersion).where(DocumentVersion.document_id == document.id, DocumentVersion.file_sha256 == sha256)
        ).one_or_none()
        if existing is not None:
            session.commit()
            return UploadResult(document, existing, created=False)
        next_version = session.scalar(
            select(func.coalesce(func.max(DocumentVersion.version), 0) + 1).where(DocumentVersion.document_id == document.id)
        )
        version = DocumentVersion(
            document_id=document.id, version=next_version, file_sha256=sha256, mime_type=PDF_MIME,
            byte_size=facts.byte_size, page_count=facts.page_count, uploaded_by=uploaded_by,
        )
        try:
            session.add(version)
            session.flush()
            append_event(session, version.id, VersionStage.stored, {"file_sha256": sha256})
            session.commit()
            return UploadResult(document, version, created=True)
        except IntegrityError:
            session.rollback()
            if attempt == 1:
                raise
    raise AssertionError("unreachable")


def append_event(session: Session, version_id: uuid.UUID, stage: VersionStage, detail: dict) -> None:
    session.add(VersionEvent(version_id=version_id, stage=stage, detail=detail))


def version_events(session: Session, version_id: uuid.UUID) -> list[VersionEvent]:
    return list(session.scalars(select(VersionEvent).where(VersionEvent.version_id == version_id).order_by(VersionEvent.id)))


def get_version(session: Session, version_id: uuid.UUID) -> DocumentVersion:
    version = session.get(DocumentVersion, version_id)
    if version is None:
        raise VersionNotFound(f"Document version {version_id} does not exist.")
    return version


def all_version_ids(session: Session) -> list[uuid.UUID]:
    # ponytail: scans every version on each worker poll; add a "pending" query when the corpus grows past hundreds
    return list(session.scalars(select(DocumentVersion.id).order_by(DocumentVersion.created_at)))
