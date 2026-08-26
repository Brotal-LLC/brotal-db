#!/bin/sh
set -eu
: "${PGHOST:=127.0.0.1}"; : "${PGPORT:=5432}"; : "${PGUSER:=app}"; : "${PGDATABASE:=app}"
export PGHOST PGPORT PGUSER PGDATABASE
cleanup=0
valid_passfile=0
if [ -n "${PGPASSWORD:-}" ]; then
  valid_passfile=1
elif [ -n "${PGPASSFILE:-}" ] && [ -r "$PGPASSFILE" ] && [ -s "$PGPASSFILE" ] && grep -Eq '^[^:]*:[^:]*:[^:]*:[^:]*:.*$' "$PGPASSFILE"; then
  valid_passfile=1
fi
if [ "$valid_passfile" -eq 0 ]; then
  password_file="${POSTGRES_PASSWORD_FILE:-.secrets/postgres_password}"
  [ -r "$password_file" ] && [ -s "$password_file" ] || { echo "missing password file: $password_file" >&2; exit 1; }
  PGPASSFILE=$(mktemp); chmod 600 "$PGPASSFILE"; cleanup=1
  printf '*:*:*:%s:%s\n' "$PGUSER" "$(cat "$password_file")" > "$PGPASSFILE"
  export PGPASSFILE
fi
trap '[ "$cleanup" -eq 1 ] && rm -f "$PGPASSFILE"' EXIT
if command -v psql >/dev/null 2>&1; then
  psql -v ON_ERROR_STOP=1 -f tests/sql/smoke.sql
  psql -v ON_ERROR_STOP=1 -c "SELECT extname, extversion FROM pg_extension ORDER BY 1;"
else
  compose_file="${SMOKE_COMPOSE_FILE:-compose/standalone.yml}"
  docker compose -f "$compose_file" exec -T -e PGUSER="$PGUSER" -e PGDATABASE="$PGDATABASE" postgres sh -c 'PGPASSWORD=$(cat /run/secrets/postgres_password); export PGPASSWORD; exec psql -h 127.0.0.1 -U "$PGUSER" -d "$PGDATABASE" -v ON_ERROR_STOP=1' < tests/sql/smoke.sql
  docker compose -f "$compose_file" exec -T -e PGUSER="$PGUSER" -e PGDATABASE="$PGDATABASE" postgres sh -c 'PGPASSWORD=$(cat /run/secrets/postgres_password); export PGPASSWORD; exec psql -h 127.0.0.1 -U "$PGUSER" -d "$PGDATABASE" -v ON_ERROR_STOP=1 -c "SELECT extname, extversion FROM pg_extension ORDER BY 1;"'
fi
