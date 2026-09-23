import uuid

from sqlalchemy import exists, select, text
from sqlalchemy.orm import Session

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
