"""Tiebreak resolution across model families and final assembly of the evaluation key and anchor cases."""
import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
import json
from pathlib import Path
import re
from string import Template

from app import config
from app.documents import dao as documents_dao
from app.ledger.db import SessionLocal
from app.ledger.types import DEMO_TENANT_ID
from scripts.evalkit.cases import CATEGORIES, MIX, Case, from_golden, write_cases
from scripts.evalkit.checkpoint import Checkpoint, summary_line
from scripts.evalkit.providers import (GROQ_LIMITS, GROQ_SETTINGS, DailyBudgetExceeded, TokenLimiter, chat_client,
                                       estimate_tokens, is_daily_limit)
from scripts.evalkit.write_key import OUTPUT_TOKENS, document_text

PROMPTS: Path = Path(__file__).parent / "prompts"
HIDDEN_FIELDS: tuple[str, ...] = ("writer", "anchor_value")
TIEBREAKERS: tuple[str, str] = ("openai/gpt-oss-20b", "qwen/qwen3.8-27b")

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)


def _strip_fence(text: str) -> str:
    """Remove an optional Markdown JSON code fence from a model reply."""
    match = _FENCE_RE.match(text)
    return match.group(1).strip() if match else text.strip()


def tiebreaker_for(writer: str) -> str:
    """Select a tiebreaker model from the opposite family of the writer so no model family arbitrates its own output."""
    if writer == "qwen/qwen3.8-27b":
        return "openai/gpt-oss-20b"
    if writer.startswith("openai/gpt-oss-"):
        return "qwen/qwen3.8-27b"
    raise ValueError(f"Unsupported writer for tiebreak: {writer}")


def explained_cases(
    documents: Sequence[tuple[str, str]],
    count: int = 10,
) -> list[Case]:
    """Build deterministic explained-abstention cases from contracts that have no linked billing household."""
    sorted_docs = sorted(documents, key=lambda pair: pair[0])[:count]
    return [
        Case(
            id=f"explained:{key}",
            category="explained",
            question=f"Compare the {title} agreement with billing.",
            expect="refuse",
            document_key=key,
            writer="data",
            origin="data",
        )
        for key, title in sorted_docs
    ]


def run_tiebreaks(
    disputed: Sequence[tuple[Case, str]],
    clients: Mapping[str, Callable[[str], str]],
    texts: Mapping[str, str],
    checkpoint: Checkpoint,
) -> dict[str, int]:
    """Run tiebreak judgements on cases where the writer and checker disagreed, checkpointing each decision."""
    done_ids = checkpoint.done()
    template = Template((PROMPTS / "tiebreak.md").read_text(encoding="utf-8"))

    kept = 0
    rejected = 0
    unreadable = 0
    skipped = 0

    for case, checker_reason in disputed:
        if case.id in done_ids:
            skipped += 1
            continue

        tiebreaker = tiebreaker_for(case.writer)
        case_dict = {k: v for k, v in asdict(case).items() if k not in HIDDEN_FIELDS}
        prompt = template.substitute(
            reason=checker_reason,
            case=json.dumps(case_dict),
            text=texts.get(case.document_key or "", ""),
        )

        keep = False
        reason = "unreadable tiebreak"
        is_unreadable = False
        try:
            raw_reply = clients[tiebreaker](prompt)
        except DailyBudgetExceeded:
            # A quota stop is not a verdict: leave the case unrecorded so the next run decides it.
            return {"kept": kept, "rejected": rejected, "unreadable": unreadable, "skipped": skipped,
                    "stopped": "daily_budget"}
        except Exception as exc:
            if is_daily_limit(exc):
                return {"kept": kept, "rejected": rejected, "unreadable": unreadable, "skipped": skipped,
                        "stopped": "daily_budget"}
            raw_reply = ""  # a failed call is recorded as unreadable, as the reply would be
        try:
            parsed = json.loads(_strip_fence(raw_reply))
            if (
                isinstance(parsed, dict)
                and isinstance(parsed.get("keep"), bool)
                and isinstance(parsed.get("reason"), str)
            ):
                keep = parsed["keep"]
                reason = parsed["reason"]
            else:
                is_unreadable = True
        except Exception:
            is_unreadable = True

        if is_unreadable:
            unreadable += 1
        elif keep:
            kept += 1
        else:
            rejected += 1

        checkpoint.append({
            "case_id": case.id,
            "keep": keep,
            "reason": reason,
            "tiebreaker": tiebreaker,
        })

    return {
        "kept": kept,
        "rejected": rejected,
        "unreadable": unreadable,
        "skipped": skipped,
        "stopped": None,
    }


