#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
network='postgres-ha-pgbouncer-test'
postgres='postgres-ha-auth-postgres'
pooler='postgres-ha-auth-pgbouncer'
secret_dir=$(mktemp -d)
postgres_password=$(openssl rand -hex 24)
auth_password=$(openssl rand -hex 24)
app_password_one=$(openssl rand -hex 24)
app_password_two=$(openssl rand -hex 24)

cleanup() {
  docker rm -f "$pooler" "$postgres" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  rm -rf "$secret_dir"
}
trap cleanup EXIT

docker network create "$network" >/dev/null
docker run -d --name "$postgres" --network "$network" --network-alias postgres \
  --user 999:999 --tmpfs /var/lib/postgresql/data:rw,uid=999,gid=999,mode=0700 \
  -e PGDATA=/var/lib/postgresql/data/pgdata -e POSTGRES_PASSWORD="$postgres_password" \
  pgvector/pgvector:0.8.5-pg18@sha256:12a379b47ad65289572ea0756efc11b7c241a6662833e8af7038cd3b73d647e0 >/dev/null
ready=0
for _ in $(seq 1 90); do
  if docker exec "$postgres" psql -U postgres -Atqc 'select 1' >/dev/null 2>&1; then
    ready=$((ready + 1))
    [[ $ready -ge 3 ]] && break
  else
    ready=0
  fi
  sleep 1
done
[[ $ready -ge 3 ]]

docker exec -i "$postgres" psql -U postgres -v ON_ERROR_STOP=1 \
  -v pgbouncer_auth_password="$auth_password" <"$root/sql/001-pgbouncer-auth.sql" >/dev/null
docker exec "$postgres" psql -U postgres -v ON_ERROR_STOP=1 \
  -c "CREATE ROLE app_user LOGIN PASSWORD '$app_password_one';" >/dev/null
docker exec "$postgres" createdb -U postgres -O app_user app

# auth_user acts as a PostgreSQL client, so it needs its plaintext secret to
# produce the SCRAM client proof; application verifiers still come from auth_query.
printf '"pgbouncer_auth" "%s"\n' "$auth_password" >"$secret_dir/pgbouncer_userlist"
chmod 0755 "$secret_dir"
chmod 0444 "$secret_dir/pgbouncer_userlist"

docker run -d --name "$pooler" --network "$network" \
  --user 6433:6433 --read-only --tmpfs /var/run/pgbouncer:rw,uid=6433,gid=6433,mode=0750 \
  --mount "type=bind,src=$root/config/pgbouncer,dst=/etc/pgbouncer,readonly" \
  --mount "type=bind,src=$secret_dir/pgbouncer_userlist,dst=/run/secrets/pgbouncer_userlist,readonly" \
  postgres-ha-pgbouncer:test >/dev/null
for _ in $(seq 1 60); do
  docker exec "$pooler" sh -c 'kill -0 1' >/dev/null 2>&1 && break
  sleep 1
done

PGPASSWORD="$app_password_one" docker run --rm --network "$network" \
  -e PGPASSWORD postgres:18 psql -h "$pooler" -p 6433 -U app_user -d app \
  -v ON_ERROR_STOP=1 -Atqc "select current_user" | grep -qx app_user

if PGPASSWORD=not-the-password docker run --rm --network "$network" \
  -e PGPASSWORD postgres:18 psql -h "$pooler" -p 6433 -U unknown_user -d app \
  -v ON_ERROR_STOP=1 -Atqc "select 1" >/dev/null 2>&1; then
  printf 'unknown role unexpectedly authenticated\n' >&2
  exit 1
fi

docker exec "$postgres" psql -U postgres -v ON_ERROR_STOP=1 \
  -c "ALTER ROLE app_user PASSWORD '$app_password_two';" >/dev/null
PGPASSWORD="$app_password_two" docker run --rm --network "$network" \
  -e PGPASSWORD postgres:18 psql -h "$pooler" -p 6433 -U app_user -d app \
  -v ON_ERROR_STOP=1 -Atqc "select current_user" | grep -qx app_user

printf 'pgbouncer-auth-integration=pass rotation=dynamic unknown-role=rejected\n'
