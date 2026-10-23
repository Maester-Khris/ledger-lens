"""Chat eval (plan 2026-10-21, Task 3): the answer call's mean token logprob, carried on the turn's final event as
`confidence`, so the eval can sweep a generation threshold against judged correctness. Measured only: nothing acts
on it yet."""
import asyncio

import pytest
from langchain_core.messages import AIMessage

from app import config
from app.assistant.graph import Answer, mean_logprob
from app.assistant.service import AssistantRuntime, run_turn
from app.assistant.tools import default_tools
from app.retrieval.vector_index import InMemoryVectorIndex
from tests.fakes import RecordingEmbeddings, ScriptedChatModel


def _final(session_factory, tenant_id, model, session_id):
    runtime = AssistantRuntime(chat_model=model, embeddings=RecordingEmbeddings(), vector_index=InMemoryVectorIndex(),
                               tools=default_tools())

    async def go():
        return [e async for e in run_turn(session_factory=session_factory, runtime=runtime, tenant_id=tenant_id,
                                          session_id=session_id, message="What is the fee?",
                                          hmac_key=config.PII_HMAC_KEY, vault_key=config.PII_VAULT_KEY)]
    return asyncio.run(go())[-1]


def test_mean_logprob_averages_token_logprobs():
    raw = AIMessage(content="", response_metadata={"logprobs": {"content": [{"logprob": -0.1}, {"logprob": -0.3}]}})
    assert mean_logprob(raw) == pytest.approx(-0.2)


def test_mean_logprob_absent_is_none():
    assert mean_logprob(AIMessage(content="")) is None
    assert mean_logprob(AIMessage(content="", response_metadata={"logprobs": {"content": []}})) is None


def test_final_event_carries_confidence(session_factory, tenant_id):
    model = ScriptedChatModel(replies=[AIMessage(content="done"), Answer(text="", citations=[], refused=True)],
                              answer_logprobs=[[-0.5]])
    final = _final(session_factory, tenant_id, model, "confidence-one")
    assert final.type == "refused"
    assert final.data["confidence"] == pytest.approx(-0.5)


def test_final_event_without_logprobs_has_none(session_factory, tenant_id):
    model = ScriptedChatModel(replies=[AIMessage(content="done"), Answer(text="", citations=[], refused=True)])
    assert _final(session_factory, tenant_id, model, "confidence-none").data["confidence"] is None


def test_retry_answer_reports_the_last_attempt(session_factory, tenant_id):
    uncited = Answer(text="The fee is 0.90%.", citations=[], refused=False)  # fails the citation check: retried
    model = ScriptedChatModel(replies=[AIMessage(content="done"), uncited, Answer(text="", citations=[], refused=True)],
                              answer_logprobs=[[-1.0], [-0.2]])
    final = _final(session_factory, tenant_id, model, "confidence-retry")
    assert final.data["confidence"] == pytest.approx(-0.2)


def test_runtime_asks_openai_for_logprobs():
    from app.assistant.runtime import _chat_model
    assert _chat_model().logprobs is True
