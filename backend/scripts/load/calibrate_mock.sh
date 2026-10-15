#!/usr/bin/env bash
# N2: calibrate the provider mock against real turns. Runs the 49 golden cases once through the real graph with the
# mock (OPENAI_BASE_URL) and the stub index, then compares turn time with the real runs (MediCoord rule: median and
# p95 within 10%). Answers are mock answers, so the gate itself fails by design; only timing is compared.
# Run from backend/:  scripts/load/calibrate_mock.sh <MOCK_LLM_MEAN_S> <MOCK_LLM_SIGMA> [real run glob, default 20261015-r*]
set -uo pipefail
cd "$(dirname "$0")/../.."

MEAN="${1:?mean seconds per chat call}"
SIGMA="${2:?log-normal sigma}"
REAL="${3:-20261015-r*}"
PORT="${MOCK_PORT:-8090}"
PYDEV="${PYDEV:-$(grep -E '^PYDEV=' .env 2>/dev/null | cut -d= -f2- || true)}"
RUN="mockcal-$MEAN-$SIGMA"

MOCK_LLM_MEAN_S="$MEAN" MOCK_LLM_SIGMA="$SIGMA" "$PYDEV/bin/uvicorn" scripts.load.mock_openai:app \
  --host 127.0.0.1 --port "$PORT" --log-level warning &
MOCK=$!
trap 'kill $MOCK 2>/dev/null || true' EXIT
for _ in $(seq 30); do curl -sf "http://127.0.0.1:$PORT/health" > /dev/null && break; sleep 0.5; done

rm -f "reports/eval-runs/$RUN.jsonl"
env -u ENV_FILE OPENAI_BASE_URL="http://127.0.0.1:$PORT/v1" OPENAI_API_KEY=mock LOADTEST_STUB_VECTORS=1 \
  EVAL_RUN_ID="$RUN" EVAL_PAUSE_SECONDS=0 "$PYDEV/bin/pytest" -m eval tests/eval/test_golden.py -q > /dev/null 2>&1
curl -s "http://127.0.0.1:$PORT/stats"; echo

"$PYDEV/bin/python" - "$RUN" "$REAL" <<'EOF'
import glob, json, statistics, sys
def seconds(pattern):
    return [json.loads(l)["seconds"] for f in glob.glob(f"reports/eval-runs/{pattern}.jsonl") for l in open(f)]
def p95(v):
    return sorted(v)[max(0, int(0.95 * len(v)) - 1)]
mock, real = seconds(sys.argv[1]), seconds(sys.argv[2])
for name, a, b in (("median", statistics.median(mock), statistics.median(real)), ("p95", p95(mock), p95(real)),
                   ("mean", statistics.mean(mock), statistics.mean(real))):
    print(f"{name:6} mock {a:5.2f} s  real {b:5.2f} s  diff {100 * (a - b) / b:+5.1f}%")
print(f"turns: mock {len(mock)}, real {len(real)}")
EOF
