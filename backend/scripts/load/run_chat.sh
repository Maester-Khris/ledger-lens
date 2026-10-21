#!/usr/bin/env bash
# N3/N4: one chat load run, local and repeatable. Starts the calibrated provider mock and one API process (stub index,
# demo mode, tracing and Sentry off), samples the box every 5 s, runs k6 (Docker) and writes everything under
# reports/load/<label>.*  Run from backend/:  scripts/load/run_chat.sh <label> [STEPS] [STEP_HOLD]
#   scripts/load/run_chat.sh baseline                  default ladder 5,10,20,40,80,160, 1 min per level
# BOX=<vcpus>:<memory>:<workers> confines the API (only) to a cgroup shaped like a deployed box, e.g. BOX=1:1G:1
# (Railway Hobby, MediCoord staging) or BOX=2:2G:2. Postgres, the mock and k6 stay outside: in a deployment they are
# a managed service, the provider and the client. Unset = the whole machine.
# PROFILE=1 starts the API under py-spy and writes <label>.profile.txt (collapsed stacks, 100 Hz, all workers, only
# the thread holding the GIL: Python CPU work, not waits). Summarise with scripts/load/profile_top.py. py-spy runs
# inside any BOX and takes CPU from it, so profile without BOX: proportions do not depend on the box.
# X3: CHAT_MAX_IN_FLIGHT=<n> sets the API's per-worker limit of chat turns in flight (unset = no limit); NO_ABORT=1
# runs the whole ladder past k6's stop rule, to measure overload instead of stopping at it. Keep-alive 75 s (nginx's
# default, as behind a proxy): at uvicorn's 5 s, k6 reused sockets the server was closing after a busy wait (X3 A1).
set -uo pipefail
cd "$(dirname "$0")/../.."

LABEL="${1:?label, e.g. baseline}"
STEPS="${2:-5,10,20,40,80,160}"
HOLD="${3:-1m}"
API_PORT=8012
IFS=: read -r BOX_CPUS BOX_MEM BOX_WORKERS <<< "${BOX:-}"
CONFINE=()
[ -n "${BOX:-}" ] && CONFINE=(systemd-run --user --scope -q -p "CPUQuota=$((BOX_CPUS * 100))%" -p "MemoryMax=$BOX_MEM")
MOCK_PORT=8090
PYDEV="${PYDEV:-$(grep -E '^PYDEV=' .env 2>/dev/null | cut -d= -f2- || true)}"
OUT="reports/load/$(date +%Y-%m-%d)-$LABEL"
mkdir -p reports/load
PROFILER=()
[ -n "${PROFILE:-}" ] && PROFILER=("$PYDEV/bin/py-spy" record --gil --format raw --rate 100 --subprocesses -o "$OUT.profile.txt" --)
grep -qE '^PINECONE_INDEX=contract-demo' .env && { echo "backend/.env points at the demo index; refusing." >&2; exit 1; }

"$PYDEV/bin/python" -c "import json; g = json.load(open('tests/eval/golden.json'));
json.dump([c['question'] for c in g if c.get('category') == 'answerable' and not c.get('setup')], open('scripts/load/questions.json', 'w'))"

MOCK_LLM_MEAN_S=1.25 MOCK_LLM_SIGMA=0.55 "$PYDEV/bin/uvicorn" scripts.load.mock_openai:app \
  --host 127.0.0.1 --port "$MOCK_PORT" --log-level warning > "$OUT.mock.log" 2>&1 &
MOCK=$!
env -u ENV_FILE OPENAI_BASE_URL="http://127.0.0.1:$MOCK_PORT/v1" OPENAI_API_KEY=mock LOADTEST_STUB_VECTORS=1 \
  DEMO_MODE= LANGFUSE_PUBLIC_KEY= LANGFUSE_SECRET_KEY= SENTRY_DSN= CHAT_MAX_IN_FLIGHT="${CHAT_MAX_IN_FLIGHT:-0}" \
  "${CONFINE[@]}" "${PROFILER[@]}" "$PYDEV/bin/uvicorn" app.main:app --host 127.0.0.1 --port "$API_PORT" --workers "${BOX_WORKERS:-1}" \
  --timeout-keep-alive 75 --log-level warning > "$OUT.api.log" 2>&1 &
