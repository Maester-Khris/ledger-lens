# Chat throughput (N4) and a shared rate limiter (N5): design

Date: 2026-10-15 · Sprint: `feat/measured-evidence` · Status: approved in brainstorming, awaiting spec review
Backlog: changelog sprint "Measured evidence", items N4 and N5. Code freeze Sun 2026-10-18 12:00.

## 1. Goal and how it is judged

Raise the chat path's throughput on one deployed-size box, and make the rate limiter correct with more than one
process, with every number backed by a run that states its method, box, sample size and limit.

- **Headline metric (A):** turns per second where turn p95 bends, on the 1 vCPU / 1 GB box.
- **Counter-metric:** failed turns per step (a faster bend that fails turns does not count).
- **Rule:** one change per measurement; each change gets its own row in the before/after table.

## 2. Starting point (the "before")

`backend/reports/load/2026-10-15-baseline-1cpu-1g.steps.md`, commit `3c5a4c3`. API alone in a cgroup of 1 vCPU and
1 GiB, one uvicorn worker; Postgres, provider mock (chat call mean 1.25 s, sigma 0.55), stub index and k6 outside.

| Conversations | Turns/s | p50 | p95 | Failed | API CPU max | DB connections | Model calls in flight |
|---|---|---|---|---|---|---|---|
| 20 | **2.98** | 5.64 s | 8.01 s | 0 | 24% | 15 | 12 |
| 40 | 1.88 | 11.38 s | 13.86 s | 0 | 19% | 15 | 12 |
| 80 | stopped | — | — | 29 (5.2%) | — | 15 | 12 |

Diagnosis: CPU is not the limit (24% of one core at the bend). Two software pools are:

| # | Candidate | Resource | Evidence |
|---|---|---|---|
| 1 | Sync model calls hold a thread each | threads (Python's default executor, 12 on the host) | 12 calls in flight, never more |
| 2 | One DB session held for the whole turn (`run_turn`) | DB connections (SQLAlchemy default 5 + 10) | pool pinned at 15; 30 s pool timeouts at 80 |
| 3 | Sync DB work on the event loop (tokenise, history, reveal, save) | event loop | blocks other requests while it runs |
| 4 | `get_guest_id` checks out a connection per chat request | DB connections | verified: closes before the stream starts (FastAPI 0.115), so a short checkout that queues only when 2 starves the pool |

Not in this design (measured or deferred elsewhere): rebuilding the graph every turn (CPU; matters only after 1-2),
`POST /guests` purging on every call, admission control (X3), the 102-title document list re-sent per model call
(cost; deferred in the changelog).

## 3. Change 1: async model calls (candidate 1)

- `backend/app/assistant/graph.py`: the `agent` and `answer` nodes become `async def` and call `ainvoke` on the same
  bound model (`bind_tools(...)`; `with_structured_output(Answer, method="json_schema", include_raw=True)`). Prompts,
  routing, retries and verification are unchanged. `run_tools`, `verify`, `route`, `refuse` stay sync.
- `run_turn` already drives the graph with `astream`; no service change.
- A turn waiting on the model holds no thread. OpenAI's async client allows 1,000 connections by default (checked in
  the installed SDK), so SDK connection limits are not a constraint.
- Side effect: the 60 s turn timeout now cancels an in-flight model call (today the thread runs on to its own 30 s
  call timeout); the related `ponytail:` comment in `service.py` is updated.
- Tests: the two `graph.invoke(...)` calls in `tests/test_assistant_graph.py` become `asyncio.run(graph.ainvoke(...))`;
  new test: two turns against a fake model that sleeps 1 s finish together in about 1 s, not 2.
- Prediction: model calls in flight exceed 12; DB connections pin at 15; the bend moves to the pool (about 15 turns
  in flight).

## 4. Change 2: short DB sessions, off the event loop (candidates 2, 3, 4)

- `run_turn` replaces its turn-long session with three short steps, each in its own session via `asyncio.to_thread`:
  1. **start:** tokenise the question, read the last turns, commit, close;
  2. **end:** unvalidated-field notices, clarifying-question titles, `reveal`, in one session;
  3. **save:** save the turn (already its own commit).
- `build_graph` takes an `open_session` callable. `run_tools` (sync, in a worker thread) opens one session per tool
  call; `execute` already commits its audit row (`record_invocation`), and the turn id is stored in that row's input,
  not as a foreign key to `chat_turns`, so no transaction spans tool calls. `ToolContext.session` stays the interface
  the tools use: no tool changes. Tests pass an `open_session` that wraps the existing test session.
- **Deliberate behaviour change:** new PII tokens found in a question (regex matches, stored encrypted in the vault)
  are committed in step 1. Today they are committed only when a tool call commits the same session (nearly every
  turn) and discarded by the final rollback otherwise. A later step in another session must be able to `reveal` them.
- Pool size and executor size stay at their defaults: connections now follow DB steps in flight, not turns in flight,
  and MediCoord measured that a larger pool lowered throughput on 1 vCPU. DB steps share the 12-thread executor with
  the tools node; the run shows whether that holds.
