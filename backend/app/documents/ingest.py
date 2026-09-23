import uuid
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session

from app.documents import dao, store
from app.documents.models import DocumentElement
from app.documents.parse import ParsedDocument
from app.documents.redact import PiiDetector, apply_redaction
from app.documents.types import VersionStage


def parse_and_redact(
    session: Session,
    version_id: uuid.UUID,
    *,
    parser: Callable[[Path], ParsedDocument],
    detector: PiiDetector,
    store_root: Path,
    hmac_key: str,
    vault_key: str,
) -> None:
    """Parse and redact in one step: Docling's raw text holds PII and is never persisted."""
    version = dao.get_version(session, version_id)
    tenant_id = dao.get_document_for_version(session, version_id).tenant_id
    if dao.list_elements(session, version_id):
        return
    session.commit()  # end the read transaction before minutes of CPU work

    parsed = parser(store.original_path(store_root, version.file_sha256))
    tokens: dict[str, tuple[str, str]] = {}
    for ordinal, element in enumerate(parsed.elements):
        redaction = apply_redaction(element.text, detector.detect(element.text), tenant_id, hmac_key)
        tokens.update(redaction.tokens)
        session.add(DocumentElement(
            version_id=version_id, ordinal=ordinal, kind=element.kind, section_path=list(element.section_path),
            page_start=element.page_start, page_end=element.page_end, text_redacted=redaction.text,
            parser_version=parsed.parser_version,
        ))
    dao.save_tokens(session, tenant_id, tokens, vault_key)
    dao.append_event(session, version_id, VersionStage.parsed, {
        "element_count": len(parsed.elements),
        "pii_token_count": len(tokens),
        "page_grades": {str(page): grade for page, grade in parsed.page_grades.items()},
        "parser_version": parsed.parser_version,
    })
    session.commit()
