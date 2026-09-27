import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.documents import store, vault
from app.documents.errors import DocumentNotFound, VersionNotFound
from app.documents.models import Document, DocumentElement, DocumentVersion, PiiToken, VersionEvent
from app.documents.redact import PII_ENTITIES, TOKEN_PATTERN, PiiSpan, apply_redaction, make_token
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


# ---------- PII vault ----------

def save_tokens(session: Session, tenant_id: uuid.UUID, tokens: Mapping[str, tuple[str, str]], key: str) -> None:
    """No commit. A token already in the vault is left alone (same value, same token)."""
    if not tokens:
        return
    rows = [
        {"tenant_id": tenant_id, "token": token, "entity_type": entity_type, "value_encrypted": vault.encrypt_value(value, key)}
        for token, (entity_type, value) in tokens.items()
    ]
    session.execute(insert(PiiToken).values(rows).on_conflict_do_nothing(index_elements=["tenant_id", "token"]))


def reveal(session: Session, tenant_id: uuid.UUID, texts: Sequence[str], key: str) -> list[str]:
    """Display only: swap tokens back to values. Unknown tokens stay as they are."""
    wanted = {match.group(0) for text in texts for match in TOKEN_PATTERN.finditer(text)}
    if not wanted:
        return list(texts)
    values = {
        row.token: vault.decrypt_value(row.value_encrypted, key)
        for row in session.scalars(select(PiiToken).where(PiiToken.tenant_id == tenant_id, PiiToken.token.in_(wanted)))
    }
    return [TOKEN_PATTERN.sub(lambda m: values.get(m.group(0), m.group(0)), text) for text in texts]


# ---------- Element queries ----------

def list_elements(session: Session, version_id: uuid.UUID) -> list[DocumentElement]:
    return list(
        session.scalars(select(DocumentElement).where(DocumentElement.version_id == version_id).order_by(DocumentElement.ordinal))
    )


def get_document_for_version(session: Session, version_id: uuid.UUID) -> Document:
    return session.scalars(
        select(Document).join(DocumentVersion, DocumentVersion.document_id == Document.id).where(DocumentVersion.id == version_id)
    ).one()


def parsed_detail(session: Session, version_id: uuid.UUID) -> dict:
    event = session.scalars(
        select(VersionEvent)
        .where(VersionEvent.version_id == version_id, VersionEvent.stage == VersionStage.parsed)
        .order_by(VersionEvent.id.desc())
    ).first()
    return {} if event is None else dict(event.detail)


# ---------- Document listing ----------

@dataclass(frozen=True)
class DocumentRow:
    document: Document
    version: DocumentVersion
    events: list[VersionEvent]
    element_count: int


def _row(session: Session, document: Document) -> DocumentRow:
    version = session.scalars(
        select(DocumentVersion).where(DocumentVersion.document_id == document.id).order_by(DocumentVersion.version.desc())
    ).first()
    count = session.scalar(select(func.count()).select_from(DocumentElement).where(DocumentElement.version_id == version.id))
    return DocumentRow(document, version, version_events(session, version.id), count)


def list_documents(session: Session, tenant_id: uuid.UUID) -> list[DocumentRow]:
    # ponytail: N+1 queries per document; fine for a handful of contracts, one grouped query when it isn't
    documents = session.scalars(select(Document).where(Document.tenant_id == tenant_id).order_by(Document.created_at.desc()))
    return [_row(session, document) for document in documents]


def get_document_row(session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID) -> DocumentRow:
    document = session.get(Document, document_id)
    if document is None or document.tenant_id != tenant_id:
        raise DocumentNotFound(f"Document {document_id} does not exist.")
    return _row(session, document)


def get_version_by_number(session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID, version: int) -> DocumentVersion:
    get_document_row(session, tenant_id, document_id)  # tenant check
    row = session.scalars(
        select(DocumentVersion).where(DocumentVersion.document_id == document_id, DocumentVersion.version == version)
    ).one_or_none()
    if row is None:
        raise VersionNotFound(f"Document {document_id} has no version {version}.")
    return row


