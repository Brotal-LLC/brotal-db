#!/bin/bash
set -Eeuo pipefail
url="${1:?Patroni post_init must receive a connection URL}"
db="${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
export PGPASSFILE="${PATRONI_PGPASSFILE:-/var/lib/postgresql/.pgpass}" PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-10}" PGPASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
[[ -r "$PGPASSFILE" ]] || { echo "Patroni pgpass file is unreadable: $PGPASSFILE" >&2; exit 1; }
IFS=',' read -ra requested <<< "${POSTGRES_EXTENSIONS:-}"
# Reject the whole request before creating a database or extension.
for ext in "${requested[@]}"; do
  ext="${ext//[[:space:]]/}"; [[ -z "$ext" ]] && continue
  case "$ext" in vector|postgis|postgis_raster|postgis_topology|pg_trgm|pg_textsearch|timescaledb|pg_stat_statements) ;;
    *) echo "extension not allowlisted: $ext" >&2; exit 64;;
  esac
done
maintenance_url="$(URL="$url" python3 - <<'PY'
import os
from psycopg.conninfo import conninfo_to_dict, make_conninfo
params = conninfo_to_dict(os.environ['URL'])
params['dbname'] = 'postgres'
print(make_conninfo(**params))
PY
)"
if [[ "$db" != postgres ]]; then
  if ! createdb --no-password --username="$POSTGRES_USER" --maintenance-db="$maintenance_url" --owner="$POSTGRES_USER" -- "$db"; then
    psql --no-password --username="$POSTGRES_USER" "$maintenance_url" -v ON_ERROR_STOP=1 -v dbname="$db" -Atqc "SELECT 1 FROM pg_database WHERE datname = :'dbname'" | grep -qx 1 || exit 1
  fi
fi
url_db="$(DB="$db" URL="$url" python3 - <<'PY'
import os
from psycopg.conninfo import conninfo_to_dict, make_conninfo
params = conninfo_to_dict(os.environ['URL'])
params['dbname'] = os.environ['DB']
print(make_conninfo(**params))
PY
)"
psql=(psql --no-password --username="$POSTGRES_USER" "$url_db" -v ON_ERROR_STOP=1)
# Dependencies first; postgis_raster/topology depend on postgis.
for ext in postgis postgis_raster postgis_topology vector pg_trgm pg_textsearch timescaledb pg_stat_statements; do
  for requested_ext in "${requested[@]}"; do
    requested_ext="${requested_ext//[[:space:]]/}"
    if [[ "$requested_ext" == "$ext" ]]; then "${psql[@]}" -c "CREATE EXTENSION IF NOT EXISTS \"$ext\""; break; fi
  done
done
