#!/usr/bin/env bash
# N0.1 + N1: the golden gate on the local corpus (backend/.env: local DB, PINECONE_INDEX), run several times.
# Resumable: after a failure, run the same command again; finished cases are skipped (reports/eval-runs/<run>.jsonl).
# Run from backend/:  scripts/gate_runs.sh <runs> [run prefix, default today]   e.g. scripts/gate_runs.sh 3
set -uo pipefail
cd "$(dirname "$0")/.."

RUNS="${1:?number of runs}"
PREFIX="${2:-$(date +%Y%m%d)}"
PYDEV="${PYDEV:-$(grep -E '^PYDEV=' .env 2>/dev/null | cut -d= -f2- || true)}"
grep -qE '^PINECONE_INDEX=contract-demo' .env && { echo "backend/.env points at the demo index; refusing." >&2; exit 1; }

for n in $(seq "$RUNS"); do
  echo "== run $PREFIX-r$n ($(date -Is))"
  # A failed gate is a result, not a crash: keep going to the next run.
  env -u ENV_FILE EVAL_RUN_ID="$PREFIX-r$n" EVAL_PAUSE_SECONDS="${EVAL_PAUSE_SECONDS:-15}" \
    "${PYDEV:?set PYDEV}/bin/pytest" -m eval tests/eval/test_golden.py -s -q 2>&1 | grep -E "eval target|corpus:|answerable|over_refusal|junk|report:|passed|failed|Error" || true
done
