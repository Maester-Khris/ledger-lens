"""Manual golden-set run against real OpenAI + Pinecone on ledger_dev (samples ingested).
Run: $PYDEV/bin/pytest -m eval tests/eval -s"""
import asyncio
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app import config
from app.assistant.citations import numbers_in
from app.assistant.graph import prompt_version
from app.assistant.runtime import get_runtime
from app.assistant.service import run_turn
from app.ledger.db import SessionLocal
from app.ledger.types import DEMO_TENANT_ID

CASES = json.loads((Path(__file__).parent / "golden.json").read_text())
REPORTS = Path(__file__).resolve().parents[2] / "reports"


def _normal(number: str) -> str:
    return format(Decimal(number).normalize(), "f")


def _run(case: dict) -> dict:
    async def go():
        return [e async for e in run_turn(session_factory=SessionLocal, runtime=get_runtime(), tenant_id=DEMO_TENANT_ID,
                                          session_id=f"eval-{case['id']}", message=case["question"],
                                          hmac_key=config.require("PII_HMAC_KEY"), vault_key=config.require("PII_VAULT_KEY"))]
    final = asyncio.run(go())[-1]
    citations = final.data.get("citations", [])
    found = numbers_in(final.data.get("text", ""))
    return {
        "id": case["id"], "event": final.type,
        "refusal_ok": (final.type == "refused") == case["expect_refusal"],
        "citation_hit": case["expect_refusal"] or any(
            case["expect_page"] is None or c.get("page") == case["expect_page"] for c in citations
        ),
        "numbers_ok": {_normal(n) for n in case["expect_numbers"]} <= found,
        "answer": final.data.get("text"), "citations": citations,
    }


@pytest.mark.eval
def test_golden_set():
    results = [_run(case) for case in CASES]
    config_hash = hashlib.sha256(f"{config.CHAT_MODEL}|{prompt_version()}|{config.EMBEDDING_MODEL}".encode()).hexdigest()[:12]
    metrics = {key: sum(r[key] for r in results) / len(results) for key in ("refusal_ok", "citation_hit", "numbers_ok")}
    REPORTS.mkdir(exist_ok=True)
    report = REPORTS / f"eval-{config_hash}.json"
    report.write_text(json.dumps({"config_hash": config_hash, "chat_model": config.CHAT_MODEL,
                                  "metrics": metrics, "results": results}, indent=2))
    print(json.dumps(metrics, indent=2), f"\nreport: {report}")
    # Capture the real result as-is (backlog rule); the test fails only if the pipeline is broken outright.
    assert metrics["refusal_ok"] >= 0.5
