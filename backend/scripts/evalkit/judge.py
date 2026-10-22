"""Answer-level ALCE judge for the chat evaluation pipeline, supporting both Anthropic API and headless Claude Code CLI.

Claude Sonnet 5.5 grades answers it neither wrote nor helped assemble into the key. To keep the evaluation free of
leakage and PII, `build_input` strips writer metadata, human anchor labels, and unredacted values, forwarding only the
question, reference answer, redacted answer text, and redacted citation quotes.
"""
import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any

from scripts.evalkit.cases import Case, read_cases
from scripts.evalkit.checkpoint import Checkpoint, summary_line
from scripts.evalkit.providers import chat_client

JUDGE_MODEL: str = "claude-sonnet-5-5"
BATCH_SIZE: int = 20
PROMPTS: Path = Path(__file__).parent / "prompts"
DISALLOWED_TOOLS: str = "Bash Edit Write Read Glob Grep WebFetch WebSearch Task NotebookEdit"

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)


def _strip_fence(text: str) -> str:
    """Remove an optional Markdown JSON fence from a model reply."""
    match = _FENCE_RE.match(text)
    return match.group(1).strip() if match else text.strip()


def build_input(case: Case, row: dict[str, Any]) -> dict[str, Any]:
    """Build the isolated judge input containing only redacted text and quotes, with no writer or anchor metadata."""
    return {
        "case_id": case.id,
        "question": case.question,
        "reference": case.reference or "",
        "answer": row["text"],
        "citations": [{"id": c["id"], "quote": c["quote"]} for c in row.get("citations", [])],
    }


def parse_judgment(
    reply: str | dict[str, Any],
    *,
    default_case_id: str | None = None,
) -> dict[str, Any] | None:
    """Validate and normalise a raw judgment JSON string or dict against the required ALCE judgment schema."""
    if isinstance(reply, str):
        try:
            data = json.loads(_strip_fence(reply))
        except (json.JSONDecodeError, TypeError):
            return None
    elif isinstance(reply, dict):
        data = dict(reply)
    else:
        return None

    if not isinstance(data, dict):
        return None

    case_id = data.get("case_id")
    if case_id is None and default_case_id is not None:
        case_id = default_case_id
    correct = data.get("correct")
    raw_statements = data.get("statements")
    raw_citations = data.get("citations")

    if (
        not isinstance(case_id, str)
        or not case_id
        or not isinstance(correct, bool)
        or not isinstance(raw_statements, list)
        or not isinstance(raw_citations, list)
    ):
        return None

    statements: list[dict[str, Any]] = []
    for item in raw_statements:
        if not isinstance(item, dict):
            return None
        text = item.get("text")
        supported = item.get("supported")
        if not isinstance(text, str) or not isinstance(supported, bool):
            return None
        statements.append({"text": text, "supported": supported})

    citations: list[dict[str, Any]] = []
    for item in raw_citations:
        if not isinstance(item, dict):
            return None
        cid = item.get("id")
        relevant = item.get("relevant")
        if not isinstance(cid, str) or not isinstance(relevant, bool):
            return None
        citations.append({"id": cid, "relevant": relevant})

    return {
        "case_id": case_id,
        "correct": correct,
        "statements": statements,
        "citations": citations,
    }


