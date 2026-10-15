import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app import config
from app.retry import call_with_retries

UPSERT_BATCH = 100


def vector_id(version_id: uuid.UUID, ordinal: int) -> str:
    return f"{version_id}#{ordinal}"


@dataclass(frozen=True)
class VectorRecord:
    id: str
    values: list[float]
    metadata: dict[str, str]


@dataclass(frozen=True)
class VectorMatch:
    id: str
    score: float


class VectorIndex(Protocol):
    def upsert(self, namespace: str, records: Sequence[VectorRecord]) -> None: ...
    def query(self, namespace: str, vector: Sequence[float], top_k: int, document_ids: Sequence[str] | None) -> list[VectorMatch]: ...
    def delete(self, namespace: str, ids: Sequence[str]) -> None: ...


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return 0.0 if norm == 0 else dot / norm


class InMemoryVectorIndex:
    """Test double with the same contract as Pinecone. O(n) scan; tests only."""

    def __init__(self) -> None:
        self._namespaces: dict[str, dict[str, VectorRecord]] = {}

    def upsert(self, namespace: str, records: Sequence[VectorRecord]) -> None:
        self._namespaces.setdefault(namespace, {}).update({r.id: r for r in records})

    def query(self, namespace: str, vector: Sequence[float], top_k: int, document_ids: Sequence[str] | None) -> list[VectorMatch]:
        records = self._namespaces.get(namespace, {}).values()
        allowed = [r for r in records if document_ids is None or r.metadata.get("document_id") in document_ids]
        matches = sorted((VectorMatch(r.id, _cosine(vector, r.values)) for r in allowed), key=lambda m: (-m.score, m.id))
        return matches[:top_k]

    def delete(self, namespace: str, ids: Sequence[str]) -> None:
        for record_id in ids:
            self._namespaces.get(namespace, {}).pop(record_id, None)


class PineconeVectorIndex:
    def __init__(self, api_key: str, index_name: str) -> None:
        from pinecone import Pinecone

        self._index = Pinecone(api_key=api_key).Index(index_name)

    def _call(self, fn):
        from pinecone.exceptions import PineconeException

        return call_with_retries(fn, retry_on=(PineconeException, TimeoutError, ConnectionError))

    def upsert(self, namespace: str, records: Sequence[VectorRecord]) -> None:
        for start in range(0, len(records), UPSERT_BATCH):
            batch = [{"id": r.id, "values": r.values, "metadata": r.metadata} for r in records[start:start + UPSERT_BATCH]]
            self._call(lambda: self._index.upsert(vectors=batch, namespace=namespace, timeout=config.PINECONE_TIMEOUT_SECONDS))

    def query(self, namespace: str, vector: Sequence[float], top_k: int, document_ids: Sequence[str] | None) -> list[VectorMatch]:
        where = None if document_ids is None else {"document_id": {"$in": list(document_ids)}}
        result = self._call(lambda: self._index.query(
            vector=list(vector), top_k=top_k, namespace=namespace, filter=where, timeout=config.PINECONE_TIMEOUT_SECONDS,
        ))
        return [VectorMatch(match.id, float(match.score)) for match in result.matches]

    def delete(self, namespace: str, ids: Sequence[str]) -> None:
        if ids:
            self._call(lambda: self._index.delete(ids=list(ids), namespace=namespace, timeout=config.PINECONE_TIMEOUT_SECONDS))
