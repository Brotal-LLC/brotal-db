#!/usr/bin/env bash
# Verify the HAProxy PostgreSQL write endpoint reaches the current Patroni primary.
# Authentication remains libpq-managed (for example, via PGPASSFILE or a service file).
set -euo pipefail

export PGHOST="${PGHOST:-postgres-ha}"
export PGPORT="${PGPORT:-6432}"
: "${PGUSER:?PGUSER must name a role allowed to create temporary tables}"
: "${PGDATABASE:?PGDATABASE must name a writable database}"

result=$(psql -q -X -w -v ON_ERROR_STOP=1 -A -t <<'SQL'
BEGIN;
CREATE TEMPORARY TABLE haproxy_write_probe (id integer NOT NULL) ON COMMIT DROP;
INSERT INTO haproxy_write_probe (id) VALUES (1);
SELECT CASE WHEN pg_is_in_recovery() THEN 'standby' ELSE 'primary-write-ok' END;
ROLLBACK;
SQL
)

if [[ "$result" != "primary-write-ok" ]]; then
    printf 'HAProxy write endpoint did not confirm a primary write (result: %s)\n' "$result" >&2
    exit 1
fi

printf '%s\n' "$result"
