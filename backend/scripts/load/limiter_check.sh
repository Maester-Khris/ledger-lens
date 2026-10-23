#!/usr/bin/env bash
# N5: bring up 2 API replicas (1 CPU, 1 GB each) behind nginx with Redis and the provider mock, run limiter_check.py,
# tear everything down. Run from backend/:  scripts/load/limiter_check.sh <memory|redis>
set -uo pipefail
cd "$(dirname "$0")/../.."
MODE="${1:?memory or redis}"
PYDEV="${PYDEV:-$(grep -E '^PYDEV=' .env 2>/dev/null | cut -d= -f2- || true)}"
COMPOSE=(docker compose -f scripts/load/compose/compose.yaml)
NETWORK=ledgerlens-load_default
[ "$MODE" = memory ] && export REDIS_URL=
trap '"${COMPOSE[@]}" down > /dev/null 2>&1; docker network disconnect $NETWORK fintech-ledger-db > /dev/null 2>&1' EXIT
"${COMPOSE[@]}" up -d --build --scale api=2 redis mock api > /dev/null
docker network connect $NETWORK fintech-ledger-db 2> /dev/null || true
"${COMPOSE[@]}" up -d --no-deps nginx > /dev/null  # after both replicas exist, so nginx resolves both; --no-deps keeps 2 replicas
for _ in $(seq 60); do curl -sf http://127.0.0.1:8088/health > /dev/null && break; sleep 1; done
"$PYDEV/bin/python" scripts/load/limiter_check.py "$MODE"
