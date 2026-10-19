#!/bin/sh
set -eu

: "${PGDATA:?PGDATA required}"
: "${PRIMARY_HOST:?PRIMARY_HOST required}"
: "${LEGACY_NODE_NAME:?LEGACY_NODE_NAME required}"
password=$(tr -d '\r\n' </run/secrets/legacy_replication_password)

if [ ! -s "$PGDATA/PG_VERSION" ]; then
    rm -rf "${PGDATA:?}"/*
    PGPASSWORD="$password" pg_basebackup \
        -h "$PRIMARY_HOST" -p 5432 -U replicator \
        -D "$PGDATA" -Fp -Xs -R --checkpoint=fast
    cat >>"$PGDATA/postgresql.auto.conf" <<EOF
primary_conninfo = 'host=$PRIMARY_HOST port=5432 user=replicator password=$password application_name=$LEGACY_NODE_NAME'
primary_slot_name = '$LEGACY_NODE_NAME'
EOF
fi

test -f "$PGDATA/standby.signal"
exec postgres \
    -c config_file=/etc/postgresql/postgresql.conf \
    -c hba_file=/etc/postgresql/pg_hba.conf
