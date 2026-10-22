"""Evaluation report builder: Wilson 95% intervals, retrieval-vs-generation failure split, anchor error bound, and confidence sweep.

Every published metric carries its sample size and Wilson 95% confidence interval (`stats.rate`), while empty categories
report `n=0` with `None` rates rather than dividing by zero. Wrong answers on answerable cases with gold passages are
partitioned into retrieval failures (gold passage absent from `retrieved`) and generation failures (gold passage
retrieved, answer still wrong).
"""
import argparse
from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from typing import Any

from app.contracts.agree import compare_field
from scripts.evalkit.cases import Case, read_cases
from scripts.evalkit.checkpoint import Checkpoint, summary_line
from scripts.evalkit.stats import rate
from scripts.x1_report import clopper_pearson_upper, cohen_kappa

JUNK: tuple[str, ...] = ("out_of_corpus", "false_premise", "underspecified", "nonsense", "off_topic")


def metrics(
    cases: Sequence[Case],
    answers: Mapping[str, dict[str, Any]],
    judgments: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    """Compute all headline evaluation rates with Wilson 95% margins, the failure split, and per-writer correctness."""
    ref_answerables = [
        c
        for c in cases
        if c.category == "answerable"
        and c.reference
        and answers.get(c.id, {}).get("event") != "error"
    ]

    def _is_correct(case_id: str) -> bool:
        row = answers.get(case_id)
        j = judgments.get(case_id)
        return bool(row and row.get("event") == "answer" and j and j.get("correct"))

    answer_correctness = rate(
        sum(1 for c in ref_answerables if _is_correct(c.id)),
        len(ref_answerables),
    )

    ans_with_row = [
        c
        for c in cases
        if c.category == "answerable"
        and c.id in answers
        and answers[c.id].get("event") != "error"
    ]
    over_refusal = rate(
        sum(1 for c in ans_with_row if answers[c.id].get("event") != "answer"),
        len(ans_with_row),
    )

    case_judgments = [judgments[c.id] for c in cases if c.id in judgments]
    all_statements = [s for j in case_judgments for s in j.get("statements", [])]
    citation_recall = rate(
        sum(1 for s in all_statements if s.get("supported")),
        len(all_statements),
    )

    all_citations = [cit for j in case_judgments for cit in j.get("citations", [])]
    citation_precision = rate(
        sum(1 for cit in all_citations if cit.get("relevant")),
        len(all_citations),
    )

    refusal_accuracy: dict[str, dict[str, Any]] = {}
    all_junk_rows: list[dict[str, Any]] = []
    for cat in JUNK:
        cat_rows = [
            answers[c.id]
            for c in cases
            if c.category == cat
            and c.id in answers
            and answers[c.id].get("event") != "error"
        ]
        refusal_accuracy[cat] = rate(
            sum(1 for r in cat_rows if r.get("behaviour_ok")),
            len(cat_rows),
        )
        all_junk_rows.extend(cat_rows)
    refusal_accuracy["overall"] = rate(
        sum(1 for r in all_junk_rows if r.get("behaviour_ok")),
        len(all_junk_rows),
    )

    gold_with_row = [
        c
        for c in cases
        if c.category == "answerable"
        and c.gold_element_ids
        and c.id in answers
        and answers[c.id].get("event") != "error"
    ]

    def _has_gold(case: Case) -> bool:
        retrieved = set(answers[case.id].get("retrieved") or ())
        return any(gid in retrieved for gid in case.gold_element_ids)

    context_recall = rate(
        sum(1 for c in gold_with_row if _has_gold(c)),
        len(gold_with_row),
    )

    wrong_gold = [c for c in gold_with_row if not _is_correct(c.id)]
    gen_failures = sum(1 for c in wrong_gold if _has_gold(c))
    ret_failures = len(wrong_gold) - gen_failures
    failure_split = {"retrieval": ret_failures, "generation": gen_failures}

    writers = sorted({c.writer for c in ref_answerables if c.writer})
    by_writer = {
        w: rate(
            sum(1 for c in ref_answerables if c.writer == w and _is_correct(c.id)),
            sum(1 for c in ref_answerables if c.writer == w),
        )
        for w in writers
    }

    return {
        "answer_correctness": answer_correctness,
        "over_refusal": over_refusal,
        "citation_recall": citation_recall,
        "citation_precision": citation_precision,
        "refusal_accuracy": refusal_accuracy,
        "context_recall": context_recall,
        "failure_split": failure_split,
        "by_writer": by_writer,
    }


def confidence_sweep(
    answers: Mapping[str, dict[str, Any]],
    judgments: Mapping[str, dict[str, Any]],
    thresholds: Sequence[float],
) -> list[dict[str, Any]]:
    """Sweep logprob confidence thresholds offline against judged correctness to measure accuracy above/below each cut."""
    eligible = [
        (float(row["confidence"]), bool(judgments[cid].get("correct")))
        for cid, row in answers.items()
        if row.get("event") == "answer" and cid in judgments and row.get("confidence") is not None
    ]
    total = len(eligible)
    out: list[dict[str, Any]] = []
    for t in thresholds:
        above = [ok for conf, ok in eligible if conf >= t]
        below = [ok for conf, ok in eligible if conf < t]
        out.append({
            "threshold": t,
            "above": rate(sum(1 for ok in above if ok), len(above)),
            "below": rate(sum(1 for ok in below if ok), len(below)),
            "share_below": (len(below) / total) if total else None,
        })
    return out


def judge_agreement(
    api: Mapping[str, dict[str, Any]],
    cli: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    """Measure agreement and Cohen's kappa between the Anthropic API reference judge and the headless CLI judge."""
    shared = sorted(set(api) & set(cli))
    n = len(shared)
    if n == 0:
        return {"n": 0, "agree": 0, "share": None, "kappa": None}
    a_seq = ["true" if api[cid].get("correct") else "false" for cid in shared]
    b_seq = ["true" if cli[cid].get("correct") else "false" for cid in shared]
    agree = sum(1 for x, y in zip(a_seq, b_seq) if x == y)
    return {
        "n": n,
        "agree": agree,
        "share": agree / n,
        "kappa": cohen_kappa(a_seq, b_seq),
    }


def anchor_error(anchors: Sequence[Case]) -> dict[str, Any]:
    """Compare LLM writer answers on human-adjudicated anchor fields against the ground-truth labels and bound the error rate."""
    valid = [c for c in anchors if c.field_path]
    n = len(valid)
    if n == 0:
        return {"n": 0, "errors": 0, "upper_bound": None}

    errors = 0
    for case in valid:
        raw = case.reference
        writer_val: object = raw
        if isinstance(raw, str) and raw.lstrip().startswith(("[", "{")):
            try:
                writer_val = json.loads(raw)
            except json.JSONDecodeError:
                writer_val = raw
        if compare_field(case.field_path or "", writer_val, case.anchor_value).outcome != "agree":
            errors += 1

    return {
        "n": n,
        "errors": errors,
        "upper_bound": clopper_pearson_upper(errors, n),
    }


def _fmt_rate(r: Mapping[str, Any]) -> str:
    """Format a `stats.rate` dictionary as `<pct>% (95% CI <low>–<high>%, n=<n>)` or `n=0` when empty."""
    n = int(r.get("n") or 0)
    if n == 0 or r.get("rate") is None:
        return "n=0"
    pct = float(r["rate"]) * 100.0
    low = float(r["low"]) * 100.0
    high = float(r["high"]) * 100.0
    return f"{pct:.1f}% (95% CI {low:.1f}–{high:.1f}%, n={n})"


def render_markdown(
    report: dict[str, Any],
    *,
    anchor: dict[str, Any],
    agreement: dict[str, Any] | None,
    sweep: Sequence[dict[str, Any]],
) -> str:
    """Render a publishable Markdown report containing every rate, its sample size and 95% interval, and stated limits."""
    refusal = report.get("refusal_accuracy", {})
    split = report.get("failure_split", {"retrieval": 0, "generation": 0})
    by_writer = report.get("by_writer", {})

    lines = [
        "# Chat Evaluation Report",
        "",
        "## Answer correctness",
        f"- {_fmt_rate(report.get('answer_correctness', {}))}",
        "",
        "## Citation recall",
        f"- {_fmt_rate(report.get('citation_recall', {}))}",
        "",
        "## Citation precision",
        f"- {_fmt_rate(report.get('citation_precision', {}))}",
        "",
        "## Refusal accuracy",
        f"- **Overall:** {_fmt_rate(refusal.get('overall', {}))}",
    ]
    for cat in JUNK:
        lines.append(f"- **{cat}:** {_fmt_rate(refusal.get(cat, {}))}")

    lines.extend([
        "",
        "## Over-refusal",
        f"- {_fmt_rate(report.get('over_refusal', {}))}",
        "",
        "## Context recall",
        f"- {_fmt_rate(report.get('context_recall', {}))}",
        "",
        "## Failure split",
        f"- **Retrieval failures (gold passage not retrieved):** {split.get('retrieval', 0)}",
        f"- **Generation failures (gold passage retrieved, answer wrong):** {split.get('generation', 0)}",
        "",
        "## Results by writer",
    ])
    if by_writer:
        for writer, w_rate in sorted(by_writer.items()):
            lines.append(f"- **{writer}:** {_fmt_rate(w_rate)}")
    else:
        lines.append("- n=0")

    lines.extend([
        "",
        "## Anchor error rate",
    ])
    if anchor.get("n"):
        ub = float(anchor["upper_bound"]) * 100.0
        err_pct = (int(anchor["errors"]) / int(anchor["n"])) * 100.0
        lines.append(
            f"- {anchor['errors']}/{anchor['n']} ({err_pct:.1f}%, one-sided 95% Clopper-Pearson upper bound {ub:.1f}%)"
        )
    else:
        lines.append("- n=0")

    if agreement is not None:
        lines.extend([
            "",
            "## Judge agreement",
        ])
        if agreement.get("n"):
            share_pct = float(agreement["share"]) * 100.0
            kappa_val = float(agreement["kappa"])
            lines.append(
                f"- {agreement['agree']}/{agreement['n']} ({share_pct:.1f}% agreement, Cohen's kappa {kappa_val:.3f})"
            )
        else:
            lines.append("- n=0")

    lines.extend([
        "",
        "## Confidence sweep",
        "",
        "| Threshold | Accuracy above | Accuracy below | Share below |",
        "|---|---|---|---|",
    ])
    for row in sweep:
        share = row.get("share_below")
        share_str = f"{float(share) * 100.0:.1f}%" if share is not None else "n=0"
        lines.append(
            f"| {row['threshold']} | {_fmt_rate(row['above'])} | {_fmt_rate(row['below'])} | {share_str} |"
        )

    lines.extend([
        "",
        "## Limits",
        "- LLM-written and LLM-checked evaluation key, anchored on 128 human-adjudicated contract fields.",
        "- LLM judge (`claude-sonnet-5-5`), validated between Anthropic API and headless CLI.",
        "- Single final run on the deployed configuration (`gpt-4.1-2025-04-14`).",
        "- Part of the key is written by `gpt-oss`, an open-weights relative of `gpt-4.1`, so correctness is split by writer.",
        "- No runtime escalation path yet; confidence and context recall are measured offline.",
        "- Golden `@scoped` variants are not run in this corpus-wide pass.",
        "",
    ])
    return "\n".join(lines)


def _read_jsonl(path: Path, key: str = "case_id") -> list[dict[str, Any]]:
    """Read rows from a finished JSONL file or fall back to its partial checkpoint if present."""
    if path.exists():
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return Checkpoint(path, key=key).rows()


def _deciles(values: Sequence[float]) -> list[float]:
    """Compute sorted unique decile thresholds (10th through 90th percentiles) over observed confidence values."""
    if not values:
        return []
    ordered = sorted(float(v) for v in values)
    n = len(ordered)
    cuts: list[float] = []
    for decile in range(1, 10):
        idx = int(round((decile / 10.0) * (n - 1)))
        val = round(ordered[idx], 4)
        if not cuts or val != cuts[-1]:
            cuts.append(val)
    return cuts


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entry point to compute evaluation metrics and write `report.json` and `report.md`."""
    parser = argparse.ArgumentParser(description="Build the final chat evaluation report.")
    parser.add_argument("--run", type=str, required=True, help="Evaluation run id under reports/eval-final/.")
    parser.add_argument("--key", type=Path, default=None, help="Directory holding key.jsonl and anchor.jsonl.")
    args = parser.parse_args(argv)

    run_dir = Path("reports/eval-final") / args.run
    key_dir: Path | None = args.key
    if key_dir is None:
        run_meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        raw_key = run_meta.get("key") or run_meta.get("key_dir")
        key_dir = Path(str(raw_key))

    cases = read_cases(key_dir / "key.jsonl")
    anchor_path = key_dir / "anchor.jsonl"
    anchors = read_cases(anchor_path) if anchor_path.exists() else []

    answer_rows = _read_jsonl(run_dir / "answers.jsonl", key="case_id")
    answers = {str(r["case_id"]): r for r in answer_rows if "case_id" in r}

    cli_rows = _read_jsonl(run_dir / "judgments-cli.jsonl", key="case_id")
    api_rows = _read_jsonl(run_dir / "judgments-api.jsonl", key="case_id")
    cli_by_id = {str(r["case_id"]): r for r in cli_rows if "case_id" in r}
    api_by_id = {str(r["case_id"]): r for r in api_rows if "case_id" in r}

    judgments = cli_by_id if cli_by_id else api_by_id
    agreement = judge_agreement(api_by_id, cli_by_id) if (api_by_id and cli_by_id) else None

    observed_confidences = [
        float(r["confidence"])
        for cid, r in answers.items()
        if r.get("event") == "answer" and cid in judgments and r.get("confidence") is not None
    ]
    thresholds = _deciles(observed_confidences)

    report_metrics = metrics(cases, answers, judgments)
    anchor_summary = anchor_error(anchors)
    sweep_rows = confidence_sweep(answers, judgments, thresholds)

    full_report = {
        **report_metrics,
        "anchor_error": anchor_summary,
        "judge_agreement": agreement,
        "confidence_sweep": sweep_rows,
    }
    json_path = run_dir / "report.json"
    md_path = run_dir / "report.md"
    run_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(full_report, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(
        render_markdown(
            report_metrics,
            anchor=anchor_summary,
            agreement=agreement,
            sweep=sweep_rows,
        ),
        encoding="utf-8",
    )
    print(
        summary_line(
            "report",
            cases=len(cases),
            answers=len(answers),
            judgments=len(judgments),
            out=str(md_path),
        )
    )


if __name__ == "__main__":
    main()
