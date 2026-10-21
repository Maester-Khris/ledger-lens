"""Parallel Groq evaluation key writers and anchor-case builders for the chat evaluation pipeline."""
import argparse
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from string import Template
import threading
from typing import Protocol

from app.contracts import dao as contracts_dao
from app.contracts.dao import AdjudicatedLabel
from app.documents import dao as documents_dao
from app.ledger.db import SessionLocal
from app.ledger.types import DEMO_TENANT_ID
from scripts.evalkit.cases import Case, validate
from scripts.evalkit.checkpoint import Checkpoint, summary_line
from scripts.evalkit.providers import (
    GROQ_LIMITS,
    DailyBudgetExceeded,
    TokenLimiter,
    chat_client,
    estimate_tokens,
)

WRITERS: tuple[str, str] = ("qwen/qwen3.8-27b", "openai/gpt-oss-120b")
JUNK_WRITER: str = "qwen/qwen3.8-27b"
JUNK_COUNT: int = 20
MAX_DOC_CHARS: int = 20000
OUTPUT_TOKENS: int = 1000
PROMPTS: Path = Path(__file__).parent / "prompts"

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)


class ElementLike(Protocol):
    id: object
    page_start: int
    text_redacted: str


class LimiterLike(Protocol):
    def acquire(self, tokens: int) -> None: ...


@dataclass(frozen=True)
class WriteItem:
    id: str
    kind: str
    writer: str
    prompt: str
    document_key: str | None = None
    known_element_ids: frozenset[str] = frozenset()
    labels: tuple[AdjudicatedLabel, ...] = ()  # anchor questions asked in the same call as the document's cases


def _load_prompt(name: str) -> Template:
    """Load a frozen prompt template so placeholders can be filled without colliding with JSON braces."""
    return Template((PROMPTS / name).read_text(encoding="utf-8"))


def _strip_fence(text: str) -> str:
    """Remove an optional Markdown JSON fence from a model reply before parsing."""
    match = _FENCE_RE.match(text)
    return match.group(1).strip() if match else text.strip()


def document_text(
    elements: Sequence[ElementLike],
    max_chars: int = MAX_DOC_CHARS,
) -> tuple[str, frozenset[str]]:
    """Format redacted elements with ids and pages up to max_chars so one call fits Groq's per-minute token limit and citations can be checked against visible lines."""
    lines: list[str] = []
    ids: list[str] = []
    total = 0
    for el in elements:
        eid = str(el.id)
        line = f"[{eid}] p{el.page_start}: {el.text_redacted}"
        added = len(line) if not lines else len(line) + 1
        if total + added > max_chars:
            break
        lines.append(line)
        ids.append(eid)
        total += added
    return "\n".join(lines), frozenset(ids)


def assign_writers(document_keys: Iterable[str]) -> dict[str, str]:
    """Alternate sorted document keys across the two Groq writer families so each model writes half the corpus."""
    return {key: WRITERS[i % len(WRITERS)] for i, key in enumerate(sorted(document_keys))}


def document_item(
    document_key: str,
    title: str,
    elements: Sequence[ElementLike],
    writer: str,
    *,
    false_premise: bool,
    labels: Sequence[AdjudicatedLabel] = (),
) -> WriteItem:
    """Build one call per contract: its answerable (and optionally false-premise) questions, plus the anchor questions
    for the fields the owner labelled by hand. Anchors ride on the same call so the contract text is sent once: sent
    per label, the 128 labels alone would pass the two writers' 400k tokens a day. The human values never enter it."""
    text, ids = document_text(elements)
    rule = (PROMPTS / "writer_false_premise_rule.md").read_text(encoding="utf-8") if false_premise else ""
    anchor_rule = ""
    if labels:
        questions = "\n".join(f"- {label.field_path}: {anchor_question(label.field_path, title)}" for label in labels)
        anchor_rule = _load_prompt("writer_anchor.md").substitute(questions=questions)
    prompt = _load_prompt("writer_answerable.md").substitute(
        document_key=document_key,
        title=title,
        text=text,
        false_premise_rule=rule,
        anchor_rule=anchor_rule,
    )
    return WriteItem(
        id=f"doc:{document_key}",
        kind="document",
        writer=writer,
        prompt=prompt,
        document_key=document_key,
        known_element_ids=ids,
        labels=tuple(labels),
    )


