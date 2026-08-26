#!/bin/bash
set -Eeuo pipefail
file_value() {
  local n="$1" fvar v f
  fvar="${n}_FILE"
  v="${!n-}"
  f="${!fvar-}"
  if [[ -n "$v" && -n "$f" ]]; then echo "${n} and ${fvar} cannot both be set" >&2; exit 64; fi
  if [[ -n "$f" ]]; then [[ -r "$f" ]] || { echo "$fvar file is unreadable" >&2; exit 1; }; v="$(<"$f")"; [[ -n "$v" ]] || { echo "$fvar file is empty" >&2; exit 1; }; fi
  printf '%s' "$v"
}
POSTGRES_PASSWORD="$(file_value POSTGRES_PASSWORD)"
export POSTGRES_PASSWORD
unset POSTGRES_PASSWORD_FILE
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
: "${DB_MODE:=standalone}"; export PGDATA="${PGDATA:-/var/lib/postgresql/18/data}"
case "$DB_MODE" in
  standalone)
    export POSTGRES_INITDB_ARGS="${POSTGRES_INITDB_ARGS:---data-checksums}"
    export POSTGRES_HOST_AUTH_METHOD=scram-sha-256
    preload="${POSTGRES_SHARED_PRELOAD_LIBRARIES:-timescaledb,pg_textsearch,pg_stat_statements}"
    # Never touch empty PGDATA: the official entrypoint uses emptiness to decide when to initdb.
    if [[ "${1:-postgres}" == postgres ]]; then
      set -- "$@" -c "shared_preload_libraries=$preload"
    fi
    exec /usr/local/bin/docker-entrypoint.sh "$@"
    ;;
  patroni)
    REPLICATION_PASSWORD="$(file_value REPLICATION_PASSWORD)"
    export REPLICATION_PASSWORD
    unset REPLICATION_PASSWORD_FILE
    : "${REPLICATION_PASSWORD:?REPLICATION_PASSWORD is required in patroni mode}"
    : "${PATRONI_NAME:?PATRONI_NAME is required}" "${ETCD_HOSTS:?ETCD_HOSTS is required}" "${POSTGRES_USER:?POSTGRES_USER is required}" "${REPLICATION_USER:?REPLICATION_USER is required}"
    if [[ "$EUID" -eq 0 ]]; then
      mkdir -p "$PGDATA"; chown -R postgres:postgres "$PGDATA"; chmod 0700 "$PGDATA"
      /usr/local/bin/render-patroni.sh
      exec setpriv --reuid postgres --regid "$(id -g postgres)" --init-groups -- patroni /etc/patroni/patroni.yml
    fi
    [[ "$(id -un)" == postgres ]] || { echo 'non-root Patroni must run as postgres' >&2; exit 64; }
    mkdir -p "$PGDATA"; chmod 0700 "$PGDATA"
    /usr/local/bin/render-patroni.sh
    exec patroni /etc/patroni/patroni.yml
    ;;
  *) echo 'DB_MODE must be standalone or patroni' >&2; exit 64;;
esac
