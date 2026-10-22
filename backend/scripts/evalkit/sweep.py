"""Retrieval threshold sweep, top-k dense recall, and context recall over the evaluation key.

`MIN_DENSE_SIMILARITY` is the single floor below which a retrieved passage is dropped before the model sees it; when no
dense match reaches it, search returns nothing and the chat refuses (`app/retrieval/search.py:71-73`). Because one
embedding call per case question yields every case's dense candidate scores, the entire sweep across candidate
thresholds is pure arithmetic over a single checkpointed pass.
"""
import argparse
from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from typing import Any

from app import config
from app.assistant.runtime import get_runtime
from app.documents.dao import tokenize_known_values
from app.ledger.db import SessionLocal
from app.ledger.types import DEMO_TENANT_ID
from app.retrieval.search import dense_matches
from scripts.evalkit.cases import Case, read_cases
from scripts.evalkit.checkpoint import Checkpoint, summary_line
from scripts.evalkit.stats import rate

THRESHOLDS: list[float] = [round(0.38 + 0.01 * i, 2) for i in range(13)]
JUNK: tuple[str, ...] = ("out_of_corpus", "false_premise", "underspecified", "nonsense", "off_topic")


def score_case(matches: Sequence[tuple[str, float]], case: Case) -> dict[str, Any]:
    """Summarise a case's dense retrieval matches so threshold sweeps and recall checks need no further vector queries.

    `matches` are `(element_id, cosine_score)` ordered best first. Returns the top score (`best`), each gold element's
    score in `case.gold_element_ids` order (`None` when absent from the candidates), and the 1-based rank of the
    highest-ranked gold element (`None` when no gold element is present).
    """
    best: float | None = matches[0][1] if matches else None
    score_by_id = {str(eid): score for eid, score in matches}
    gold_scores: list[float | None] = [score_by_id.get(gid) for gid in case.gold_element_ids]

    gold_set = set(case.gold_element_ids)
    gold_rank: int | None = None
    if gold_set:
        for rank, (eid, _) in enumerate(matches, start=1):
            if str(eid) in gold_set:
                gold_rank = rank
                break

    return {
        "best": best,
        "gold_scores": gold_scores,
        "gold_rank": gold_rank,
    }


def sweep(
    rows: Mapping[str, dict[str, Any]],
    cases: Sequence[Case],
    thresholds: Sequence[float],
) -> list[dict[str, Any]]:
    """Evaluate how each candidate `MIN_DENSE_SIMILARITY` floor trades off answerable gating, gold passage loss, and
    junk leakage without re-running embeddings.
    """
    scored = [(c, rows[c.id]) for c in cases if c.id in rows]
    answerable = [(c, r) for c, r in scored if c.category == "answerable"]
    gold = [(c, r) for c, r in answerable if c.gold_element_ids]
    junk = [(c, r) for c, r in scored if c.category in JUNK]

    results: list[dict[str, Any]] = []
    for t in thresholds:
        answerable_gated = sum(1 for _, r in answerable if r["best"] is None or r["best"] < t)
        gold_cut = sum(
            1
            for _, r in gold
            if not any(s is not None and s >= t for s in r["gold_scores"])
        )
        junk_through = sum(1 for _, r in junk if r["best"] is not None and r["best"] >= t)
        results.append({
            "threshold": t,
            "answerable_n": len(answerable),
            "answerable_gated": answerable_gated,
            "gold_n": len(gold),
            "gold_cut": gold_cut,
            "junk_n": len(junk),
            "junk_through": junk_through,
        })
    return results


def topk_recall(
    rows: Mapping[str, dict[str, Any]],
    cases: Sequence[Case],
    k: int,
) -> dict[str, Any]:
    """Compute the Wilson rate at which an answerable case's first gold passage falls within the top `k` matches.

    Limit: rank is measured among the dense candidates (`SEARCH_CANDIDATES`), before reciprocal-rank fusion with
    full-text search, and on the raw case question before any agent query rewrite.
    """
    gold_rows = [
        rows[c.id]
        for c in cases
        if c.category == "answerable" and c.gold_element_ids and c.id in rows
    ]
    hits = sum(1 for r in gold_rows if r["gold_rank"] is not None and r["gold_rank"] <= k)
    return rate(hits, len(gold_rows))