def junk_item(
    category: str,
    writer: str,
    *,
    titles: Sequence[str],
    fields: Sequence[str],
) -> WriteItem:
    """Build a prompt item asking for non-answerable cases (out_of_corpus, underspecified, nonsense, off_topic)."""
    prompt = _load_prompt("writer_junk.md").substitute(
        category=category,
        count=JUNK_COUNT,
        titles="\n".join(titles),
        fields=", ".join(fields),
    )
    return WriteItem(
        id=f"junk:{category}",
        kind="junk",
        writer=writer,
        prompt=prompt,
    )


def anchor_question(field_path: str, title: str) -> str:
    """Turn a field path and contract title into a natural question so the key writer answers the same question as a user."""
    name = re.sub(r"\[(\d+)\]", lambda m: f" number {int(m.group(1)) + 1}", field_path.replace("_", " "))
    return f"What is the {name} in the {title}?"


def parse_cases(reply: str, *, item: WriteItem) -> list[Case]:
    """Parse and validate a writer's JSON reply, dropping malformed entries or citations to unseen element ids."""
    try:
        data = json.loads(_strip_fence(reply))
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        return []

    cases: list[Case] = []
    for i, entry in enumerate(data["cases"]):
        if not isinstance(entry, dict):
            continue
        raw_numbers = entry.get("expect_numbers") or ()
        raw_ids = entry.get("gold_element_ids") or ()
        if not isinstance(raw_numbers, (list, tuple)) or not isinstance(raw_ids, (list, tuple)):
            continue
        question = entry.get("question")
        category = entry.get("category")
        expect = entry.get("expect")
        if not isinstance(question, str) or not question or not isinstance(category, str) or not isinstance(expect, str):
            continue
        reference = entry.get("reference")
        premise_id = entry.get("premise_element_id")
        field_path = entry.get("field_path")
        page = entry.get("page")
        case = Case(
            id=f"{item.id}#{i}",
            category=category,
            question=question,
            expect=expect,
            document_key=item.document_key,
            reference=reference if isinstance(reference, str) and reference else None,
            expect_numbers=tuple(str(x) for x in raw_numbers),
            gold_element_ids=tuple(str(x) for x in raw_ids),
            page=page if isinstance(page, int) else None,
            premise_element_id=str(premise_id) if premise_id else None,
            writer=item.writer,
            origin="written",
            field_path=str(field_path) if field_path else None,
        )
        if validate(case):
            continue
        if any(eid not in item.known_element_ids for eid in case.gold_element_ids):
            continue
        if case.premise_element_id is not None and case.premise_element_id not in item.known_element_ids:
            continue
        cases.append(case)
    return cases


def parse_anchors(reply: str, *, item: WriteItem) -> list[Case]:
    """Turn the "anchors" list of a document reply into anchor cases, one per labelled field the writer stated. Each
    keeps the human label in anchor_value for the report only; unstated (null) and unasked fields are skipped."""
    try:
        data = json.loads(_strip_fence(reply))
    except (json.JSONDecodeError, TypeError):
        return []
    entries = data.get("anchors") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return []
    stated = {e["field_path"]: e for e in entries if isinstance(e, dict) and isinstance(e.get("field_path"), str)}
    cases: list[Case] = []
    for label in item.labels:
        entry = stated.get(label.field_path)
        if entry is None or entry.get("value") is None:
            continue
        value = entry["value"]
        raw_ids = entry.get("gold_element_ids") or ()
        ids = tuple(str(x) for x in raw_ids if str(x) in item.known_element_ids) if isinstance(raw_ids, (list, tuple)) else ()
        page = entry.get("page")
        cases.append(Case(
            id=f"anchor:{label.document_key}:{label.field_path}#0",
            category="answerable",
            question=anchor_question(label.field_path, label.title),
            expect="answer",
            document_key=label.document_key,
            reference=value if isinstance(value, str) else json.dumps(value),
            gold_element_ids=ids,
            page=page if isinstance(page, int) else None,
            writer=item.writer,
            origin="anchor",
            field_path=label.field_path,
            anchor_value=label.value,
        ))
    return cases


