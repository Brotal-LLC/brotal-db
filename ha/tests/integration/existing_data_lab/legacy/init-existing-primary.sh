#!/usr/bin/env bash
set -euo pipefail

read_secret() { tr -d '\r\n' <"/run/secrets/$1"; }

psql -v ON_ERROR_STOP=1 --username postgres --dbname postgres \
  --set=replicator_password="$(read_secret legacy_replication_password)" \
  --set=superuser_password="$(read_secret patroni_superuser_password)" \
  --set=replication_password="$(read_secret patroni_replication_password)" \
  --set=rewind_password="$(read_secret patroni_rewind_password)" <<'SQL'
CREATE ROLE replicator LOGIN REPLICATION PASSWORD :'replicator_password';
CREATE ROLE patroni_superuser LOGIN SUPERUSER PASSWORD :'superuser_password';
CREATE ROLE patroni_replication LOGIN REPLICATION PASSWORD :'replication_password';
CREATE ROLE patroni_rewind LOGIN PASSWORD :'rewind_password';
GRANT EXECUTE ON function pg_catalog.pg_ls_dir(text, boolean, boolean) TO patroni_rewind;
GRANT EXECUTE ON function pg_catalog.pg_stat_file(text, boolean) TO patroni_rewind;
GRANT EXECUTE ON function pg_catalog.pg_read_binary_file(text) TO patroni_rewind;
GRANT EXECUTE ON function pg_catalog.pg_read_binary_file(text, bigint, bigint, boolean) TO patroni_rewind;
SELECT pg_create_physical_replication_slot('rogue', true);
SELECT pg_create_physical_replication_slot('fluffy', true);
CREATE TABLE adoption_markers(id integer PRIMARY KEY, note text NOT NULL);
INSERT INTO adoption_markers VALUES (1, 'legacy-primary');
SQL
