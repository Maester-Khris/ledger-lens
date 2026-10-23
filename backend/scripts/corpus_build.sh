#!/usr/bin/env bash
# N0 corpus build, end to end and repeatable: discover EDGAR agreements, render, upload a batch, ingest, report.
# Run from backend/:  scripts/corpus_build.sh <discover N> <upload K>
#   scripts/corpus_build.sh 60 5    trial: find 60, upload the first 5
#   scripts/corpus_build.sh 60 60   the rest (already-uploaded files are the same bytes, so nothing is duplicated)
# Local only: the API runs with DEMO_MODE off on a spare port, against backend/.env (local DB, PINECONE_INDEX).
set -euo pipefail
cd "$(dirname "$0")/.."

DISCOVER="${1:?discover count}"
UPLOAD="${2:?upload count}"
PORT="${CORPUS_API_PORT:-8011}"
PYDEV="${PYDEV:-$(grep -E '^PYDEV=' .env 2>/dev/null | cut -d= -f2- || true)}"
PY="${PYDEV:?set PYDEV}/bin/python"
LOG="var/samples/corpus-build.log"

grep -qE '^PINECONE_INDEX=contract-demo' .env && { echo "backend/.env points at the demo index; refusing." >&2; exit 1; }
export SEC_USER_AGENT="$(grep -E '^SEC_USER_AGENT=' .env | cut -d= -f2- | tr -d '"')"
mkdir -p var/samples

DEMO_MODE= "$PYDEV/bin/uvicorn" app.main:app --host 127.0.0.1 --port "$PORT" --log-level warning >> "$LOG" 2>&1 &
API=$!
trap 'kill $API 2>/dev/null || true' EXIT
for _ in $(seq 60); do curl -sf "http://127.0.0.1:$PORT/health" > /dev/null && break; sleep 1; done

echo "== discover $DISCOVER, upload $UPLOAD ($(date -Is))" | tee -a "$LOG"
"$PY" scripts/prepare_samples.py --discover "$DISCOVER" --upload "http://127.0.0.1:$PORT" --upload-count "$UPLOAD" 2>&1 | tee -a "$LOG"
kill $API 2>/dev/null || true

echo "== ingest ($(date -Is))" | tee -a "$LOG"
STARTED=$(date +%s)
# One pass runs one stage per version (parse, index, extract), so it takes about three passes; stop when idle.
while :; do
  out="$("$PY" scripts/ingestion_worker.py --once 2>&1)" || { echo "$out" | tee -a "$LOG"; echo "worker failed" >&2; exit 1; }
  echo "$out" >> "$LOG"
  grep -q "ran 0 stage" <<< "$out" && break
done

echo "ingest wall seconds: $(( $(date +%s) - STARTED ))" | tee -a "$LOG"
echo "== report ($(date -Is))" | tee -a "$LOG"
"$PY" scripts/corpus_report.py | tee -a "$LOG"
