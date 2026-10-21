#!/usr/bin/env bash
# X3: 4 API replicas (1 CPU, 1 GB, one worker each) behind nginx, Redis shared, the calibrated provider mock; one
# constant level of conversations; one replica hard-killed (docker kill: a crash, its streams are cut) and started
# again. Nothing here reaches Railway, OpenAI or Pinecone. Run from backend/:
#   scripts/load/compose/replica_loss.sh <label> [CONVERSATIONS] [HOLD] [KILL_AT] [START_AT]
#   scripts/load/compose/replica_loss.sh x3-b-4-replicas 320 6m 120 240
# KILL_AT and START_AT are seconds after the hold starts (k6 ramps for 10 s first). Writes reports/load/<date>-<label>.*
# (k6 csv/json, events.tsv with the kill/start epoch times, docker stats every 5 s); summarise with
# scripts/load/replica_buckets.py reports/load/<date>-<label>.
set -uo pipefail
cd "$(dirname "$0")/../../.."

LABEL="${1:?label, e.g. x3-b-4-replicas}"
CONVERSATIONS="${2:-320}"
HOLD="${3:-6m}"
KILL_AT="${4:-120}"
START_AT="${5:-240}"
RAMP=10
PYDEV="${PYDEV:-$(grep -E '^PYDEV=' .env 2>/dev/null | cut -d= -f2- || true)}"
COMPOSE=(docker compose -f scripts/load/compose/compose.yaml)
NETWORK=ledgerlens-load_default
OUT="reports/load/$(date +%Y-%m-%d)-$LABEL"
grep -qE '^PINECONE_INDEX=contract-demo' .env && { echo "backend/.env points at the demo index; refusing." >&2; exit 1; }

export CHAT_LIMIT_PER_GUEST=100000 MOCK_DELAY_SCALE=1 MOCK_LLM_MEAN_S=1.25 MOCK_LLM_SIGMA=0.55
export CHAT_MAX_IN_FLIGHT="${CHAT_MAX_IN_FLIGHT:-64}"
STATS=
trap 'kill $STATS 2>/dev/null; "${COMPOSE[@]}" down > /dev/null 2>&1; docker network disconnect $NETWORK fintech-ledger-db > /dev/null 2>&1' EXIT
"${COMPOSE[@]}" up -d --build --scale api=4 redis mock api > /dev/null
docker network connect $NETWORK fintech-ledger-db 2> /dev/null || true
"${COMPOSE[@]}" up -d --no-deps nginx > /dev/null
for _ in $(seq 60); do curl -sf http://127.0.0.1:8088/health > /dev/null && break; sleep 1; done
mapfile -t REPLICAS < <("${COMPOSE[@]}" ps -q api)
[ "${#REPLICAS[@]}" -eq 4 ] || { echo "expected 4 api replicas, got ${#REPLICAS[@]}" >&2; exit 1; }
VICTIM="${REPLICAS[0]}"
address() { docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$1"; }
{ echo -e "role\tcontainer\taddress"; for r in "${REPLICAS[@]}"; do
  echo -e "$([ "$r" = "$VICTIM" ] && echo victim || echo survivor)\t$r\t$(address "$r")"; done; } > "$OUT.replicas.tsv"

"$PYDEV/bin/python" -c "import json; g = json.load(open('tests/eval/golden.json'));
json.dump([c['question'] for c in g if c.get('category') == 'answerable' and not c.get('setup')], open('scripts/load/questions.json', 'w'))"

# Container CPU and memory every 5 s (docker stats takes about 2 s per sample).
(
  echo -e "epoch\tcontainer\tcpu_pct\tmem"
  while true; do
    now=$(date +%s)
    docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' | grep ledgerlens-load | sed "s/^/$now\t/"
    sleep 3
  done
) > "$OUT.stats.tsv" &
STATS=$!

echo -e "event\tepoch\tcontainer" > "$OUT.events.tsv"
echo "== replica loss $LABEL conversations=$CONVERSATIONS hold=$HOLD kill_at=$KILL_AT start_at=$START_AT max_in_flight=$CHAT_MAX_IN_FLIGHT ($(date -Is))"
# CSV times in ms: whole seconds cannot place a cut stream against the kill.
echo -e "k6_start\t$(date +%s.%N)\t" >> "$OUT.events.tsv"
docker run --rm -i --network host --user "$(id -u):$(id -g)" \
  -e BASE_URL=http://127.0.0.1:8088 -e STEPS="$CONVERSATIONS" -e STEP_HOLD="$HOLD" -e NO_ABORT=1 \
  -e K6_CSV_TIME_FORMAT=unix_milli \
  -v "$PWD/scripts/load:/scripts:ro" -v "$PWD/reports/load:/out" \
  grafana/k6 run /scripts/chat.js --summary-export "/out/$(basename "$OUT").k6.json" \
  --out "csv=/out/$(basename "$OUT").k6.csv" > "$OUT.k6.log" 2>&1 &
K6=$!
sleep $((RAMP + KILL_AT))
KILLED=$(date +%s.%N)  # taken before the kill: streams are cut while the command is still returning
docker kill "$VICTIM" > /dev/null && echo -e "kill\t$KILLED\t$VICTIM" >> "$OUT.events.tsv"
sleep $((START_AT - KILL_AT))
STARTED=$(date +%s.%N)
docker start "$VICTIM" > /dev/null && echo -e "start\t$STARTED\t$VICTIM" >> "$OUT.events.tsv"
echo -e "victim_restarted\t$VICTIM\t$(address "$VICTIM")" >> "$OUT.replicas.tsv"  # a new address shows up here
wait $K6
tail -30 "$OUT.k6.log"
cat "$OUT.replicas.tsv"
echo "written $OUT.*"
