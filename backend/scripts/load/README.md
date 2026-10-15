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
