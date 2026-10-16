"""Input tokens per chat turn, offline (spec section 5). Runs the golden questions, setup questions included, through
the real graph and the real retrieval (OpenAI embeddings, a fraction of a cent; the local Pinecone index), with chat
answered in-process by the provider mock (`scripts/load/mock_openai.py`, no delay, $0). Counts every chat request with
tiktoken `o200k_base` (gpt-4.1's encoding). Usage line:
`Run from backend/:  MIN_DENSE_SIMILARITY=0.43 $PYDEV/bin/python scripts/token_report.py <label>`. Writes
`reports/tokens/<date>-<label>.json` and prints one markdown row for the changelog. Limits: the mock's path (forced
tools, one search, stop) stands in for the real model's choices; the count is of the serialised request, an
approximation of OpenAI's billed count."""
import asyncio
import functools
import json
import os
import statistics
import sys
from datetime import date
from pathlib import Path

import tiktoken

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

LIMITS = (
    "the mock's path (forced tools, one search, stop) stands in for the real model's choices; "
    "the count is of the serialised request, an approximation of OpenAI's billed count."
)


@functools.cache
def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding("o200k_base")


def request_tokens(body: dict) -> list[int]:
    enc = _encoding()
    tokens: list[int] = []
    if "tools" in body and body["tools"] is not None:
        tokens.extend(enc.encode(json.dumps(body["tools"]), disallowed_special=()))
    for message in body.get("messages", []):
        parts: list[str] = [str(message.get("role", ""))]
        content = message.get("content")
        if content is None:
            parts.append("")
        elif isinstance(content, str):
            parts.append(content)
        else:
            parts.append(json.dumps(content))
        if "tool_calls" in message and message["tool_calls"] is not None:
            parts.append(json.dumps(message["tool_calls"]))
        tokens.extend(enc.encode("\n".join(parts), disallowed_special=()))
    if "response_format" in body and body["response_format"] is not None:
        tokens.extend(enc.encode(json.dumps(body["response_format"]), disallowed_special=()))
    return tokens


def shared_prefix(a: list[int], b: list[int]) -> int:
    count = 0
    for x, y in zip(a, b):
        if x != y:
            break
        count += 1
    return count


def turn_record(bodies: list[dict]) -> dict:
    calls: list[dict] = []
    agent_count = 0
    seen_answer = False
    prev_tokens: list[int] = []

    for i, body in enumerate(bodies):
        tokens = request_tokens(body)
        if "response_format" in body and body["response_format"] is not None:
            if not seen_answer:
                kind = "answer"
                seen_answer = True
            else:
                kind = "retry"
        else:
            agent_count += 1
            if agent_count == 1:
                kind = "agent 1"
            elif agent_count == 2:
                kind = "agent 2"
            else:
                kind = "agent 3+"

        prefix = 0 if i == 0 else shared_prefix(prev_tokens, tokens)
        calls.append({
            "kind": kind,
            "tokens": len(tokens),
            "shared_prefix": prefix,
        })
        prev_tokens = tokens

    return {
        "calls": calls,
        "tokens": sum(c["tokens"] for c in calls),
    }


def p95(values: list[int] | list[float]) -> int | float:
    if not values:
        return 0
    return sorted(values)[max(0, int(0.95 * len(values)) - 1)]


def summarise(turns: list[dict]) -> dict:
    turn_totals = [t["tokens"] for t in turns]
    per_turn = {
        "median": statistics.median(turn_totals) if turn_totals else 0,
        "p95": p95(turn_totals) if turn_totals else 0,
    }

    kind_tokens: dict[str, list[int]] = {}
    for turn in turns:
        for call in turn.get("calls", []):
            kind_tokens.setdefault(call["kind"], []).append(call["tokens"])

    median_by_call = {
        kind: statistics.median(tokens)
        for kind, tokens in sorted(kind_tokens.items())
    }
    calls_by_kind = {
        kind: len(tokens)
        for kind, tokens in sorted(kind_tokens.items())
    }

    prefix_sum = sum(call["shared_prefix"] for turn in turns for call in turn.get("calls", [])[1:])
    tokens_sum = sum(call["tokens"] for turn in turns for call in turn.get("calls", [])[1:])
    shared_prefix_share = (prefix_sum / tokens_sum) if tokens_sum > 0 else 0.0

    return {
        "turns": len(turns),
        "per_turn": per_turn,
        "median_by_call": median_by_call,
        "calls_by_kind": calls_by_kind,
        "shared_prefix_share": shared_prefix_share,
    }


