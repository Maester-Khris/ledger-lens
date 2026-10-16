"""N1: LLM cost per answer and per session from Langfuse (the price table applies the model's list price).
Run from backend/:  $PYDEV/bin/python scripts/cost_report.py <from ISO time> <to ISO time> [tag, default chat]
Reads backend/.env for the Langfuse keys; writes reports/cost-<from date>.json and prints the summary.
One trace = one chat turn (the graph run); its session is the chat session (one golden case, setup turns included)."""
import json
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import httpx
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")
HOST = os.environ.get("LANGFUSE_BASE_URL") or os.environ["LANGFUSE_HOST"]
AUTH = (os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])


def pages(path: str, params: dict) -> list[dict]:
    rows, page = [], 1
    while True:
        body = httpx.get(f"{HOST}/api/public/{path}", params=params | {"page": page, "limit": 100}, auth=AUTH, timeout=60).json()
        rows += body["data"]
        if page >= body["meta"]["totalPages"]:
            return rows
        page += 1


def p95(values: list[float]) -> float:
    return sorted(values)[max(0, int(0.95 * len(values)) - 1)]


def spread(values: list[float]) -> dict:
    return {"n": len(values), "median": statistics.median(values), "p95": p95(values), "max": max(values)}


def prompt_usage(call: dict) -> tuple[int, int]:
    """(cached, all) prompt tokens of one generation. Langfuse names usage keys by the SDK: every key starting with
    'input' counts prompt tokens, and those naming a cache are the cached part."""
    usage = call.get("usageDetails") or {}
    cached = sum(v for k, v in usage.items() if k.startswith("input") and "cache" in k)
    return cached, sum(v for k, v in usage.items() if k.startswith("input"))


def main() -> None:
    start, end, tag = sys.argv[1], sys.argv[2], (sys.argv[3] if len(sys.argv) > 3 else "chat")
    traces = {t["id"]: t for t in pages("traces", {"fromTimestamp": start, "toTimestamp": end, "tags": tag})}
    window = {"fromStartTime": start, "toStartTime": end}
    observations = [o for o in pages("observations", window) if o["traceId"] in traces]
    names = {o["id"]: o["name"] for o in observations}
    calls = [o for o in observations if o["type"] == "GENERATION"]

    per_turn, steps, by_node = defaultdict(float), defaultdict(int), defaultdict(list)
    for call in calls:
        cost = call.get("calculatedTotalCost") or 0.0
        per_turn[call["traceId"]] += cost
        steps[call["traceId"]] += 1
        by_node[names.get(call.get("parentObservationId"), "unknown")].append(cost)
    per_session = defaultdict(float)
    for trace_id, cost in per_turn.items():
        per_session[traces[trace_id].get("sessionId")] += cost
    unpriced = sum(1 for c in calls if not c.get("calculatedTotalCost"))

    summary = {
        "window": [start, end], "tag": tag, "models": sorted({c.get("model") for c in calls}),
        "turns": len(per_turn), "sessions": len(per_session), "llm_calls": len(calls), "calls_without_price": unpriced,
        "total_usd": sum(per_turn.values()),
        "prompt_tokens": sum(prompt_usage(c)[1] for c in calls),
        "cached_prompt_tokens": sum(prompt_usage(c)[0] for c in calls),
        "cache_hit_rate": sum(prompt_usage(c)[0] for c in calls) / max(1, sum(prompt_usage(c)[1] for c in calls)),
        "usd_per_turn": spread(list(per_turn.values())),
        "usd_per_session": spread(list(per_session.values())),
        "llm_calls_per_turn": spread([float(n) for n in steps.values()]),
        "usd_by_step": {node: {"calls": len(costs), "total": sum(costs), "median": statistics.median(costs)}
                        for node, costs in sorted(by_node.items(), key=lambda kv: -sum(kv[1]))},
        "limit": "golden-set questions (curated, not user traffic); list prices from the Langfuse model table; local run",
    }
    out = BACKEND_DIR / "reports" / f"cost-{start[:10]}.json"
    out.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2), f"\nwritten {out.relative_to(BACKEND_DIR)}")


if __name__ == "__main__":
    main()
