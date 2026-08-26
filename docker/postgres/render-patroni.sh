#!/bin/bash
set -Eeuo pipefail
: "${PATRONI_NAME:?PATRONI_NAME is required}" "${ETCD_HOSTS:?ETCD_HOSTS is required}" "${POSTGRES_USER:?POSTGRES_USER is required}" "${REPLICATION_USER:?REPLICATION_USER is required}" "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}" "${REPLICATION_PASSWORD:?REPLICATION_PASSWORD is required}"
output="${1:-/etc/patroni/patroni.yml}"
python3 - "$output" <<'PY'
import json, os, sys
out = sys.argv[1]
def q(value):
    return json.dumps(value)
name = os.environ['PATRONI_NAME']
pgdata = os.environ.get('PGDATA', '/var/lib/postgresql/18/data')
lines = f'''scope: brotal
name: {q(name)}
restapi:
  listen: 0.0.0.0:8008
  connect_address: {q(name + ':8008')}
etcd3:
  hosts: {q(os.environ['ETCD_HOSTS'])}
bootstrap:
  dcs:
    ttl: 30
    loop_wait: 10
    retry_timeout: 10
    synchronous_mode: false
    maximum_lag_on_failover: 1048576
    failsafe_mode: true
    postgresql:
      use_pg_rewind: true
      use_slots: true
      parameters:
        wal_level: replica
        hot_standby: 'on'
        wal_log_hints: 'on'
        max_wal_senders: 10
        max_replication_slots: 10
        shared_preload_libraries: timescaledb,pg_textsearch,pg_stat_statements
        password_encryption: scram-sha-256
      pg_hba:
        - local all all scram-sha-256
        - host all all 127.0.0.1/32 scram-sha-256
        - host all all 0.0.0.0/0 scram-sha-256
        - host all all ::/0 scram-sha-256
        - {q('host replication ' + os.environ['REPLICATION_USER'] + ' 0.0.0.0/0 scram-sha-256')}
        - {q('host replication ' + os.environ['REPLICATION_USER'] + ' ::/0 scram-sha-256')}
  initdb:
    - encoding: UTF8
    - data-checksums
  post_init: /usr/local/bin/post_bootstrap.sh
postgresql:
  listen: 0.0.0.0:5432
  connect_address: {q(name + ':5432')}
  data_dir: {q(pgdata)}
  pgpass: /var/lib/postgresql/.pgpass
  basebackup:
    checkpoint: fast
  authentication:
    superuser: {{username: {q(os.environ['POSTGRES_USER'])}, password: {q(os.environ['POSTGRES_PASSWORD'])}}}
    replication: {{username: {q(os.environ['REPLICATION_USER'])}, password: {q(os.environ['REPLICATION_PASSWORD'])}}}
'''
with open(out, 'w', encoding='utf8') as handle:
    handle.write(lines)
os.chmod(out, 0o600)
PY
if [[ "$EUID" -eq 0 ]]; then chown postgres:postgres "$output"; fi