def assemble(
    golden: Sequence[Case],
    candidates: Sequence[Case],
    verdicts: Mapping[str, dict],
    tiebreaks: Mapping[str, dict],
    explained: Sequence[Case],
) -> tuple[list[Case], list[Case], list[dict], dict]:
    """Assemble the final evaluation key, separate anchor cases, and record dropped candidates and category counts."""
    key: list[Case] = list(golden)
    anchors: list[Case] = []
    dropped: list[dict] = []

    for case in candidates:
        verdict = verdicts.get(case.id)
        if verdict is None:
            dropped.append({"case_id": case.id, "reason": "unchecked"})
            continue

        agrees = bool(verdict.get("agrees"))
        if not agrees:
            tb = tiebreaks.get(case.id)
            if tb is None or not bool(tb.get("keep")):
                dropped.append({"case_id": case.id, "reason": "tiebreak"})
                continue

        if case.origin == "anchor":
            anchors.append(case)
        else:
            key.append(case)

    key.extend(explained)

    writers: dict[str, int] = {}
    for c in key:
        if c.writer and c.writer not in ("golden", "data"):
            writers[c.writer] = writers.get(c.writer, 0) + 1

    summary = {
        "key": len(key),
        "anchors": len(anchors),
        "dropped": len(dropped),
        "categories": {
            cat: {
                "have": sum(1 for c in key if c.category == cat),
                "target": MIX[cat],
            }
            for cat in CATEGORIES
        },
        "writers": writers,
    }
    return key, anchors, dropped, summary


def _read_jsonl_or_checkpoint(path: Path, key: str = "id") -> list[dict]:
    """Read rows from a finished JSONL file or fall back to its partial checkpoint."""
    if path.exists():
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return Checkpoint(path, key=key).rows()


def _load_candidates(path: Path) -> list[Case]:
    """Unpack candidate Case objects from candidates.jsonl."""
    cases: list[Case] = []
    for row in _read_jsonl_or_checkpoint(path, key="id"):
        for raw in row.get("cases", []):
            raw = dict(raw)
            raw["expect_numbers"] = tuple(raw.get("expect_numbers", ()))
            raw["gold_element_ids"] = tuple(raw.get("gold_element_ids", ()))
            cases.append(Case(**raw))
    return cases


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entry point to resolve tiebreaks and write key.jsonl, anchor.jsonl, dropped.jsonl, and summary.json."""
    parser = argparse.ArgumentParser(description="Run tiebreaks and assemble the evaluation key.")
    parser.add_argument("--key", type=Path, required=True, help="Directory holding candidates.jsonl and verdicts.jsonl.")
    args = parser.parse_args(argv)
    key_dir: Path = args.key

    candidates = _load_candidates(key_dir / "candidates.jsonl")
    verdict_rows = _read_jsonl_or_checkpoint(key_dir / "verdicts.jsonl", key="case_id")
    verdicts = {str(r["case_id"]): r for r in verdict_rows if "case_id" in r}

    disputed: list[tuple[Case, str]] = [
        (case, str(verdicts[case.id].get("reason", "")))
        for case in candidates
        if case.id in verdicts and not bool(verdicts[case.id].get("agrees"))
    ]

    texts: dict[str, str] = {}
    no_household_docs: list[tuple[str, str]] = []
    with SessionLocal() as session:
        for row in documents_dao.list_documents(session, DEMO_TENANT_ID):
            vid = documents_dao.current_version_id(session, row.document.id)
            elements = documents_dao.list_elements(session, vid)
            text, _ = document_text(elements)
            texts[row.document.document_key] = text
            if row.document.household_id is None:
                no_household_docs.append((row.document.document_key, row.document.title))

    tb_checkpoint = Checkpoint(key_dir / "tiebreaks.jsonl", key="case_id")
    if disputed:
        limiters = {
            model: TokenLimiter(**{**GROQ_LIMITS, "tokens_per_day": None}, usage_log=key_dir / f"usage-{model.replace('/', '_')}.jsonl")
            for model in TIEBREAKERS
        }

        def _make_client(model: str) -> Callable[[str], str]:
            def _call(prompt: str) -> str:
                limiters[model].acquire(estimate_tokens(prompt) + OUTPUT_TOKENS)
                return str(chat_client("groq", model, **{**GROQ_SETTINGS[model], "max_tokens": 600}).invoke(prompt).content)
            return _call

        clients = {model: _make_client(model) for model in TIEBREAKERS}
        tb_summary = run_tiebreaks(disputed, clients, texts, tb_checkpoint)
        if tb_summary["stopped"]:
            print(summary_line("assemble_key", stopped=tb_summary["stopped"], tiebreaks_left=len(disputed) - len(tb_checkpoint.done())))
            return
        tb_checkpoint.finish()

    tiebreak_rows = _read_jsonl_or_checkpoint(key_dir / "tiebreaks.jsonl", key="case_id")
    tiebreaks = {str(r["case_id"]): r for r in tiebreak_rows if "case_id" in r}

    golden_path = config.BACKEND_DIR / "tests" / "eval" / "golden.json"
    golden = [from_golden(entry) for entry in json.loads(golden_path.read_text(encoding="utf-8"))]
    explained = explained_cases(no_household_docs)

    key_cases, anchors, dropped, summary = assemble(golden, candidates, verdicts, tiebreaks, explained)
    write_cases(key_dir / "key.jsonl", key_cases)
    write_cases(key_dir / "anchor.jsonl", anchors)
    with (key_dir / "dropped.jsonl").open("w", encoding="utf-8") as out:
        for row in dropped:
            out.write(json.dumps(row) + "\n")
    (key_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(summary_line("assemble_key", key=summary["key"], anchors=summary["anchors"], dropped=summary["dropped"]))


if __name__ == "__main__":
    main()
