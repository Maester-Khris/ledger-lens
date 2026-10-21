"""Isolated Gemini checker (via agy CLI in temporary folders) and deterministic data checks for evaluation keys."""
import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import subprocess
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
from scripts.evalkit.write_key import document_text

CHECKER_MODEL: str = "gemini-4-argon-high"
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
    """Invoke the agy CLI sandboxed inside the batch folder and return its structured JSON output."""
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
        envelope = json.loads(proc.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(envelope, dict):
        return {}
    structured = envelope.get("structured_output")
    return structured if isinstance(structured, dict) else {}


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
) -> dict[str, int]:
    """Run unchecked cases in fixed-size batches with one retry per rejected batch and checkpoint every accepted verdict."""
    done_ids = verdicts.done()
    pending: list[Case] = []
    skipped = 0
    for case in cases:
        if case.id in done_ids:
            skipped += 1
        else:
            pending.append(case)

    checked = 0
    failed_batches = 0
    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        accepted: list[dict] | None = None
        for _ in range(2):
            reply = runner(batch)
            accepted = accept_verdicts(batch, reply)
            if accepted is not None:
                break
        if accepted is not None:
            for v in accepted:
                verdicts.append({
                    "case_id": v["case_id"],
                    "agrees": v["agrees"],
                    "reason": v["reason"],
                    "checker": CHECKER_MODEL,
                })
                checked += 1
        else:
            failed.append({
                "id": batch[0].id,
                "case_ids": [c.id for c in batch],
            })
            failed_batches += 1

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


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entry point to verify candidate evaluation cases with data checks and isolated Gemini agy batches."""
    parser = argparse.ArgumentParser(description="Check evaluation key candidates in isolated agy batches.")
    parser.add_argument("--key", type=Path, required=True, help="Directory holding candidates.jsonl.")
    parser.add_argument("--batch-size", type=int, default=40, help="Number of cases per agy batch.")
    args = parser.parse_args(argv)
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
            return run_agy(folder, schema)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    summary = check_batches(other_cases, _runner, verdicts, failed, args.batch_size)
    summary["checked"] += data_checked
    summary["skipped"] += data_skipped

    if summary["failed_batches"] == 0:
        verdicts.finish()
        failed.finish()
    print(summary_line("check_key", **summary))


if __name__ == "__main__":
    main()