def _load_existing_scores(checkpoint: Checkpoint) -> list[dict[str, Any]]:
    """Read already-scored rows from an active partial checkpoint or a finished scores.jsonl file."""
    if checkpoint.partial_path.exists():
        return checkpoint.rows()
    if checkpoint.final_path.exists():
        return [
            json.loads(line)
            for line in checkpoint.final_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return []


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entry point: embed unscored case questions once with checkpointing, then write the threshold sweep JSON."""
    parser = argparse.ArgumentParser(description="Sweep MIN_DENSE_SIMILARITY and compute top-k dense recall.")
    parser.add_argument("--key", type=Path, required=True, help="Directory holding key.jsonl.")
    parser.add_argument("--yes", action="store_true", help="Confirm paid embedding calls.")
    args = parser.parse_args(argv)
    key_dir: Path = args.key

    cases = read_cases(key_dir / "key.jsonl")
    checkpoint = Checkpoint(key_dir / "scores.jsonl", key="case_id")
    existing_rows = _load_existing_scores(checkpoint)
    done_ids = {str(r["case_id"]) for r in existing_rows if "case_id" in r}
    pending = [c for c in cases if c.id not in done_ids]

    n = len(pending)
    cost = n * 20 / 1e6 * 0.02
    print(f"Estimate: {n} embedding calls, about ${cost:.4f} (text-embedding-3-small)")
    if not args.yes:
        raise SystemExit(2)

    if pending:
        if checkpoint.final_path.exists() and not checkpoint.partial_path.exists():
            for row in existing_rows:
                checkpoint.append(row)
        runtime = get_runtime()
        hmac_key = config.require("PII_HMAC_KEY")
        vault_key = config.require("PII_VAULT_KEY")
        with SessionLocal() as session:
            for case in pending:
                query = tokenize_known_values(
                    session,
                    DEMO_TENANT_ID,
                    case.question,
                    hmac_key,
                    vault_key,
                )
                raw_matches = dense_matches(
                    session,
                    tenant_id=DEMO_TENANT_ID,
                    query=query,
                    embeddings=runtime.embeddings,
                    vector_index=runtime.vector_index,
                )
                matches = [(str(eid), score) for eid, score in raw_matches]
                checkpoint.append({"case_id": case.id, **score_case(matches, case)})

    if checkpoint.partial_path.exists() and {c.id for c in cases} <= checkpoint.done():
        checkpoint.finish()

    all_rows = _load_existing_scores(checkpoint)
    rows_by_id: dict[str, dict[str, Any]] = {str(r["case_id"]): r for r in all_rows if "case_id" in r}
    sweep_rows = sweep(rows_by_id, cases, THRESHOLDS)
    context_recall_by_threshold = [
        {
            "threshold": r["threshold"],
            "gold_n": r["gold_n"],
            "gold_cut": r["gold_cut"],
            **rate(r["gold_n"] - r["gold_cut"], r["gold_n"]),
        }
        for r in sweep_rows
    ]
    out_path = key_dir / "sweep.json"
    out_path.write_text(
        json.dumps(
            {
                "threshold_range": list(THRESHOLDS),
                "sweep": sweep_rows,
                "topk": {
                    "5": topk_recall(rows_by_id, cases, 5),
                    "8": topk_recall(rows_by_id, cases, 8),
                },
                "context_recall_by_threshold": context_recall_by_threshold,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        summary_line(
            "sweep",
            cases=len(cases),
            scored=len(pending),
            skipped=len(cases) - len(pending),
            estimate_usd=round(cost, 6),
            out=str(out_path),
        )
    )


if __name__ == "__main__":
    main()
