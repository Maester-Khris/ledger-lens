import logging
import uuid
from collections.abc import Sequence

from langchain_core.embeddings import Embeddings
from sqlalchemy.orm import Session

from app import config
from app.documents import dao as documents_dao
from app.documents.types import ElementKind, VersionStage
from app.retrieval import dao
from app.retrieval.vector_index import VectorIndex, VectorRecord, vector_id

logger = logging.getLogger(__name__)
BREADCRUMB_SEPARATOR = " › "


def embedding_text(section_path: Sequence[str], text: str) -> str:
    """Prefix the heading path: a cheap form of contextual retrieval (a clause alone rarely names its section)."""
    breadcrumb = BREADCRUMB_SEPARATOR.join(section_path)
    return f"{breadcrumb}\n{text}" if breadcrumb else text


def index_version(session: Session, version_id: uuid.UUID, *, embeddings: Embeddings, vector_index: VectorIndex) -> None:
    document = documents_dao.get_document_for_version(session, version_id)
    if documents_dao.current_version_id(session, document.id) != version_id:
        documents_dao.append_event(session, version_id, VersionStage.indexed, {"skipped": "superseded"})
        session.commit()
        return
    if dao.is_indexed(session, version_id):
        return
    elements = [e for e in documents_dao.list_elements(session, version_id) if e.kind is not ElementKind.heading]
    session.commit()  # no transaction held open across network calls

    vectors = embeddings.embed_documents([embedding_text(e.section_path, e.text_redacted) for e in elements])
    namespace = str(document.tenant_id)
    vector_index.upsert(namespace, [
        VectorRecord(vector_id(version_id, e.ordinal), values, {"document_id": str(document.id), "version_id": str(version_id)})
        for e, values in zip(elements, vectors)
    ])  # fixed ids: a rerun after a crash overwrites instead of duplicating

    replaced = dao.replace_search_rows(session, tenant_id=document.tenant_id, document_id=document.id, version_id=version_id)
    documents_dao.append_event(session, version_id, VersionStage.indexed, {
        "element_count": len(elements), "embedding_model": config.EMBEDDING_MODEL,
    })
    session.commit()

    for old_version_id in replaced:  # best effort: search drops vectors missing from element_search anyway
        old_ids = [vector_id(old_version_id, e.ordinal) for e in documents_dao.list_elements(session, old_version_id)]
        try:
            vector_index.delete(namespace, old_ids)
        except Exception:  # never fail an indexed version over cleanup of derived data
            logger.warning("could not delete %d stale vectors of version %s", len(old_ids), old_version_id, exc_info=True)