def run_writers(
    items: Sequence[WriteItem],
    clients: Mapping[str, Callable[[str], str]],
    limiters: Mapping[str, object],
    written: Checkpoint,
    failed: Checkpoint,
) -> dict[str, int | str | None]:
    """Run one thread per writer concurrently with per-writer rate limiting and crash-resumable checkpoints."""
    done_ids = written.done()
    by_writer: dict[str, list[WriteItem]] = {}
    skipped = 0
    for item in items:
        if item.id in done_ids:
            skipped += 1
        else:
            by_writer.setdefault(item.writer, []).append(item)

    lock = threading.Lock()
    written_count = 0
    failed_count = 0
    stopped: str | None = None

    def _worker(writer: str, writer_items: list[WriteItem]) -> None:
        nonlocal written_count, failed_count, stopped
        limiter = limiters[writer]
        client = clients[writer]
        for item in writer_items:
            last_error = "empty parse"
            succeeded = False
            for _ in range(2):
                try:
                    limiter.acquire(estimate_tokens(item.prompt) + OUTPUT_TOKENS)  # type: ignore[attr-defined]
                    reply = client(item.prompt)
                except DailyBudgetExceeded:
                    with lock:
                        stopped = "daily_budget"
                    return
                except Exception as exc:
                    last_error = str(exc) or exc.__class__.__name__
                    continue

                cases = parse_cases(reply, item=item)
                if cases:  # anchors only count alongside the document's own cases
                    cases += parse_anchors(reply, item=item)

                if cases:
                    with lock:
                        written.append({
                            "id": item.id,
                            "writer": item.writer,
                            "kind": item.kind,
                            "cases": [asdict(c) for c in cases],
                        })
                        written_count += 1
                    succeeded = True
                    break
                last_error = "empty parse"

            if not succeeded:
                with lock:
                    failed.append({
                        "id": item.id,
                        "writer": item.writer,
                        "error": last_error,
                    })
                    failed_count += 1

    threads = [
        threading.Thread(target=_worker, args=(writer, writer_items))
        for writer, writer_items in by_writer.items()
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    return {
        "written": written_count,
        "failed": failed_count,
        "skipped": skipped,
        "stopped": stopped,
    }


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entry point to generate candidate evaluation cases across the demo tenant's contracts."""
    parser = argparse.ArgumentParser(description="Write evaluation key candidates with two Groq models.")
    parser.add_argument("--out", type=Path, required=True, help="Output JSONL path for candidate cases.")
    args = parser.parse_args(argv)
    out: Path = args.out

    with SessionLocal() as session:
        doc_rows = documents_dao.list_documents(session, DEMO_TENANT_ID)
        docs_by_key = {row.document.document_key: row.document for row in doc_rows}
        sorted_keys = sorted(docs_by_key)
        writers = assign_writers(sorted_keys)
        elements_by_key = {
            key: documents_dao.list_elements(
                session,
                documents_dao.current_version_id(session, docs_by_key[key].id),
            )
            for key in sorted_keys
        }
        labels = contracts_dao.adjudicated_labels(session, DEMO_TENANT_ID)
        accepted = contracts_dao.accepted_values(session, DEMO_TENANT_ID)

    labels_by_key: dict[str, list[AdjudicatedLabel]] = {}
    for label in labels:
        labels_by_key.setdefault(label.document_key, []).append(label)
    items: list[WriteItem] = []
    for i, key in enumerate(sorted_keys):
        items.append(
            document_item(
                key,
                docs_by_key[key].title,
                elements_by_key[key],
                writers[key],
                false_premise=(i % 5 == 0),
                labels=labels_by_key.get(key, ()),
            )
        )

    titles = [docs_by_key[key].title for key in sorted_keys]
    fields = sorted(field for field, vals in accepted.items() if len(vals) >= 2)
    for category in ("out_of_corpus", "underspecified", "nonsense", "off_topic"):
        items.append(junk_item(category, JUNK_WRITER, titles=titles, fields=fields))

    clients: dict[str, Callable[[str], str]] = {
        model: (lambda m: lambda p: str(chat_client("groq", m).invoke(p).content))(model)
        for model in WRITERS
    }
    limiters: dict[str, TokenLimiter] = {
        model: TokenLimiter(**GROQ_LIMITS, usage_log=out.parent / f"usage-{model.replace('/', '_')}.jsonl")
        for model in WRITERS
    }
    written = Checkpoint(out)
    failed = Checkpoint(out.parent / "failed.jsonl")
    summary = run_writers(items, clients, limiters, written, failed)
    if summary["stopped"] is None and {item.id for item in items} <= (written.done() | failed.done()):
        written.finish()
        failed.finish()
    print(summary_line("write_key", **summary))


if __name__ == "__main__":
    main()
