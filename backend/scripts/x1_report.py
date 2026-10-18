"""Free, read only, run from backend/.

X1 per-stage report: cost, time and confidence per stage, labelled error rates
with Clopper-Pearson upper bounds, and 100k projections naming prices and assumptions.
"""
from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
import uuid

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.contracts import dao
from app.contracts.agree import compare_field
from app.contracts.models import ExtractedField, ExtractionRun, FieldLabel, FieldReview, FieldVerification
from app.contracts.terms import SERVED_STATUSES, field_class, field_status, verification_path
from app.contracts.types import FieldRouting, ReviewDecision
from app.documents.models import VersionEvent
from app.documents.types import VersionStage
from app.ledger.db import SessionLocal

TARGETS = {"A": 0.05, "B": 0.05, "C": 0.10}
A_TIGHT = 0.01  # class A target once n_A >= 300
CHARS_PER_TOKEN = 4
TURNS_PER_USER_PER_DAY = 3  # assumption, stated in the report


def clopper_pearson_upper(errors: int, n: int, confidence: float = 0.95) -> float:
    """One-sided Clopper-Pearson upper bound for binomial error rate via bisection."""
    if n <= 0:
        raise ValueError("n must be positive")
    if errors < 0 or errors > n:
        raise ValueError(f"errors must be between 0 and {n}")
    if errors == n:
        return 1.0

    target = 1.0 - confidence

    def binomial_cdf(k: int, num: int, p: float) -> float:
        return sum(math.comb(num, i) * (p ** i) * ((1.0 - p) ** (num - i)) for i in range(k + 1))

    low = 0.0
    high = 1.0
    for _ in range(80):
        mid = (low + high) / 2.0
        if binomial_cdf(errors, n, mid) > target:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def class_verdict(errors: int, n: int, target: float) -> bool:
    """True if one-sided 95% Clopper-Pearson upper bound is <= target."""
    if n <= 0:
        return False
    return clopper_pearson_upper(errors, n) <= target


def min_sample(target: float) -> int:
    """The smallest sample that can support `target` with zero errors (one-sided 95%)."""
    n = 1
    while clopper_pearson_upper(0, n) > target:
        n += 1
    return n


def verdict_label(row: Mapping) -> str:
    """FAIL only when the errors themselves fail; a clean sample that is merely too small says so."""
    if not row.get("n"):
        return "NO LABELS"
    if row.get("passes"):
        return "PASS"
    if row.get("errors") == 0 and row["n"] < min_sample(row["target"]):
        return f"SAMPLE TOO SMALL (needs {min_sample(row['target'])})"
    return "FAIL"


def cohen_kappa(a: Sequence[str], b: Sequence[str]) -> float:
    """Cohen's kappa coefficient between two sequences of categorical ratings."""
    if len(a) != len(b):
        raise ValueError("Sequences must have the same length")
    n = len(a)
    if n == 0:
        return 1.0
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    ca = Counter(a)
    cb = Counter(b)
    cats = set(ca.keys()) | set(cb.keys())
    pe = sum((ca[c] / n) * (cb[c] / n) for c in cats)
    if math.isclose(pe, 1.0):
        return 1.0 if math.isclose(po, 1.0) else 0.0
    return (po - pe) / (1.0 - pe)


def percentiles(values: Sequence[float]) -> tuple[float | None, float | None]:
    """Return (median, p95) using linear interpolation, or (None, None) if empty."""
    if not values:
        return None, None
    s = sorted(float(v) for v in values)
    n = len(s)
    if n == 1:
        return s[0], s[0]

    def _interp(q: float) -> float:
        idx = q * (n - 1) / 100.0
        k = int(math.floor(idx))
        d = idx - k
        if k >= n - 1:
            return s[-1]
        return s[k] + d * (s[k + 1] - s[k])

    return _interp(50.0), _interp(95.0)


def _dist_dict(values: Sequence[float]) -> dict[str, float | int | None]:
    med, p95 = percentiles(values)
    return {
        "n": len(values),
        "median": med,
        "p95": p95,
    }