- Candidate 4 needs no code; the table shows whether its queueing disappears.
- Tests: existing service, chat route, privacy and graph tests pass (apart from the `open_session` argument); new:
  a turn holds no pool connection while waiting on a slow fake model (pool checked-out count); a new question token is
  revealed at the end of a turn with no tool call.
- Prediction: DB connections stay well below 15; the bend moves to CPU (API CPU near 100%) or to the mock's timing.
- **Next option, not built:** fully async database access (SQLAlchemy async, psycopg async driver). It removes the
  thread hops for DB work but touches DAOs in six packages (assistant, documents, retrieval, contracts, governance,
  ledger) while the rest of the app stays sync. Taken only if the profile after change 2 shows DB thread hops as the
  limit. Async DB alone would not fix candidate 2: a session held across model calls caps turns in flight either way.

## 5. N5: shared rate limiter in Redis

- `backend/app/rate_limit.py` keeps the `SlidingWindowLimiter` interface (`wait`, `hit`) and `admit(checks)`; a Redis
  implementation stores one sorted set of timestamps per key. When the limiters passed to `admit` are Redis-backed,
  `admit` runs one Lua script over all their keys: it trims each window, checks every key (guest and IP) and records
  the hit on all of them only if all allow it, atomically across replicas. In-memory limiters keep today's path. Time
  comes from Redis (`TIME`), so replicas agree.
- Wiring (`backend/app/deps.py`, `backend/app/config.py`): `REDIS_URL` set = Redis limiter; unset = today's in-memory
  limiter (local development and existing tests unchanged). New API dependency `redis` in `backend/requirements.txt`.
- Redis unreachable: **fail open**, as MediCoord does: allow the request, log `rate_limit_unavailable`, send a Sentry
  warning. Over the limit stays a 429 with `Retry-After`. Overload (too many turns in flight) is admission control,
  X3, not this item. Provider-side spend caps (backlog P3, open) are the backstop when Redis is down.
- Tests run against a real `redis:7-alpine` container started by `backend/scripts/db_up.sh` next to Postgres: limits,
  the window sliding, atomic `admit` under concurrent callers, fail-open when Redis is unreachable.
- **Two-replica proof** (MediCoord's pattern): `backend/scripts/load/compose/` with `redis`, the mock, nginx
  round-robin (adds `X-Upstream`), and 2 API replicas of **1 CPU and 1 GB** each (same box as N4; MediCoord's 768 MB
  default had no recorded reason). The local Postgres container joins the stack's network. API image: the API set
  only (`requirements.txt`, no Docling). `limiter_check.py` sends 30 chat requests from one guest through nginx with
  demo mode on and a limit of 10, checks `X-Upstream` shows both replicas, and passes only if exactly 10 are admitted
  and 20 refused. It runs on the in-memory limiter first (expected about 20 admitted) for the correctness
  before/after.
- Limiter cost: `admit` latency p50/p95 over 1,000 calls against local Redis (limit: a managed Redis adds a network
  round trip).
- The same stack later supports a 2-replica throughput run and stopping one replica mid-run (X1), not in this design.

## 6. Measurement protocol

- Same ladder (5, 10, 20, 40, 80, 160 conversations, 10 s ramp, 1 min hold), same mock settings, same box
  (`BOX=1:1G:1 backend/scripts/load/run_chat.sh <label>`), one committed `.steps.md` per run (`per_step.py`).
- Golden gate (real OpenAI, threshold 0.46, `backend/scripts/gate_runs.sh`) once after change 1 and once after
  change 2, since both touch the answer path.
- **Second profile:** after change 2, one run with `BOX=2:2G:2` (2 vCPU, 2 GB, 2 uvicorn workers); first measured
  version of MediCoord's unmeasured "1.5-2x one box" claim.
- **Control:** at the end, the baseline code (commit `3c5a4c3`, in a separate git worktree) re-run on the same box;
  within about 10% of the first baseline means no drift.
- Changelog: a before/after table, one row per run, each with its `.steps.md` path.
- Limits stated with every number: local; a cgroup quota approximates a vCPU; DB and Redis latency is local; the mock
  reproduces golden-set timing, not provider latency or limits; one run per change.

## 7. Order and time

| Step | Estimate |
|---|---|
| Change 1, tests, run, gate | about 1.5 h |
| Change 2, tests, run, gate | 2 to 3 h |
| N5 limiter, tests, Compose stack, check | 3 to 4 h |
| 2 vCPU run and control run | about 20 min |
| Write-up | after the freeze |

If time runs short, N5 stops first and this section stays as the prepared answer.

## 8. Lenses used

- release-it: timeouts, blocked threads, bulkheads (pools as the limiting resource), fail-open on a non-critical
  dependency, load test past the bend with a control run.
- system-design and ddia-systems: shared state for horizontal scaling (limiter in Redis), atomic check-and-record,
  one clock for the window.
- clean-architecture and pragmatic-programmer: tools keep their interface (`ToolContext.session`); the session
  factory is injected at the composition root; one change per measurement (tracer, then widen).
- supabase-postgres-best-practices: connection hold time, not pool size, as the lever; pool size changed only on
  measurement.
- lean-startup and lean-analytics (sprint plan): one headline metric with a counter-metric; predictions written before
  each run.
