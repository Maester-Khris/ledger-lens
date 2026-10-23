"""Isolated checker (headless Claude, or Gemini via the agy CLI, in temporary folders) and deterministic data checks for evaluation keys."""
import argparse
from collections.abc import Callable, Mapping, Sequence
import concurrent.futures
from dataclasses import asdict
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from app import config
from app.assistant.runtime import get_runtime
from app.contracts import dao as contracts_dao
from app.documents import dao as documents_dao
from app.ledger.db import SessionLocal
from app.ledger.types import DEMO_TENANT_ID
from app.retrieval import dao as retrieval_dao
from app.retrieval.search import dense_matches
from scripts.evalkit.cases import Case
from scripts.evalkit.checkpoint import Checkpoint, summary_line
from scripts.evalkit.judge import DISALLOWED_TOOLS
from scripts.evalkit.write_key import document_text

CHECKER_MODEL: str = "gemini-4-argon-high"
MEDIUM_MODEL: str = "gemini-4-argon-medium"
# The settled checker: Gemini's quota ended and every free model accepted every case, even Opus at default effort did;
# Opus at medium effort rejected all 20 corrupted negative controls and none of the 10 intact ones.
CLAUDE_MODEL: str = "claude-opus-5-5"
CLAUDE_EFFORT: str = "medium"
CHECKER_SYSTEM_PROMPT: str = "You check evaluation cases against agreement text. Reply with the JSON object only."
PROMPTS: Path = Path(__file__).parent / "prompts"
HIDDEN_FIELDS: tuple[str, ...] = ("writer", "anchor_value")


def prepare_batch(
    cases: Sequence[Case],
    folder: Path,
    texts: Mapping[str, str],
    corpus_passages: Mapping[str, str],
    instructions: str,
) -> None:
    """Populate an isolated directory with only the batch's cases, redacted texts, passages, and instructions so the checker cannot see writer metadata or human labels."""
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "batch.jsonl").open("w", encoding="utf-8") as out:
        for case in cases:
            row = {k: v for k, v in asdict(case).items() if k not in HIDDEN_FIELDS}
            out.write(json.dumps(row) + "\n")

    (folder / "instructions.md").write_text(instructions, encoding="utf-8")

    doc_keys = sorted({c.document_key for c in cases if c.document_key and c.document_key in texts})
    for key in doc_keys:
        doc_path = folder / "documents" / f"{key}.txt"
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(texts[key], encoding="utf-8")

    for case in cases:
        if case.category == "out_of_corpus" and case.id in corpus_passages:
            passage_path = folder / "passages" / f"{case.id}.txt"
            passage_path.parent.mkdir(parents=True, exist_ok=True)
            passage_path.write_text(corpus_passages[case.id], encoding="utf-8")


def run_agy(
    folder: Path,
    schema: Path,
    *,
    model: str = CHECKER_MODEL,
    timeout: int = 900,
) -> dict:
    """Invoke the agy CLI sandboxed inside the batch folder, logging unusable calls to stderr so empty results are never silent."""
    inst_path = folder / "instructions.md"
    prompt = (
        inst_path.read_text(encoding="utf-8")
        if inst_path.exists()
        else (PROMPTS / "checker.md").read_text(encoding="utf-8")
    )
    command = [
        "agy",
        "-p",
        prompt,
        "--model",
        model,
        "--sandbox",
        "--output-format",
        "json",
        "--json-schema",
        str(schema),
        "--print-timeout",
        f"{timeout}s",
    ]
    try:
        proc = subprocess.run(
            command,
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=timeout + 60,
        )
    except subprocess.TimeoutExpired:
        print(f"agy call timed out after {timeout}s ({folder.name})", file=sys.stderr)
        return {}
    except subprocess.SubprocessError as exc:
        detail = str(exc).replace("\r", " ").replace("\n", " ").strip()
        print(f"agy call failed ({folder.name}): {detail}", file=sys.stderr)
        return {}

    try:
        envelope = json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError):
        tail = (proc.stderr or "")[-300:].replace("\r", " ").replace("\n", " ").strip()
        print(f"agy output was not JSON (rc={proc.returncode}, {folder.name}): {tail}", file=sys.stderr)
        return {}

    structured = envelope.get("structured_output") if isinstance(envelope, dict) else None
    if not isinstance(structured, dict):
        parts = (
            [str(envelope[k]) for k in ("status", "error") if envelope.get(k) is not None]
            if isinstance(envelope, dict)
            else [f"got {type(envelope).__name__}"]
        )
        detail = ": ".join(parts).replace("\r", " ").replace("\n", " ").strip() or "missing"
        print(f"agy envelope had no structured_output ({folder.name}): {detail}", file=sys.stderr)
        return {}
    return structured


