import uuid

import pytest

from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.vector_index import InMemoryVectorIndex, VectorRecord, vector_id
from app.retry import call_with_retries


def test_rrf_rewards_agreement_between_rankings():
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "d"]])
    assert [item for item, _ in fused][:2] == ["b", "a"]
    assert dict(fused)["b"] == pytest.approx(1 / 62 + 1 / 61)


def test_rrf_handles_empty_rankings():
    assert reciprocal_rank_fusion([[], []]) == []


def test_in_memory_index_filters_by_document_and_deletes():
    index = InMemoryVectorIndex()
    index.upsert("t", [VectorRecord("x#0", [1.0, 0.0], {"document_id": "d1"}),
                       VectorRecord("y#0", [0.9, 0.1], {"document_id": "d2"})])
    assert [m.id for m in index.query("t", [1.0, 0.0], 5, None)] == ["x#0", "y#0"]
    assert [m.id for m in index.query("t", [1.0, 0.0], 5, ["d2"])] == ["y#0"]
    index.delete("t", ["x#0"])
    assert [m.id for m in index.query("t", [1.0, 0.0], 5, None)] == ["y#0"]
    assert index.query("other-tenant", [1.0, 0.0], 5, None) == []


def test_vector_id_is_stable():
    version = uuid.UUID(int=7)
    assert vector_id(version, 3) == f"{version}#3"


def test_retries_then_succeeds_and_then_gives_up():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise TimeoutError
        return "ok"

    assert call_with_retries(flaky, base_delay=0, retry_on=(TimeoutError,)) == "ok"
    with pytest.raises(TimeoutError):
        call_with_retries(lambda: (_ for _ in ()).throw(TimeoutError()), base_delay=0, retry_on=(TimeoutError,))
