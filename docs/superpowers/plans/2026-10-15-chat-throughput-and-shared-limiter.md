# Chat throughput (N4) and shared rate limiter (N5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The owner will execute it with the `claude-agy-orch` skill.

**Goal:** Remove the two pool caps that bend chat throughput at about 3 turns/s on a 1 vCPU / 1 GB box, measure each change on the same box, and make the chat rate limiter correct across replicas with Redis.

**Architecture:** Change 1 makes the graph's model-calling nodes async so a turn waiting on the model holds no thread. Change 2 replaces the turn-long DB session in `run_turn` with short sessions run off the event loop, plus one session per tool call injected into the graph. N5 adds a Redis-backed sliding window whose check-and-record is one atomic Lua script, selected by `REDIS_URL`, proven on two replicas behind nginx.

**Tech Stack:** Python 3.12 (`/home/niki/Documents/workenv/pydev`), FastAPI 0.115, LangGraph, LangChain OpenAI, SQLAlchemy 2.0 (sync, psycopg), Postgres 18 (Docker), Redis 7 (Docker), k6 (Docker), Docker Compose, nginx.

**Spec:** `docs/superpowers/specs/2026-10-15-chat-throughput-and-shared-limiter-design.md`

## Global Constraints

- Python commands run through `/home/niki/Documents/workenv/pydev/bin/<tool>` from `backend/`; never create a `.venv`.
- One change per measurement; each measured change gets its own row in the changelog before/after table.
- Same box for every N4 run: `BOX=1:1G:1 backend/scripts/load/run_chat.sh <label>` (ladder 5,10,20,40,80,160; 1 min hold).
- Pool size and executor size stay at their defaults (SQLAlchemy 5 + 10; Python's default executor).
- Redis unreachable = fail open: allow, log `rate_limit_unavailable`, Sentry warning. Over the limit stays a 429 with `Retry-After`.
- Compose replicas: 1 CPU and 1 GB each.
- Only new dependency: `redis` in `backend/requirements.txt` (exact pin).
- Never target Railway, the public demo, or the `contract-demo` Pinecone index.
- Layering (CLAUDE.md): routes stay thin; DB access only through each package's `dao.py`.
- Commits: one line, conventional (`feat:`, `fix:`, `test:`, `docs:`, `chore:`), no AI attribution of any kind; stage files by name; never commit to `main` or `preview` (branch is `feat/measured-evidence`).
- Before marking any task done, run the whole suite: `cd backend && /home/niki/Documents/workenv/pydev/bin/pytest -q` and report any failure by name.

## Review Focus

1. A client that disconnects mid-turn still leaves a `chat_turns` row with outcome `cancelled` (the save must survive task cancellation). Test in Task 2.
2. A turn that hits the 60 s turn timeout still answers "took too long" and saves outcome `timed_out`, now that the model call is a cancellable coroutine. Test in Task 1.
3. A tool that raises mid-turn returns its pool connection (per-call session closes). Test in Task 2.
4. Redis unreachable: chat requests are admitted, not failed, and a warning is logged. Test in Task 4.
5. A refused request at the limit records nothing in Redis, so it never extends its own wait (same rule as the in-memory limiter). Test in Task 4.

---

### Task 1: Async model calls in the graph (change 1)

**Files:**
- Modify: `backend/app/assistant/graph.py` (nodes `agent`, `answer` inside `build_graph`)
- Modify: `backend/app/assistant/service.py` (the `ponytail:` comment above `graph.astream`)
- Modify: `backend/tests/fakes.py` (add `SlowScriptedChatModel`)
- Modify: `backend/tests/test_assistant_graph.py` (`_run` and the calculation test call `ainvoke`; two new tests)

**Interfaces:**
- Consumes: `build_graph(chat_model, tools, ctx)` (existing).
- Produces: graph nodes `agent` and `answer` are coroutines; the compiled graph must be driven with `ainvoke`/`astream` (`invoke` raises for async nodes). `tests.fakes.SlowScriptedChatModel(replies=[...], delay=float)` for later tasks.

- [ ] **Step 1: Add the slow fake model** to `backend/tests/fakes.py` (below `ScriptedChatModel`; add `import asyncio` and `import time` at the top):

```python
class SlowScriptedChatModel(ScriptedChatModel):
    """ScriptedChatModel taking `delay` seconds per call: blocking on the sync path, awaiting on the async one."""

    delay: float = 0.5

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        time.sleep(self.delay)
        return super()._generate(messages, stop, run_manager, **kwargs)

    async def _agenerate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        await asyncio.sleep(self.delay)
        return super()._generate(messages, stop, run_manager, **kwargs)

    def with_structured_output(self, schema: Any, include_raw: bool = False, **kwargs: Any):
        scripted = super().with_structured_output(schema, include_raw, **kwargs)

        def run(messages: list[BaseMessage]) -> Any:
            time.sleep(self.delay)
            return scripted.invoke(messages)

        async def arun(messages: list[BaseMessage]) -> Any:
            await asyncio.sleep(self.delay)
            return scripted.invoke(messages)

        return RunnableLambda(run, afunc=arun)
```

- [ ] **Step 2: Write the failing tests** in `backend/tests/test_assistant_graph.py`. Add at the top: `import asyncio`, `import time`, `from concurrent.futures import ThreadPoolExecutor`, and `SlowScriptedChatModel` to the `tests.fakes` import. Add:

```python
def test_a_turn_waiting_on_the_model_holds_no_thread(db_session, tenant_id, indexed):
    """With one executor thread, two turns overlap only if waiting on the model does not occupy a thread."""
    def turn_graph():
        model = SlowScriptedChatModel(delay=0.5, replies=[
            AIMessage(content="done"), Answer(text="", citations=[], refused=True)])
        return build_graph(model, default_tools(), _ctx(db_session, tenant_id, *indexed))

    async def two_turns() -> float:
        asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1))
        started = time.perf_counter()
        await asyncio.gather(*(turn_graph().ainvoke({"messages": [HumanMessage("q")]},
                                                    config={"recursion_limit": RECURSION_LIMIT}) for _ in range(2)))
        return time.perf_counter() - started

    # each turn makes two 0.5 s model calls: about 1 s if they overlap, about 2 s if they queue for the thread
    assert asyncio.run(two_turns()) < 1.5


def test_turn_timeout_cancels_the_model_call_and_saves_timed_out(session_factory, tenant_id, monkeypatch):
    from app import config
    from app.assistant import dao
    from app.assistant.models import ChatOutcome
    from app.assistant.service import AssistantRuntime, run_turn

    model = SlowScriptedChatModel(delay=5, replies=[AIMessage(content="done"), Answer(text="", citations=[], refused=True)])
    runtime = AssistantRuntime(chat_model=model, embeddings=RecordingEmbeddings(), vector_index=InMemoryVectorIndex(),
                               tools=default_tools())

    async def ask():
        return [e async for e in run_turn(session_factory=session_factory, runtime=runtime, tenant_id=tenant_id,
                                          session_id="timeout-turn", message="What is the fee?",
                                          hmac_key=config.PII_HMAC_KEY, vault_key=config.PII_VAULT_KEY)]

    monkeypatch.setattr(config, "CHAT_TURN_TIMEOUT_SECONDS", 0.5)
    started = time.perf_counter()
    final = asyncio.run(ask())[-1]  # asyncio.run waits for executor threads, so a blocking call shows in `elapsed`
    elapsed = time.perf_counter() - started
    assert final.type == "refused" and "too long" in final.data["text"]
    assert elapsed < 2  # the 5 s model call was cancelled, not waited out
    with session_factory() as session:
        assert dao.recent_turns(session, tenant_id, "timeout-turn", 1)[0].outcome is ChatOutcome.timed_out
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd backend && /home/niki/Documents/workenv/pydev/bin/pytest -q tests/test_assistant_graph.py -k "holds_no_thread or timeout_cancels"`
Expected: FAIL. `holds_no_thread` measures about 2 s (sync nodes queue for the single thread); `timeout_cancels` takes about 5 s (the thread runs the sleep to its end).

- [ ] **Step 4: Make the two nodes async** in `backend/app/assistant/graph.py`, inside `build_graph`:

```python
    async def agent(state: TurnState) -> dict:
        [choice, *rest] = state.get("forced_tools") or ["auto"]
        reply = await chat_model.bind_tools(schemas, tool_choice=choice).ainvoke([SystemMessage(AGENT_PROMPT), *state["messages"]])
        return {"messages": [reply], "forced_tools": rest}
```

```python
    async def answer(state: TurnState) -> dict:
        feedback = []
        if state.get("violations"):
            feedback = [HumanMessage("Your previous answer failed verification: " + "; ".join(state["violations"])
                                     + ". Fix it using only cited sources, or refuse.")]
        result = await chat_model.with_structured_output(Answer, method="json_schema", include_raw=True).ainvoke(
            [SystemMessage(ANSWER_PROMPT), *state["messages"], *feedback]
        )
        return {"answer": result["parsed"], "answer_attempts": state.get("answer_attempts", 0) + 1}
```

- [ ] **Step 5: Switch the existing graph tests to `ainvoke`** in `backend/tests/test_assistant_graph.py`:

```python
def _run(model, ctx, question):
    graph = build_graph(model, default_tools(), ctx)
    return asyncio.run(graph.ainvoke({"messages": [HumanMessage(content=question)]}, config={"recursion_limit": RECURSION_LIMIT}))
```

and in `test_calculation_question_looks_up_the_id_before_the_forced_tool`:

```python
    state = asyncio.run(graph.ainvoke({"messages": [HumanMessage("How much would the Tremblay household pay under this contract?")]},
                                      config={"recursion_limit": RECURSION_LIMIT}))
```

- [ ] **Step 6: Update the comment** in `backend/app/assistant/service.py` above `graph.astream`:

```python
                # Model calls are coroutines, so the turn timeout cancels them; tools and checks stay sync and run in
                # LangGraph's thread pool. ponytail: a timed-out tool call keeps running in its thread until it returns.
```

- [ ] **Step 7: Run the graph tests, then the whole suite**

Run: `cd backend && /home/niki/Documents/workenv/pydev/bin/pytest -q tests/test_assistant_graph.py tests/test_mock_openai.py -m "slow or not slow"` then `/home/niki/Documents/workenv/pydev/bin/pytest -q`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/assistant/graph.py backend/app/assistant/service.py backend/tests/fakes.py backend/tests/test_assistant_graph.py
git commit -m "feat(assistant): call the model asynchronously so a waiting turn holds no thread"
```

---

### Task 2: Short DB sessions off the event loop (change 2)

**Files:**
- Modify: `backend/app/assistant/graph.py` (`build_graph` signature, `run_tools`)
- Modify: `backend/app/assistant/tools.py` (`ToolContext.session` type and comment)
- Modify: `backend/app/assistant/service.py` (`run_turn` and new helpers)
- Create: `backend/tests/test_assistant_sessions.py`

**Interfaces:**
- Consumes: `tests.fakes.SlowScriptedChatModel` (Task 1); `run_turn(*, session_factory, runtime, tenant_id, session_id, message, hmac_key, vault_key, guest_id=None, document_id=None, overlay_guest=None)` (signature unchanged).
- Produces: `build_graph(chat_model, tools, ctx, open_session: Callable[[], AbstractContextManager[Session]] | None = None)`; when `open_session` is None the graph uses `ctx.session` (tests); `run_turn` passes its `session_factory`. `ToolContext.session: Session | None`.

- [ ] **Step 1: Write the failing tests** in `backend/tests/test_assistant_sessions.py`:

```python
"""Change 2 (spec §4): a turn holds DB connections only around DB work, never while it waits on the model."""
import asyncio
import time

from langchain_core.messages import AIMessage

from app import config
from app.assistant import dao
from app.assistant.graph import Answer
from app.assistant.models import ChatOutcome
from app.assistant.service import AssistantRuntime, run_turn
from app.assistant.tools import ToolSpec, NoArgs, default_tools
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


def test_a_cancelled_turn_is_still_saved(session_factory, tenant_id):
    model = SlowScriptedChatModel(delay=3, replies=[AIMessage(content="done"), Answer(text="", citations=[], refused=True)])

    async def cancel_mid_call():
        task = asyncio.create_task(asyncio.to_thread(lambda: None))  # warm the default executor
        await task
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


async def _consume(factory, runtime, tenant_id):
    async for _ in run_turn(session_factory=factory, runtime=runtime, tenant_id=tenant_id, session_id="cancelled-turn",
                            message="What is the fee?", hmac_key=config.PII_HMAC_KEY, vault_key=config.PII_VAULT_KEY):
        pass
```

- [ ] **Step 2: Run them to verify which fail**

Run: `cd backend && /home/niki/Documents/workenv/pydev/bin/pytest -q tests/test_assistant_sessions.py`
Expected: `holds_no_connection` FAILS (the turn-long session is checked out, `max(seen) == 1`); `tokens_are_committed` FAILS (no tool ran, so the final rollback dropped the token and `reveal` leaves it unresolved). `failing_tool_returns_its_connection` and `cancelled_turn_is_still_saved` may already pass: they guard behaviour that must survive the change (Review Focus 1 and 3).

- [ ] **Step 3: Inject the session opener into the graph** in `backend/app/assistant/graph.py`. Add imports:

```python
import dataclasses
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, nullcontext

from sqlalchemy.orm import Session
```

Change the signature and `run_tools`:

```python
def build_graph(chat_model: BaseChatModel, tools: Sequence[ToolSpec], ctx: ToolContext,
                open_session: Callable[[], AbstractContextManager[Session]] | None = None):
    """`open_session` gives each tool call its own short session (production passes the sessionmaker); without it the
    tools share `ctx.session` (tests that hand in one session)."""
    by_name = {spec.name: spec for spec in tools}
    schemas = [spec.schema() for spec in tools]
    session_for_call = open_session or (lambda: nullcontext(ctx.session))
```

```python
    def run_tools(state: TurnState) -> dict:
        last = state["messages"][-1]
        messages, sources, citations, retrieved = [], {}, {}, []
        unvalidated, notices = [], []
        for call in last.tool_calls:
            spec = by_name.get(call["name"])
            if spec is None:
                messages.append(ToolMessage(f"Unknown tool {call['name']}", tool_call_id=call["id"]))
                continue
            with session_for_call() as session:  # held only for this call; execute() commits its audit row
                outcome = execute(spec, dataclasses.replace(ctx, session=session), call["args"])
            messages.append(ToolMessage(outcome.content, tool_call_id=call["id"]))
            sources |= outcome.sources
            citations |= outcome.citations
            retrieved += [{"tool": spec.name, "id": source_id} for source_id in outcome.sources]
            unvalidated += [str(outcome.unvalidated_document_id)] if outcome.unvalidated_document_id else []
            notices += [outcome.system_notice] if outcome.system_notice else []
        return {"messages": messages, "sources": sources, "citations": citations, "retrieved": retrieved, "unvalidated": unvalidated, "system_notices": notices}
```

(Replace the old `from collections.abc import Sequence` line with the import above.)

- [ ] **Step 4: Loosen `ToolContext.session`** in `backend/app/assistant/tools.py`:

```python
@dataclass
class ToolContext:
    session: Session | None  # set per tool call by the graph (graph.run_tools); a test may pass one shared session
```

- [ ] **Step 5: Restructure `run_turn`** in `backend/app/assistant/service.py`. Add imports `from collections.abc import AsyncIterator, Callable` (replacing the existing `AsyncIterator` import) and `from typing import Literal, TypeVar`; add `T = TypeVar("T")` after `logger`. Replace everything from `async def run_turn(` to the end of the file with:

```python
def _with_session(session_factory: sessionmaker, work: Callable[..., T], *args) -> T:
    """One short session around one piece of DB work, so a turn holds no connection while it waits on the model."""
    with session_factory() as session:
        return work(session, *args)


def _open_turn(session: Session, tenant_id: uuid.UUID, session_id: str, message: str, hmac_key: str,
               vault_key: str) -> tuple[str, list]:
    question = documents_dao.tokenize_known_values(session, tenant_id, message, hmac_key, vault_key)
    history = []
    for turn in dao.recent_turns(session, tenant_id, session_id, HISTORY_TURNS):
        history += [HumanMessage(turn.question_redacted), AIMessage(turn.answer_redacted or "")]
    session.commit()  # new question tokens must be visible to reveal(), which runs in another session
    return question, history


def _final(turn_id: uuid.UUID, kind: Literal["answer", "refused", "clarify"], text: str, citations: list[dict]) -> TurnEvent:
    """The event that ends a turn. It names the turn so the client can attach feedback to it (spec P5 D5)."""
    return TurnEvent(kind, {"text": text, "citations": citations, "turn_id": str(turn_id)})


@dataclass(frozen=True)
class TurnEnd:
    events: list[TurnEvent]
    outcome: ChatOutcome
    record: dict


def _close_turn(session: Session, tenant_id: uuid.UUID, state: dict, turn_id: uuid.UUID, document_id: uuid.UUID | None,
                overlay_guest: uuid.UUID | None, vault_key: str) -> TurnEnd:
    """Everything after the graph that reads the database, in one session: notices, clarification, reveal."""
    answer = state["answer"]
    events = _unvalidated_events(session, tenant_id, state.get("unvalidated", []), overlay_guest)
    input_tokens, output_tokens = _usage(state.get("messages", []))
    record = {"retrieved": state.get("retrieved", []), "input_tokens": input_tokens, "output_tokens": output_tokens}
    notices = state.get("system_notices", [])
    if answer.refused and notices:
        citation = {"id": SYSTEM_CITATION_ID, "kind": "system", "source": "billing records", "detail": notices[-1]}
        text = NOT_COMPARABLE_TEXT.format(reason=notices[-1])
        return TurnEnd(events + [_final(turn_id, "refused", text, [citation])], ChatOutcome.refused,
                       record | {"answer_redacted": text, "citations": [citation]})
    if answer.refused:
        # P4: every refusal but N11 is fixed text plus a system reason; the model's own wording is never shown.
        text = FAILED_VERIFICATION_MESSAGE if answer.text == FAILED_VERIFICATION_MESSAGE else NO_EVIDENCE_MESSAGE
        citation = _no_support_citation()
        return TurnEnd(events + [_final(turn_id, "refused", text, [citation])], ChatOutcome.refused,
                       record | {"answer_redacted": text, "citations": [citation]})
    if answer.clarification:
        text = _clarifying_question(session, tenant_id, document_id)
        return TurnEnd(events + [_final(turn_id, "clarify", text, [])], ChatOutcome.clarified,
                       record | {"answer_redacted": text, "citations": []})
    cited = [state["citations"][c] | {"id": c} for c in answer.citations if c in state.get("citations", {})]
    [text, *quotes] = documents_dao.reveal(session, tenant_id, [answer.text, *(c.get("quote", "") for c in cited)], vault_key)
    shown = [c | ({"quote": q} if "quote" in c else {}) for c, q in zip(cited, quotes)]
    return TurnEnd(events + [_final(turn_id, "answer", text, shown)], ChatOutcome.answered,
                   record | {"answer_redacted": answer.text, "citations": cited})


async def run_turn(
    *, session_factory: sessionmaker, runtime: AssistantRuntime, tenant_id: uuid.UUID, session_id: str,
    message: str, hmac_key: str, vault_key: str,
    guest_id: uuid.UUID | None = None, document_id: uuid.UUID | None = None, overlay_guest: uuid.UUID | None = None,
) -> AsyncIterator[TurnEvent]:
    started = time.perf_counter()
    model_id = getattr(runtime.chat_model, "model_name", None) or config.CHAT_MODEL
    turn_id = uuid.uuid4()
    record = dict(id=turn_id, tenant_id=tenant_id, session_id=session_id, citations=[], retrieved=[],
                  answer_redacted=None, model_id=model_id, prompt_version=prompt_version(), graph_version=GRAPH_VERSION,
                  input_tokens=0, output_tokens=0, guest_id=guest_id, document_id=document_id)
    outcome = ChatOutcome.cancelled  # anything that exits early without setting an outcome was a disconnect
    question, history = await asyncio.to_thread(_with_session, session_factory, _open_turn, tenant_id, session_id,
                                                message, hmac_key, vault_key)
    record["question_redacted"] = question
    ctx = ToolContext(session=None, tenant_id=tenant_id, session_id=session_id, turn_id=turn_id,
                      embeddings=runtime.embeddings, vector_index=runtime.vector_index,
                      model=ModelConfig("openai", model_id, record["prompt_version"], Decimal(0)), hmac_key=hmac_key,
                      vault_key=vault_key, document_id=document_id, overlay_guest=overlay_guest, question=question)
    graph = build_graph(runtime.chat_model, runtime.tools, ctx, open_session=session_factory)
    state: dict = {}
    handler = get_tracing_handler()
    run_config = {"recursion_limit": RECURSION_LIMIT}
    if handler:
        run_config["callbacks"] = [handler]
        run_config["metadata"] = {
            "langfuse_session_id": session_id,
            "langfuse_tags": ["chat"],
            "prompt_version": record["prompt_version"],
            "graph_version": record["graph_version"],
            "model_id": record["model_id"],
        }
    try:
        async with asyncio.timeout(config.CHAT_TURN_TIMEOUT_SECONDS):
            # Model calls are coroutines, so the turn timeout cancels them; tools and checks stay sync and run in
            # LangGraph's thread pool. ponytail: a timed-out tool call keeps running in its thread until it returns.
            async for mode, data in graph.astream({"messages": [*history, HumanMessage(question)]},
                                                  config=run_config, stream_mode=["updates", "values"]):
                if mode == "values":
                    state = data
                else:
                    for node in data:
                        yield TurnEvent("progress", {"step": PROGRESS.get(node, "thinking")})
        end = await asyncio.to_thread(_with_session, session_factory, _close_turn, tenant_id, state, turn_id,
                                      document_id, overlay_guest, vault_key)
        record.update(end.record)
        outcome = end.outcome
        for event in end.events:
            yield event
    except TimeoutError:
        outcome = ChatOutcome.timed_out
        record["citations"] = [_no_support_citation()]
        yield _final(turn_id, "refused", "That took too long; please try a narrower question.", record["citations"])
    except GraphRecursionError:
        outcome = ChatOutcome.refused
        record["citations"] = [_no_support_citation()]
        yield _final(turn_id, "refused", "I couldn't settle on an answer within my step limit.", record["citations"])
    except Exception:  # the client gets a generic error; the details stay in the logs and the audit row
        logger.exception("chat turn failed")
        outcome = ChatOutcome.error
        yield TurnEvent("error", {"text": "Something went wrong answering that question."})
    finally:
        if handler and hasattr(handler, "last_trace_id"):
            record["trace_id"] = handler.last_trace_id
        record["latency_ms"] = int((time.perf_counter() - started) * 1000)
        # shield: a client disconnect cancels this task, and the audit row must still be written
        await asyncio.shield(asyncio.to_thread(_with_session, session_factory, dao.save_turn,
                                               ChatTurn(outcome=outcome, **record)))
```

Keep `_usage`, `_unvalidated_events`, `_clarifying_question`, `_no_support_citation` and the constants above as they are.

- [ ] **Step 6: Run the new tests, the chat and privacy tests, then the whole suite**

Run: `cd backend && /home/niki/Documents/workenv/pydev/bin/pytest -q tests/test_assistant_sessions.py tests/test_api_chat.py tests/test_assistant_graph.py tests/test_privacy_end_to_end.py tests/test_mock_openai.py -m "slow or not slow"` then `/home/niki/Documents/workenv/pydev/bin/pytest -q`
Expected: all PASS. If a test in `test_api_chat.py` depended on the turn-long session (for example a tool reading an uncommitted row written earlier in the turn), stop and report it rather than reworking the test.

- [ ] **Step 7: Commit**

```bash
git add backend/app/assistant/graph.py backend/app/assistant/tools.py backend/app/assistant/service.py backend/tests/test_assistant_sessions.py
git commit -m "feat(assistant): hold DB sessions only around DB work, off the event loop"
```

---

### Task 3: Measure changes 1 and 2 on the 1 vCPU box, with a golden gate each

**Files:**
- Modify: `backend/scripts/gate_runs.sh` (pass the demo threshold)
- Create: `backend/reports/load/<date>-n4-async-llm.steps.md`, `backend/reports/load/<date>-n4-short-sessions.steps.md`
- Modify: `CHANGELOG.md` (N4 entry and a before/after table)

**Interfaces:**
- Consumes: `backend/scripts/load/run_chat.sh` (with `BOX`), `backend/scripts/load/per_step.py`, `backend/scripts/gate_runs.sh`.
- Produces: one committed `.steps.md` per run; changelog rows.

This task runs once per change: after Task 1 is committed (label `n4-async-llm`, checked out at the Task 1 commit) and again after Task 2 (label `n4-short-sessions`). If both are already committed, measure Task 1 from a worktree: `git worktree add /tmp/claude-1000/n4-async <task-1-commit>` and run the script from that worktree's `backend/`.

- [ ] **Step 1: Pass the demo threshold to the gate** in `backend/scripts/gate_runs.sh`, adding `MIN_DENSE_SIMILARITY` to the `env` line:

```bash
  env -u ENV_FILE EVAL_RUN_ID="$PREFIX-r$n" EVAL_PAUSE_SECONDS="${EVAL_PAUSE_SECONDS:-15}" \
    MIN_DENSE_SIMILARITY="${MIN_DENSE_SIMILARITY:-0.46}" \
    "${PYDEV:?set PYDEV}/bin/pytest" -m eval tests/eval/test_golden.py -s -q 2>&1 | grep -E "eval target|corpus:|answerable|over_refusal|junk|report:|passed|failed|Error" || true
```

- [ ] **Step 2: Run the ladder** (background; about 7 min)

Run: `cd backend && BOX=1:1G:1 scripts/load/run_chat.sh n4-async-llm`
Expected: completes or stops itself on a threshold; writes `reports/load/<date>-n4-async-llm.*`. Check the prediction in `.box.tsv`: `mock_in_flight` above 12, `db_connections` reaching 15.

- [ ] **Step 3: Save the per-step table**

Run: `/home/niki/Documents/workenv/pydev/bin/python scripts/load/per_step.py reports/load/<date>-n4-async-llm > reports/load/<date>-n4-async-llm.steps.md`, then append one paragraph: box, ladder, totals (`chat_turns_served`, failed) from the k6 summary, mock stats from `.mock-stats.json`, and whether the prediction held.

- [ ] **Step 4: Golden gate, one run, real OpenAI (about $1.25, 15 min, background)**

Run: `cd backend && scripts/gate_runs.sh 1 n4-async`
Expected: `1 passed` with answerable 28/28 and junk 21/21 at threshold 0.46. A failure is a result: record it, do not change the gate.

- [ ] **Step 5: Record in the changelog.** Tick nothing yet; under the N4 item add a table (create it on the first run, add a row on the second):

```markdown
      | Run (1 vCPU / 1 GB) | Bend (turns/s at conversations) | p95 at bend | Failed | First saturated | Table |
      |---|---|---|---|---|---|
      | Baseline | 2.98 at 20 | 8.01 s | 29 at 80 | threads (12), then DB pool (15) | `2026-10-15-baseline-1cpu-1g.steps.md` |
      | Change 1, async model calls | <from the table> | <…> | <…> | <from .box.tsv> | `<date>-n4-async-llm.steps.md` |
```

Fill the row from the run (no placeholders left in the committed file), plus one line with the gate result and its report path.

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/gate_runs.sh backend/reports/load/<date>-n4-async-llm.steps.md backend/reports/load/<date>-n4-async-llm.k6.json backend/reports/load/<date>-n4-async-llm.mock-stats.json backend/reports/eval-*-n4-async-r1.json CHANGELOG.md
git commit -m "test(load): measure async model calls on the 1 vCPU box"
```

- [ ] **Step 7: Repeat Steps 2 to 6 after Task 2** with label `n4-short-sessions`, gate prefix `n4-sessions`, and commit message `test(load): measure short DB sessions on the 1 vCPU box`. Prediction to check: `db_connections` stays well below 15; the bend moves to CPU (`api_cpu_pct` near 100) or to the mock's timing. Then tick N4 in the changelog with the before/after summary.

---

### Task 4: Redis-backed sliding window limiter (N5, code)

**Files:**
- Modify: `backend/requirements.txt` (add `redis==5.2.1`)
- Modify: `backend/app/config.py` (`REDIS_URL`, `TEST_REDIS_URL`, `REDIS_TIMEOUT_SECONDS`)
- Modify: `backend/app/rate_limit.py` (`RedisWindowLimiter`, Lua script, `admit` dispatch, fail-open)
- Modify: `backend/app/deps.py` (`chat_limits` built from config)
- Modify: `backend/scripts/db_up.sh` (start a `redis:7-alpine` container)
- Create: `backend/tests/test_rate_limit_redis.py`

**Interfaces:**
- Consumes: `admit(checks: Sequence[tuple[limiter, str]]) -> float` (existing contract: 0 = allowed and recorded on every limiter; otherwise the longest wait in seconds and nothing recorded).
- Produces: `RedisWindowLimiter(client: redis.Redis, name: str, limit: int, window_seconds: float)`; `deps.build_chat_limits() -> tuple[limiter, limiter]`; `config.REDIS_URL: str | None`.

- [ ] **Step 1: Start Redis locally.** Append to `backend/scripts/db_up.sh` (before the final echo, after migrations):

```bash
REDIS_CONTAINER="$(env_or REDIS_CONTAINER_NAME fintech-ledger-redis)"
REDIS_PORT="$(env_or REDIS_PORT 6379)"
if docker inspect "$REDIS_CONTAINER" > /dev/null 2>&1; then
  [ "$(docker inspect -f '{{.State.Running}}' "$REDIS_CONTAINER")" = "true" ] || docker start "$REDIS_CONTAINER" > /dev/null
else
  echo "Creating container $REDIS_CONTAINER (redis:7-alpine)..."
  docker run -d --name "$REDIS_CONTAINER" -p "127.0.0.1:$REDIS_PORT:6379" redis:7-alpine > /dev/null
fi
echo "Redis on localhost:$REDIS_PORT ($REDIS_CONTAINER)."
```

Run: `./backend/scripts/db_up.sh` and `docker exec fintech-ledger-redis redis-cli ping`
Expected: `PONG`.

- [ ] **Step 2: Add the dependency and settings.** `backend/requirements.txt` gets a line `redis==5.2.1` (the API imports it). Install: `/home/niki/Documents/workenv/pydev/bin/pip install -r backend/requirements-worker.txt && /home/niki/Documents/workenv/pydev/bin/pip check`. In `backend/app/config.py`, after the chat limit settings:

```python
# Shared rate-limit windows (N5). Set = the limiter lives in Redis, correct across workers and replicas; unset = in
# process memory (local development, single process). Short timeouts: a Redis outage must fail fast (and open).
REDIS_URL = os.environ.get("REDIS_URL") or None
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")
REDIS_TIMEOUT_SECONDS = _float("REDIS_TIMEOUT_SECONDS", 0.5)
```

- [ ] **Step 3: Write the failing tests** in `backend/tests/test_rate_limit_redis.py`:

```python
"""N5: the Redis window must behave like the in-memory one and stay exact across processes."""
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
import redis

from app import config, deps
from app.rate_limit import RedisWindowLimiter, SlidingWindowLimiter, admit


@pytest.fixture()
def client():
    return redis.Redis.from_url(config.TEST_REDIS_URL, socket_timeout=1)


def _limiter(client, limit, window):
    return RedisWindowLimiter(client, f"test-{uuid.uuid4().hex[:8]}", limit, window)


def test_allows_up_to_the_limit_then_reports_the_wait(client):
    limiter = _limiter(client, 2, 2)
    assert admit([(limiter, "k")]) == 0
    assert admit([(limiter, "k")]) == 0
    wait = admit([(limiter, "k")])
    assert 0 < wait <= 2


def test_the_window_slides(client):
    limiter = _limiter(client, 1, 0.3)
    assert admit([(limiter, "k")]) == 0
    assert admit([(limiter, "k")]) > 0
    time.sleep(0.35)
    assert admit([(limiter, "k")]) == 0


def test_a_refused_request_records_nothing_on_any_key(client):
    tight, loose = _limiter(client, 1, 10), _limiter(client, 5, 10)
    assert admit([(tight, "a"), (loose, "ip")]) == 0
    assert admit([(tight, "a"), (loose, "ip")]) > 0
    assert client.zcard(loose.key("ip")) == 1  # the refused request did not count against the IP


def test_admission_is_exact_under_concurrent_callers(client):
    limiter = _limiter(client, 10, 30)
    with ThreadPoolExecutor(max_workers=20) as pool:
        waits = list(pool.map(lambda _: admit([(limiter, "guest")]), range(40)))
    assert sum(1 for w in waits if w == 0) == 10


def test_redis_down_fails_open_and_warns(caplog):
    unreachable = redis.Redis(host="127.0.0.1", port=1, socket_timeout=0.2, socket_connect_timeout=0.2)
    limiter = RedisWindowLimiter(unreachable, "down", 1, 10)
    with caplog.at_level(logging.WARNING):
        assert admit([(limiter, "k")]) == 0
        assert admit([(limiter, "k")]) == 0
    assert "rate_limit_unavailable" in caplog.text


def test_chat_limits_use_redis_only_when_configured(monkeypatch):
    monkeypatch.setattr(config, "REDIS_URL", config.TEST_REDIS_URL)
    assert all(isinstance(l, RedisWindowLimiter) for l in deps.build_chat_limits())
    monkeypatch.setattr(config, "REDIS_URL", None)
    assert all(isinstance(l, SlidingWindowLimiter) for l in deps.build_chat_limits())
```

- [ ] **Step 4: Run them to verify they fail**

Run: `cd backend && /home/niki/Documents/workenv/pydev/bin/pytest -q tests/test_rate_limit_redis.py`
Expected: FAIL at import: `cannot import name 'RedisWindowLimiter'`.

- [ ] **Step 5: Implement the Redis window** in `backend/app/rate_limit.py`. Update the module docstring's `ponytail:` paragraph to say the Redis window (below) is the multi-process version. Add imports `import logging`, `import uuid`, `import sentry_sdk`, and below the existing classes:

```python
logger = logging.getLogger(__name__)

# One sorted set of hit timestamps (ms) per key. Trims every window, checks every key, and records the hit on all of
# them only if all allow it: one script, so concurrent requests on any replica cannot both take the last slot.
# Time comes from Redis, so every replica uses the same clock. KEYS: one per check. ARGV: limit and window (ms) per
# key, then a unique member. Returns 0 (admitted) or the longest wait in ms.
_ADMIT_SCRIPT = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local wait = 0
for i, key in ipairs(KEYS) do
  local limit, window = tonumber(ARGV[2 * i - 1]), tonumber(ARGV[2 * i])
  redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
  if redis.call('ZCARD', key) >= limit then
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    wait = math.max(wait, tonumber(oldest[2]) + window - now)
  end
end
if wait > 0 then return wait end
for i, key in ipairs(KEYS) do
  redis.call('ZADD', key, now, ARGV[2 * #KEYS + 1])
  redis.call('PEXPIRE', key, tonumber(ARGV[2 * i]))
end
return 0
"""


class RedisWindowLimiter:
    """The same sliding window, shared by every process that uses the same Redis (workers, replicas)."""

    def __init__(self, client, name: str, limit: int, window_seconds: float) -> None:
        self.client = client
        self.name = name
        self.limit = limit
        self.window_seconds = window_seconds

    def key(self, key: str) -> str:
        return f"rl:{self.name}:{key}"


def _admit_in_redis(checks: Sequence[tuple[RedisWindowLimiter, str]]) -> float:
    client = checks[0][0].client
    keys = [limiter.key(key) for limiter, key in checks]
    args = [value for limiter, _ in checks for value in (limiter.limit, int(limiter.window_seconds * 1000))]
    try:
        wait_ms = client.eval(_ADMIT_SCRIPT, len(keys), *keys, *args, uuid.uuid4().hex)
    except Exception as error:  # a broken limiter must not take the chat down: fail open, loudly
        logger.warning("rate_limit_unavailable: %s", type(error).__name__)
        sentry_sdk.capture_message("rate limiter unavailable, allowing requests", level="warning")
        return 0.0
    return int(wait_ms) / 1000
```

and make `admit` dispatch (replace the existing `admit`):

```python
def admit(checks: Sequence[tuple[SlidingWindowLimiter, str]] | Sequence[tuple[RedisWindowLimiter, str]]) -> float:
    """0 = allowed, and the hit is recorded on every limiter. Otherwise the longest wait, and nothing is recorded,
    so a refused request never extends its own wait. Redis limiters do this in one atomic script."""
    if checks and all(isinstance(limiter, RedisWindowLimiter) for limiter, _ in checks):
        return _admit_in_redis(checks)
    wait = max(limiter.wait(key) for limiter, key in checks)
    if wait <= 0:
        for limiter, key in checks:
            limiter.hit(key)
    return wait
```

- [ ] **Step 6: Build the chat limits from config** in `backend/app/deps.py`, replacing the `chat_limits = (...)` block:

```python
def build_chat_limits():
    """Public demo (P3, N5): one pair of chat windows, per guest and per client IP. In Redis when REDIS_URL is set
    (shared by every worker and replica), else in this process."""
    if config.REDIS_URL:
        import redis  # only the deployed API needs the client

        client = redis.Redis.from_url(config.REDIS_URL, socket_timeout=config.REDIS_TIMEOUT_SECONDS,
                                      socket_connect_timeout=config.REDIS_TIMEOUT_SECONDS)
        return (RedisWindowLimiter(client, "chat:guest", config.CHAT_LIMIT_PER_GUEST, config.CHAT_LIMIT_WINDOW_SECONDS),
                RedisWindowLimiter(client, "chat:ip", config.CHAT_LIMIT_PER_IP, config.CHAT_LIMIT_WINDOW_SECONDS))
    return (SlidingWindowLimiter(config.CHAT_LIMIT_PER_GUEST, config.CHAT_LIMIT_WINDOW_SECONDS),
            SlidingWindowLimiter(config.CHAT_LIMIT_PER_IP, config.CHAT_LIMIT_WINDOW_SECONDS))


chat_limits = build_chat_limits()  # tests replace it
```

and import `RedisWindowLimiter` next to `SlidingWindowLimiter`.

- [ ] **Step 7: Run the new tests, the existing limiter tests, then the whole suite**

Run: `cd backend && /home/niki/Documents/workenv/pydev/bin/pytest -q tests/test_rate_limit_redis.py tests/test_rate_limit.py` then `/home/niki/Documents/workenv/pydev/bin/pytest -q`
Expected: all PASS.

- [ ] **Step 8: Measure the limiter's cost** (no file kept; the numbers go in the changelog)

Run from `backend/`:

```bash
/home/niki/Documents/workenv/pydev/bin/python -c "
import statistics, time, redis
from app import config
from app.rate_limit import RedisWindowLimiter, admit
c = redis.Redis.from_url(config.TEST_REDIS_URL)
g, ip = RedisWindowLimiter(c, 'bench:g', 10**9, 600), RedisWindowLimiter(c, 'bench:ip', 10**9, 600)
ms = []
for i in range(1000):
    t = time.perf_counter(); admit([(g, f'g{i % 50}'), (ip, 'one')]); ms.append((time.perf_counter() - t) * 1000)
ms.sort(); print(f'admit p50 {statistics.median(ms):.3f} ms, p95 {ms[949]:.3f} ms, n=1000')"
```

Expected: one line with p50 and p95 in milliseconds.

- [ ] **Step 9: Commit**

```bash
git add backend/requirements.txt backend/app/config.py backend/app/rate_limit.py backend/app/deps.py backend/scripts/db_up.sh backend/tests/test_rate_limit_redis.py
git commit -m "feat(api): share chat rate-limit windows across processes through Redis"
```

---

### Task 5: Two-replica proof behind nginx (N5, evidence)

**Files:**
- Create: `backend/scripts/load/compose/Dockerfile`
- Create: `backend/scripts/load/compose/docker-compose.yml`
- Create: `backend/scripts/load/compose/nginx.conf`
- Create: `backend/scripts/load/limiter_check.py`
- Create: `backend/scripts/load/limiter_check.sh`
- Create: `backend/reports/load/<date>-limiter-memory.json`, `backend/reports/load/<date>-limiter-redis.json`
- Modify: `backend/scripts/load/README.md`, `CHANGELOG.md`

**Interfaces:**
- Consumes: `REDIS_URL` wiring (Task 4); the provider mock and stub index (`OPENAI_BASE_URL`, `LOADTEST_STUB_VECTORS=1`).
- Produces: `scripts/load/limiter_check.sh <memory|redis>`, which exits 0 only when the expected admission count holds.

- [ ] **Step 1: The API image** `backend/scripts/load/compose/Dockerfile` (code is mounted read-only, so the image holds only dependencies):

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
```

- [ ] **Step 2: The stack** `backend/scripts/load/compose/docker-compose.yml`:

```yaml
# Local proof that the chat limiter holds across replicas (N5). Nothing here reaches Railway, OpenAI or Pinecone.
# The local Postgres container (fintech-ledger-db) is attached to this network by limiter_check.sh.
name: ledgerlens-load

x-app: &app
  build:
    context: ../../..
    dockerfile: scripts/load/compose/Dockerfile
  image: ledgerlens-load-app
  working_dir: /app
  volumes:
    - ../../..:/app:ro

services:
  api:
    <<: *app
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level warning
    cpus: 1
    mem_limit: 1g
    depends_on: [redis, mock]
    env_file: ../../../.env  # PII keys; everything that points elsewhere is overridden below
    environment:
      DATABASE_URL: postgresql+psycopg://ledger_app:localdev@fintech-ledger-db:5432/ledger_dev
      DEMO_MODE: "1"
      CHAT_LIMIT_PER_GUEST: "10"
      CHAT_LIMIT_PER_IP: "100000"  # one client sends everything: isolate the per-guest limit
      CHAT_LIMIT_WINDOW_SECONDS: "600"
      REDIS_URL: ${REDIS_URL-redis://redis:6379/0}  # set REDIS_URL= (empty) for the in-memory run
      OPENAI_BASE_URL: http://mock:8090/v1
      OPENAI_API_KEY: mock
      LOADTEST_STUB_VECTORS: "1"
      LANGFUSE_PUBLIC_KEY: ""
      LANGFUSE_SECRET_KEY: ""
      SENTRY_DSN: ""
      FRONTEND_URL: ""

  mock:
    <<: *app
    command: uvicorn scripts.load.mock_openai:app --host 0.0.0.0 --port 8090 --log-level warning
    environment:
      MOCK_DELAY_SCALE: "0.05"  # the check counts admissions, not latency

  redis:
    image: redis:7-alpine

  nginx:
    image: nginx:1.27-alpine
    depends_on: [api]
    ports: ["127.0.0.1:8088:80"]
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
```

- [ ] **Step 3: Round-robin with a replica marker** `backend/scripts/load/compose/nginx.conf`:

```nginx
# Round-robin over the API replicas; X-Upstream names the replica that answered (MediCoord pattern).
worker_processes 1;
events { worker_connections 1024; }
http {
  access_log off;
  resolver 127.0.0.11 valid=5s;
  upstream api { server api:8000; }
  server {
    listen 80;
    location / {
      proxy_pass http://api;
      proxy_http_version 1.1;
      proxy_set_header Connection "";
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_read_timeout 120s;
      proxy_buffering off;
      add_header X-Upstream $upstream_addr always;
    }
  }
}
```

- [ ] **Step 4: The check** `backend/scripts/load/limiter_check.py`:

```python
"""N5 proof: one guest sends 30 chat requests through nginx to 2 replicas; the per-guest limit is 10.
Usage (from backend/): python scripts/load/limiter_check.py <memory|redis> [base url]
Exit 0 only if the result matches the mode: redis = exactly 10 admitted; memory = more than 10 (each replica counts
on its own). Writes reports/load/<date>-limiter-<mode>.json."""
import json
import sys
import uuid
from datetime import date
from pathlib import Path

import httpx

REQUESTS, LIMIT = 30, 10


def main() -> int:
    mode = sys.argv[1]
    base = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8088"
    with httpx.Client(base_url=base, timeout=60) as client:
        guest = client.post("/guests").json()["id"]
        statuses, upstreams = [], set()
        for i in range(REQUESTS):
            response = client.post("/chat", headers={"X-Guest-Id": guest},
                                   json={"session_id": f"limiter-{uuid.uuid4().hex[:8]}", "message": "What is the fee?"})
            statuses.append(response.status_code)
            upstreams.add(response.headers.get("x-upstream"))
    admitted, refused = statuses.count(200), statuses.count(429)
    passed = len(upstreams) >= 2 and (admitted == LIMIT if mode == "redis" else admitted > LIMIT)
    result = {"mode": mode, "requests": REQUESTS, "limit_per_guest": LIMIT, "admitted": admitted, "refused": refused,
              "other": REQUESTS - admitted - refused, "replicas_seen": sorted(u for u in upstreams if u), "passed": passed}
    out = Path(__file__).resolve().parents[2] / "reports" / "load" / f"{date.today()}-limiter-{mode}.json"
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: The runner** `backend/scripts/load/limiter_check.sh` (`chmod +x`):

```bash
#!/usr/bin/env bash
# N5: bring up 2 API replicas behind nginx with Redis, run limiter_check.py, tear down.
# Run from backend/:  scripts/load/limiter_check.sh <memory|redis>
set -uo pipefail
cd "$(dirname "$0")/../.."
MODE="${1:?memory or redis}"
PYDEV="${PYDEV:-$(grep -E '^PYDEV=' .env 2>/dev/null | cut -d= -f2- || true)}"
COMPOSE=(docker compose -f scripts/load/compose/docker-compose.yml)
[ "$MODE" = memory ] && export REDIS_URL=
trap '"${COMPOSE[@]}" down > /dev/null 2>&1; docker network disconnect ledgerlens-load_default fintech-ledger-db > /dev/null 2>&1' EXIT
"${COMPOSE[@]}" up -d --build --scale api=2 > /dev/null
docker network connect ledgerlens-load_default fintech-ledger-db 2> /dev/null || true
for _ in $(seq 60); do curl -sf http://127.0.0.1:8088/health > /dev/null && break; sleep 1; done
"$PYDEV/bin/python" scripts/load/limiter_check.py "$MODE"
```

- [ ] **Step 6: Run both modes**

Run: `cd backend && scripts/load/limiter_check.sh memory; scripts/load/limiter_check.sh redis`
Expected: memory prints `"passed": true` with `admitted` above 10 (about 20); redis prints `"passed": true` with `admitted` exactly 10 and `refused` 20; both list 2 replicas. If `admitted` + `refused` < 30, read the API logs (`docker compose -f scripts/load/compose/docker-compose.yml logs api`) before changing anything.

- [ ] **Step 7: Document and record.** Add a "Two replicas (N5)" section to `backend/scripts/load/README.md` with the two commands and the pass rule. Under N5 in `CHANGELOG.md`: tick it and record memory vs redis admitted counts, replicas seen, the `admit` p50/p95 from Task 4 Step 8, and the limits (local; one client; Redis latency local, a managed Redis adds a network round trip).

- [ ] **Step 8: Commit**

```bash
git add backend/scripts/load/compose/Dockerfile backend/scripts/load/compose/docker-compose.yml backend/scripts/load/compose/nginx.conf backend/scripts/load/limiter_check.py backend/scripts/load/limiter_check.sh backend/scripts/load/README.md backend/reports/load/<date>-limiter-memory.json backend/reports/load/<date>-limiter-redis.json CHANGELOG.md
git commit -m "test(load): prove the Redis limiter counts exactly across two replicas"
```

---

### Task 6: Second profile and the control run

**Files:**
- Create: `backend/reports/load/<date>-n4-2cpu-2g.steps.md`, `backend/reports/load/<date>-baseline-control.steps.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `run_chat.sh` with `BOX`, `per_step.py`; baseline commit `3c5a4c3`.
- Produces: two committed `.steps.md` files and their changelog rows.

- [ ] **Step 1: 2 vCPU / 2 GB, 2 workers, on the final code** (background, about 7 min)

Run: `cd backend && BOX=2:2G:2 scripts/load/run_chat.sh n4-2cpu-2g`, then `per_step.py` into `<date>-n4-2cpu-2g.steps.md` with the same closing paragraph as Task 3 Step 3.

- [ ] **Step 2: Control: the baseline code on the 1 vCPU box**

Run:

```bash
git worktree add /tmp/claude-1000/n4-control 3c5a4c3
cp backend/scripts/load/run_chat.sh backend/scripts/load/per_step.py /tmp/claude-1000/n4-control/backend/scripts/load/
cd /tmp/claude-1000/n4-control/backend && ln -s /home/niki/Documents/saas/fintech-prod/backend/.env .env
BOX=1:1G:1 scripts/load/run_chat.sh baseline-control
```

(The current runner and sampler are copied in so the control measures the old code with today's instruments.) Then `per_step.py` into `<date>-baseline-control.steps.md`, copy it and the `.k6.json` back into the main tree's `backend/reports/load/`, and `git worktree remove /tmp/claude-1000/n4-control --force`.
Expected: the bend within about 10% of 2.98 turns/s at 20 conversations. If not, record the drift; it limits every before/after claim.

- [ ] **Step 3: Record and commit.** Add both rows to the N4 before/after table in `CHANGELOG.md` (the 2 vCPU row compared with the 1 vCPU final row; the control row compared with the first baseline).

```bash
git add backend/reports/load/<date>-n4-2cpu-2g.steps.md backend/reports/load/<date>-n4-2cpu-2g.k6.json backend/reports/load/<date>-baseline-control.steps.md backend/reports/load/<date>-baseline-control.k6.json CHANGELOG.md
git commit -m "test(load): measure the 2 vCPU profile and re-run the baseline as a control"
```

---

## Notes for the executor

- Replace `<date>` with the run date (`date +%Y-%m-%d`) everywhere; commit no file name containing `<date>`.
- Long runs (ladders, gates, the Compose check) go in the background; the owner has limited screen time. Report each run in two or three lines: bend, failures, prediction held or not.
- The golden gate spends real OpenAI money (about $1.25 per run). Run it only where this plan says.
- Stop and report, rather than improvise, if: a prediction is badly off (for example change 1 does not lift calls in flight above 12), an existing test needs semantic changes, or a run fails for an environmental reason (Docker, ports, Postgres).