def build_report(session: Session, *, label: str, since: datetime | None, chat_usd_per_answer: float) -> dict:
    # 1. Documents = versions whose stored event is at or after since (all when None)
    stmt = select(VersionEvent).where(VersionEvent.stage == VersionStage.stored)
    if since is not None:
        stmt = stmt.where(VersionEvent.created_at >= since)
    stored_events = session.scalars(stmt).all()
    doc_version_ids = sorted({e.version_id for e in stored_events})
    doc_count = len(doc_version_ids)

    # 2. Events for in-scope versions
    if doc_version_ids:
        all_events_stmt = (
            select(VersionEvent)
            .where(VersionEvent.version_id.in_(doc_version_ids))
            .order_by(VersionEvent.created_at.asc())
        )
        if since is not None:
            all_events_stmt = all_events_stmt.where(VersionEvent.created_at >= since)
        all_events = session.scalars(all_events_stmt).all()
    else:
        all_events = []

    events_by_vid: dict[uuid.UUID, dict[VersionStage, VersionEvent]] = {}
    for ev in all_events:
        events_by_vid.setdefault(ev.version_id, {})[ev.stage] = ev

    parse_times: list[float] = []
    extract_times: list[float] = []
    verify_times: list[float] = []
    verify_work: list[float] = []
    index_times: list[float] = []
    cpu_seconds_list: list[float] = []
    extract_usd_list: list[float] = []
    extract_in_tokens: list[float] = []
    extract_out_tokens: list[float] = []
    index_usd_list: list[float] = []
    review_ready_times: list[float] = []
    searchable_times: list[float] = []

    page_grades_counter: Counter[str] = Counter()
    parsed_count = 0

    for vid in doc_version_ids:
        vevents = events_by_vid.get(vid, {})
        stored = vevents.get(VersionStage.stored)
        parsed = vevents.get(VersionStage.parsed)
        extracted = vevents.get(VersionStage.extracted)
        verified = vevents.get(VersionStage.verified)
        indexed = vevents.get(VersionStage.indexed)

        # A backfilled document was indexed before X1 and verified weeks later: its gaps between events are not stage
        # times. Only documents that went through the X1 order (verified before indexed) give wall-clock stage times.
        x1_order = bool(verified and indexed and verified.created_at < indexed.created_at)
        if verified:
            work_ms = sum(float(verified.detail.get(k) or 0) for k in ("ocr_ms", "vision_ms"))
            if work_ms:
                verify_work.append(work_ms / 1000)  # the stage's own OCR + vision time, valid for backfills too
        if not x1_order:
            stored = parsed_for_time = None
        else:
            parsed_for_time = parsed
        if stored and parsed_for_time:
            dt = (parsed.created_at - stored.created_at).total_seconds()
            if dt >= 0:
                parse_times.append(dt)
        if x1_order and parsed and extracted:
            dt = (extracted.created_at - parsed.created_at).total_seconds()
            if dt >= 0:
                extract_times.append(dt)
        if x1_order and extracted and verified:
            dt = (verified.created_at - extracted.created_at).total_seconds()
            if dt >= 0:
                verify_times.append(dt)
        if x1_order and verified and indexed:
            dt = (indexed.created_at - verified.created_at).total_seconds()
            if dt >= 0:
                index_times.append(dt)

        if parsed:
            parsed_count += 1
            if "cpu_seconds" in parsed.detail and parsed.detail["cpu_seconds"] is not None:
                cpu_seconds_list.append(float(parsed.detail["cpu_seconds"]))
            grades = parsed.detail.get("page_grades", {})
            if isinstance(grades, dict):
                for g in grades.values():
                    page_grades_counter[str(g)] += 1

        if extracted:
            if "cost_usd" in extracted.detail and extracted.detail["cost_usd"] is not None:
                extract_usd_list.append(float(extracted.detail["cost_usd"]))
            if "input_tokens" in extracted.detail and extracted.detail["input_tokens"] is not None:
                extract_in_tokens.append(float(extracted.detail["input_tokens"]))
            if "output_tokens" in extracted.detail and extracted.detail["output_tokens"] is not None:
                extract_out_tokens.append(float(extracted.detail["output_tokens"]))

        if indexed:
            chars = float(indexed.detail.get("embedding_chars", 0) or 0)
            cost = (chars / CHARS_PER_TOKEN) * float(config.EMBEDDING_PRICE_PER_MTOK) / 1e6
            index_usd_list.append(cost)

        # End to end times: counted ONLY for documents whose verified event precedes their indexed event
        stored = vevents.get(VersionStage.stored)
        if stored and verified and indexed:
            if verified.created_at < indexed.created_at:
                t_rr = (verified.created_at - stored.created_at).total_seconds()
                t_s = (indexed.created_at - stored.created_at).total_seconds()
                if t_rr >= 0:
                    review_ready_times.append(t_rr)
                if t_s >= 0:
                    searchable_times.append(t_s)

    # 3. Latest runs of each version
    latest_runs: dict[uuid.UUID, ExtractionRun] = {}
    for vid in doc_version_ids:
        r = session.scalars(
            select(ExtractionRun)
            .where(ExtractionRun.version_id == vid)
            .order_by(ExtractionRun.created_at.desc())
        ).first()
        if r is not None:
            latest_runs[vid] = r
    latest_run_ids = [r.id for r in latest_runs.values()]

    if latest_run_ids:
        all_extracted_fields = session.scalars(
            select(ExtractedField)
            .where(ExtractedField.run_id.in_(latest_run_ids))
            .order_by(ExtractedField.field_path.asc())
        ).all()
        all_verifications = session.scalars(
            select(FieldVerification)
            .where(FieldVerification.run_id.in_(latest_run_ids))
            .order_by(FieldVerification.id.asc())
        ).all()
        all_reviews = session.scalars(
            select(FieldReview)
            .where(FieldReview.run_id.in_(latest_run_ids))
        ).all()
        all_labels = session.scalars(
            select(FieldLabel)
            .where(FieldLabel.run_id.in_(latest_run_ids))
            .order_by(FieldLabel.created_at.asc())
        ).all()
    else:
        all_extracted_fields = []
        all_verifications = []
        all_reviews = []
        all_labels = []

    # Extraction confidence metrics
    routing_by_class: dict[str, dict[str, int]] = {
        cls: {"accepted": 0, "needs_review": 0} for cls in ("A", "B", "C")
    }
    grounded_count = 0
    total_extracted_fields = len(all_extracted_fields)
    validator_failures = 0

    for f in all_extracted_fields:
        if f.grounded:
            grounded_count += 1
        if f.validator_errors:
            validator_failures += len(f.validator_errors)
        cls = field_class(f.field_path)
        if cls in routing_by_class:
            if f.routing is FieldRouting.accepted:
                routing_by_class[cls]["accepted"] += 1
            else:
                routing_by_class[cls]["needs_review"] += 1

    grounded_pct = (grounded_count / total_extracted_fields) if total_extracted_fields else 1.0

    # Verification metrics
    verify_cost_by_run: dict[uuid.UUID, float] = {rid: 0.0 for rid in latest_run_ids}
    for v in all_verifications:
        if v.run_id in verify_cost_by_run:
            verify_cost_by_run[v.run_id] += float(v.cost_usd or 0)
    verify_usd_per_doc_list = list(verify_cost_by_run.values())

    layer_costs: dict[str, list[float]] = {}
    layer_latencies: dict[str, list[float]] = {}
    for v in all_verifications:
        layer_costs.setdefault(v.layer, []).append(float(v.cost_usd or 0))
        layer_latencies.setdefault(v.layer, []).append(float(v.latency_ms or 0))

    usd_per_field_by_layer = {
        layer: (sum(costs) / len(costs) if costs else 0.0)
        for layer, costs in layer_costs.items()
    }
    latency_ms_by_layer = {
        layer: _dist_dict(lats)
        for layer, lats in layer_latencies.items()
    }

    agreement: dict[str, dict[str, dict[str, int]]] = {
        c: {} for c in ("A", "B", "C")
    }
    for v in all_verifications:
        cls = field_class(v.field_path)
        cls_dict = agreement.setdefault(cls, {})
        layer_dict = cls_dict.setdefault(v.layer, {})
        layer_dict[v.outcome] = layer_dict.get(v.outcome, 0) + 1

    reviews_by_run_field: dict[tuple[uuid.UUID, str], FieldReview] = {
        (r.run_id, r.field_path): r for r in all_reviews
    }
    outcomes_by_run: dict[uuid.UUID, dict[str, dict[str, str]]] = {
        rid: dao.verification_outcomes(session, rid) for rid in latest_run_ids
    }

    needs_review_count = 0
    total_fields_status_count = 0
    for f in all_extracted_fields:
        total_fields_status_count += 1
        review = reviews_by_run_field.get((f.run_id, f.field_path))
        outcomes = outcomes_by_run.get(f.run_id, {})
        st = field_status(
            f.routing,
            None if review is None else review.decision,
            outcomes.get(verification_path(f.field_path), {}),
            f.field_path,
        )
        if st == "needs_review":
            needs_review_count += 1

    review_rate = (needs_review_count / total_fields_status_count) if total_fields_status_count else 0.0

    disagreed_run_paths = {
        (v.run_id, verification_path(v.field_path))
        for v in all_verifications
        if v.outcome == "disagree"
    }
    verifier_vs_human_fields = set()
    for rev in all_reviews:
        v_path = verification_path(rev.field_path)
        if (rev.run_id, v_path) in disagreed_run_paths:
            verifier_vs_human_fields.add((rev.run_id, v_path))
    verifier_vs_human = len(verifier_vs_human_fields)

    def machine_value(rid: uuid.UUID, fpath: str) -> object:
        """What the machine auto-accepted: the extracted value, whatever a person decided later. The sample is
        drawn from auto-accepted fields, so a later human correction must not hide the machine's error."""
        if fpath == "fee_tiers":
            bands = sorted((f for f in all_extracted_fields if f.run_id == rid and verification_path(f.field_path) == "fee_tiers"),
                           key=lambda f: dao._tier_index(f.field_path))
            return [f.value for f in bands] or None
        return next((f.value for f in all_extracted_fields if f.run_id == rid and f.field_path == fpath), None)

    labelled_report: dict[str, dict] = {}
    for cls in ("A", "B", "C"):
        class_labels = [l for l in all_labels if field_class(l.field_path) == cls]
        adj_labels = [l for l in class_labels if l.labeller == "adjudicated"]
        if adj_labels:
            gt_name = "adjudicated"
            selected = adj_labels
        else:
            human_labels = [l for l in class_labels if l.labeller.startswith("human:")]
            if human_labels:
                first_human = sorted(human_labels, key=lambda l: (l.created_at, l.labeller))[0].labeller
                gt_name = first_human
                selected = [l for l in human_labels if l.labeller == first_human]
            else:
                judge_labels = [l for l in class_labels if l.labeller.startswith("judge:")]
                if judge_labels:
                    first_judge = sorted(judge_labels, key=lambda l: (l.created_at, l.labeller))[0].labeller
                    gt_name = first_judge
                    selected = [l for l in judge_labels if l.labeller == first_judge]
                else:
                    gt_name = None
                    selected = []

        n = len(selected)
        errors = 0
        for l in selected:
            cmp = compare_field(l.field_path, machine_value(l.run_id, l.field_path), l.label_value)
            if cmp.outcome != "agree":
                errors += 1

        target = (A_TIGHT if n >= 300 else TARGETS["A"]) if cls == "A" else TARGETS[cls]
        upper_bound = clopper_pearson_upper(errors, n) if n > 0 else None
        passes = class_verdict(errors, n, target) if n > 0 else False

        labelled_report[cls] = {
            "n": n,
            "errors": errors,
            "upper_bound": upper_bound,
            "target": target,
            "passes": passes,
            "ground_truth": gt_name,
        }

    stages = {
        "parse_redact": {
            "time_seconds": _dist_dict(parse_times),
            "cpu_seconds": _dist_dict(cpu_seconds_list),
            "confidence": {
                "parse_success_rate": (parsed_count / doc_count) if doc_count else 1.0,
                "page_grades": dict(page_grades_counter),
            },
        },
        "extract": {
            "time_seconds": _dist_dict(extract_times),
            "usd_per_doc": _dist_dict(extract_usd_list),
            "tokens": {
                "input": percentiles(extract_in_tokens)[0],
                "output": percentiles(extract_out_tokens)[0],
            },
            "confidence": {
                "grounded_pct": grounded_pct,
                "validator_failures": validator_failures,
                "routing_by_class": routing_by_class,
            },
        },
        "verify": {
            "time_seconds": _dist_dict(verify_times),
            "work_seconds": _dist_dict(verify_work),
            "usd_per_doc": _dist_dict(verify_usd_per_doc_list),
            "usd_per_field_by_layer": usd_per_field_by_layer,
            "latency_ms_by_layer": latency_ms_by_layer,
            "confidence": {
                "agreement": agreement,
                "review_rate": review_rate,
                "labelled": labelled_report,
                "verifier_vs_human": verifier_vs_human,
            },
        },
        "index": {
            "time_seconds": _dist_dict(index_times),
            "usd_per_doc": _dist_dict(index_usd_list),
            "confidence": "n/a (retrieval quality is the golden gate's job)",
        },
    }

    end_to_end = {
        "review_ready_seconds": _dist_dict(review_ready_times),
        "searchable_seconds": _dist_dict(searchable_times),
    }

    medians = {name: stages[name]["usd_per_doc"]["median"] for name in ("extract", "verify", "index")}
    # A stage with no measured cost (events older than token logging) makes the total unknown, never smaller.
    missing = [name for name, value in medians.items() if not value]
    doc_100k_usd = None if missing else 100_000 * sum(medians.values())
    dau_usd_per_day = 100_000 * TURNS_PER_USER_PER_DAY * chat_usd_per_answer

    projection_100k = {
        "documents": {
            "usd": doc_100k_usd,
            "missing": missing,
            "prices": {
                config.EXTRACTION_MODEL: (float(config.EXTRACTION_PRICE_PER_MTOK[0]), float(config.EXTRACTION_PRICE_PER_MTOK[1])),
                config.VERIFIER_MODEL: (float(config.VERIFIER_PRICE_PER_MTOK[0]), float(config.VERIFIER_PRICE_PER_MTOK[1])),
                config.EMBEDDING_MODEL: (float(config.EMBEDDING_PRICE_PER_MTOK), 0.0),
            },
            "assumptions": [
                "list prices",
                f"medians of {doc_count} documents",
                "local parse CPU not priced",
            ],
        },
        "daily_active_users": {
            "turns_per_user_per_day": TURNS_PER_USER_PER_DAY,
            "usd_per_answer": float(chat_usd_per_answer),
            "usd_per_day": float(dau_usd_per_day),
            "assumptions": [
                "100,000 daily active users",
                f"{TURNS_PER_USER_PER_DAY} turns per user per day",
                f"chat cost of ${chat_usd_per_answer:.4f} per answer",
                "list prices",
            ],
        },
    }

    return {
        "label": label,
        "since": since.isoformat() if since is not None else None,
        "documents": doc_count,
        "stages": stages,
        "end_to_end": end_to_end,
        "projection_100k": projection_100k,
    }


