"""T7, whether the expected passage survives top-k 5 as well as 8. Retrieval only: the golden
answerable questions go through search as the tool calls it (real embeddings, local index, no chat call). Top 5
is the first five of top 8 (same fused ranking), so one search per case answers both.

Usage line:
  Run from backend/:  MIN_DENSE_SIMILARITY=0.43 $PYDEV/bin/python scripts/topk_check.py

Limit: the question stands in for the model's own search query.
"""
import json
import sys
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

KS = (5, 8)


def rank_of_expected(hits: list, case: dict, keys: dict[uuid.UUID, str]) -> int | None:
    expected_doc = case.get("expect_document")
    expected_page = case.get("expect_page")
    for rank, hit in enumerate(hits, start=1):
        if keys.get(hit.document_id) == expected_doc:
            if expected_page is None or hit.page_start == expected_page:
                return rank
    return None


def main() -> None:
    from app import config
    from app.assistant.runtime import get_runtime
    from app.documents import dao as documents_dao
    from app.ledger.db import SessionLocal
    from app.ledger.types import DEMO_TENANT_ID
    from app.retrieval.search import search
    from tests.eval.test_golden import CASES, expand

    if config.LOADTEST_STUB_VECTORS or config.PINECONE_INDEX == "contract-demo":
        sys.exit(
            f"Cannot run top-k check: LOADTEST_STUB_VECTORS={config.LOADTEST_STUB_VECTORS}, "
            f"PINECONE_INDEX={config.PINECONE_INDEX!r}. Requires real vector index."
        )

    runtime = get_runtime()
    with SessionLocal() as session:
        titles = documents_dao.document_titles(session, DEMO_TENANT_ID)
        id_to_key: dict[uuid.UUID, str] = {doc.id: doc.document_key for doc in titles}
        key_to_id: dict[str, uuid.UUID] = {doc.document_key: doc.id for doc in titles}

        rows: list[dict] = []
        for case in expand(CASES):
            if case.get("expect") != "answer":
                continue
            doc_ids = [key_to_id[case["document_key"]]] if "document_key" in case else None
            hits = search(
                session,
                tenant_id=DEMO_TENANT_ID,
                query=case["question"],
                embeddings=runtime.embeddings,
                vector_index=runtime.vector_index,
                k=max(KS),
                question=case["question"],
                document_ids=doc_ids,
            )
            rank = rank_of_expected(hits, case, id_to_key)
            rows.append({"id": case["id"], "rank": rank})

    summary = {
        "cases": len(rows),
        "found_in_top_5": sum(1 for r in rows if r["rank"] is not None and r["rank"] <= 5),
        "found_in_top_8": sum(1 for r in rows if r["rank"] is not None and r["rank"] <= 8),
    }

    out_dir = BACKEND / "reports" / "tokens"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "topk-check.json"
    payload = {
        "summary": summary,
        "lost_at_5": [r["id"] for r in rows if r["rank"] is not None and r["rank"] > 5],
        "rows": rows,
    }
    out_path.write_text(json.dumps(payload, indent=2))
    print(json.dumps(summary, indent=2))
    print(f"written {out_path.relative_to(BACKEND)}")


if __name__ == "__main__":
    main()
