"""Gated final-run evaluation runner over the assembled evaluation key.

Each turn calls the deployed `gpt-4.1` configuration, so this stage enforces a hard `--yes` cost gate before creating
the runtime, checkpoints every completed case for crash- and rate-limit-resumability, and reads text/citations from the
stored `chat_turns` row rather than the revealed SSE event so no unredacted PII ever enters evaluation logs.
"""
import argparse
import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import time
from typing import Any
import uuid

from app import config
from app.assistant.citations import numbers_in
from app.assistant.dao import find_turn
from app.assistant.graph import eval_config_hash
from app.assistant.runtime import get_runtime
from app.assistant.service import run_turn
from app.ledger.db import SessionLocal
from app.ledger.types import DEMO_TENANT_ID
from scripts.evalkit.cases import Case, read_cases
from scripts.evalkit.checkpoint import Checkpoint, summary_line

PER_TURN_USD: float = 0.011
PAUSE_SECONDS: float = float(os.environ.get("EVAL_PAUSE_SECONDS", "5"))
RETRY_WAIT_SECONDS: float = 65.0
EVENT_FOR: dict[str, str] = {"answer": "answer", "refuse": "refused", "clarify": "clarify"}
CITATION_KEYS: tuple[str, ...] = ("id", "quote", "page", "document_id")


@dataclass
class Reply:
    """Outcome of a single evaluation turn, pairing the final stream event with the stored redacted DB turn."""

    event: str
    data: dict[str, Any]
    turn: dict[str, Any] | None


def estimate_usd(n_cases: int, per_turn: float = PER_TURN_USD) -> float:
    """Estimate list-price OpenAI spend for `n_cases` chat turns before any paid call is made."""
    return n_cases * per_turn


def behaviour_ok(case: Case, event: str) -> bool:
    """Check whether the turn's terminal event matches the case's expected behaviour.

    For `underspecified` and `nonsense` cases, either a clarifying question or a refusal is acceptable, matching the
    golden runner.
    """
    if case.category in ("underspecified", "nonsense"):
        return event in ("clarify", "refused")
    return event == EVENT_FOR[case.expect]


def _normalise_number(value: str) -> str:
    """Normalise a numeric string to canonical fixed-point form for comparison with `numbers_in`."""
    return format(Decimal(value).normalize(), "f")


