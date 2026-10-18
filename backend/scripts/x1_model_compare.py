"""Extraction-model comparison on labelled documents (X1 section 12).

Candidate extractors run the production prompt and schema on owner-adjudicated labelled
documents; their outputs are written to a report file and never touch extraction_runs or
extracted_fields.

This is a paid run that the owner approves first before executing against external providers.

Example candidate commands:
  Gemini 3.5 Flash-Lite:
    $PYDEV/bin/python scripts/x1_model_compare.py --model gemini-2.5-flash-lite --base-url https://generativelanguage.googleapis.com/v1beta/openai/ --api-key-env GEMINI_API_KEY --price-in 0.075 --price-out 0.30

  gpt-5-mini:
    $PYDEV/bin/python scripts/x1_model_compare.py --model gpt-5-mini --base-url https://api.openai.com/v1 --api-key-env OPENAI_API_KEY --reasoning-effort minimal --no-temperature --price-in 0.25 --price-out 2.00

  gpt-4.1-mini:
    $PYDEV/bin/python scripts/x1_model_compare.py --model gpt-4.1-mini --base-url https://api.openai.com/v1 --api-key-env OPENAI_API_KEY --price-in 0.40 --price-out 1.60

  Baseline (current extractor runs):
    $PYDEV/bin/python scripts/x1_model_compare.py --baseline
"""
import argparse
from collections.abc import Mapping, Sequence
import concurrent.futures
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys
import time
from typing import Any
import uuid

# Ensure backend root is on sys.path
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from dotenv import dotenv_values  # noqa: E402
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import config  # noqa: E402
from app.contracts import dao, extract, fields  # noqa: E402
from app.contracts.agree import compare_field  # noqa: E402
from app.contracts.fields import ElementRef  # noqa: E402
from app.contracts.models import ExtractionRun, FieldLabel  # noqa: E402
from app.contracts.terms import field_class  # noqa: E402
from app.documents import dao as documents_dao  # noqa: E402
from app.ledger.db import SessionLocal  # noqa: E402

_INDEXED_TIER = re.compile(r"^fee_tiers\[(\d+)\]$")


def labelled_version_ids(session: Session) -> list[uuid.UUID]:
    """Distinct, sorted document version IDs with owner-adjudicated labels."""
    stmt = (
        select(ExtractionRun.version_id)
        .join(FieldLabel, FieldLabel.run_id == ExtractionRun.id)
        .where(FieldLabel.labeller == "adjudicated")
        .distinct()
        .order_by(ExtractionRun.version_id)
    )
    return list(session.scalars(stmt).all())


def load_labels(session: Session) -> list[tuple[uuid.UUID, str, str, object]]:
    """Load owner-adjudicated ground truth labels as (version_id, path, class, value)."""
    stmt = (
        select(ExtractionRun.version_id, FieldLabel.field_path, FieldLabel.label_value)
        .join(FieldLabel, FieldLabel.run_id == ExtractionRun.id)
        .where(FieldLabel.labeller == "adjudicated")
        .order_by(ExtractionRun.version_id, FieldLabel.field_path)
    )
    rows = session.execute(stmt).all()
    return [(v_id, path, field_class(path), val) for v_id, path, val in rows]


def _evaluate_one(
    v_id: uuid.UUID,
    elements: list,
    detail: dict,
    chat_model: BaseChatModel,
) -> dict:
    t0 = time.perf_counter()
    try:
        text = extract.render_input(elements)
        terms, tokens = extract.call_model(chat_model, text)
        refs = {
            f"E{e.ordinal}": ElementRef(e.id, e.text_redacted, e.page_start, e.page_end)
            for e in elements
        }
        page_grades = detail.get("page_grades", {}) if isinstance(detail, dict) else {}
        results = fields.evaluate_terms(terms, refs, page_grades)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        field_dicts = [
            {
                "field_path": r.field_path,
                "value": r.value,
                "routing": r.routing.value if hasattr(r.routing, "value") else str(r.routing),
            }
            for r in results
        ]
        return {
            "version_id": str(v_id),
            "error": None,
            "input_tokens": int(tokens.get("input_tokens") or 0),
            "output_tokens": int(tokens.get("output_tokens") or 0),
            "latency_ms": latency_ms,
            "fields": field_dicts,
        }
    except Exception as exc:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        err_msg = str(exc)
        if not err_msg:
            err_msg = exc.__class__.__name__
        return {
            "version_id": str(v_id),
            "error": err_msg[:500],
            "input_tokens": 0,
            "output_tokens": 0,
            "latency_ms": latency_ms,
            "fields": [],
        }


