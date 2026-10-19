#!/usr/bin/env bash
# Stage only PostgreSQL HA control/access services; never the database service.
set -euo pipefail

usage() {
  printf 'Usage: %s {dcs|db|pool|access} COMPOSE_FILE [ENV_FILE]\n' "$0" >&2
  exit 2
}

[[ $# -ge 2 && $# -le 3 ]] || usage
plane=$1
compose_file=$2
env_file=${3:-}
[[ -f $compose_file ]] || {
  printf 'compose file does not exist: %s\n' "$compose_file" >&2
  exit 2
}

case $plane in
  dcs) services=(etcd) ;;
  db) services=(pgbouncer haproxy) ;;
  pool) services=(pgbouncer) ;;
  access) services=(haproxy) ;;
  *)
    printf 'refusing unknown plane %q; postgres is never a staging target\n' "$plane" >&2
    exit 2
    ;;
esac

compose=(docker compose)
if [[ -n $env_file ]]; then
  [[ -f $env_file ]] || {
    printf 'environment file does not exist: %s\n' "$env_file" >&2
    exit 2
  }
  compose+=(--env-file "$env_file")
fi
compose+=(-f "$compose_file")

"${compose[@]}" config --quiet
"${compose[@]}" up -d --force-recreate --no-deps "${services[@]}"
