import uuid
from collections.abc import Sequence

from sqlalchemy import exists, func, select, text
from sqlalchemy.orm import Session

from app.documents.models import Document, DocumentElement, DocumentVersion
from app.retrieval.models import ElementSearch

_INSERT_CURRENT = text("""
    INSERT INTO element_search (element_id, tenant_id, document_id, version_id, tsv)
    SELECT e.id, :tenant_id, :document_id, e.version_id,
           setweight(to_tsvector('english', array_to_string(e.section_path, ' ')), 'A')
           || setweight(to_tsvector('english', e.text_redacted), 'B')
    FROM document_elements e
    WHERE e.version_id = :version_id AND e.kind <> 'heading'
    ON CONFLICT (element_id) DO NOTHING
""")
_DELETE_OLDER = text("""
    DELETE FROM element_search WHERE document_id = :document_id AND version_id <> :version_id
    RETURNING version_id
""")


def is_indexed(session: Session, version_id: uuid.UUID) -> bool:
    return session.scalar(select(exists().where(ElementSearch.version_id == version_id)))


def replace_search_rows(session: Session, *, tenant_id: uuid.UUID, document_id: uuid.UUID, version_id: uuid.UUID) -> list[uuid.UUID]:
    """Insert the new version's rows and drop older versions' rows in the same transaction (caller commits)."""
    params = {"tenant_id": tenant_id, "document_id": document_id, "version_id": version_id}
    session.execute(_INSERT_CURRENT, params)
    return sorted(set(session.scalars(_DELETE_OLDER, params)))

def full_text_hits(session: Session, *, tenant_id: uuid.UUID, query: str, document_ids: Sequence[uuid.UUID] | None, limit: int) -> list[uuid.UUID]:
    tsquery = func.websearch_to_tsquery("english", query)
    statement = (
        select(ElementSearch.element_id)
        .where(ElementSearch.tenant_id == tenant_id, ElementSearch.tsv.op("@@")(tsquery))
        .order_by(func.ts_rank_cd(ElementSearch.tsv, tsquery).desc(), ElementSearch.element_id)
        .limit(limit)
    )
    if document_ids:
        statement = statement.where(ElementSearch.document_id.in_(document_ids))
    return list(session.scalars(statement))


def current_element_ids(session: Session, *, tenant_id: uuid.UUID, vector_ids: Sequence[str]) -> dict[str, uuid.UUID]:
    """Map Pinecone ids ('<version>#<ordinal>' ) to element ids that are still in element_search (i.e. current)."""
    pairs = {}
    for vid in vector_ids:
        version, _, ordinal = vid.partition("#")
        try:
            pairs[(uuid.UUID(version), int(ordinal))] = vid
        except ValueError:
            continue  # a malformed id is not ours: drop it
    if not pairs:
        return {}
    rows = session.execute(
        select(DocumentElement.version_id, DocumentElement.ordinal, DocumentElement.id)
        .join(ElementSearch, ElementSearch.element_id == DocumentElement.id)
        .where(ElementSearch.tenant_id == tenant_id, DocumentElement.version_id.in_({v for v, _ in pairs}))
    )
    return {pairs[(v, o)]: element_id for v, o, element_id in rows if (v, o) in pairs}


def evidence_rows(session: Session, element_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, tuple[DocumentElement, DocumentVersion, Document]]:
    rows = session.execute(
        select(DocumentElement, DocumentVersion, Document)
        .join(DocumentVersion, DocumentVersion.id == DocumentElement.version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(DocumentElement.id.in_(element_ids))
    )
    return {element.id: (element, version, document) for element, version, document in rows}


def section_texts(session: Session, version_id: uuid.UUID, section_path: Sequence[str]) -> list[str]:
    return list(session.scalars(
        select(DocumentElement.text_redacted)
        .where(DocumentElement.version_id == version_id, DocumentElement.section_path == list(section_path))
        .order_by(DocumentElement.ordinal)
    ))

