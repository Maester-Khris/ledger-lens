"""Stand-in for the OpenAI API (chat completions and embeddings) for load tests, so a test measures this API and not
the provider's latency, rate limits or bill. Point the API at it with OPENAI_BASE_URL=http://127.0.0.1:8090/v1 and
LOADTEST_STUB_VECTORS=1 (scripts/load/README.md). Pattern from MediCoord Sprint 22.

    uvicorn scripts.load.mock_openai:app --port 8090        (from backend/)

It plays the agent's real path: the first agent call searches, the next one stops, and the answer call returns a
structured Answer that quotes and cites the first passage the search returned, so citation checking passes for real.
Settings (env): MOCK_LLM_MEAN_S (mean chat call time, s), MOCK_LLM_SIGMA (log-normal spread), MOCK_EMBED_S (embedding
call time, s), MOCK_DELAY_SCALE (multiplies every delay; 0 answers at once). GET /stats, POST /stats/reset."""
import asyncio
import json
import math
import os
import random
import time
import uuid

from fastapi import FastAPI, Request

app = FastAPI(title="OpenAI mock")
EMBEDDING_DIMENSIONS = 1536
_stats: dict[str, int] = {}
_in_flight = 0


def reset_stats() -> None:
    global _in_flight
    _stats.clear()
    _stats.update(chat_calls=0, tool_calls=0, answers=0, refusals=0, embedding_calls=0, peak_in_flight=0)
    _in_flight = 0


reset_stats()


def _setting(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def chat_delay() -> float:
    """Log-normal with the configured mean (calibrated against recorded real turns, see the README)."""
    mean, sigma = _setting("MOCK_LLM_MEAN_S", 1.0), _setting("MOCK_LLM_SIGMA", 0.35)
    return random.lognormvariate(math.log(mean) - sigma ** 2 / 2, sigma) * _setting("MOCK_DELAY_SCALE", 1.0)


async def _wait(seconds: float) -> None:
    global _in_flight
    _in_flight += 1
    _stats["peak_in_flight"] = max(_stats["peak_in_flight"], _in_flight)
    try:
        await asyncio.sleep(seconds)
    finally:
        _in_flight -= 1


def _since_last_question(messages: list[dict]) -> list[dict]:
    last_user = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
    return messages[last_user + 1:]


def _first_passage(messages: list[dict]) -> dict | None:
    """The first search hit in this turn's tool results: a JSON dict with {"sections": ..., "hits": [{id, text, ...}]}."""
    for message in _since_last_question(messages):
        if message.get("role") != "tool":
            continue
        try:
            payload = json.loads(message.get("content") or "")
        except (ValueError, TypeError):
            continue
        if isinstance(payload, dict):
            hits = payload.get("hits")
            if isinstance(hits, list) and hits:
                return hits[0]
    return None


def reply(body: dict) -> dict:
    """The assistant message for one chat completion request. Pure, so it is unit-tested without a server."""
    messages = body.get("messages", [])
    if body.get("response_format"):  # the answer node: structured output
        passage = _first_passage(messages)
        answer = ({"text": f"The cited passage says: {passage['text'][:300]}", "citations": [passage["id"]],
                   "refused": False, "clarification": False, "sections": []} if passage else
                  {"text": "", "citations": [], "refused": True, "clarification": False, "sections": []})
        _stats["answers" if passage else "refusals"] += 1
        return {"role": "assistant", "content": json.dumps(answer)}
    choice = body.get("tool_choice")
    forced = choice.get("function", {}).get("name") if isinstance(choice, dict) else None
    searched = any(m.get("role") == "tool" for m in _since_last_question(messages))
    name = forced or (None if searched else "search_contracts")
    if name is None:  # the agent has its evidence: hand over to the answer node
        return {"role": "assistant", "content": "I have the passages I need."}
    question = next((m.get("content") for m in reversed(messages) if m.get("role") == "user"), "")
    if name == "find_documents":
        arguments = {"name": str(question)[:200]}
    elif name == "search_contracts":
        arguments = {"query": str(question)[:200]}
    else:
        arguments = {}
    _stats["tool_calls"] += 1
    return {"role": "assistant", "content": None, "tool_calls": [{
        "id": f"call_{uuid.uuid4().hex[:12]}", "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)}}]}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> dict:
    body = await request.json()
    _stats["chat_calls"] += 1
    message = reply(body)
    await _wait(chat_delay())
    prompt_tokens = len(json.dumps(body.get("messages", [])) + json.dumps(body.get("tools", []))) // 4
    completion_tokens = len(json.dumps(message)) // 4
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}", "object": "chat.completion", "created": int(time.time()),
        "model": body.get("model", "mock"),
        "choices": [{"index": 0, "message": message,
                     "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                  "total_tokens": prompt_tokens + completion_tokens},
    }


@app.post("/v1/embeddings")
async def embeddings(request: Request) -> dict:
    body = await request.json()
    inputs = body.get("input")
    inputs = inputs if isinstance(inputs, list) and not (inputs and isinstance(inputs[0], int)) else [inputs]
    _stats["embedding_calls"] += 1
    await _wait(_setting("MOCK_EMBED_S", 0.2) * _setting("MOCK_DELAY_SCALE", 1.0))
    data = []
    for index, item in enumerate(inputs):
        rng = random.Random(json.dumps(item))  # same input, same vector
        data.append({"object": "embedding", "index": index,
                     "embedding": [rng.uniform(-1, 1) for _ in range(body.get("dimensions") or EMBEDDING_DIMENSIONS)]})
    return {"object": "list", "data": data, "model": body.get("model", "mock"),
            "usage": {"prompt_tokens": 8 * len(inputs), "total_tokens": 8 * len(inputs)}}


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/stats")
def stats() -> dict:
    return _stats | {"in_flight": _in_flight}


@app.post("/stats/reset")
def stats_reset() -> dict:
    reset_stats()
    return _stats
