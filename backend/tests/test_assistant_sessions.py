"""Change 2 (spec §4): a turn holds DB connections only around DB work, never while it waits on the model."""
import asyncio
import time

from langchain_core.messages import AIMessage

from app import config
from app.assistant import dao
from app.assistant.graph import Answer
from app.assistant.models import ChatOutcome
from app.assistant.service import AssistantRuntime, run_turn
from app.assistant.tools import NoArgs, ToolSpec, default_tools
from app.documents import dao as documents_dao
from app.ledger.db import make_session_factory
from app.retrieval.vector_index import InMemoryVectorIndex
from tests.fakes import RecordingEmbeddings, SlowScriptedChatModel


class ProbingChatModel(SlowScriptedChatModel):
    """Records how many pool connections are checked out while it is being waited on."""

    probe: object = None
    seen: list = []

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        await asyncio.sleep(self.delay / 2)
        self.seen.append(self.probe())
        return await super()._agenerate(messages, stop, run_manager, **kwargs)


def _runtime(model, tools=None):
    return AssistantRuntime(chat_model=model, embeddings=RecordingEmbeddings(), vector_index=InMemoryVectorIndex(),
                            tools=tools if tools is not None else default_tools())


def _ask(factory, runtime, tenant_id, session_id, message="What is the fee?"):
    async def go():
        return [e async for e in run_turn(session_factory=factory, runtime=runtime, tenant_id=tenant_id,
                                          session_id=session_id, message=message,
                                          hmac_key=config.PII_HMAC_KEY, vault_key=config.PII_VAULT_KEY)]
    return asyncio.run(go())


def test_a_turn_holds_no_connection_while_waiting_on_the_model(migrated_test_database, tenant_id):
    factory = make_session_factory(config.TEST_DATABASE_URL)  # its own pool: nothing else checks out from it
    pool = factory.kw["bind"].pool
    model = ProbingChatModel(delay=0.4, probe=pool.checkedout, seen=[],
                             replies=[AIMessage(content="done"), Answer(text="", citations=[], refused=True)])
    _ask(factory, _runtime(model), tenant_id, "no-hold")
    assert model.seen and max(model.seen) == 0


def test_question_tokens_are_committed_even_when_no_tool_runs(session_factory, tenant_id):
    model = SlowScriptedChatModel(delay=0, replies=[AIMessage(content="done"), Answer(text="", citations=[], refused=True)])
    _ask(session_factory, _runtime(model), tenant_id, "token-commit", message="Write to bob@example.com about fees")
    with session_factory() as session:
        question = dao.recent_turns(session, tenant_id, "token-commit", 1)[0].question_redacted
        assert "bob@example.com" not in question
        assert "bob@example.com" in documents_dao.reveal(session, tenant_id, [question], config.PII_VAULT_KEY)[0]


def test_a_failing_tool_returns_its_connection(migrated_test_database, tenant_id):
    factory = make_session_factory(config.TEST_DATABASE_URL)

    def explode(ctx, args):
        raise RuntimeError("tool failed")

    broken = ToolSpec(name="search_contracts", description="always fails", args_model=NoArgs, run=explode)
    model = SlowScriptedChatModel(delay=0, replies=[
        AIMessage(content="", tool_calls=[{"name": "search_contracts", "args": {}, "id": "c1"}])])
    final = _ask(factory, _runtime(model, tools=[broken]), tenant_id, "broken-tool")[-1]
    assert final.type == "error"
    assert factory.kw["bind"].pool.checkedout() == 0


async def _consume(factory, runtime, tenant_id):
    async for _ in run_turn(session_factory=factory, runtime=runtime, tenant_id=tenant_id, session_id="cancelled-turn",
                            message="What is the fee?", hmac_key=config.PII_HMAC_KEY, vault_key=config.PII_VAULT_KEY):
        pass


def test_a_cancelled_turn_is_still_saved(session_factory, tenant_id):
    model = SlowScriptedChatModel(delay=3, replies=[AIMessage(content="done"), Answer(text="", citations=[], refused=True)])

    async def cancel_mid_call():
        turn = asyncio.create_task(_consume(session_factory, _runtime(model), tenant_id))
        await asyncio.sleep(0.5)  # inside the 3 s model call
        turn.cancel()
        try:
            await turn
        except asyncio.CancelledError:
            pass

    asyncio.run(cancel_mid_call())
    deadline = time.monotonic() + 3
    while True:
        with session_factory() as session:
            turns = dao.recent_turns(session, tenant_id, "cancelled-turn", 1)
        if turns or time.monotonic() > deadline:
            break
        time.sleep(0.1)
    assert turns and turns[0].outcome is ChatOutcome.cancelled
