#!/bin/bash
set -Eeuo pipefail
psql=(psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB")
IFS=',' read -ra requested <<< "${POSTGRES_EXTENSIONS:-}"
for ext in "${requested[@]}"; do
  ext="${ext//[[:space:]]/}"; [[ -z "$ext" ]] && continue
  case "$ext" in vector|postgis|postgis_raster|postgis_topology|pg_trgm|pg_textsearch|timescaledb|pg_stat_statements) ;;
    *) echo "extension not allowlisted: $ext" >&2; exit 64;;
  esac
done
for ext in postgis postgis_raster postgis_topology vector pg_trgm pg_textsearch timescaledb pg_stat_statements; do
  for requested_ext in "${requested[@]}"; do
    requested_ext="${requested_ext//[[:space:]]/}"
    if [[ "$requested_ext" == "$ext" ]]; then "${psql[@]}" -c "CREATE EXTENSION IF NOT EXISTS \"$ext\""; break; fi
  done
done