def current_version_id(session: Session, document_id: uuid.UUID) -> uuid.UUID:
    return session.scalars(
        select(DocumentVersion.id).where(DocumentVersion.document_id == document_id).order_by(DocumentVersion.version.desc())
    ).first()

MAX_WINDOW_WORDS = 4
_WORD = re.compile(r"\S+")
_TRAILING_PUNCTUATION = ".,;:!?)\"'"

_REGEX_RECOGNIZERS = {
    "EMAIL_ADDRESS": re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    "PHONE_NUMBER": re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    "CA_SIN": re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{3}\b"),
    "US_SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "CREDIT_CARD": re.compile(r"\b(?:\d{4}[-.\s]?){3}\d{4}\b"),
    "IBAN_CODE": re.compile(r"(?i)\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
    "STREET_ADDRESS": re.compile(r"(?i)\b\d{1,5}\s+(?:[a-z0-9.-]+\s+){1,4}(?:street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|lane|ln|court|ct|circle|cir|trail|trl|way)(?:\s+(?:apt|suite|unit|#)\s*[\w-]+)?\b"),
    "POSTAL_CODE": re.compile(r"(?i)\b(?:[a-z]\d[a-z][ -]?\d[a-z]\d|\d{5}(?:-\d{4})?)\b"),
}

def tokenize_known_values(session: Session, tenant_id: uuid.UUID, text: str, hmac_key: str, vault_key: str) -> str:
    """Tokenise PII in a question without loading spaCy in the API: hash every 1–4 word window and keep
    the ones the vault already knows. Only values seen in an ingested document can match (by design).
    Then, apply regex recognizers to tokenise standard PII even if it wasn't seen before."""
    words = list(_WORD.finditer(text))
    candidates: dict[str, PiiSpan] = {}
    for i in range(len(words)):
        for n in range(1, MAX_WINDOW_WORDS + 1):
            if i + n > len(words):
                break
            start, end = words[i].start(), words[i + n - 1].end()
            while end > start and text[end - 1] in _TRAILING_PUNCTUATION:
                end -= 1
            for entity_type in PII_ENTITIES:
                candidates[make_token(tenant_id, entity_type, text[start:end], hmac_key)] = PiiSpan(start, end, entity_type, 1.0)
    known = set(session.scalars(select(PiiToken.token).where(PiiToken.tenant_id == tenant_id, PiiToken.token.in_(candidates))))
    
    # First apply known values
    redacted_text = apply_redaction(text, [candidates[t] for t in known], tenant_id, hmac_key).text

    # Then apply regexes for unknown standard PII
    new_spans: list[PiiSpan] = []
    for entity_type, pattern in _REGEX_RECOGNIZERS.items():
        for match in pattern.finditer(redacted_text):
            new_spans.append(PiiSpan(match.start(), match.end(), entity_type, 1.0))
            
    if new_spans:
        redaction = apply_redaction(redacted_text, new_spans, tenant_id, hmac_key)
        save_tokens(session, tenant_id, redaction.tokens, vault_key)
        redacted_text = redaction.text

    return redacted_text



def find_document(session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID) -> Document | None:
    document = session.get(Document, document_id)
    return document if document is not None and document.tenant_id == tenant_id else None


def first_page(session: Session, element_ids: Sequence[uuid.UUID]) -> int | None:
    if not element_ids:
        return None
    return session.scalar(select(func.min(DocumentElement.page_start)).where(DocumentElement.id.in_(element_ids)))

def last_event_at(session: Session, tenant_id: uuid.UUID) -> datetime | None:
    return session.scalar(
        select(func.max(VersionEvent.created_at))
        .join(DocumentVersion, DocumentVersion.id == VersionEvent.version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(Document.tenant_id == tenant_id)
    )