def _fmt_usd(val: float | None) -> str:
    if val is None:
        return "—"
    if val == 0:
        return "$0.00"
    if val < 0.0001:
        return f"${val:.6f}"
    if val < 0.01:
        return f"${val:.4f}"
    return f"${val:.4f}"


def _fmt_time(d: dict) -> str:
    med = d.get("median")
    p95 = d.get("p95")
    if med is None:
        return "—"
    if p95 is None:
        return f"{med:.2f}s"
    return f"{med:.2f}s (p95 {p95:.2f}s)"


def render_markdown(report: dict) -> str:
    stages = report.get("stages", {})
    e2e = report.get("end_to_end", {})
    proj = report.get("projection_100k", {})

    pr = stages.get("parse_redact", {})
    ex = stages.get("extract", {})
    vr = stages.get("verify", {})
    ix = stages.get("index", {})

    pr_cost = (
        f"{pr.get('cpu_seconds', {}).get('median', 0.0):.1f}s CPU"
        if pr.get("cpu_seconds", {}).get("median") is not None
        else "—"
    )
    ex_cost = _fmt_usd(ex.get("usd_per_doc", {}).get("median"))
    vr_cost = _fmt_usd(vr.get("usd_per_doc", {}).get("median"))
    ix_cost = _fmt_usd(ix.get("usd_per_doc", {}).get("median"))

    pr_time = _fmt_time(pr.get("time_seconds", {}))
    ex_time = _fmt_time(ex.get("time_seconds", {}))
    vr_time = _fmt_time(vr.get("time_seconds", {}))
    if not vr.get("time_seconds", {}).get("n") and vr.get("work_seconds", {}).get("n"):
        vr_time = f"work {_fmt_time(vr['work_seconds'])} (OCR + vision; backfill, no wall time)"
    ix_time = _fmt_time(ix.get("time_seconds", {}))

    pr_conf = f"parse success {pr.get('confidence', {}).get('parse_success_rate', 0.0) * 100:.1f}%"
    ex_conf = f"grounded {ex.get('confidence', {}).get('grounded_pct', 0.0) * 100:.1f}%, failures {ex.get('confidence', {}).get('validator_failures', 0)}"
    vr_conf = f"review rate {vr.get('confidence', {}).get('review_rate', 0.0) * 100:.1f}%, verifier vs human {vr.get('confidence', {}).get('verifier_vs_human', 0)}"
    ix_conf = str(ix.get("confidence", "n/a"))

    rr_time = _fmt_time(e2e.get("review_ready_seconds", {}))
    search_time = _fmt_time(e2e.get("searchable_seconds", {}))
    e2e_time = f"review-ready {rr_time}, searchable {search_time}"

    lines = [
        f"# X1 Per-Stage Report: {report.get('label', '')}",
        "",
        "Costs are list prices.",
        "",
        "| Stage | Cost per document | Time per document | Confidence |",
        "|---|---|---|---|",
        f"| parse and redact | {pr_cost} | {pr_time} | {pr_conf} |",
        f"| extract | {ex_cost} | {ex_time} | {ex_conf} |",
        f"| verify | {vr_cost} | {vr_time} | {vr_conf} |",
        f"| index | {ix_cost} | {ix_time} | {ix_conf} |",
        f"| end to end | — | {e2e_time} | — |",
        "",
        "## Labelled Error Rates (one-sided 95% Clopper-Pearson)",
        "",
        "| Class | Sample (n) | Errors | Upper Bound | Target | Verdict | Ground Truth |",
        "|---|---|---|---|---|---|---|",
    ]

    labelled = vr.get("confidence", {}).get("labelled", {})
    for cls in ("A", "B", "C"):
        row = labelled.get(cls, {})
        n = row.get("n", 0)
        errs = row.get("errors", 0)
        ub = row.get("upper_bound")
        ub_str = f"{ub * 100:.2f}%" if ub is not None else "—"
        tgt = row.get("target")
        tgt_str = f"{tgt * 100:.1f}%" if tgt is not None else "—"
        verdict = verdict_label(row)
        gt = row.get("ground_truth") or "—"
        lines.append(f"| {cls} | {n} | {errs} | {ub_str} | {tgt_str} | {verdict} | {gt} |")

    lines.extend([
        "",
        "## 100k Projections",
        "",
        "### 100k Documents Ingestion",
    ])
    doc_proj = proj.get("documents", {})
    if doc_proj.get("usd") is None:
        lines.append(f"- **Estimated Cost:** not measured: no cost recorded for {', '.join(doc_proj.get('missing', []))}"
                     " on these documents (their events predate token logging)")
    else:
        lines.append(f"- **Estimated Cost:** ${_fmt_usd(doc_proj.get('usd'))[1:]}")
    lines.append("- **Prices:**")
    for m, p in doc_proj.get("prices", {}).items():
        if isinstance(p, (list, tuple)):
            lines.append(f"  - `{m}`: ${p[0]:.2f} in / ${p[1]:.2f} out per 1M tokens")
        else:
            lines.append(f"  - `{m}`: ${p:.4f} per 1M tokens")
    lines.append("- **Assumptions:**")
    for a in doc_proj.get("assumptions", []):
        lines.append(f"  - {a}")

    lines.extend([
        "",
        "### 100k Daily Active Users",
    ])
    dau_proj = proj.get("daily_active_users", {})
    lines.append(f"- **Estimated Cost per Day:** ${_fmt_usd(dau_proj.get('usd_per_day'))[1:]}")
    lines.append(f"- **Turns per User per Day:** {dau_proj.get('turns_per_user_per_day', TURNS_PER_USER_PER_DAY)}")
    lines.append(f"- **Cost per Answer:** ${_fmt_usd(dau_proj.get('usd_per_answer'))[1:]}")
    lines.append("- **Assumptions:**")
    for a in dau_proj.get("assumptions", []):
        lines.append(f"  - {a}")

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True, help="report label name")
    parser.add_argument("--since", default=None, help="ISO-date filter for stored events")
    parser.add_argument("--chat-usd-per-answer", type=float, default=None, help="chat cost per answer in USD")
    args = parser.parse_args()

    chat_usd = args.chat_usd_per_answer
    reports_dir = BACKEND_DIR / "reports"
    if chat_usd is None:
        cost_files = sorted(reports_dir.glob("cost-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for cf in cost_files:
            try:
                data = json.loads(cf.read_text())
                if "usd_per_answer" in data:
                    chat_usd = float(data["usd_per_answer"])
                    break
            except Exception:
                continue
        if chat_usd is None:
            parser.error("--chat-usd-per-answer is required when no cost-*.json with usd_per_answer is found")

    since_dt = None
    if args.since:
        since_dt = datetime.fromisoformat(args.since)
        if since_dt.tzinfo is None:
            since_dt = since_dt.replace(tzinfo=timezone.utc)

    with SessionLocal() as session:
        report = build_report(session, label=args.label, since=since_dt, chat_usd_per_answer=chat_usd)

    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / f"x1-{args.label}.json"
    md_path = reports_dir / f"x1-{args.label}.md"

    json_path.write_text(json.dumps(report, indent=2))
    md_path.write_text(render_markdown(report))
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()
