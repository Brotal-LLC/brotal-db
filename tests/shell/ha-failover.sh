#!/bin/sh
set -eu
compose='docker compose -f compose/ha.yml'
: "${PGUSER:=app}"; : "${PGDATABASE:=app}"; export PGUSER PGDATABASE
nodes='postgres1 postgres2 postgres3'
password_file=.secrets/postgres_password
if [ ! -r "$password_file" ] || [ ! -s "$password_file" ]; then
  echo "missing $password_file" >&2
  exit 1
fi
# Expansion is intentionally deferred until a trap fires.
# shellcheck disable=SC2016
trap 'if [ -n "${old_leader:-}" ]; then $compose start "$old_leader" >/dev/null 2>&1 || true; fi' EXIT INT TERM
psql_from() {
  client_node=$1
  shift
  # Expansion is intentionally deferred to the container shell.
  # shellcheck disable=SC2016
  $compose exec -T "$client_node" sh -c 'PGPASSWORD=$(cat /run/secrets/postgres_password); export PGPASSWORD; exec psql "$@"' sh "$@"
}
wait_for_leader() {
  end=$(( $(date +%s) + 90 ))
  while [ "$(date +%s)" -lt "$end" ]; do
    for node in $nodes; do
      if $compose exec -T "$node" curl -fsS http://localhost:8008/primary >/dev/null 2>&1; then printf '%s\n' "$node"; return 0; fi
    done
    sleep 2
  done
  echo 'timed out waiting for Patroni leader' >&2; return 1
}
wait_for_writer_route() {
  client_node=$1
  end=$(( $(date +%s) + 60 ))
  while [ "$(date +%s)" -lt "$end" ]; do
    if psql_from "$client_node" -h pgbouncer -p 6432 -U "$PGUSER" -d "$PGDATABASE" -Atq -c 'SELECT NOT pg_is_in_recovery();' 2>/dev/null | grep -qx t; then return 0; fi
    sleep 2
  done
  echo 'timed out waiting for PgBouncer writer route' >&2; return 1
}
old_leader=$(wait_for_leader)
end=$(( $(date +%s) + 180 ))
while [ "$(date +%s)" -lt "$end" ]; do
  replicas=0
  for node in $nodes; do
    if $compose exec -T "$node" curl -fsS http://localhost:8008/replica >/dev/null 2>&1; then
      replicas=$((replicas + 1))
    fi
  done
  if [ "$replicas" -eq 2 ]; then
    break
  fi
  sleep 2
done
if [ "${replicas:-0}" -ne 2 ]; then
  echo 'timed out waiting for two Patroni replicas' >&2
  exit 1
fi
wait_for_writer_route "$old_leader"
# PostgreSQL dollar quoting is literal, not shell expansion.
# shellcheck disable=SC2016
psql_from "$old_leader" -h pgbouncer -p 6432 -U "$PGUSER" -d "$PGDATABASE" -v ON_ERROR_STOP=1 -c 'CREATE TABLE IF NOT EXISTS ha_probe(id integer primary key, value text); INSERT INTO ha_probe VALUES (1, $$before-failover$$) ON CONFLICT (id) DO UPDATE SET value=EXCLUDED.value;'
$compose stop "$old_leader" >/dev/null
new_leader=''
end=$(( $(date +%s) + 90 ))
while [ "$(date +%s)" -lt "$end" ]; do
  for node in $nodes; do
    if [ "$node" = "$old_leader" ]; then
      continue
    fi
    if $compose exec -T "$node" curl -fsS http://localhost:8008/primary >/dev/null 2>&1; then new_leader="$node"; break 2; fi
  done
  sleep 2
done
if [ -z "$new_leader" ]; then
  echo 'no different Patroni leader elected' >&2
  exit 1
fi
leaders=0
for node in $nodes; do
  if $compose exec -T "$node" curl -fsS http://localhost:8008/primary >/dev/null 2>&1; then
    leaders=$((leaders + 1))
  fi
done
if [ "$leaders" -ne 1 ]; then
  echo "expected one writable leader, got $leaders" >&2
  exit 1
fi
wait_for_writer_route "$new_leader"
# shellcheck disable=SC2016
psql_from "$new_leader" -h pgbouncer -p 6432 -U "$PGUSER" -d "$PGDATABASE" -v ON_ERROR_STOP=1 -c 'INSERT INTO ha_probe VALUES (2, $$after-failover$$);'
psql_from "$new_leader" -h pgbouncer -p 6432 -U "$PGUSER" -d "$PGDATABASE" -Atq -v ON_ERROR_STOP=1 -c "SELECT 1 FROM ha_probe WHERE id=2 AND value='after-failover';" | grep -qx 1
$compose start "$old_leader" >/dev/null
end=$(( $(date +%s) + 120 ))
while [ "$(date +%s)" -lt "$end" ]; do
  if $compose exec -T "$old_leader" curl -fsS http://localhost:8008/replica >/dev/null 2>&1 && psql_from "$old_leader" -h 127.0.0.1 -p 5432 -U "$PGUSER" -d "$PGDATABASE" -Atq -v ON_ERROR_STOP=1 -c "SELECT 1 FROM ha_probe WHERE id=2 AND value='after-failover';" 2>/dev/null | grep -qx 1; then
    printf 'HA failover/rejoin drill passed (leader %s -> %s)\n' "$old_leader" "$new_leader"; exit 0
  fi
  sleep 2
done
echo 'old leader did not rejoin with replicated data before timeout' >&2
exit 1
