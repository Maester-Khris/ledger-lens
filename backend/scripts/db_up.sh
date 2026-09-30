#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Value of $1: from the shell, else the last NAME= line in backend/.env, else $2.
env_or() {
  local value="${!1:-}"
  if [ -z "$value" ] && [ -f "$SCRIPT_DIR/.env" ]; then
    value="$(sed -n "s/^$1=//p" "$SCRIPT_DIR/.env" | tail -n 1)"
  fi
  echo "${value:-$2}"
}

CONTAINER_NAME="$(env_or PG_CONTAINER_NAME fintech-ledger-db)"
PG_IMAGE="$(env_or PG_IMAGE postgres:18)"
PG_PASSWORD="localdev"
ROLE_PASSWORD="localdev" # dev-only password shared by ledger_owner and ledger_app
PG_PORT="$(env_or PG_PORT 5432)" # keep in sync with the port in the *DATABASE_URL values
DATABASES="ledger_dev ledger_test ledger_migration_test"

if docker inspect "$CONTAINER_NAME" > /dev/null 2>&1; then
  current_image=$(docker inspect -f '{{.Config.Image}}' "$CONTAINER_NAME")
  if [ "$current_image" != "$PG_IMAGE" ]; then
    echo "Container $CONTAINER_NAME runs $current_image, expected $PG_IMAGE." >&2
    echo "Recreate it (destroys local dev data): docker rm -f $CONTAINER_NAME && $0" >&2
    exit 1
  fi
  if [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME")" != "true" ]; then
    echo "Starting existing container $CONTAINER_NAME..."
    docker start "$CONTAINER_NAME" > /dev/null
  else
    echo "Container $CONTAINER_NAME already running."
  fi
else
  echo "Creating container $CONTAINER_NAME ($PG_IMAGE)..."
  docker run -d --name "$CONTAINER_NAME" \
    -e POSTGRES_PASSWORD="$PG_PASSWORD" \
    -p "$PG_PORT:5432" \
    "$PG_IMAGE"
fi

echo "Waiting for Postgres to accept connections..."
ready=false
for _ in $(seq 1 30); do
  if docker exec "$CONTAINER_NAME" pg_isready -U postgres > /dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done
if [ "$ready" != "true" ]; then
  echo "Postgres did not become ready in time" >&2
  exit 1
fi

psql_admin() {
  docker exec "$CONTAINER_NAME" psql -U postgres -v ON_ERROR_STOP=1 -tAc "$1"
}

for role in ledger_owner ledger_app; do
  if [ "$(psql_admin "SELECT 1 FROM pg_roles WHERE rolname='${role}'")" != "1" ]; then
    echo "Creating role ${role}..."
    psql_admin "CREATE ROLE ${role} LOGIN PASSWORD '${ROLE_PASSWORD}'"
  fi
done

for db in $DATABASES; do
  if [ "$(psql_admin "SELECT 1 FROM pg_database WHERE datname='${db}'")" != "1" ]; then
    echo "Creating database ${db}..."
    psql_admin "CREATE DATABASE ${db} OWNER ledger_owner"
  fi
  psql_admin "ALTER DATABASE ${db} OWNER TO ledger_owner" > /dev/null
done

# Python env root; without it, alembic from PATH.
PYDEV="$(env_or PYDEV "")"
ALEMBIC="${PYDEV:+$PYDEV/bin/}alembic"
OWNER_URL="postgresql+psycopg://ledger_owner:${ROLE_PASSWORD}@localhost:${PG_PORT}"

for db in ledger_dev ledger_test; do
  echo "Running migrations against ${db} as ledger_owner..."
  (cd "$SCRIPT_DIR" && ALEMBIC_DATABASE_URL="${OWNER_URL}/${db}" "$ALEMBIC" upgrade head)
done

echo "Done. ledger_dev and ledger_test are up to date (ledger_migration_test is managed by the test suite)."
