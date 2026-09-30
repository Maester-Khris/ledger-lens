import asyncio
import json
import os
import random
import statistics
import subprocess
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import text

from app import config
from app.ledger.dao import create_account
from app.ledger.types import DEMO_TENANT_ID, NormalBalance
from tests.support import BACKEND_DIR

pytestmark = pytest.mark.stress

PORT = 8765
BASE_URL = f"http://127.0.0.1:{PORT}"
WORKERS = 4
CONCURRENCY = 50
NEW_KEYS = 300
DUPLICATED_KEYS = 50
COPIES_PER_DUPLICATE = 3
HOT_ACCOUNT_POSTINGS = 50
MAX_409_RETRIES = 5
REPORT_PATH = BACKEND_DIR / "reports" / "concurrency.json"


@pytest.fixture(scope="module")
def live_server(migrated_test_database):
    env = {**os.environ, "DATABASE_URL": config.TEST_DATABASE_URL}
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT),
         "--workers", str(WORKERS), "--log-level", "warning"],
        cwd=BACKEND_DIR,
        env=env,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{BASE_URL}/health", timeout=1).status_code == 200:
                    break
            except httpx.TransportError:
                time.sleep(0.2)
        else:
            pytest.fail("uvicorn did not start within 20s")
        yield BASE_URL
    finally:
        process.terminate()
        process.wait(timeout=10)


def _body(debit_id, credit_id, amount):
    return {
        "description": "stress",
        "source": "stress_test",
        "entries": [
            {"account_id": str(debit_id), "direction": "debit", "amount": amount},
            {"account_id": str(credit_id), "direction": "credit", "amount": amount},
        ],
    }


def _build_requests(run_id, accounts, hot_account, counter_account, rng):
    requests = []
    for n in range(NEW_KEYS):
        debit, credit = rng.sample(accounts, 2)
        requests.append((f"stress-{run_id}-new-{n}", _body(debit, credit, rng.randint(1, 10_000))))
    for n in range(DUPLICATED_KEYS):
        debit, credit = rng.sample(accounts, 2)
        body = _body(debit, credit, rng.randint(1, 10_000))
        requests.extend([(f"stress-{run_id}-dup-{n}", body)] * COPIES_PER_DUPLICATE)
    hot_amounts = [rng.randint(1, 10_000) for _ in range(HOT_ACCOUNT_POSTINGS)]
    for n, amount in enumerate(hot_amounts):
        requests.append((f"stress-{run_id}-hot-{n}", _body(hot_account, counter_account, amount)))
    rng.shuffle(requests)
    return requests, sum(hot_amounts)


async def _fire_all(base_url, requests):
    results = []  # (key, final_status, first_attempt_seconds)
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def fire(client, key, body):
        async with semaphore:
            start = time.perf_counter()
            response = await client.post("/postings", json=body, headers={"Idempotency-Key": key})
            first_latency = time.perf_counter() - start
            retries = 0
            while response.status_code == 409 and retries < MAX_409_RETRIES:
                await asyncio.sleep(float(response.headers.get("Retry-After", "1")))
                response = await client.post("/postings", json=body, headers={"Idempotency-Key": key})
                retries += 1
            results.append((key, response.status_code, first_latency))

    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        await asyncio.gather(*(fire(client, key, body) for key, body in requests))
    return results


def test_concurrent_postings_keep_every_invariant(live_server, db_session):
    rng = random.Random(20260922)
    run_id = uuid.uuid4().hex[:8]
    accounts = [
        create_account(db_session, tenant_id=DEMO_TENANT_ID, name=f"stress-{run_id}-{i}",
                       currency="CAD", normal_balance=NormalBalance.debit).id
        for i in range(20)
    ]
    hot, counter = accounts[0], accounts[1]
    requests, hot_total = _build_requests(run_id, accounts, hot, counter, rng)

    results = asyncio.run(_fire_all(live_server, requests))

    statuses = Counter(status for _, status, _ in results)
    created_per_key = Counter(key for key, status, _ in results if status == 201)
    distinct_keys = {key for key, _ in requests}
    like = f"stress-{run_id}-%"

    postings_created = db_session.execute(
        text("SELECT count(*) FROM postings WHERE idempotency_key LIKE :like"), {"like": like}
    ).scalar_one()
    postings_without_two_entries = db_session.execute(
        text(
            "SELECT count(*) FROM (SELECT p.id FROM postings p JOIN entries e ON e.posting_id = p.id "
            "WHERE p.idempotency_key LIKE :like GROUP BY p.id HAVING count(*) <> 2) AS bad"
        ),
        {"like": like},
    ).scalar_one()
    imbalanced_currencies = db_session.execute(
        text(
            "SELECT count(*) FROM (SELECT a.currency FROM entries e JOIN postings p ON p.id = e.posting_id "
            "JOIN accounts a ON a.id = e.account_id WHERE p.idempotency_key LIKE :like GROUP BY a.currency "
            "HAVING SUM(CASE WHEN e.direction = 'debit' THEN e.amount ELSE -e.amount END) <> 0) AS bad"
        ),
        {"like": like},
    ).scalar_one()
    hot_debits = db_session.execute(
        text(
            "SELECT COALESCE(SUM(e.amount), 0) FROM entries e JOIN postings p ON p.id = e.posting_id "
            "WHERE p.idempotency_key LIKE :hot AND e.account_id = :account AND e.direction = 'debit'"
        ),
        {"hot": f"stress-{run_id}-hot-%", "account": hot},
    ).scalar_one()

    latencies_ms = sorted(seconds * 1000 for _, _, seconds in results)
    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "requests": len(requests),
        "distinct_keys": len(distinct_keys),
        "postings_created": postings_created,
        "duplicate_postings": postings_created - len(distinct_keys),
        "imbalanced_currencies": imbalanced_currencies,
        "hot_account_lost_updates": hot_total - int(hot_debits),
        "status_counts": {str(code): count for code, count in sorted(statuses.items())},
        "latency_ms": {
            "p50": round(statistics.median(latencies_ms), 1),
            "p99": round(statistics.quantiles(latencies_ms, n=100)[98], 1),
            "max": round(latencies_ms[-1], 1),
        },
        "concurrency": CONCURRENCY,
        "workers": WORKERS,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n")

    assert set(statuses) <= {200, 201}, f"unexpected statuses: {statuses}"
    assert all(created_per_key[key] == 1 for key in distinct_keys)
    assert postings_created == len(distinct_keys)
    assert postings_without_two_entries == 0
    assert imbalanced_currencies == 0
    assert int(hot_debits) == hot_total
