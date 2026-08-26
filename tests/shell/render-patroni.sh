#!/bin/sh
set -eu
out=$(mktemp)
trap 'rm -f "$out"' EXIT
PATRONI_NAME=demo ETCD_HOSTS=etcd:2379 POSTGRES_USER=app REPLICATION_USER=replicator POSTGRES_PASSWORD=secret REPLICATION_PASSWORD=repsecret PGDATA=/var/lib/postgresql/18/data \
  docker/postgres/render-patroni.sh "$out"
python3 - "$out" <<'PY'
import sys, yaml
with open(sys.argv[1], encoding='utf8') as h: c=yaml.safe_load(h)
assert c['name'] == 'demo'
assert c['restapi']['connect_address'] == 'demo:8008'
assert c['postgresql']['connect_address'] == 'demo:5432'
assert c['postgresql']['data_dir'] == '/var/lib/postgresql/18/data'
assert c['postgresql']['basebackup']['checkpoint'] == 'fast'
assert c['bootstrap']['post_init'] == '/usr/local/bin/post_bootstrap.sh'
assert c['bootstrap']['dcs']['maximum_lag_on_failover'] == 1048576
assert c['bootstrap']['dcs']['failsafe_mode'] is True
assert any('replication replicator 0.0.0.0/0 scram-sha-256' in rule for rule in c['bootstrap']['dcs']['postgresql']['pg_hba'])
assert any('host all all 0.0.0.0/0 scram-sha-256' in rule for rule in c['bootstrap']['dcs']['postgresql']['pg_hba'])
PY
mode=$(stat -c '%a' "$out")
[ "$mode" = 600 ]
printf '%s\n' 'Patroni renderer test passed'
