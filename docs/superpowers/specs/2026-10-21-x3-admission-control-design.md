# X3: admission control and a replica-loss run

Date: 2026-10-21. Sprint `feat/measured-evidence`, branch `feat/x3-admission-control`. Not epic-tracked.

## Why

Today an overloaded chat API answers everyone slowly. After N4 and N7 (C3b row), one 1 vCPU / 1 GB worker serves the
whole ladder to 160 conversations with 0 failed turns, but past the knee CPU is shared by every turn: from 80 to 160
conversations throughput falls from 14.75 to 11.28 turns/s and p95 rises from 7.03 s to 17.04 s
(`backend/reports/load/2026-10-15-c3b-hmac-once.steps.md`). Further up the ladder, turns reach the 60 s per-turn
timeout. (The brief's "30 s DB-pool timeouts" describes the N3 code; N4 change 2 removed them.)

Admission control turns that into a fast, explicit "busy" answer: past a limit of turns in flight, a new turn is
refused at once, so the turns already admitted keep their normal speed. The replica run then shows whether load moves
to the remaining replicas and whether requests fail cleanly or hang when one replica dies.

## Goals

1. A per-process limit on chat turns in flight; past it, `POST /chat` answers 503 at once.
2. The chat screen waits and retries on its own, as MediCoord does, then shows a clear busy state.
3. Measured on the N3/N4 box: before/after on one replica, and 4 replicas with one hard-killed and restarted.

## Non-goals

- A cluster-wide (Redis) in-flight count. The owner chose MediCoord's design, which is per process.
- nginx retrying a busy 503 on another replica. Railway's edge does not do that, so the run should not either.
- Queueing, priorities, per-guest fairness, and autoscaling.
- Changing the guest rate limiter (N5) beyond running the admission check before it.

## Anti-goals (a failure even if it technically works)

- A slot that leaks: a turn that ends (normally, by error, or by client disconnect) without giving its slot back.
  Over time the process would refuse everything.
- A busy refusal that uses up the guest's rate-limit allowance or writes anything (a turn row, a session).
- A busy refusal that is slow (it must not touch the DB, Redis or the model).

## Decisions (owner, 2026-10-21)

| Question | Decision |
|---|---|
| Where the limit lives | **Per process**, copied from MediCoord `backend/services/admission.py`: a module-level counter on the event loop (no lock: every change happens between awaits). Each replica protects its own CPU, and capacity adds up as replicas are added. |
| Response | **503** problem+json, type `busy`, `Retry-After` header. Kept separate from the guest limiter's 429. |
| Frontend | **MediCoord's waiting state** (`webapp/src/lib/busy.ts`): retry on its own up to 3 times after `Retry-After`, showing "High demand, retrying in N s"; then a "busy, try again in about a minute" state. |
| Replica stop | **Hard kill, then restart**: `docker kill` about 1/3 through the hold, `docker start` about 2/3 through. |
| Done when | The targets in "Done when" below. |

## Builder's calls (made by Claude, check while reading)

- **Order:** admission check → guest/IP rate limit (`limit_chat`) → document check → turn. This is the order
  MediCoord uses: a refused turn stores nothing and uses none of the guest's allowance.
- **Config:** `CHAT_MAX_IN_FLIGHT` (int, default **0 = no limit**, as in MediCoord, so tests and local dev are
  unchanged) and `CHAT_BUSY_RETRY_SECONDS` (default 3). `Retry-After` = base + 0 to 2 s of jitter, so refused clients
  do not all come back at the same moment.
- **Sizing:** by Little's law, at the C3b knee (80 conversations) 14.75 turns/s × 4.11 s p50 ≈ 61 turns in flight
  with p95 still flat, and the mock saw up to 70 calls in flight. Start the measured runs at **64 per worker** and
  record the value used. If the first after-run misses the latency target, try one lower value (48) and record both.
  The chosen value goes into the compose file and the handoff, not into the code default.
- **Detail text:** "The assistant is busy right now; try again in N seconds." Title "Assistant busy".
- **Metrics:** none added. Measurement comes from k6 and the box sampler. A `chat_busy` warning log line per refusal
  is enough for the API log.
- **Where the code goes:** `backend/app/assistant/admission.py` (framework-free, no FastAPI import) holds the
  counter, `Busy` and `retry_after_seconds()`; `backend/app/errors.py` gets `AssistantBusy(DomainError)` (status 503,
  type `busy`, `Retry-After` header), shaped like `RateLimited`; the route stays thin.
- **k6 does not retry** a busy reply: it records it and ends that conversation, as it does today for a 429, but sleeps
  `Retry-After` first so a refused virtual user does not loop on `POST /guests` and add load of its own.

## The one real difference from MediCoord: the turn is a stream

MediCoord's turn is one request/response, so `with admission.admit(): return await _run_turn(...)` covers it. Ours is
an SSE `StreamingResponse`: the route returns before the turn runs, and the turn runs inside the generator. With
FastAPI 0.115 / Starlette 0.38, a `yield` dependency's exit code runs **before** the streamed body is sent, so it cannot
hold the slot either.

Requirement: the slot is taken before the rate limit and held until the stream ends. It is released exactly once in
each of these cases, and each one gets a test:

1. the stream finishes normally;
2. the turn raises inside the stream;
3. the client disconnects mid-stream (Starlette cancels the response task: `CancelledError` at an await inside the
   generator);
4. the route fails after the slot was taken and before a response exists (`RateLimited` from `limit_chat`,
   `DocumentNotFound`, a validation error raised after the dependency ran);
5. the response is never iterated (the client is gone before the first chunk).

**Two FastAPI versions are in play.** `fastapi` is unpinned in `requirements.txt`: the shared dev env has FastAPI
0.115.0 / Starlette 0.38.6, while the load image (`ledgerlens-load-app`, the same install Railway does) has
**0.143.2 / Starlette 1.8.0**, and `yield`-dependency exit timing differs between them. So the mechanism must not
depend on dependency exit timing (Claude's call; pinning is out of scope), and `tests/test_admission.py` runs in
**both**: the shared env (`$PYDEV/bin/pytest`) and inside the load image (`docker run ... ledgerlens-load-app pytest
tests/test_admission.py`, DB-free). Both runs are recorded.

Shape (Claude's call): `admission.admit()` returns a `Slot` with an idempotent `release()`, or raises `Busy`. The
route takes the slot **first thing in its body** and calls the rate limit itself (`limit_chat` moves from
`dependencies=[...]` into the body, after the slot; it stays in `deps.py` unchanged). A `try/except BaseException`
around the rate-limit call and the document check releases the slot and re-raises (case 4). The generator's `finally`
releases it (cases 1 to 3), and `StreamingResponse(..., background=BackgroundTask(slot.release))` covers case 5. The
release is idempotent, so the overlap between `finally` and the background task is harmless. A test asserts that the
in-flight count is back to 0 after each case. Validation errors on the body (422) happen before the route runs, so
they never take a slot.

## Frontend

- `frontend/src/api.ts`: `streamChat` throws a typed `BusyError` (with `retryAfterSeconds` from the header, default 3)
  on a 503 whose problem type is `busy`. Every other error path is unchanged.
- `frontend/src/lib/busy.ts` (+ `busy.test.ts`): `nextBusyStep(retryAfterSeconds, attempt)` and
  `busyMessage(busyUntil, now)`, ported from MediCoord without the emergency line. Retry when Retry-After ≤ 10 s and
  attempt < 3; otherwise show busy for 60 s.
- `Chat.tsx`: on `BusyError` the turn stays `pending`, shows the retry line counting down, and resends the same
  question. After the last retry it ends as `error` with the busy text. Typing stays disabled while it waits (the
  existing `busy` flag covers pending turns) and for the 60 s busy period after the last retry, as in MediCoord: a
  `busyUntil` state, cleared by a timer, is added to the `busy` flag.
- No new npm package.

## Measurement

Same box and ladder as N3/N4/N7: `BOX=1:1G:1 backend/scripts/load/run_chat.sh <label>`, calibrated provider mock
(mean 1.25 s, sigma 0.55), `LOADTEST_STUB_VECTORS=1`, 2 turns per conversation, 1 s reading pause, 1 min per level.
**The ladder extends to 5,10,20,40,80,160,320**, because the current code does not fail below the knee. The k6 stop
rule (p95 > 15 s or > 5% failed) stays for admitted turns; busy replies are not failures, but they are reported.

**k6 changes (`backend/scripts/load/chat.js`):** a 503 counts as busy **only when its problem type is `busy`**
(Claude's call: nginx can answer 502/503/504 on its own when a replica dies, and those are errors); the 429 count
stays as it is; a new trend
`chat_busy_duration` records how long the refusal took; a second rate, `chat_turn_timeout`, separates failures that
took ≥ 55 s (timeouts) from fast failures. `per_step.py` gets two columns: busy % and busy p95.

**Run A, one replica (1 vCPU / 1 GB, one worker):**

- A0 before: current code, `CHAT_MAX_IN_FLIGHT=0`, ladder to 320, with the k6 stop rule turned off for this run only
  (`NO_ABORT=1`) so the overload is measured instead of stopping it.
- A1 after: `CHAT_MAX_IN_FLIGHT=64`, same ladder.

Per level: turns/s (admitted), p50/p95 of admitted turns, busy %, busy p95, failed %, failure kind (fast / timeout),
CPU median, DB connections, mock in flight.

**Run B, 4 replicas (Docker Compose, N5 stack extended):** 4 `api` replicas, each `cpus: 1`, `mem_limit: 1g`, one
worker, `CHAT_MAX_IN_FLIGHT=64`, the calibrated mock (not the 0.05 delay scale of the limiter check), Redis shared,
nginx round-robin in front. **nginx is set up like a real load balancer, not left at its defaults** (Claude's call: run
B tests the app, not nginx's 60 s connect timeout). After a `docker kill` the replica's address can hang a connect,
and nginx resolves `api` only once at start, so a restarted replica with a new address would never get traffic. So:
`proxy_connect_timeout 2s`, passive checks `max_fails=1 fail_timeout=5s`, Docker's resolver (`127.0.0.11 valid=5s`)
with `server api:8000 resolve` in the upstream (nginx ≥ 1.27.3), or fixed addresses per replica if `resolve` does
not work. Connect failures go to the next replica (`proxy_next_upstream error timeout`, nginx's default: a POST that
never reached a replica is safe to resend). Busy 503s are **not** retried at nginx (non-goal). The config used is
recorded in the report. DEMO_MODE stays on as in N5, with the guest and
IP limits raised so they never trigger, so the admission → rate-limit order runs with Redis in the loop. One constant
level of **320 conversations** (about 4 × the one-replica knee) held for 6 min: kill one replica at 2:00, start it at
4:00. Results in 15 s buckets: turns/s, error %, busy %, p95, and requests per replica (`X-Upstream`). Report:

- before (0:30–2:00), during (2:00–4:00), after (4:30–6:00);
- what happened to the turns in flight on the killed replica (k6 sees a cut stream: how many, and how fast they
  ended);
- whether any request hung (anything that did not end within 1 s of the kill, or that hit the 120 s k6 timeout);
- recovery time: from `docker start` until the restarted replica serves again, and until the error rate and p95 of
  a 15 s bucket are back within the before band.

Expected (a guess to check, not a target): with 3 replicas at 320 conversations, each is about 1/3 over its knee, so
the admission limit should show up as busy replies rather than slower turns.

**Before every measured run, ask the owner whether the X0 ingest is idle.** No paid API is touched (mock + stub
index), and nothing reaches Railway, Pinecone or the demo database (`run_chat.sh` already refuses the demo index).

Reports: `backend/reports/load/2026-10-2x-x3-<label>.steps.md`, same table shape as the existing ones, each with
method, where it ran, sample size and limits.

## Done when

**One replica (A1 against A0):**

- p95 of admitted turns at 160 and 320 conversations ≤ 1.25 × the knee p95 (C3b at 80: 7.03 s → **≤ 8.8 s**);
- busy replies p95 **< 100 ms**;
- **0** timeouts (no turn ≥ 55 s), no other failed turn;
- admitted turns/s at 160 and 320 ≥ **90%** of the 14.75 peak (≥ 13.3).

**Four replicas (run B):**

- no request hangs: every request ends answered, busy, or cut, and a cut stream ends within 1 s of the kill;
- the error rate is back to 0 within **30 s** of `docker start` (the clock starts at the command, not at "healthy",
  so slow start-up counts). **Error** = every request that did not end answered/refused/clarify or `busy`: cut
  streams, a failed `POST /guests`, proxy 502/503/504, timeouts. Each kind is counted separately in the report;
- the requests-per-replica split shows the restarted replica taking traffic again.

**Code:** backend tests pass in full (including the five release cases), the frontend tests pass, and
`graphify update .` has been run.

If a target is missed, the run is still recorded as measured, with the miss and its likely cause; targets are not
moved after the fact.

## Known limits (go next to every number)

- Local, one machine (8 cores, 15 GB). In run B the 4 replicas take 4 cores, and k6, the mock, Postgres, Redis and
  nginx share the rest. The X0 ingest may run on the same machine (hence the check before each run).
- A cgroup / Compose CPU quota approximates a vCPU. DB and Redis latency are local, not a private network.
- The mock reproduces golden-set timing, not live provider latency or rate limits.
- One run per configuration.
- The per-process limit is per worker: a box with N workers admits N × the limit.

## Files expected to change

`backend/app/assistant/admission.py` (new), `backend/app/errors.py`, `backend/app/config.py`,
`backend/app/routes/chat.py`, `backend/tests/test_admission.py` (new), `frontend/src/api.ts`,
`frontend/src/lib/busy.ts` (+ test, new), `frontend/src/screens/Chat.tsx`, `backend/scripts/load/chat.js`,
`backend/scripts/load/per_step.py`, `backend/scripts/load/run_chat.sh` (pass `CHAT_MAX_IN_FLIGHT`, `NO_ABORT`),
`backend/scripts/load/compose/*` (4 replicas, calibrated mock, kill/start runner), reports under
`backend/reports/load/`, handoff `artifacts/2026-10-2x-x3-handoff.md`.