def run_candidate(
    session: Session,
    *,
    chat_model: BaseChatModel,
    version_ids: Sequence[uuid.UUID],
    concurrency: int = 8,
) -> list[dict]:
    """Run a candidate model across document versions outside the session."""
    if not version_ids:
        return []

    items = []
    for v_id in version_ids:
        elements = documents_dao.list_elements(session, v_id)
        detail = documents_dao.parsed_detail(session, v_id)
        items.append((v_id, elements, detail))

    workers = max(1, concurrency)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(_evaluate_one, v_id, elements, detail, chat_model)
            for v_id, elements, detail in items
        ]
        return [f.result() for f in futures]


def baseline_outputs(session: Session, version_ids: Sequence[uuid.UUID]) -> list[dict]:
    """Collect extraction outputs from each version's latest existing run."""
    outputs: list[dict] = []
    for v_id in version_ids:
        run = dao.latest_run(session, v_id)
        if run is None:
            outputs.append({
                "version_id": str(v_id),
                "error": "no extraction run found",
                "input_tokens": 0,
                "output_tokens": 0,
                "latency_ms": 0,
                "fields": [],
            })
            continue

        extracted = dao.run_fields(session, run.id)
        field_dicts = [
            {
                "field_path": f.field_path,
                "value": f.value,
                "routing": f.routing.value if hasattr(f.routing, "value") else str(f.routing),
            }
            for f in extracted
        ]
        outputs.append({
            "version_id": str(v_id),
            "error": None,
            "input_tokens": 0,
            "output_tokens": 0,
            "latency_ms": 0,
            "fields": field_dicts,
        })
    return outputs


def score(
    outputs: Sequence[Mapping],
    labels: Sequence[tuple[uuid.UUID, str, str, object]],
) -> dict:
    """Score outputs against ground truth labels."""
    output_by_version = {str(o.get("version_id")): o for o in outputs}

    classes = sorted({label[2] for label in labels})
    class_stats = {cls: {"n": 0, "correct": 0} for cls in classes}
    total_n = 0
    total_correct = 0

    for v_id, path, cls, label_value in labels:
        total_n += 1
        class_stats[cls]["n"] += 1

        out = output_by_version.get(str(v_id))
        if out is None or out.get("error") is not None:
            continue

        fields_list = out.get("fields") or []
        if path == "fee_tiers":
            tier_items: list[tuple[int, object]] = []
            for f in fields_list:
                m = _INDEXED_TIER.match(f.get("field_path", ""))
                if m:
                    tier_items.append((int(m.group(1)), f.get("value")))
            if tier_items:
                tier_items.sort(key=lambda t: t[0])
                machine_value = [val for _, val in tier_items]
            else:
                direct = next((f for f in fields_list if f.get("field_path") == "fee_tiers"), None)
                machine_value = direct.get("value") if direct is not None else None
        else:
            direct = next((f for f in fields_list if f.get("field_path") == path), None)
            machine_value = direct.get("value") if direct is not None else None

        try:
            comparison = compare_field(path, machine_value, label_value)
            if comparison.outcome == "agree":
                class_stats[cls]["correct"] += 1
                total_correct += 1
        except Exception:
            pass

    by_class = {
        cls: {
            "n": stats["n"],
            "correct": stats["correct"],
            "accuracy": (stats["correct"] / stats["n"]) if stats["n"] > 0 else 0.0,
        }
        for cls, stats in class_stats.items()
    }
    overall = {
        "n": total_n,
        "correct": total_correct,
        "accuracy": (total_correct / total_n) if total_n > 0 else 0.0,
    }

    successful_outputs = [o for o in outputs if o.get("error") is None]
    all_successful_fields = [f for o in successful_outputs for f in (o.get("fields") or [])]
    total_fields_count = len(all_successful_fields)
    needs_review_count = sum(1 for f in all_successful_fields if f.get("routing") == "needs_review")
    review_rate = (needs_review_count / total_fields_count) if total_fields_count > 0 else 0.0

    failed_documents = sum(1 for o in outputs if o.get("error") is not None)

    return {
        "by_class": by_class,
        "overall": overall,
        "review_rate": review_rate,
        "failed_documents": failed_documents,
    }


def usd(input_tokens: int, output_tokens: int, price_per_mtok: tuple[float, float]) -> float:
    """Calculate USD spend from tokens and list prices per million tokens."""
    price_in, price_out = price_per_mtok
    return (input_tokens * price_in + output_tokens * price_out) / 1e6