def checker_label(backend: str, model: str, effort: str) -> str:
    """Name written on every verdict row; the effort is part of a Claude checker's identity, agy's is in its model id."""
    return f"{model}@{effort}" if backend == "claude" else model


def _inline_prompt(folder: Path) -> str:
    """The batch folder's files as one prompt: the model cannot read a folder, so the instructions' own pointer to it is replaced."""
    instructions = (folder / "instructions.md").read_text(encoding="utf-8")
    parts = [
        instructions.replace("Read only the files in this folder.", "The files are given below; use only them."),
        "=== batch.jsonl ===\n" + (folder / "batch.jsonl").read_text(encoding="utf-8"),
    ]
    for sub in ("documents", "passages"):
        for path in sorted((folder / sub).glob("*.txt")):
            parts.append(f"=== {sub}/{path.name} ===\n" + path.read_text(encoding="utf-8"))
    return "\n\n".join(parts)


def run_claude(
    folder: Path,
    *,
    model: str = CLAUDE_MODEL,
    effort: str = CLAUDE_EFFORT,
    timeout: int = 900,
) -> dict:
    """Run one batch through headless `claude -p` with the judge's isolation (fixed system prompt, no skills, MCP or tools), logging unusable calls to stderr."""
    command = [
        "claude",
        "-p",
        _inline_prompt(folder),
        "--model",
        model,
        "--effort",
        effort,
        "--output-format",
        "json",
        "--system-prompt",
        CHECKER_SYSTEM_PROMPT,
        "--disable-slash-commands",
        "--strict-mcp-config",
        "--disallowedTools",
        DISALLOWED_TOOLS,
    ]
    try:
        proc = subprocess.run(command, cwd=folder, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"claude call timed out after {timeout}s ({folder.name})", file=sys.stderr)
        return {}
    except subprocess.SubprocessError as exc:
        print(f"claude call failed ({folder.name}): {str(exc)[:300]}", file=sys.stderr)
        return {}

    try:
        envelope = json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError):
        tail = (proc.stderr or "")[-300:].replace("\r", " ").replace("\n", " ").strip()
        print(f"claude output was not JSON (rc={proc.returncode}, {folder.name}): {tail}", file=sys.stderr)
        return {}

    result = envelope.get("result") if isinstance(envelope, dict) else None
    if not isinstance(envelope, dict) or envelope.get("is_error") or not isinstance(result, str):
        detail = str(result if isinstance(envelope, dict) else envelope)[:300].replace("\n", " ")
        print(f"claude call failed ({folder.name}): {detail}", file=sys.stderr)
        return {}
    found = re.search(r"\{.*\}", result, re.S)
    try:
        reply = json.loads(found.group(0)) if found else None
    except json.JSONDecodeError:
        reply = None
    if not isinstance(reply, dict):
        print(f"claude reply was not JSON ({folder.name}): {result[:200]!r}", file=sys.stderr)
        return {}
    return reply


def accept_verdicts(cases: Sequence[Case], reply: dict) -> list[dict] | None:
    """Validate that the checker returned one well-formed verdict per case id in the batch and return them in batch order."""
    if not isinstance(reply, dict):
        return None
    raw_verdicts = reply.get("verdicts")
    if not isinstance(raw_verdicts, list) or len(raw_verdicts) != len(cases):
        return None

    expected_ids = {c.id for c in cases}
    by_id: dict[str, dict] = {}
    for item in raw_verdicts:
        if not isinstance(item, dict):
            return None
        case_id = item.get("case_id")
        agrees = item.get("agrees")
        reason = item.get("reason")
        if not isinstance(case_id, str) or not isinstance(agrees, bool) or not isinstance(reason, str):
            return None
        by_id[case_id] = {"case_id": case_id, "agrees": agrees, "reason": reason}

    if set(by_id) != expected_ids:
        return None
    return [by_id[c.id] for c in cases]


