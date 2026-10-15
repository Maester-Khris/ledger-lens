"""Manual golden-set run against real OpenAI + Pinecone on the live demo configuration (P4 spec §9).
Run (from backend/): ENV_FILE=.env.demo $PYDEV/bin/pytest -m eval tests/eval -s"""
import asyncio
import json
import os
import time
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from app import config
from app.assistant.citations import numbers_in
from app.assistant.graph import prompt_version, eval_config_hash
from app.assistant.runtime import get_runtime
from app.assistant.service import run_turn
from app.documents import dao as documents_dao
from app.ledger.db import SessionLocal
from app.ledger.types import DEMO_TENANT_ID

CASES = json.loads((Path(__file__).parent / "golden.json").read_text())
REPORTS = Path(__file__).resolve().parents[2] / "reports"
# The service feeds a session's last turns back as history, so session ids must not be reused across runs.
RUN_ID = uuid.uuid4().hex[:8]
# The provider's tokens-per-minute limit, not the code, was behind the 56–59 s turns: pace the cases.
PAUSE_SECONDS = float(os.environ.get("EVAL_PAUSE_SECONDS", "5"))


def session_id(run_id: str, case: dict) -> str:
    return f"eval-{run_id}-{case['id']}"


def questions(case: dict) -> list[str]:
    """Optional "setup" questions are asked first in the same session (results discarded), then the scored question."""
    return [*case.get("setup", []), case["question"]]


def expand(cases: list[dict]) -> list[dict]:
    """Every case as written, then the ones marked "scoped" again with the chat limited to their document:
    a guest who picked a document card asks that way, and the unscoped run never exercises it."""
    return [*cases, *(c | {"id": f"{c['id']}@scoped", "document_key": c["expect_document"]} for c in cases if c.get("scoped"))]


def _document_ids() -> dict[str, uuid.UUID]:
    with SessionLocal() as session:
        return {row.document.document_key: row.document.id for row in documents_dao.list_documents(session, DEMO_TENANT_ID)}


def _normal(number: str) -> str:
    return format(Decimal(number).normalize(), "f")


JUNK = ("out_of_corpus", "false_premise", "underspecified", "nonsense", "off_topic")
EVENT_FOR = {"answer": "answer", "refuse": "refused", "clarify": "clarify"}


def score_case(case: dict, event_type: str, data: dict) -> dict:
    """Pure scoring, unit-tested in tests/test_golden_scoring.py without OpenAI."""
    citations = data.get("citations", [])
    found = numbers_in(data.get("text", ""))
    if case["category"] in ("underspecified", "nonsense"):  # a clarifying question or a refusal are both acceptable
        behaviour_ok = event_type in ("clarify", "refused")
    else:
        behaviour_ok = event_type == EVENT_FOR[case["expect"]]
    citation_hit = case["expect"] != "answer" or any(
        case["expect_page"] is None or c.get("page") == case["expect_page"] for c in citations
    )
    if case.get("expect_system_notice"):  # explained abstention (N11): only the billing-records reason counts
        behaviour_ok = citation_hit = any(c.get("kind") == "system" and c.get("source") == "billing records"
                                          for c in citations)
    return {"id": case["id"], "category": case["category"], "event": event_type, "behaviour_ok": behaviour_ok,
            "citation_hit": citation_hit,
            "numbers_ok": {_normal(n) for n in case.get("expect_numbers", [])} <= found}


def _rate(results: list[dict], key: str) -> float:
    return sum(r[key] for r in results) / len(results) if results else 1.0


def summarise(results: list[dict]) -> dict:
    graded = [r for r in results if r["category"] in ("answerable", "explained")]
    answerable = [r for r in results if r["category"] == "answerable"]
    junk = [r for r in results if r["category"] in JUNK]
    return {
        "answerable": {key: _rate(graded, key) for key in ("behaviour_ok", "citation_hit", "numbers_ok")},
        "over_refusal": sum(r["event"] != "answer" for r in answerable) / len(answerable) if answerable else 0.0,
        "junk_acceptable": _rate(junk, "behaviour_ok"),
        "junk_by_category": {c: _rate([r for r in junk if r["category"] == c], "behaviour_ok")
                             for c in JUNK if any(r["category"] == c for r in junk)},
    }


def gate_failures(summary: dict) -> list[str]:
    """P4 go/no-go (spec §7.4): no answerable refused, junk >= 90% overall and >= 75% in every category."""
    failures = []
    if summary["over_refusal"] > 0:
        failures.append(f"over-refusal {summary['over_refusal']:.0%} > 0%")
    if summary["junk_acceptable"] < 0.90:
        failures.append(f"junk overall {summary['junk_acceptable']:.0%} < 90%")
    failures += [f"{category} {rate:.0%} < 75%" for category, rate in summary["junk_by_category"].items() if rate < 0.75]
    return failures


def _run(case: dict, document_ids: dict[str, uuid.UUID]) -> dict:
    # The session-scoped `document_settings` fixture overwrites config.PII_HMAC_KEY/PII_VAULT_KEY
    # with random per-run keys for hermetic unit tests. This eval decrypts real vault rows written
    # by a real ingestion run, so it needs the real keys from the environment, not the patched ones.
    async def go(question: str):
        return [e async for e in run_turn(session_factory=SessionLocal, runtime=get_runtime(), tenant_id=DEMO_TENANT_ID,
                                          session_id=session_id(RUN_ID, case), message=question,
                                          hmac_key=os.environ["PII_HMAC_KEY"], vault_key=os.environ["PII_VAULT_KEY"],
                                          document_id=document_ids[case["document_key"]] if "document_key" in case else None)]
    retried = False
    for question in questions(case):  # only the last one (the case's own question) is scored
        final = asyncio.run(go(question))[-1]
        if final.type == "error":  # a provider error (rate limit) says nothing about behaviour: wait out the
            retried = True         # per-minute window and ask once more, in the same session
            time.sleep(65)
            final = asyncio.run(go(question))[-1]
    return score_case(case, final.type, final.data) | {
        "answer": final.data.get("text"), "citations": final.data.get("citations", []),
    } | ({"retried": True} if retried else {})


@pytest.mark.eval
def test_golden_set():
    print(f"eval target: db={str(config.DATABASE_URL).rsplit('/', 1)[-1]} index={config.PINECONE_INDEX} "
          f"threshold={config.MIN_DENSE_SIMILARITY} hash={eval_config_hash()} run={RUN_ID}")
    results = []
    document_ids = _document_ids()
    for position, case in enumerate(expand(CASES)):
        if position:
            time.sleep(PAUSE_SECONDS)
        results.append(_run(case, document_ids))
    config_hash = eval_config_hash()
    summary = summarise(results)
    REPORTS.mkdir(exist_ok=True)
    relevance = sorted(REPORTS.glob("relevance-*.json"), key=lambda p: p.stat().st_mtime)
    report = REPORTS / f"eval-{config_hash}.json"
    report.write_text(json.dumps({
        "config_hash": config_hash, "run_id": RUN_ID, "chat_model": config.CHAT_MODEL,
        "min_dense_similarity": config.MIN_DENSE_SIMILARITY,
        "relevance_report": relevance[-1].name if relevance else None, "summary": summary, "results": results,
    }, indent=2))
    print(json.dumps(summary, indent=2), f"\nreport: {report}")
    failures = gate_failures(summary)
    assert not failures, "P4 gate failed: " + "; ".join(failures)
