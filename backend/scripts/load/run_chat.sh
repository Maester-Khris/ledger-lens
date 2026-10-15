#!/usr/bin/env bash
# N3/N4: one chat load run, local and repeatable. Starts the calibrated provider mock and one API process (stub index,
# demo mode, tracing and Sentry off), samples the box every 5 s, runs k6 (Docker) and writes everything under
# reports/load/<label>.*  Run from backend/:  scripts/load/run_chat.sh <label> [STEPS] [STEP_HOLD]
#   scripts/load/run_chat.sh baseline                  default ladder 5,10,20,40,80,160, 1 min per level
set -uo pipefail
cd "$(dirname "$0")/../.."

LABEL="${1:?label, e.g. baseline}"
STEPS="${2:-5,10,20,40,80,160}"
HOLD="${3:-1m}"
API_PORT=8012
MOCK_PORT=8090
PYDEV="${PYDEV:-$(grep -E '^PYDEV=' .env 2>/dev/null | cut -d= -f2- || true)}"
OUT="reports/load/$(date +%Y-%m-%d)-$LABEL"
mkdir -p reports/load
grep -qE '^PINECONE_INDEX=contract-demo' .env && { echo "backend/.env points at the demo index; refusing." >&2; exit 1; }

"$PYDEV/bin/python" -c "import json; g = json.load(open('tests/eval/golden.json'));
json.dump([c['question'] for c in g if c.get('category') == 'answerable' and not c.get('setup')], open('scripts/load/questions.json', 'w'))"

MOCK_LLM_MEAN_S=1.25 MOCK_LLM_SIGMA=0.55 "$PYDEV/bin/uvicorn" scripts.load.mock_openai:app \
  --host 127.0.0.1 --port "$MOCK_PORT" --log-level warning > "$OUT.mock.log" 2>&1 &
MOCK=$!
env -u ENV_FILE OPENAI_BASE_URL="http://127.0.0.1:$MOCK_PORT/v1" OPENAI_API_KEY=mock LOADTEST_STUB_VECTORS=1 \
  DEMO_MODE= LANGFUSE_PUBLIC_KEY= LANGFUSE_SECRET_KEY= SENTRY_DSN= \
  "$PYDEV/bin/uvicorn" app.main:app --host 127.0.0.1 --port "$API_PORT" --workers 1 --log-level warning > "$OUT.api.log" 2>&1 &
API=$!
SAMPLER=
trap 'kill $API $MOCK $SAMPLER 2>/dev/null || true' EXIT
for _ in $(seq 60); do curl -sf "http://127.0.0.1:$API_PORT/health" > /dev/null && break; sleep 1; done
curl -s -X POST "http://127.0.0.1:$MOCK_PORT/stats/reset" > /dev/null

# Box sample every 5 s: API process CPU % and resident MB, its threads, DB connections, mock calls in flight.
(
  echo -e "time\tapi_cpu_pct\tapi_rss_mb\tapi_threads\tdb_connections\tmock_in_flight"
  while kill -0 $API 2>/dev/null; do
    read -r cpu rss threads < <(ps -o %cpu=,rss=,nlwp= -p $API)
    conns=$(docker exec fintech-ledger-db psql -U postgres -Atc "select count(*) from pg_stat_activity where datname='ledger_dev' and usename='ledger_app'" 2>/dev/null)
    inflight=$(curl -s "http://127.0.0.1:$MOCK_PORT/stats" | "$PYDEV/bin/python" -c "import json,sys; print(json.load(sys.stdin)['in_flight'])" 2>/dev/null)
    echo -e "$(date +%T)\t$cpu\t$((rss / 1024))\t$threads\t$conns\t$inflight"
    sleep 5
  done
) > "$OUT.box.tsv" &
SAMPLER=$!

echo "== k6 $LABEL steps=$STEPS hold=$HOLD ($(date -Is))"
docker run --rm -i --network host --user "$(id -u):$(id -g)" \
  -e BASE_URL="http://127.0.0.1:$API_PORT" -e STEPS="$STEPS" -e STEP_HOLD="$HOLD" \
  -v "$PWD/scripts/load:/scripts:ro" -v "$PWD/reports/load:/out" \
  grafana/k6 run /scripts/chat.js --summary-export "/out/$(basename "$OUT").k6.json" \
  --out "csv=/out/$(basename "$OUT").k6.csv" 2>&1 | tail -40
curl -s "http://127.0.0.1:$MOCK_PORT/stats" > "$OUT.mock-stats.json"
grep -ciE "error|exception|timeout" "$OUT.api.log" | xargs echo "api log lines with error/exception/timeout:"
echo "written $OUT.*"
