#!/bin/sh
set -eu
compose="docker compose -f ${HA_COMPOSE_FILE:-compose/ha.yml}"
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
# The production contract requires an acknowledged synchronous copy before loss.
# The generic demo starts asynchronously; enable and verify its real DCS setting.
$compose exec -T "$old_leader" curl -fsS -XPATCH -H 'Content-Type: application/json' \
  -d '{"synchronous_mode":true,"synchronous_mode_strict":false,"synchronous_node_count":1}' \
  http://localhost:8008/config >/dev/null
end=$(( $(date +%s) + 90 ))
while ! psql_from "$old_leader" -h 127.0.0.1 -U "$PGUSER" -d "$PGDATABASE" -Atq \
  -c "SELECT count(*) FROM pg_stat_replication WHERE sync_state IN ('sync','quorum');" | grep -Eq '^[1-9][0-9]*$'; do
  [ "$(date +%s)" -lt "$end" ] || { echo 'no synchronous standby' >&2; exit 1; }
  sleep 2
done
# Patroni publishes promotion eligibility to DCS after PostgreSQL's sync setting.
# Stopping between those steps correctly leaves no eligible promotion candidate.
while ! $compose exec -T "$old_leader" python3 -c \
  'import json,sys,urllib.request; d=json.load(urllib.request.urlopen("http://localhost:8008/cluster")); sys.exit(0 if any(n["role"] == "sync_standby" for n in d["members"]) else 1)'; do
  [ "$(date +%s)" -lt "$end" ] || { echo 'standby not eligible in DCS' >&2; exit 1; }
  sleep 2
done
# A unique marker prevents an older successful run from hiding a lost write.
probe_marker="before-failover-$(date +%s)-$$"
psql_from "$old_leader" -h pgbouncer -p 6432 -U "$PGUSER" -d "$PGDATABASE" -v ON_ERROR_STOP=1 -c "CREATE TABLE IF NOT EXISTS ha_probe(id integer primary key, value text); INSERT INTO ha_probe VALUES (1, '$probe_marker') ON CONFLICT (id) DO UPDATE SET value=EXCLUDED.value;"
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
psql_from "$new_leader" -h pgbouncer -p 6432 -U "$PGUSER" -d "$PGDATABASE" -Atq -v ON_ERROR_STOP=1 -c 'SELECT value FROM ha_probe WHERE id=1;' | grep -Fxq "$probe_marker"
# shellcheck disable=SC2016
psql_from "$new_leader" -h pgbouncer -p 6432 -U "$PGUSER" -d "$PGDATABASE" -v ON_ERROR_STOP=1 -c 'INSERT INTO ha_probe VALUES (2, $$after-failover$$) ON CONFLICT (id) DO UPDATE SET value=EXCLUDED.value;'
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
