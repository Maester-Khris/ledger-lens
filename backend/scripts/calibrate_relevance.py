"""Retrieval-only calibration of MIN_DENSE_SIMILARITY (P4 spec §5). No LLM call; fractions of a cent.
Run from backend/ against the live demo configuration:
  ENV_FILE=.env.demo $PYDEV/bin/python scripts/calibrate_relevance.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config  # noqa: E402
from app.assistant.graph import eval_config_hash  # noqa: E402
from app.assistant.runtime import get_runtime  # noqa: E402
from app.documents import dao as documents_dao  # noqa: E402
from app.ledger.db import SessionLocal  # noqa: E402
from app.ledger.types import DEMO_TENANT_ID  # noqa: E402
from app.retrieval.search import dense_matches  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
GOLDEN = BACKEND / "tests" / "eval" / "golden.json"
REPORTS = BACKEND / "reports"
JUNK = ("out_of_corpus", "false_premise", "underspecified", "nonsense", "off_topic")
MARGIN = 0.01


def best_dense_score(session, runtime, question: str) -> float | None:
    query = documents_dao.tokenize_known_values(session, DEMO_TENANT_ID, question, config.require("PII_HMAC_KEY"),
                                                config.require("PII_VAULT_KEY"))
    scores = [score for _, score in dense_matches(session, tenant_id=DEMO_TENANT_ID, query=query,
                                                  embeddings=runtime.embeddings, vector_index=runtime.vector_index)]
    return max(scores, default=None)


def main() -> None:
    cases = json.loads(GOLDEN.read_text())
    runtime = get_runtime()
    with SessionLocal() as session:
        rows = [{"id": c["id"], "category": c["category"], "expect": c["expect"], "retrieval": c.get("retrieval", False),
                 "best_dense_score": best_dense_score(session, runtime, c["question"])} for c in cases]
    floor = [r["best_dense_score"] for r in rows if r["retrieval"] and r["best_dense_score"] is not None]
    suggested = round(min(floor) - MARGIN, 3)
    junk = [r for r in rows if r["category"] in JUNK]
    gated = [r for r in junk if r["best_dense_score"] is None or r["best_dense_score"] < suggested]
    for r in sorted(rows, key=lambda r: -(r["best_dense_score"] or 0.0)):
        score = "-" if r["best_dense_score"] is None else f"{r['best_dense_score']:.3f}"
        print(f"{score:>7}  {r['category']:<15} {r['expect']:<8} {r['id']}{'  (sets the floor)' if r['retrieval'] else ''}")
    print(f"\nconfigured MIN_DENSE_SIMILARITY = {config.MIN_DENSE_SIMILARITY}")
    print(f"suggested  MIN_DENSE_SIMILARITY = {suggested}  (lowest floor-setting answerable score - {MARGIN})")
    print(f"junk refused by the retrieval gate alone at the suggestion: {len(gated)}/{len(junk)}")
    REPORTS.mkdir(exist_ok=True)
    report = REPORTS / f"relevance-{eval_config_hash()}.json"
    report.write_text(json.dumps({"configured": config.MIN_DENSE_SIMILARITY, "suggested": suggested, "margin": MARGIN,
                                  "junk_gated": len(gated), "junk_total": len(junk), "cases": rows}, indent=2))
    print(f"report: {report}")


if __name__ == "__main__":
    main()