def check_batches(
    cases: Sequence[Case],
    runner: Callable[[list[Case]], dict],
    verdicts: Checkpoint,
    failed: Checkpoint,
    batch_size: int,
    *,
    workers: int = 1,
    checker: str = CHECKER_MODEL,
) -> dict[str, int]:
    """Run unchecked cases in fixed-size batches (with one retry each), keeping checkpoint writes on the calling thread because the checkpoint file is not safe for concurrent writers."""
    done_ids = verdicts.done()
    pending: list[Case] = []
    skipped = 0
    for case in cases:
        if case.id in done_ids:
            skipped += 1
        else:
            pending.append(case)

    batches = [pending[start:start + batch_size] for start in range(0, len(pending), batch_size)]

    def _run_batch(batch: list[Case]) -> tuple[list[Case], list[dict] | None]:
        for _ in range(2):
            accepted = accept_verdicts(batch, runner(batch))
            if accepted is not None:
                return batch, accepted
        return batch, None

    checked = 0
    failed_batches = 0

    def _record(batch: list[Case], accepted: list[dict] | None) -> None:
        nonlocal checked, failed_batches
        if accepted is not None:
            for v in accepted:
                verdicts.append({
                    "case_id": v["case_id"],
                    "agrees": v["agrees"],
                    "reason": v["reason"],
                    "checker": checker,
                })
                checked += 1
        else:
            failed.append({
                "id": batch[0].id,
                "case_ids": [c.id for c in batch],
            })
            failed_batches += 1

    if workers > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_run_batch, batch) for batch in batches]
            for future in concurrent.futures.as_completed(futures):
                batch, accepted = future.result()
                _record(batch, accepted)
    else:
        for batch in batches:
            _, accepted = _run_batch(batch)
            _record(batch, accepted)

    return {
        "checked": checked,
        "failed_batches": failed_batches,
        "skipped": skipped,
    }


def passage_cases(cases: Sequence[Case], done: set[str]) -> list[Case]:
    """Out-of-corpus cases still to check: their corpus passages cost an embedding call each, so a resumed run must
    not fetch them again for cases already checked."""
    return [c for c in cases if c.category == "out_of_corpus" and c.id not in done]


def underspecified_ok(values_by_field: Mapping[str, set[str]], field_path: str) -> bool:
    """Return True when a field has at least two distinct accepted values across contracts, making an unnamed-contract question genuinely underspecified."""
    return len(values_by_field.get(field_path, set())) >= 2


def data_verdicts(
    cases: Sequence[Case],
    values_by_field: Mapping[str, set[str]],
) -> list[dict]:
    """Compute deterministic verdicts for underspecified cases directly from corpus field values."""
    rows: list[dict] = []
    for case in cases:
        if case.category != "underspecified":
            continue
        field_path = case.field_path or ""
        ok = underspecified_ok(values_by_field, field_path)
        count = len(values_by_field.get(field_path, set()))
        rows.append({
            "case_id": case.id,
            "agrees": ok,
            "reason": f"{field_path} has {count} distinct accepted values across contracts",
            "checker": "data",
        })
    return rows


