#!/usr/bin/env bash
set -euo pipefail

backup_root=${1:?usage: restore-logical-backup.sh <backup-directory> [restore-directory]}
restore_root=${2:-/srv/state/postgres-ha-restore-test}
container=${RESTORE_CONTAINER:-postgres-ha-restore-test}
image='pgvector/pgvector:0.8.5-pg18@sha256:12a379b47ad65289572ea0756efc11b7c241a6662833e8af7038cd3b73d647e0'

cleanup() { docker rm -f "$container" >/dev/null 2>&1 || true; }
trap cleanup EXIT

(cd "$backup_root" && sha256sum -c SHA256SUMS)
gzip -t "$backup_root/globals.sql.gz"
rm -rf "$restore_root"
install -d -o 999 -g 999 -m 0700 "$restore_root"

docker run -d --name "$container" \
  --user 999:999 --network none \
  -e POSTGRES_HOST_AUTH_METHOD=trust \
  -e PGDATA=/var/lib/postgresql/data/pgdata \
  --mount "type=bind,src=$restore_root,dst=/var/lib/postgresql/data" \
  --mount "type=bind,src=$backup_root,dst=/backup,readonly" \
  "$image" >/dev/null

for _ in $(seq 1 120); do
  docker exec "$container" pg_isready -U postgres -d postgres >/dev/null 2>&1 && break
  docker inspect -f '{{.State.Running}}' "$container" | grep -qx true || {
    docker logs "$container" >&2
    exit 1
  }
  sleep 1
done
docker exec "$container" pg_isready -U postgres -d postgres >/dev/null

# The disposable cluster already owns postgres. Remove only its duplicate role declaration;
# retain every other role, membership, ownership, and grant from globals.sql.gz.
gzip -dc "$backup_root/globals.sql.gz" \
  | grep -v -E '^(CREATE ROLE postgres;|ALTER ROLE postgres WITH )' \
  | docker exec -i "$container" psql -v ON_ERROR_STOP=1 -U postgres -d postgres

restored=0
for dump in "$backup_root"/*.dump; do
  database=$(basename "$dump" .dump)
  [[ $database == postgres ]] || docker exec "$container" createdb -U postgres "$database"
  docker exec "$container" pg_restore --exit-on-error -U postgres -d "$database" \
    "/backup/$(basename "$dump")"
  restored=$((restored + 1))
done
expected=$(find "$backup_root" -maxdepth 1 -type f -name '*.dump' | wc -l)
[[ $restored -eq $expected ]]

docker exec "$container" psql -v ON_ERROR_STOP=1 -U postgres -d postgres -Atqc \
  "select count(*) from pg_database where datallowconn and not datistemplate" | grep -qx "$expected"
docker exec "$container" psql -v ON_ERROR_STOP=1 -U postgres -d postgres -Atqc \
  "select extname || '=' || extversion from pg_extension order by extname"
docker exec "$container" psql -v ON_ERROR_STOP=1 -U postgres -d postgres -Atqc \
  "select count(*) from pg_auth_members" | grep -Eq '^[1-9][0-9]*$'

printf 'restore-test=pass databases=%s backup=%s\n' "$restored" "$(basename "$backup_root")"
cleanup
trap - EXIT
rm -rf "$restore_root"