def clean(judgment: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """Drop fabricated citation ids not present in the turn's citations and flag inconsistent judgments."""
    known_ids = {
        c["id"]
        for c in row.get("citations", [])
        if isinstance(c, dict) and isinstance(c.get("id"), str)
    }
    raw_citations = judgment.get("citations", [])
    kept_citations = [c for c in raw_citations if c.get("id") in known_ids]
    statements = list(judgment.get("statements", []))
    inconsistent = len(kept_citations) != len(raw_citations) or len(statements) == 0
    return {
        **judgment,
        "statements": statements,
        "citations": kept_citations,
        "judge_inconsistent": inconsistent,
    }


def select_sample(rows: Sequence[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    """Deterministically pick the first `n` answered rows ordered by `case_id` so API and CLI backends judge the same set."""
    answered = [r for r in rows if r.get("event") == "answer"]
    return sorted(answered, key=lambda r: str(r["case_id"]))[:n]


def run_cli_batch(inputs: Sequence[dict[str, Any]], folder: Path) -> list[dict[str, Any]]:
    """Run one batch through headless `claude -p` in an isolated folder with all tools disabled."""
    folder.mkdir(parents=True, exist_ok=True)
    instructions = (PROMPTS / "judge.md").read_text(encoding="utf-8")
    batch_text = "".join(json.dumps(item) + "\n" for item in inputs)
    (folder / "batch.jsonl").write_text(batch_text, encoding="utf-8")
    (folder / "instructions.md").write_text(instructions, encoding="utf-8")

    prompt = f"{instructions}\n\n{batch_text}"
    command = [
        "claude",
        "-p",
        prompt,
        "--model",
        JUDGE_MODEL,
        "--output-format",
        "json",
        "--disallowedTools",
        DISALLOWED_TOOLS,
    ]
    try:
        proc = subprocess.run(
            command,
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=900,
        )
        envelope = json.loads(proc.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError, TypeError):
        return []

    if not isinstance(envelope, dict) or envelope.get("is_error"):
        return []

    raw_result = envelope.get("result")
    if isinstance(raw_result, str):
        try:
            payload = json.loads(_strip_fence(raw_result))
        except (json.JSONDecodeError, TypeError):
            return []
    elif isinstance(raw_result, dict):
        payload = raw_result
    else:
        return []

    if not isinstance(payload, dict) or not isinstance(payload.get("judgments"), list):
        return []

    parsed: list[dict[str, Any]] = []
    for entry in payload["judgments"]:
        j = parse_judgment(entry)
        if j is not None:
            parsed.append(j)
    return parsed


def run_api(inputs: Sequence[dict[str, Any]], client: Any) -> list[dict[str, Any]]:
    """Judge each input individually via the Anthropic API client, skipping unreadable replies."""
    instructions = (PROMPTS / "judge.md").read_text(encoding="utf-8")
    out: list[dict[str, Any]] = []
    for item in inputs:
        prompt = (
            f"{instructions}\n\nOne case:\n{json.dumps(item)}\n"
            'Reply with the judgment object only: {"case_id": ...}'
        )
        try:
            reply = str(client.invoke(prompt).content)
        except Exception:
            continue
        parsed = parse_judgment(reply, default_case_id=str(item.get("case_id", "")))
        if parsed is not None:
            out.append(parsed)
    return out


def _load_answers(answers_path: Path) -> list[dict[str, Any]]:
    """Read answer rows from `answers.jsonl` or fall back to its partial checkpoint."""
    if answers_path.exists():
        return [
            json.loads(line)
            for line in answers_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return Checkpoint(answers_path, key="case_id").rows()


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entry point to judge answered evaluation turns via either headless Claude Code (`cli`) or Anthropic (`api`)."""
    parser = argparse.ArgumentParser(description="Judge answered evaluation turns with Claude Sonnet 5.5.")
    parser.add_argument("--run", type=str, required=True, help="Evaluation run id under reports/eval-final/.")
    parser.add_argument("--backend", choices=("cli", "api"), required=True, help="Execution backend.")
    parser.add_argument("--key", type=Path, default=None, help="Directory holding key.jsonl (defaults to run.json).")
    parser.add_argument("--sample", type=int, default=None, help="Judge only the first N answered cases by case_id.")
    parser.add_argument("--yes", action="store_true", help="Confirm paid Anthropic API calls.")
    args = parser.parse_args(argv)

    if args.backend == "api" and not args.yes:
        print(
            "Estimate: about $0.009 per judged case (claude-sonnet-5-5 API, one call each). "
            "Re-run with --yes after checking your Anthropic credit."
        )
        raise SystemExit(2)

    run_dir = Path("reports/eval-final") / args.run
    all_rows = _load_answers(run_dir / "answers.jsonl")

    key_dir: Path | None = args.key
    if key_dir is None:
        run_meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        raw_key = run_meta.get("key") or run_meta.get("key_dir")
        key_dir = Path(str(raw_key))

    cases_by_id = {c.id: c for c in read_cases(key_dir / "key.jsonl")}
    if args.sample is not None:
        target_rows = select_sample(all_rows, args.sample)
    else:
        target_rows = [r for r in all_rows if r.get("event") == "answer"]

    rows_by_id = {str(r["case_id"]): r for r in target_rows if "case_id" in r}
    checkpoint = Checkpoint(run_dir / f"judgments-{args.backend}.jsonl", key="case_id")
    done_ids = checkpoint.done()

    pending_inputs = [
        build_input(cases_by_id[cid], row)
        for cid, row in rows_by_id.items()
        if cid not in done_ids and cid in cases_by_id
    ]

    judged = 0
    if args.backend == "cli":
        for start in range(0, len(pending_inputs), BATCH_SIZE):
            batch = pending_inputs[start:start + BATCH_SIZE]
            folder = Path(tempfile.mkdtemp(prefix="evalkit-judge-"))
            try:
                raw_judgments = run_cli_batch(batch, folder)
            finally:
                shutil.rmtree(folder, ignore_errors=True)
            for j in raw_judgments:
                cid = j["case_id"]
                if cid in rows_by_id:
                    cleaned = clean(j, rows_by_id[cid])
                    checkpoint.append({**cleaned, "backend": args.backend})
                    judged += 1
    else:
        client = chat_client("anthropic", JUDGE_MODEL)
        for item in pending_inputs:
            for j in run_api([item], client):
                cid = j["case_id"]
                if cid in rows_by_id:
                    cleaned = clean(j, rows_by_id[cid])
                    checkpoint.append({**cleaned, "backend": args.backend})
                    judged += 1

    if set(rows_by_id) <= checkpoint.done():
        checkpoint.finish()

    print(
        summary_line(
            "judge",
            backend=args.backend,
            judged=judged,
            skipped=len(rows_by_id) - len(pending_inputs),
            total=len(rows_by_id),
            out=str(checkpoint.final_path),
        )
    )


if __name__ == "__main__":
    main()
