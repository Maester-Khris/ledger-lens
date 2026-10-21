# Load tests

Local only. Never point these at the public demo (Railway) or the `contract-demo` index.

## Provider mock (N2)

`mock_openai.py` stands in for OpenAI chat completions and embeddings; `LOADTEST_STUB_VECTORS=1` replaces Pinecone
with a read-only stub that serves real, current passages from Postgres. Together every chat turn runs the real path
(search, answer, citation check) with no provider call and no bill.

```bash
cd backend
MOCK_LLM_MEAN_S=1.25 MOCK_LLM_SIGMA=0.55 $PYDEV/bin/uvicorn scripts.load.mock_openai:app --port 8090
OPENAI_BASE_URL=http://127.0.0.1:8090/v1 OPENAI_API_KEY=mock LOADTEST_STUB_VECTORS=1 $PYDEV/bin/uvicorn app.main:app
curl -s localhost:8090/stats        # chat and embedding calls, answers, refusals, peak in flight
```

**Calibration** (`scripts/load/calibrate_mock.sh <mean> <sigma>`): the 49 golden cases through the real graph with
the mock, turn time compared with the 147 real turns of 2026-10-15 (gpt-4.1, 102 documents). Accepted rule: median
and p95 within 10%.

| Settings | Median (real 3.86 s) | p95 (real 7.11 s) |
|---|---|---|
| mean 1.1 s, sigma 0.35 | 3.46 s (-10.4%) | 4.79 s (-32.6%) |
| mean 1.2 s, sigma 0.7 | 3.57 s (-7.5%) | 8.21 s (+15.5%) |
| **mean 1.25 s, sigma 0.55** (two runs) | 3.69 s (-4.4%) | 6.83 s (-3.9%) |

Limits: one chat call's time is drawn independently of its prompt size; turn time is matched, per-call time is not
(no traces were recorded for the real runs); the mock reproduces golden-set timing, not live provider latency, rate
limits or outages; the stub index skips Pinecone's network time, which the mock delay absorbs.

## Admission control (X3)

`CHAT_MAX_IN_FLIGHT=<n>` caps chat turns in flight per API worker (unset or 0 = no limit); past it `POST /chat`
answers 503 `/problems/busy` with `Retry-After` at once. `chat.js` counts those as busy (not failed), records how
long a refusal took (`chat_busy_duration`), and tags each failure with its kind (`guest`, `cut`, `timeout`,
`http_<status>`, `error_event`). `NO_ABORT=1` runs the whole ladder past the stop rule, to measure overload.
`per_step.py` appends Busy %, Busy p95 and Timeouts.

```bash
cd backend
BOX=1:1G:1 NO_ABORT=1 scripts/load/run_chat.sh x3-a0-no-limit 5,10,20,40,80,160,320
BOX=1:1G:1 NO_ABORT=1 CHAT_MAX_IN_FLIGHT=64 scripts/load/run_chat.sh x3-a1-limit-64 5,10,20,40,80,160,320
```

## Two replicas, shared rate limit (N5)

`compose/` runs nginx (round-robin, `X-Upstream` names the replica that answered) in front of 2 API replicas of
1 CPU and 1 GB each, with Redis and the provider mock; the local Postgres container joins the stack's network.
`limiter_check.sh` brings it up, sends 30 chat requests from one guest (limit 10 per guest) and tears it down.

```bash
cd backend
scripts/load/limiter_check.sh memory   # pass = more than 10 admitted: each replica counts on its own
scripts/load/limiter_check.sh redis    # pass = exactly 10 admitted: one window shared through Redis
```

Results land in `reports/load/<date>-limiter-<mode>.json`.

## Four replicas, one killed and restarted (X3)

`compose/replica_loss.sh` runs the same stack with 4 replicas (each `CHAT_MAX_IN_FLIGHT=64`, guest limit raised so
it never triggers, the calibrated mock), holds one level of conversations, hard-kills one replica (`docker kill`: a
crash, its streams are cut) and starts it again. nginx is set up like a load balancer (re-resolves replicas every
5 s, skips a failed one for 5 s, 2 s connect timeout); a busy 503 is not retried at nginx. `replica_buckets.py`
prints 15 s buckets (turns/s, p95, busy, failures by kind, served per replica), the before / during / after phases,
cut and hung streams, and recovery after the restart.

```bash
cd backend
scripts/load/compose/replica_loss.sh x3-b-4-replicas 320 6m 120 240   # kill at 2:00, start at 4:00 of the hold
$PYDEV/bin/python scripts/load/replica_buckets.py reports/load/<date>-x3-b-4-replicas 360
```
