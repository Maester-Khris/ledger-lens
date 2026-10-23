# X3 Admission Control and Replica-Loss Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Past a per-process limit of chat turns in flight, `POST /chat` answers 503 "busy" at once. The chat
screen waits and retries. Measured on one replica (before/after) and on 4 replicas with one killed and restarted.

**Architecture:** A framework-free counter (`app/assistant/admission.py`, copied from MediCoord) is taken by the
first route dependency, before the guest lookup and the rate limit. The slot is held until the streamed response
finishes, and released by the response object itself so the release does not depend on the FastAPI/Starlette
version. The frontend ports MediCoord's `busy.ts`. Load tooling gains a busy class, an overload ladder and a
4-replica Compose run.

**Tech Stack:** Python 3.12, FastAPI (0.115 in the shared env, 0.143 in the load image), pytest, React + Vite +
vitest, k6, Docker Compose, nginx 1.27.

**Spec:** `docs/superpowers/specs/2026-10-21-x3-admission-control-design.md`

**Execution (owner's process):** Tasks 1 and 2 go through claude-agy-orch: Claude commits the tests first on a
`tmp/agy-x3-*` branch cut from `feat/x3-admission-control`, Gemini writes the code, Claude reviews the diff and
ff-merges it into `feat/x3-admission-control`. Tasks 3 to 6 are glue, runs and reports, and Claude does them. At
most two agy passes per chunk, then Claude implements it.

**Skills applied:** release-it (fail fast / load shedding instead of an unbounded queue; Retry-After jitter
against a thundering herd; hard-kill as the failure injection, steady state measured first); clean-architecture
(admission is framework-free and takes its limit as an argument; HTTP lives in `deps.py`/`errors.py`/the route);
pragmatic-programmer (one authoritative release point, idempotent; DRY with `RateLimited` for the problem shape);
clean-code (names from the spec; no test-only code in production modules); test-driven-development (every task
starts from a committed failing test, and for agy the tests are Claude's, never Gemini's).

## Global Constraints

- No Claude/AI attribution anywhere (commits, docs, reports). Conventional commits, files staged explicitly.
- No new Python dependency, no new npm package.
- Type hints on every Python signature; no `any` in TypeScript; prop interfaces for components.
- Routes stay thin; logic lives in a package.
- `CHAT_MAX_IN_FLIGHT` default **0 = no limit**; `CHAT_BUSY_RETRY_SECONDS` default **3**; Retry-After = base + 0 to 2 s.
- 503 problem+json: type `/problems/busy`, title `Assistant busy`, detail
  `The assistant is busy right now; try again in {n} seconds.`, header `Retry-After: {n}`, extension `retry_after`.
- Busy refusal: no DB, Redis or model call; no rate-limit hit recorded; nothing written.
- Before every measured load run: ask the owner whether the X0 ingest is idle. Nothing touches Railway, the
  `contract-demo` index, the demo DB, or a paid API.
- Do not edit `CHANGELOG.md`. Do not push.

## Review Focus

1. **Client gone on the uvicorn (ASGI 2.4) path:** `send` raises instead of a `http.disconnect` arriving. The slot
   must still come back. Pinned by `test_a_send_that_fails_mid_stream_frees_the_slot` (Task 1), run on both FastAPI
   versions.
2. **A refused turn writes nothing:** `get_guest_id` → `touch_guest` must not run when busy. Pinned by
   `test_busy_touches_no_guest_and_records_no_rate_limit_hit` (Task 1).
3. **Two refusals in one request path:** busy then rate-limited, or rate-limited after the slot was taken. Exactly
   one release, never a negative count. Pinned by `test_a_rate_limited_turn_frees_its_slot` and the idempotency
   unit test (Task 1).
4. **The frontend meets a 503 that is not busy** (nginx's own 503 during the kill, no `/problems/busy` body). It must
   be a normal error, not a retry loop. Pinned by `streamChat throws a plain error on a non-busy 503` (Task 2), and by
   the k6 classification in Task 3.
5. **A user who keeps hitting send while waiting:** no second turn starts while a retry is pending or during the
   60 s busy period. Pinned by `isWaiting` in Task 2.

---

### Task 1: Backend admission control (agy chunk)

**Files:**
- Create: `backend/app/assistant/admission.py`
- Modify: `backend/app/errors.py` (add `AssistantBusy` after `RateLimited`), `backend/app/config.py` (next to
  `CHAT_LIMIT_*`), `backend/app/deps.py` (add `take_turn_slot`), `backend/app/routes/chat.py`
- Test: `backend/tests/test_admission.py` (new, DB-free)

**Interfaces:**
- Produces:
  - `admission.Busy(Exception)`
  - `admission.Slot` with `release(self) -> None` (idempotent: the second call does nothing)
  - `admission.admit(limit: int) -> Slot`. It raises `Busy` when `limit > 0 and in_flight() >= limit`; `limit == 0`
    means no limit.
  - `admission.in_flight() -> int`
  - `admission.retry_after_seconds(base: int, rng: Callable[[], float] = random.random) -> int` = `base + int(rng() * 3)`
  - `errors.AssistantBusy(retry_after: int)`: `DomainError`, status 503, `type_slug = "busy"`, title and detail as
    in Global Constraints, `headers()` → `{"Retry-After": str(retry_after)}`, extension `retry_after`
  - `config.CHAT_MAX_IN_FLIGHT = _int("CHAT_MAX_IN_FLIGHT", 0)`,
    `config.CHAT_BUSY_RETRY_SECONDS = _int("CHAT_BUSY_RETRY_SECONDS", 3)`
  - `deps.take_turn_slot() -> Iterator[Slot]`. A `yield` dependency: `admit(config.CHAT_MAX_IN_FLIGHT)`. On `Busy`
    it logs `chat_busy in_flight=%d limit=%d` as a warning and raises
    `AssistantBusy(retry_after_seconds(config.CHAT_BUSY_RETRY_SECONDS))`. It yields the slot, and
    `except BaseException: slot.release(); raise`. It does **not** release on a normal exit.
  - `routes/chat.py`: `@router.post("", dependencies=[Depends(take_turn_slot), Depends(limit_chat)])`, a parameter
    `slot: Annotated[Slot, Depends(take_turn_slot)]` (the same cached instance), and the return value is a
    `StreamingResponse` subclass whose `__call__` is `try: await super().__call__(scope, receive, send) finally:
    self.slot.release()`.

- [ ] **Step 1: Branch** — `git switch -c tmp/agy-x3-backend` from `feat/x3-admission-control`.

- [ ] **Step 2: Write the failing tests** in `backend/tests/test_admission.py`. They are DB-free: build
  `TestClient(app)` directly (not the `client` fixture). Override `get_assistant_runtime` → `None`, and
  monkeypatch `app.routes.chat.run_turn` with a fake async generator (yields `TurnEvent("answer", {...})`, raises,
  or blocks on an `asyncio.Event`). Set `PII_HMAC_KEY` / `PII_VAULT_KEY` with `monkeypatch.setenv`, and set
  `config.CHAT_MAX_IN_FLIGHT` with monkeypatch. Raw-ASGI tests call `await app(scope, receive, send)` with an http
  scope that carries no `asgi.spec_version`. Each test asserts `admission.in_flight() == 0` at its end.
  - `test_admit_counts_up_to_the_limit_then_refuses`: limit 2 → two slots, the third raises `Busy`; after one
    release, a new admit succeeds.
  - `test_release_twice_frees_one_slot`: admit, release, release → `in_flight() == 0`, never -1.
  - `test_limit_zero_admits_everything`: 100 admits with limit 0, no `Busy`.
  - `test_retry_after_adds_up_to_two_seconds_of_jitter`: `retry_after_seconds(3, rng=lambda: 0.0) == 3`,
    `retry_after_seconds(3, rng=lambda: 0.999) == 5`.
  - `test_a_busy_turn_is_a_fast_503_with_retry_after`: limit 1, one slot already held in the test. POST /chat →
    503; `json()["type"] == "/problems/busy"`, `json()["retry_after"]` in 3..5;
    `headers["Retry-After"] == str(json()["retry_after"])`; `json()["detail"]` matches the Global Constraints text.
  - `test_busy_touches_no_guest_and_records_no_rate_limit_hit`: DEMO_MODE on, `deps.chat_limits` =
    `(SlidingWindowLimiter(1, 600), SlidingWindowLimiter(100, 600))`, `assistant_dao.touch_guest` monkeypatched to
    record calls, a valid `X-Guest-Id` sent. While busy, POST → 503 and touch_guest is not called. Release the held
    slot, POST again with the same guest → 200 (the refusal used none of the guest's allowance).
  - `test_a_finished_stream_frees_the_slot`: limit 1, POST → 200, final event `answer`, then `in_flight() == 0`.
  - `test_a_turn_that_raises_mid_stream_frees_the_slot`: the fake yields one event, then raises `RuntimeError`.
    The request may raise in the TestClient (use `pytest.raises` or `raise_server_exceptions=False`); afterwards
    `in_flight() == 0`.
  - `test_a_client_disconnect_mid_stream_frees_the_slot`: raw ASGI. The fake yields one event, then blocks.
    `receive` returns the body, then `http.disconnect` once the first body chunk was sent → `in_flight() == 0`
    (with a 2 s `asyncio.wait_for` around the app call).
  - `test_a_send_that_fails_mid_stream_frees_the_slot`: raw ASGI. `send` raises `OSError` on the first
    `http.response.body` → whatever the app raises, `in_flight() == 0`.
  - `test_a_send_that_fails_before_the_first_chunk_frees_the_slot`: `send` raises `OSError` on
    `http.response.start` → `in_flight() == 0` (case 5).
  - `test_a_rate_limited_turn_frees_its_slot`: DEMO_MODE on, a guest limiter already full → 429, and
    `in_flight() == 0`.
  - `test_an_unknown_document_frees_its_slot`: `documents_dao.find_document` monkeypatched to return `None`, the
    body has a `document_id` → 404, `in_flight() == 0`.

- [ ] **Step 3: Run to verify they fail**
  Run: `cd backend && $PYDEV/bin/pytest tests/test_admission.py -q`
  Expected: collection error / ImportError on `app.assistant.admission`. Commit the tests:
  `git add backend/tests/test_admission.py && git commit -m "test(api): add failing tests for chat admission control"`

- [ ] **Step 4: agy chunk.** Write the chunk file in the scratchpad: the Interfaces block above, the Global
  Constraints lines for copy and config, the "why" for the docstrings (the module docstring adapted from MediCoord's
  `services/admission.py`: it counts per process, there is no lock because every change happens on the event loop
  between awaits, and 0 means off until it is set from a measured knee; and on the response subclass, why a
  generator `finally` is not enough on the ASGI 2.4 path). Allowed files: the five listed under Files minus the test.
  Run:
  ```bash
  python ~/.claude/skills/claude-agy-orch/orch.py --repo /home/niki/Documents/saas/fintech-prod-x3 \
    --chunk <scratchpad>/x3-backend.md \
    --allow backend/app/assistant/admission.py --allow backend/app/errors.py --allow backend/app/config.py \
    --allow backend/app/deps.py --allow backend/app/routes/chat.py \
    --test "cd backend && /home/niki/Documents/workenv/pydev/bin/pytest tests/test_admission.py tests/test_api_chat.py tests/test_rate_limit.py -q" \
    --message "feat(api): refuse chat turns past a per-process in-flight limit with a fast 503"
  ```
  Expected: `"result": "committed"`.

- [ ] **Step 5: Run the same tests on the load image's FastAPI 0.143 / Starlette 1.8**
  Run: `docker run --rm -v "$PWD/backend:/app:ro" -w /app --entrypoint sh ledgerlens-load-app -c "pip install -q --user pytest httpx && python -m pytest -p no:cacheprovider tests/test_admission.py -q"`
  Expected: all pass. If the conftest needs the DB at import, add `--noconftest`, and note that in the commit.

- [ ] **Step 6: Review the diff** (`git show`), make small fixes yourself, run the full backend suite
  (`cd backend && $PYDEV/bin/pytest -q`). Expected: everything passes except the known
  `test_a_blank_message_is_rejected` live-key test, if it still fails here (name it in the report). Then
  `git switch feat/x3-admission-control && git merge --ff-only tmp/agy-x3-backend && git branch -d tmp/agy-x3-backend`.

### Task 2: Frontend busy waiting state (agy chunk)

**Files:**
- Create: `frontend/src/lib/busy.ts`, `frontend/src/lib/busy.test.ts`
- Modify: `frontend/src/api.ts` (`streamChat`, export `BusyError`), `frontend/src/api.test.ts`,
  `frontend/src/screens/Chat.tsx`

**Interfaces:**
- Consumes: the 503 contract from Task 1 (`type: "/problems/busy"`, `Retry-After`).
- Produces:
  - `class BusyError extends Error { retryAfterSeconds: number }`. `streamChat` throws it on a 503 whose body
    `type === '/problems/busy'`; `retryAfterSeconds` comes from the `Retry-After` header (fallback: body
    `retry_after`, then 3); `message` is the body's `detail`.
  - `busy.ts`: `SHORT_WAIT_SECONDS = 10`, `MAX_AUTO_RETRIES = 3`, `BUSY_HOLD_MS = 60_000`,
    `nextBusyStep(retryAfterSeconds: number, attempt: number): { kind: 'retry' | 'busy'; waitMs: number }`
    (MediCoord's logic), `busyMessage(busyUntil: number, now: number): string`,
    `isWaiting(turnPending: boolean, busyUntil: number | null, now: number): boolean`.
  - Copy: retry line `High demand, retrying in {n} second(s).`; busy line
    `The assistant is busy right now. Try again in about {m} minute(s).`

- [ ] **Step 1: Branch** `tmp/agy-x3-frontend` from `feat/x3-admission-control`.
- [ ] **Step 2: Write the failing tests.**
  `busy.test.ts`:
  - `nextBusyStep(3, 0)` → `{kind:'retry', waitMs:3000}`; `nextBusyStep(3, 3)` → `{kind:'busy', waitMs:60000}`;
    `nextBusyStep(30, 0)` → `{kind:'busy', waitMs:30000}`; `nextBusyStep(0, 0).waitMs === 1000`.
  - `busyMessage(now + 3000, now)` === `'High demand, retrying in 3 seconds.'`; `busyMessage(now + 1000, now)` ends in
    `'1 second.'`; `busyMessage(now + 60000, now)` === `'The assistant is busy right now. Try again in about 1 minute.'`
  - `isWaiting(false, null, 0) === false`; `isWaiting(true, null, 0) === true`; `isWaiting(false, 5000, 4000) === true`;
    `isWaiting(false, 5000, 6000) === false`.
  `api.test.ts`:
  - `streamChat throws BusyError with Retry-After on a busy 503`: a 503 with body
    `{type:'/problems/busy', detail:'…', retry_after:4}` and header `Retry-After: 4` → rejects with an
    `instanceof BusyError` whose `retryAfterSeconds === 4`.
  - `streamChat throws a plain error on a non-busy 503`: a 503 whose body is `{}` → rejects with an error that is not
    `instanceof BusyError`.
  Run `cd frontend && npx vitest run src/lib/busy.test.ts src/api.test.ts` → FAIL (missing module/export). Commit
  `test(frontend): add failing tests for the chat busy waiting state`.
- [ ] **Step 3: agy chunk.** Allowed: `busy.ts`, `api.ts`, `Chat.tsx`. Chat.tsx behaviour:
  - In `ask`, catch `BusyError` and loop with an `attempt` counter. Each `{kind:'retry'}` step keeps the turn
    `pending`, sets `busyUntil = now + waitMs`, shows `busyMessage` as the turn text (re-render each second with a
    1 s interval while `busyUntil` is set), waits, and resends the same question.
  - On `{kind:'busy'}`, the turn ends as `outcome: 'error'` with the busy line, and `busyUntil = now + waitMs` stays,
    so input stays locked.
  - `busy` (the existing flag that disables send) becomes `isWaiting(turns.some(pending), busyUntil, now)`.
    `busyUntil` is cleared when it passes. Every other error path is unchanged.
  Test command: `cd frontend && npx vitest run && npx tsc -b --noEmit`. Message:
  `feat(frontend): wait and retry on a busy chat reply, then hold a busy state`.
- [ ] **Step 4: Review the diff, then check it in the running app.** Run the API with `CHAT_MAX_IN_FLIGHT=1`,
  against the provider mock with `MOCK_LLM_MEAN_S=5`, and `npm run dev`. Ask in two tabs: the second shows the retry
  line, then answers once the first finishes. Merge `--ff-only` into `feat/x3-admission-control`.

### Task 3: Load tooling for overload (Claude)

**Files:** `backend/scripts/load/chat.js`, `backend/scripts/load/per_step.py`, `backend/scripts/load/run_chat.sh`,
`backend/scripts/load/README.md`

- [ ] **Step 1: `chat.js`.**
  - `busy = status === 503 && body type === '/problems/busy'` (parse safely). A 429 stays counted as it is today.
  - New `Trend('chat_busy_duration', true)` takes the refusal's `timings.duration`.
  - New `Rate('chat_turn_timeout')`: true when a failed turn took ≥ 55,000 ms.
  - On busy, `sleep(Number(turn.headers['Retry-After'] || 3))` before `break`.
  - `NO_ABORT=1` drops both `abortOnFail` thresholds.
  - New counter `chat_turns_cut`: a 200 without a final event (a stream cut by a killed replica).
  - `X-Upstream` is added as a tag on chat requests (`tags: {name: 'chat'}` stays, and `upstream` is set from the
    response header with `turnsServed.add(1, {upstream})`), for run B.
- [ ] **Step 2: `per_step.py`.** Add columns `Busy %` (busy / (busy + served + failed)), `Busy p95` (ms), and
  `Timeouts`. The existing column order is unchanged; the new columns are appended. Check: re-run it on
  `reports/load/2026-10-15-c3b-hmac-once` → the existing columns are byte-identical to the committed table, and the
  new ones are 0 / n/a.
- [ ] **Step 3: `run_chat.sh`.** Pass `CHAT_MAX_IN_FLIGHT` (default unset = 0) into the API env, pass `NO_ABORT` into
  k6, and print both in the run header. Document them in `README.md`.
- [ ] **Step 4: Smoke test** at a tiny ladder (no owner check needed; not a measured run):
  `BOX=1:1G:1 CHAT_MAX_IN_FLIGHT=2 backend/scripts/load/run_chat.sh x3-smoke 5 10s`. Expected: busy > 0, failed 0,
  and per_step prints the new columns. Delete the smoke outputs.
- [ ] **Step 5: Commit** `chore(load): count busy replies, timeouts and cut streams in the chat load run`.

### Task 4: 4-replica Compose run with a kill and a restart (Claude)

**Files:** `backend/scripts/load/compose/compose.yaml`, `backend/scripts/load/compose/nginx.conf`,
`backend/scripts/load/compose/replica_loss.sh` (new), `backend/scripts/load/replica_buckets.py` (new)

- [ ] **Step 1: compose.yaml.** `api` gets `CHAT_MAX_IN_FLIGHT: ${CHAT_MAX_IN_FLIGHT-64}`, `CHAT_LIMIT_PER_GUEST`
  and `CHAT_LIMIT_PER_IP` raised to 100000 (DEMO_MODE stays on, so the order admission → limiter → Redis runs). The
  `mock` delay comes from env: `MOCK_DELAY_SCALE: ${MOCK_DELAY_SCALE-0.05}`, plus `MOCK_LLM_MEAN_S` /
  `MOCK_LLM_SIGMA`. The N5 `limiter_check.sh` behaves as before. Check: `limiter_check.sh redis` still prints
  exactly 10 admitted.
- [ ] **Step 2: nginx.conf.** `resolver 127.0.0.11 valid=5s;`, `upstream api { zone api 64k; server api:8000
  resolve max_fails=1 fail_timeout=5s; }`, `proxy_connect_timeout 2s;`, and `proxy_next_upstream error timeout;`
  stays at its default. If nginx 1.27-alpine rejects `resolve`, use nginx:1.27.3-alpine or later; if that is not
  possible, give the 4 replicas fixed addresses. Record which one was used.
- [ ] **Step 3: replica_loss.sh.** Bring up redis, mock (calibrated: `MOCK_DELAY_SCALE=1 MOCK_LLM_MEAN_S=1.25
  MOCK_LLM_SIGMA=0.55`), 4 api replicas, then nginx. Connect `fintech-ledger-db` to the network. Write
  `questions.json` as run_chat.sh does. Then:
  - run k6 (`STEPS=320 STEP_HOLD=6m NO_ABORT=1 BASE_URL=http://127.0.0.1:8088`, CSV out) in the background;
  - after 10 s of ramp, sleep 120 s, `docker kill` one replica (`docker compose ps -q api | head -1`), and log the
    epoch time;
  - sleep 120 s, `docker start` it, and log the epoch time;
  - wait for k6, sample `docker stats --no-stream` every 5 s to a TSV, and tear everything down.
  All outputs go to `reports/load/<date>-<label>.*`, including `<label>.events.tsv` (kill / start times).
- [ ] **Step 4: replica_buckets.py.** From the k6 CSV and `events.tsv`, print 15 s buckets: turns/s, error %,
  error kind counts (cut / guest failed / 5xx / timeout), busy %, p95, and served per upstream. Then a summary for
  before (0:30–2:00 after the ramp), during, and after (4:30–6:00). It also reports:
  - **hung**: a request that ended more than 1 s after the kill and was cut, or hit the 120 s timeout;
  - **recovery**: the first 15 s bucket after `docker start` with 0 errors, and the restarted replica's first
    served turn.
  Unit check: `$PYDEV/bin/python -c` asserts on a 3-row synthetic CSV (bucket boundaries, the hung rule), as a
  `__main__` self-check in the file.
- [ ] **Step 5: Smoke test** at 20 conversations, 90 s hold, with the kill at 30 s and the start at 60 s (args
  `CONVERSATIONS HOLD KILL_AT START_AT`). Expected: the script ends, the buckets print, and the restarted replica
  serves again. Delete the smoke outputs.
- [ ] **Step 6: Commit** `chore(load): add the 4-replica run with one replica killed and restarted`.

### Task 5: Measured runs (Claude; ask the owner before each run whether the X0 ingest is idle)

- [ ] **A0 before:** at `feat/x3-admission-control` with `CHAT_MAX_IN_FLIGHT` unset:
  `BOX=1:1G:1 NO_ABORT=1 backend/scripts/load/run_chat.sh x3-a0-no-limit 5,10,20,40,80,160,320`, then
  `per_step.py reports/load/<date>-x3-a0-no-limit 5,10,20,40,80,160,320` → `2026-10-2x-x3-a0-no-limit.steps.md`.
- [ ] **A1 after:** the same with `CHAT_MAX_IN_FLIGHT=64` → `x3-a1-limit-64`. Check against the one-replica Done-when
  targets. If p95 at 160/320 is > 8.8 s, run once more with 48 (`x3-a1-limit-48`) and record both.
- [ ] **B:** `backend/scripts/load/compose/replica_loss.sh x3-b-4-replicas 320 6m 120 240` with the limit that met A1
  (or 64) → `2026-10-2x-x3-b-4-replicas.steps.md` with the bucket table and the summary.
- [ ] Each `.steps.md` has the same table shape as the existing ones, plus method, where it ran (machine, cores,
  box, image FastAPI version), sample size (turns per level), the limit value, and limits (from the spec's "Known
  limits"). Commit them with the run's raw `.k6.json`/`.box.tsv`, as the earlier runs did:
  `docs(reports): add the X3 admission and replica-loss load runs`.

### Task 6: Finish (Claude)

- [ ] Full backend suite `cd backend && $PYDEV/bin/pytest -q`; frontend `cd frontend && npm test && npx tsc -b`.
  Record the counts, and name any failure.
- [ ] `graphify update .` at the worktree root. Commit `graphify-out/` only if it is tracked.
- [ ] Handoff `artifacts/2026-10-2x-x3-handoff.md`: commits, the measured numbers (A0/A1/B tables), deviations from
  the spec and plan, and what is left, written as ready-to-paste CHANGELOG lines ending `→ **Not epic-tracked**`.
  `artifacts/` is local; check `git check-ignore` and do not force-add.
- [ ] Report to the owner and stop: no push, no PR. The X0 session reviews and merges.