API=$!
SAMPLER=
trap 'pkill -P $API 2>/dev/null; kill $API $MOCK $SAMPLER 2>/dev/null || true' EXIT
for _ in $(seq 60); do curl -sf "http://127.0.0.1:$API_PORT/health" > /dev/null && break; sleep 1; done
curl -s -X POST "http://127.0.0.1:$MOCK_PORT/stats/reset" > /dev/null

# Box sample every 5 s, summed over the API process and its workers: CPU % over the last interval (100 = one core,
# from /proc utime+stime ticks; not ps %cpu, which is a lifetime average), resident MB, threads; then DB
# connections and mock calls in flight.
TICKS=$(getconf CLK_TCK)
(
  echo -e "time\tapi_cpu_pct\tapi_rss_mb\tapi_threads\tdb_connections\tmock_in_flight"
  last_ticks=0; last_time=$(date +%s.%N)
  while kill -0 $API 2>/dev/null; do
    pids=$(pgrep -d' ' -P $API); pids="$pids $API"
    read -r ticks rss threads < <(for pid in $pids; do
      [ -r /proc/$pid/stat ] && awk '{print $14 + $15, $24, $20}' /proc/$pid/stat; done | awk '{t+=$1; r+=$2; n+=$3} END {print t+0, r+0, n+0}')
    now=$(date +%s.%N)
    cpu=$(awk -v t="$ticks" -v lt="$last_ticks" -v n="$now" -v ln="$last_time" -v hz="$TICKS" \
      'BEGIN {printf "%.0f", (lt == 0 ? 0 : 100 * (t - lt) / hz / (n - ln))}')
    last_ticks=$ticks; last_time=$now
    conns=$(docker exec fintech-ledger-db psql -U postgres -Atc "select count(*) from pg_stat_activity where datname='ledger_dev' and usename='ledger_app'" 2>/dev/null)
    inflight=$(curl -s "http://127.0.0.1:$MOCK_PORT/stats" | "$PYDEV/bin/python" -c "import json,sys; print(json.load(sys.stdin)['in_flight'])" 2>/dev/null)
    echo -e "$(date +%T)\t$cpu\t$((rss * $(getconf PAGESIZE) / 1048576))\t$threads\t$conns\t$inflight"
    sleep 5
  done
) > "$OUT.box.tsv" &
SAMPLER=$!

echo "== k6 $LABEL steps=$STEPS hold=$HOLD box=${BOX:-whole machine} max_in_flight=${CHAT_MAX_IN_FLIGHT:-0} no_abort=${NO_ABORT:-} ($(date -Is))"
docker run --rm -i --network host --user "$(id -u):$(id -g)" \
  -e BASE_URL="http://127.0.0.1:$API_PORT" -e STEPS="$STEPS" -e STEP_HOLD="$HOLD" -e NO_ABORT="${NO_ABORT:-}" \
  -v "$PWD/scripts/load:/scripts:ro" -v "$PWD/reports/load:/out" \
  grafana/k6 run /scripts/chat.js --summary-export "/out/$(basename "$OUT").k6.json" \
  --out "csv=/out/$(basename "$OUT").k6.csv" 2>&1 | tail -40
curl -s "http://127.0.0.1:$MOCK_PORT/stats" > "$OUT.mock-stats.json"
if [ -n "${PROFILE:-}" ]; then kill -INT $API; wait $API 2>/dev/null; fi  # py-spy writes its file on SIGINT
grep -ciE "error|exception|timeout" "$OUT.api.log" | xargs echo "api log lines with error/exception/timeout:"
echo "written $OUT.*"
