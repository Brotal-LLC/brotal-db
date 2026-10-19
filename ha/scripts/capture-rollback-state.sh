#!/usr/bin/env bash
set -euo pipefail
umask 077

output=${1:-./backups/pre-patroni-$(date -u +%Y%m%dT%H%M%SZ)}
stack=${STACK_DIR:-/srv/stacks/databases}
mkdir -p "$output/files"

# Capture values needed for exact recreation. The environment file is intentionally represented
# only by key names; credentials belong in the secret backend, never this artifact.
docker inspect postgres >"$output/docker-inspect-postgres.json"
docker image inspect "$(docker inspect -f '{{.Image}}' postgres)" >"$output/docker-image-inspect.json"
docker exec postgres pg_controldata /var/lib/postgresql/data >"$output/pg-controldata.txt"
docker exec postgres psql -U postgres -X -Atqc \
  "select slot_name,slot_type,active,restart_lsn,wal_status from pg_replication_slots order by slot_name" \
  >"$output/pg_replication_slots.txt"
docker exec postgres psql -U postgres -X -Atqc \
  "select application_name,client_addr,state,sync_state,sent_lsn,flush_lsn,replay_lsn from pg_stat_replication order by application_name" \
  >"$output/pg_stat_replication.txt"

for file in compose.yaml config/postgresql.conf config/pg_hba.conf scripts/entrypoint.sh; do
  if [[ -f $stack/$file ]]; then
    install -D -m 0600 "$stack/$file" "$output/files/$file"
  fi
done
if [[ -f $stack/.env ]]; then
  sed -n -E 's/^([A-Za-z_][A-Za-z0-9_]*)=.*/\1/p' "$stack/.env" | sort -u \
    >"$output/env-key-names.txt"
else
  : >"$output/env-key-names.txt"
fi
(
  cd "$output"
  sums=$(mktemp)
  find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum >"$sums"
  mv "$sums" SHA256SUMS
)
printf 'captured credential-free rollback state under %s\n' "$output"
