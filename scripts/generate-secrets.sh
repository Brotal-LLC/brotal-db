#!/bin/sh
set -eu
umask 077
mkdir -p .secrets
for name in postgres_password replication_password; do
  [ -s ".secrets/$name" ] || openssl rand -base64 32 | tr -d '\n' > ".secrets/$name"
done
cat > .env <<'EOF'
POSTGRES_USER=app
POSTGRES_DB=app
POSTGRES_PASSWORD_FILE=./.secrets/postgres_password
REPLICATION_USER=replicator
REPLICATION_PASSWORD_FILE=./.secrets/replication_password
POSTGRES_EXTENSIONS=vector,postgis,postgis_raster,postgis_topology,pg_trgm,pg_textsearch,timescaledb,pg_stat_statements
EOF
printf '"app" "%s"\n' "$(cat .secrets/postgres_password)" > .secrets/pgbouncer_users
chmod 600 .env .secrets/*