def answer_row(case: Case, reply: Reply, seconds: float, retried: bool) -> dict[str, Any]:
    """Build one checkpointed evaluation row using redacted text and quotes from the stored turn when present."""
    turn = reply.turn
    if turn is not None:
        text = turn.get("answer_redacted") or ""
        raw_citations = turn.get("citations") or []
        citations = [
            {k: c.get(k) for k in CITATION_KEYS}
            for c in raw_citations
            if isinstance(c, dict)
        ]
        retrieved = [
            item["id"]
            for item in (turn.get("retrieved") or [])
            if isinstance(item, dict) and "id" in item
        ]
        input_tokens = int(turn.get("input_tokens", 0) or 0)
        output_tokens = int(turn.get("output_tokens", 0) or 0)
    else:
        text = str(reply.data.get("text", "") or "")
        citations = []
        retrieved = []
        input_tokens = 0
        output_tokens = 0

    citation_hit = not (case.expect == "answer" and case.page is not None) or any(
        c.get("page") == case.page for c in citations
    )
    found_numbers = numbers_in(text)
    numbers_ok = {_normalise_number(n) for n in case.expect_numbers} <= found_numbers

    return {
        "case_id": case.id,
        "event": reply.event,
        "text": text,
        "citations": citations,
        "retrieved": retrieved,
        "confidence": reply.data.get("confidence"),
        "seconds": seconds,
        "retried": retried,
        "behaviour_ok": behaviour_ok(case, reply.event),
        "citation_hit": citation_hit,
        "numbers_ok": numbers_ok,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def run_cases(
    cases: Sequence[Case],
    ask: Callable[[Case], Reply],
    checkpoint: Checkpoint,
    *,
    pause: float = PAUSE_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, int]:
    """Run all uncheckpointed cases with inter-turn pacing and one 65-second retry on provider error."""
    done_ids = checkpoint.done()
    run_count = 0
    skipped = 0
    errors = 0

    for case in cases:
        if case.id in done_ids:
            skipped += 1
            continue
        if run_count > 0 and pause:
            sleep(pause)

        started = time.perf_counter()
        retried = False
        reply = ask(case)
        if reply.event == "error":
            retried = True
            sleep(65)
            reply = ask(case)

        seconds = round(time.perf_counter() - started, 2)
        row = answer_row(case, reply, seconds, retried)
        checkpoint.append(row)
        run_count += 1
        if row["event"] == "error":
            errors += 1

    return {
        "run": run_count,
        "skipped": skipped,
        "errors": errors,
    }


def load_key(key_dir: Path) -> list[Case]:
    """Load the assembled evaluation key cases from `<key_dir>/key.jsonl`."""
    return read_cases(Path(key_dir) / "key.jsonl")


def make_ask(run_id: str = "run") -> Callable[[Case], Reply]:
    """Build a case runner that executes `run_turn` against the demo tenant and fetches the redacted `ChatTurn` row."""
    runtime = get_runtime()
    hmac_key = config.require("PII_HMAC_KEY")
    vault_key = config.require("PII_VAULT_KEY")

    def _ask(case: Case) -> Reply:
        async def _consume() -> list:
            return [
                event
                async for event in run_turn(
                    session_factory=SessionLocal,
                    runtime=runtime,
                    tenant_id=DEMO_TENANT_ID,
                    session_id=f"evalfinal-{run_id}-{case.id}",
                    message=case.question,
                    hmac_key=hmac_key,
                    vault_key=vault_key,
                )
            ]

        events = asyncio.run(_consume())
        if not events:
            return Reply("error", {}, None)
        final = events[-1]
        if final.type not in ("answer", "refused", "clarify"):
            return Reply("error", final.data, None)

        turn_id = final.data.get("turn_id")
        turn_dict: dict[str, Any] | None = None
        if turn_id:
            with SessionLocal() as session:
                stored = find_turn(session, DEMO_TENANT_ID, uuid.UUID(str(turn_id)))
                if stored is not None:
                    turn_dict = {
                        "answer_redacted": stored.answer_redacted,
                        "citations": list(stored.citations or []),
                        "retrieved": list(stored.retrieved or []),
                        "input_tokens": stored.input_tokens,
                        "output_tokens": stored.output_tokens,
                    }
        return Reply(final.type, final.data, turn_dict)

    return _ask


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entry point: print the spend estimate, require `--yes`, run uncheckpointed cases, and write `answers.jsonl`."""
    parser = argparse.ArgumentParser(description="Run the gated final chat evaluation.")
    parser.add_argument("--key", type=Path, required=True, help="Directory holding key.jsonl.")
    parser.add_argument("--run", type=str, required=True, help="Unique identifier for this evaluation run.")
    parser.add_argument("--yes", action="store_true", help="Confirm paid OpenAI chat calls.")
    args = parser.parse_args(argv)

    key_dir: Path = args.key
    cases = load_key(key_dir)
    out_dir = Path("reports/eval-final") / args.run
    checkpoint = Checkpoint(out_dir / "answers.jsonl", key="case_id")

    done_ids = checkpoint.done()
    n_pending = sum(1 for c in cases if c.id not in done_ids)
    est = estimate_usd(n_pending)
    print(f"Estimate: {n_pending} cases, about ${est:.2f} at list price (gpt-4.1)")
    if not args.yes:
        print("Re-run with --yes after checking your OpenAI credit.")
        raise SystemExit(2)

    out_dir.mkdir(parents=True, exist_ok=True)
    run_meta_path = out_dir / "run.json"
    if not run_meta_path.exists():
        run_meta_path.write_text(
            json.dumps(
                {
                    "run_id": args.run,
                    "key_dir": str(key_dir),
                    "threshold": config.MIN_DENSE_SIMILARITY,
                    "min_dense_similarity": config.MIN_DENSE_SIMILARITY,
                    "config_hash": eval_config_hash(),
                    "chat_model": config.CHAT_MODEL,
                    "case_count": len(cases),
                    "started_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    try:
        ask = make_ask(args.run)
    except TypeError:
        ask = make_ask()

    summary = run_cases(cases, ask, checkpoint)
    rows = checkpoint.rows()
    if {c.id for c in cases} <= checkpoint.done() and not any(r.get("event") == "error" for r in rows):
        checkpoint.finish()

    print(
        summary_line(
            "run_final",
            **summary,
            estimate_usd=round(est, 4),
            out=str(out_dir / "answers.jsonl"),
        )
    )


if __name__ == "__main__":
    main()
