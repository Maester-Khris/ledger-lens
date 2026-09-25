import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from langchain_core.embeddings import Embeddings
from sqlalchemy.orm import Session

from app import config
from app.retrieval import dao
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.vector_index import VectorIndex

# ponytail: caps section context by characters, not tokens; switch to a tokenizer if prompts get tight
MAX_CONTEXT_CHARS = 4000


@dataclass(frozen=True)
class Evidence:
    element_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    version: int
    version_id: uuid.UUID
    page_start: int
    page_end: int
    section_path: tuple[str, ...]
    text: str
    context: str


def search(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    query: str,
    embeddings: Embeddings,
    vector_index: VectorIndex,
    document_ids: Sequence[uuid.UUID] | None = None,
    k: int = 8,
) -> list[Evidence]:
    """Hybrid search over current versions. `query` must already be tokenised (documents_dao.tokenize_known_values)."""
    text_ids = dao.full_text_hits(session, tenant_id=tenant_id, query=query, document_ids=document_ids,
                                  limit=config.SEARCH_CANDIDATES)
    matches = vector_index.query(str(tenant_id), embeddings.embed_query(query), config.SEARCH_CANDIDATES,
                                 None if document_ids is None else [str(d) for d in document_ids])
    current = dao.current_element_ids(session, tenant_id=tenant_id, vector_ids=[m.id for m in matches])
    dense = [(current[m.id], m.score) for m in matches if m.id in current]  # stale vectors drop out here
    if not text_ids and (not dense or max(score for _, score in dense) < config.MIN_DENSE_SIMILARITY):
        return []  # relevance gate: say "I don't know" instead of answering from noise

    fused = reciprocal_rank_fusion([[str(i) for i in text_ids], [str(i) for i, _ in dense]])[:k]
    rows = dao.evidence_rows(session, [uuid.UUID(item) for item, _ in fused])
    results = []
    for item, _ in fused:
        element, version, document = rows[uuid.UUID(item)]
        context = "\n\n".join(dao.section_texts(session, version.id, element.section_path))[:MAX_CONTEXT_CHARS]
        results.append(Evidence(element.id, document.id, document.title, version.version, version.id,
                                element.page_start, element.page_end, tuple(element.section_path),
                                element.text_redacted, context))
    return results