def _load_candidate_cases(candidates_path: Path) -> list[Case]:
    """Read all candidate Case objects from the writer stage's candidates.jsonl file."""
    cases: list[Case] = []
    for line in candidates_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        for raw in row.get("cases", []):
            raw = dict(raw)
            raw["expect_numbers"] = tuple(raw.get("expect_numbers", ()))
            raw["gold_element_ids"] = tuple(raw.get("gold_element_ids", ()))
            cases.append(Case(**raw))
    return cases


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI flags separately from main so defaults and mutually exclusive model options can be tested in isolation."""
    parser = argparse.ArgumentParser(description="Check evaluation key candidates in isolated batches.")
    parser.add_argument("--key", type=Path, required=True, help="Directory holding candidates.jsonl.")
    parser.add_argument("--backend", choices=("claude", "agy"), default="claude", help="Headless Claude, or Gemini through agy.")
    parser.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max"), default=CLAUDE_EFFORT,
                        help="Reasoning effort of the Claude checker.")
    parser.add_argument("--batch-size", type=int, default=10, help="Number of cases per batch.")
    parser.add_argument("--workers", type=int, default=3, help="Number of concurrent batch workers.")
    parser.add_argument("--timeout", type=int, default=1500, help="Seconds allowed for one call.")
    model_group = parser.add_mutually_exclusive_group()
    model_group.add_argument("--model", default=None, help="Checker model name (default depends on the backend).")
    model_group.add_argument("--medium", action="store_true", help="agy backend only: the cheaper medium Gemini model.")
    args = parser.parse_args(argv)
    if args.medium and args.backend != "agy":
        parser.error("--medium selects a Gemini model; use --backend agy, or --effort for the Claude checker")
    if args.model is None:
        args.model = CLAUDE_MODEL if args.backend == "claude" else MEDIUM_MODEL if args.medium else CHECKER_MODEL
    return args


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entry point to verify candidate evaluation cases with data checks and isolated Gemini agy batches."""
    args = parse_args(argv)
    key_dir: Path = args.key

    cases = _load_candidate_cases(key_dir / "candidates.jsonl")
    verdicts = Checkpoint(key_dir / "verdicts.jsonl", key="case_id")
    failed = Checkpoint(key_dir / "check_failed.jsonl")

    runtime = get_runtime()
    texts: dict[str, str] = {}
    corpus_passages: dict[str, str] = {}
    with SessionLocal() as session:
        for row in documents_dao.list_documents(session, DEMO_TENANT_ID):
            vid = documents_dao.current_version_id(session, row.document.id)
            elements = documents_dao.list_elements(session, vid)
            text, _ = document_text(elements)
            texts[row.document.document_key] = text

        values_by_field = contracts_dao.accepted_values(session, DEMO_TENANT_ID)

        hmac_key = config.require("PII_HMAC_KEY")
        vault_key = config.require("PII_VAULT_KEY")
        for case in passage_cases(cases, verdicts.done()):
            tokenised = documents_dao.tokenize_known_values(
                session, DEMO_TENANT_ID, case.question, hmac_key, vault_key,
            )
            top_hits = dense_matches(
                session,
                tenant_id=DEMO_TENANT_ID,
                query=tokenised,
                embeddings=runtime.embeddings,
                vector_index=runtime.vector_index,
            )[:8]
            ev_rows = retrieval_dao.evidence_rows(session, [eid for eid, _ in top_hits])
            lines = [
                f"[{eid}] p{ev_rows[eid][0].page_start}: {ev_rows[eid][0].text_redacted}"
                for eid, _ in top_hits
                if eid in ev_rows
            ]
            corpus_passages[case.id] = "\n".join(lines)

    done_ids = verdicts.done()
    underspecified_cases = [c for c in cases if c.category == "underspecified"]
    other_cases = [c for c in cases if c.category != "underspecified"]

    data_checked = 0
    data_skipped = 0
    for verdict in data_verdicts(underspecified_cases, values_by_field):
        if verdict["case_id"] in done_ids:
            data_skipped += 1
        else:
            verdicts.append(verdict)
            data_checked += 1

    instructions = (PROMPTS / "checker.md").read_text(encoding="utf-8")
    schema = (PROMPTS / "checker_verdict.schema.json").resolve()

    def _runner(batch: list[Case]) -> dict:
        folder = Path(tempfile.mkdtemp(prefix="evalkit-check-"))
        try:
            prepare_batch(batch, folder, texts, corpus_passages, instructions)
            if args.backend == "claude":
                return run_claude(folder, model=args.model, effort=args.effort, timeout=args.timeout)
            return run_agy(folder, schema, model=args.model, timeout=args.timeout)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    summary = check_batches(
        other_cases,
        _runner,
        verdicts,
        failed,
        args.batch_size,
        workers=args.workers,
        checker=checker_label(args.backend, args.model, args.effort),
    )
    summary["checked"] += data_checked
    summary["skipped"] += data_skipped

    if summary["failed_batches"] == 0:
        verdicts.finish()
        failed.finish()
    print(summary_line("check_key", **summary))


if __name__ == "__main__":
    main()