def _format_num(n: int | float) -> str:
    return f"{int(round(n)):,}"


def row(label: str, summary: dict) -> str:
    turns = summary.get("turns", 0)
    per_turn = summary.get("per_turn", {})
    med_turn = per_turn.get("median", 0)
    p95_turn = per_turn.get("p95", 0)
    mbc = summary.get("median_by_call", {})
    a1 = mbc.get("agent 1", 0)
    a2 = mbc.get("agent 2", 0)
    ans = mbc.get("answer", 0)
    ret = mbc.get("retry", 0)
    share = summary.get("shared_prefix_share", 0.0)
    share_pct = f"{int(round(share * 100)):,}%"

    return (
        f"| {label} | {_format_num(turns)} | {_format_num(med_turn)} / {_format_num(p95_turn)} | "
        f"{_format_num(a1)} / {_format_num(a2)} / {_format_num(ans)} / {_format_num(ret)} | "
        f"{share_pct} |"
    )


async def run_report(label: str) -> list[dict]:
    import dataclasses
    import httpx
    from langchain_openai import ChatOpenAI
    from app import config
    import app.assistant.service
    from app.assistant.runtime import get_runtime
    from app.documents import dao as documents_dao
    from app.ledger.db import SessionLocal
    from app.ledger.types import DEMO_TENANT_ID
    from scripts.load import mock_openai
    from tests.eval.test_golden import CASES, expand, questions

    if config.LOADTEST_STUB_VECTORS:
        sys.exit("Refusing to run: config.LOADTEST_STUB_VECTORS is true (needs real retrieval on local index).")
    if config.PINECONE_INDEX == "contract-demo":
        sys.exit("Refusing to run: config.PINECONE_INDEX is 'contract-demo' (needs real retrieval on local index).")

    app.assistant.service.get_tracing_handler = lambda: None

    recorded_bodies: list[dict] = []

    async def _on_request(request: httpx.Request) -> None:
        if request.url.path.endswith("/chat/completions"):
            body = json.loads(await request.aread())
            recorded_bodies.append(body)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mock_openai.app),
        event_hooks={"request": [_on_request]},
    ) as client:
        chat_model = ChatOpenAI(
            model=config.CHAT_MODEL,
            api_key="mock",
            base_url="http://mock/v1",
            max_retries=0,
            http_async_client=client,
        )
        runtime = dataclasses.replace(get_runtime(), chat_model=chat_model)

        with SessionLocal() as session:
            document_ids = {
                doc.document_key: doc.id
                for doc in documents_dao.document_titles(session, DEMO_TENANT_ID)
            }

        turns: list[dict] = []
        for case in expand(CASES):
            doc_id = document_ids.get(case["document_key"]) if "document_key" in case else None
            for question in questions(case):
                recorded_bodies.clear()
                events = [
                    event
                    async for event in app.assistant.service.run_turn(
                        session_factory=SessionLocal,
                        runtime=runtime,
                        tenant_id=DEMO_TENANT_ID,
                        session_id=f"tokens-{label}-{case['id']}",
                        message=question,
                        hmac_key=config.PII_HMAC_KEY,
                        vault_key=config.PII_VAULT_KEY,
                        document_id=doc_id,
                    )
                ]
                outcome = events[-1].type if events else "unknown"
                turn = {"case": case["id"], "outcome": outcome} | turn_record(recorded_bodies)
                turns.append(turn)

        return turns


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("Usage: python scripts/token_report.py <label>")
    label = sys.argv[1]
    os.environ["MOCK_DELAY_SCALE"] = "0"
    turns = asyncio.run(run_report(label))
    summary = summarise(turns)
    backend_dir = Path(__file__).resolve().parents[1]
    reports_dir = backend_dir / "reports" / "tokens"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_file = reports_dir / f"{date.today()}-{label}.json"
    output = {
        "label": label,
        "summary": summary,
        "limits": LIMITS,
        "turns": turns,
    }
    report_file.write_text(json.dumps(output, indent=2))
    print(row(label, summary))
    print(f"written {report_file.relative_to(backend_dir)}")


if __name__ == "__main__":
    main()
