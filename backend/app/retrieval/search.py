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


def dense_matches(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    query: str,
    embeddings: Embeddings,
    vector_index: VectorIndex,
    document_ids: Sequence[uuid.UUID] | None = None,
) -> list[tuple[uuid.UUID, float]]:
    """Dense candidates as (current element id, cosine score), best first. Stale vectors drop out here."""
    matches = vector_index.query(str(tenant_id), embeddings.embed_query(query), config.SEARCH_CANDIDATES,
                                 None if document_ids is None else [str(d) for d in document_ids])
    current = dao.current_element_ids(session, tenant_id=tenant_id, vector_ids=[m.id for m in matches])
    return [(current[m.id], m.score) for m in matches if m.id in current]


def search(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    query: str,
    embeddings: Embeddings,
    vector_index: VectorIndex,
    document_ids: Sequence[uuid.UUID] | None = None,
    k: int = 8,
    question: str | None = None,
) -> list[Evidence]:
    """Hybrid search over current versions. `query` must already be tokenised (documents_dao.tokenize_known_values).
    `question` is the guest's own tokenised question, when the query is the chat model's rewrite of it."""
    text_ids = dao.full_text_hits(session, tenant_id=tenant_id, query=query, document_ids=document_ids,
                                  limit=config.SEARCH_CANDIDATES)
    # Relevance gate (P4): the dense score decides and full-text only ranks, so a shared keyword alone ("fee") never
    # opens the gate, and passages below the floor never reach the model's context.
    # A passage passes when it is relevant to the query or to the guest's question: the model's rewrite is often
    # terse ("fees") and scores far below the full question, which is what the floor was calibrated on.
    best: dict[uuid.UUID, float] = {}
    for text in dict.fromkeys(t for t in (query, question) if t):
        for element_id, score in dense_matches(session, tenant_id=tenant_id, query=text, embeddings=embeddings,
                                               vector_index=vector_index, document_ids=document_ids):
            best[element_id] = max(score, best.get(element_id, score))
    dense = sorted(((i, s) for i, s in best.items() if s >= config.MIN_DENSE_SIMILARITY), key=lambda pair: -pair[1])
    if not dense:
        return []  # say "I don't know" instead of answering from noise

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