def main() -> None:
    parser = argparse.ArgumentParser(description="X1 extraction-model comparison against ground truth labels.")
    parser.add_argument("--model", type=str, default=None, help="Candidate model identifier.")
    parser.add_argument("--base-url", type=str, default=None, help="OpenAI-compatible base URL.")
    parser.add_argument("--api-key-env", type=str, default=None, help="Environment variable name for API key.")
    parser.add_argument("--env-file", type=str, default=None, help="Env file path relative to backend/.")
    parser.add_argument("--reasoning-effort", type=str, default=None, help="Reasoning effort (e.g. minimal).")
    parser.add_argument("--no-temperature", action="store_true", help="Omit temperature parameter.")
    parser.add_argument("--price-in", type=float, default=0.0, help="Input token price per million tokens in USD.")
    parser.add_argument("--price-out", type=float, default=0.0, help="Output token price per million tokens in USD.")
    parser.add_argument("--concurrency", type=int, default=8, help="Model call concurrency.")
    parser.add_argument("--limit", type=int, default=None, help="Limit to first N labelled versions.")
    parser.add_argument("--baseline", action="store_true", help="Score current extractor runs without calling models.")
    args = parser.parse_args()

    if args.baseline:
        model_name = args.model or "baseline"
        base_url = args.base_url or ""
        prices = {"in": args.price_in, "out": args.price_out}
    else:
        if not args.model:
            parser.error("--model is required unless --baseline is set")
        if not args.api_key_env:
            parser.error("--api-key-env is required unless --baseline is set")
        model_name = args.model
        base_url = args.base_url or ""
        prices = {"in": args.price_in, "out": args.price_out}

    key = None
    if not args.baseline:
        key = os.environ.get(args.api_key_env)
        if not key:
            target_env = BACKEND_DIR / (args.env_file or ".env")
            if target_env.is_file():
                env_vals = dotenv_values(target_env)
                key = env_vals.get(args.api_key_env)
        if not key:
            raise RuntimeError(f"API key environment variable {args.api_key_env} is not set")

    with SessionLocal() as session:
        version_ids = labelled_version_ids(session)
        if args.limit is not None and args.limit > 0:
            version_ids = version_ids[:args.limit]

        all_labels = load_labels(session)
        target_vids = set(version_ids)
        labels = [lbl for lbl in all_labels if lbl[0] in target_vids]

        if args.baseline:
            outputs = baseline_outputs(session, version_ids)
        else:
            chat_kwargs: dict[str, Any] = {
                "model": model_name,
                "api_key": key,
                "timeout": config.EXTRACTION_TIMEOUT_SECONDS,
                "max_retries": config.LLM_MAX_RETRIES,
            }
            if base_url:
                chat_kwargs["base_url"] = base_url
            if not args.no_temperature:
                chat_kwargs["temperature"] = 0
            if args.reasoning_effort:
                chat_kwargs["reasoning_effort"] = args.reasoning_effort

            chat_model = ChatOpenAI(**chat_kwargs)
            outputs = run_candidate(
                session,
                chat_model=chat_model,
                version_ids=version_ids,
                concurrency=args.concurrency,
            )

    score_result = score(outputs, labels)

    total_in = sum(o.get("input_tokens", 0) for o in outputs)
    total_out = sum(o.get("output_tokens", 0) for o in outputs)
    total_usd = usd(total_in, total_out, (args.price_in, args.price_out))

    latencies = [o.get("latency_ms", 0) for o in outputs]
    if latencies:
        sorted_lats = sorted(latencies)
        median_lat = int(round(statistics.median(sorted_lats)))
        p95_idx = min(len(sorted_lats) - 1, max(0, math.ceil(0.95 * len(sorted_lats)) - 1))
        p95_lat = sorted_lats[p95_idx]
    else:
        median_lat = 0
        p95_lat = 0

    report_data = {
        "model": model_name,
        "base_url": base_url,
        "prices": prices,
        "documents": len(outputs),
        "input_tokens": total_in,
        "output_tokens": total_out,
        "usd": total_usd,
        "latency_ms": {
            "median": median_lat,
            "p95": p95_lat,
        },
        "score": score_result,
        "outputs": outputs,
    }

    reports_dir = BACKEND_DIR / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_filename = "x1-model-baseline.json" if args.baseline else f"x1-model-{model_name.replace('/', '_')}.json"
    report_path = reports_dir / report_filename
    report_path.write_text(json.dumps(report_data, indent=2, default=str))

    classes_summary = ", ".join(
        f"{cls}: {stats['accuracy']:.1%} ({stats['correct']}/{stats['n']})"
        for cls, stats in score_result["by_class"].items()
    )
    print(
        f"[{model_name}] classes: [{classes_summary}] | review rate: {score_result['review_rate']:.1%} | "
        f"usd: ${total_usd:.4f} | failed documents: {score_result['failed_documents']}"
    )


if __name__ == "__main__":
    main()
