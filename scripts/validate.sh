#!/bin/sh
set -eu
root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd); cd "$root"
if command -v shellcheck >/dev/null 2>&1; then shellcheck docker/postgres/*.sh docker/pgbouncer/*.sh scripts/*.sh tests/shell/*.sh; fi
for f in docker/postgres/*.sh docker/pgbouncer/*.sh scripts/*.sh tests/shell/*.sh; do
  first=$(sed -n '1s/^#!//p' "$f")
  case "$first" in */bash*) bash -n "$f";; */sh*) sh -n "$f";; *) echo "unsupported shell shebang: $f" >&2; exit 1;; esac
done
case "$(stat -c '%a' docker/haproxy/haproxy.cfg)" in *[4567]) : ;; *) echo 'docker/haproxy/haproxy.cfg must be world-readable for the HAProxy container' >&2; exit 1;; esac
python3 - <<'PY'
import glob, yaml
files = glob.glob('**/*.yml', recursive=True) + glob.glob('**/*.yaml', recursive=True) + glob.glob('.github/workflows/*.yml') + glob.glob('.github/workflows/*.yaml')
for f in sorted(set(files)):
    with open(f, encoding='utf8') as h: yaml.safe_load(h)
with open('compose/ha.yml', encoding='utf8') as h:
    ha = yaml.safe_load(h)
with open('.github/workflows/release.yml', encoding='utf8') as h:
    release_text = h.read()
    release = yaml.safe_load(release_text)
assert '$REGISTRY/$GITHUB_REPOSITORY' not in release_text
assert 'ghcr.io/${{ github.repository }}' not in release_text
assert release_text.count('repository="${GITHUB_REPOSITORY,,}"') >= 3
assert release_text.count('org.opencontainers.image.source=') >= 2
assert release_text.count('org.opencontainers.image.revision=') >= 2
assert release_text.count('org.opencontainers.image.version=') >= 2
assert 'db="$REGISTRY/$repository:$TAG"' in release_text
assert 'pool="$REGISTRY/$repository-pgbouncer:$TAG"' in release_text
assert release['jobs']['build']['needs'] == 'verify'
assert release['jobs']['merge']['needs'] == 'build'
expected = {'etcd1:2379', 'etcd2:2379', 'etcd3:2379'}
for node in ('postgres1', 'postgres2', 'postgres3'):
    env = ha['services'][node]['environment']
    assert isinstance(env, dict) and set(env) == {'DB_MODE', 'PGDATA', 'PATRONI_NAME', 'ETCD_HOSTS', 'POSTGRES_PASSWORD_FILE', 'REPLICATION_PASSWORD_FILE'}
    assert set(env['ETCD_HOSTS'].split(',')) == expected
versions = {}
with open('versions.env', encoding='utf8') as h:
    for line in h:
        line = line.strip()
        if line and not line.startswith('#'):
            key, value = line.split('=', 1)
            versions[key] = value
assert ha['services']['etcd1']['image'] == versions['ETCD_IMAGE']
assert ha['services']['haproxy']['image'] == versions['HAPROXY_IMAGE']
assert f":{versions['ETCD_VERSION']}@" in versions['ETCD_IMAGE']
assert f":{versions['HAPROXY_VERSION']}@" in versions['HAPROXY_IMAGE']
assert f":{versions['POSTGRES_MAJOR']}." in versions['POSTGRES_IMAGE']
for workflow in ('.github/workflows/ci.yml', '.github/workflows/release.yml'):
    with open(workflow, encoding='utf8') as h: workflow_text = h.read()
    assert 'brotal/postgres:candidate' in workflow_text and 'brotal/pgbouncer:candidate' in workflow_text
    assert f"brotal/postgres:{versions['POSTGRES_MAJOR']}-bundle" not in workflow_text
    assert f"brotal/pgbouncer:{versions['PGBOUNCER_VERSION']}" not in workflow_text
    assert f"/usr/lib/postgresql/{versions['POSTGRES_MAJOR']}/" not in workflow_text
    assert f"timescaledb-{versions['TIMESCALEDB_VERSION']}.so" not in workflow_text
with open('.dockerignore', encoding='utf8') as h: ignored = {line.strip() for line in h if line.strip()}
assert {'.env', '.secrets'} <= ignored
with open('docker-bake.hcl', encoding='utf8') as h: bake = h.read()
with open('docker/postgres/Dockerfile', encoding='utf8') as h: postgres_dockerfile = h.read()
with open('docker/pgbouncer/Dockerfile', encoding='utf8') as h: pgbouncer_dockerfile = h.read()
with open('docker/postgres/requirements.lock', encoding='utf8') as h: python_lock = h.read()
assert f"patroni=={versions['PATRONI_VERSION']} \\" in python_lock
assert f"psycopg=={versions['PSYCOPG_VERSION']} \\" in python_lock
assert f"psycopg-binary=={versions['PSYCOPG_VERSION']} \\" in python_lock
assert '--hash=sha256:' in python_lock
assert '--require-hashes -r /tmp/requirements.lock' in postgres_dockerfile
assert ' util-linux && rm -f /usr/local/bin/gosu' in postgres_dockerfile
assert 'setpriv --reuid postgres --regid "$(id -g postgres)" --init-groups' in postgres_dockerfile
assert ' util-linux ' in pgbouncer_dockerfile and ' gosu' not in pgbouncer_dockerfile
assert 'exec setpriv --reuid postgres --regid "$(id -g postgres)" --init-groups' in open('docker/postgres/entrypoint.sh', encoding='utf8').read()
assert 'exec setpriv --reuid pgbouncer --regid "$(id -g pgbouncer)" --init-groups' in open('docker/pgbouncer/entrypoint.sh', encoding='utf8').read()
assert f'variable "POSTGRES_MAJOR" {{ default = "{versions["POSTGRES_MAJOR"]}" }}' in bake
assert 'tags = ["brotal/postgres:${POSTGRES_MAJOR}-bundle", "brotal/postgres:candidate"]' in bake
assert 'tags = ["brotal/pgbouncer:${PGBOUNCER_VERSION}", "brotal/pgbouncer:candidate"]' in bake
postgres_keys = ('POSTGRES_IMAGE', 'PGVECTOR_VERSION', 'POSTGIS_VERSION', 'PG_TEXTSEARCH_VERSION', 'TIMESCALEDB_VERSION', 'PATRONI_VERSION', 'PSYCOPG_VERSION', 'PGVECTOR_SHA256', 'POSTGIS_SHA256', 'PG_TEXTSEARCH_SHA256', 'TIMESCALEDB_SHA256')
pgbouncer_keys = ('DEBIAN_BOOKWORM_IMAGE', 'DEBIAN_BOOKWORM_SLIM_IMAGE', 'PGBOUNCER_VERSION', 'PGBOUNCER_SHA256')
for key in postgres_keys + pgbouncer_keys:
    assert f'variable "{key}" {{ default = "{versions[key]}" }}' in bake, f'{key} drifted in docker-bake.hcl'
for key in postgres_keys:
    assert f'{key}={versions[key]}' in postgres_dockerfile, f'{key} drifted in PostgreSQL Dockerfile'
for key in pgbouncer_keys:
    assert f'{key}={versions[key]}' in pgbouncer_dockerfile, f'{key} drifted in PgBouncer Dockerfile'
PY
env_created=0; [ -f .env ] || env_created=1
secret_created_postgres=0; [ -f .secrets/postgres_password ] || secret_created_postgres=1
secret_created_replication=0; [ -f .secrets/replication_password ] || secret_created_replication=1
secret_created_pgbouncer=0; [ -f .secrets/pgbouncer_users ] || secret_created_pgbouncer=1
if [ "$env_created" -eq 1 ] || [ "$secret_created_postgres" -eq 1 ] || [ "$secret_created_replication" -eq 1 ] || [ "$secret_created_pgbouncer" -eq 1 ]; then ./scripts/generate-secrets.sh; fi
cleanup() {
  [ "$env_created" -eq 1 ] && rm -f .env
  [ "$secret_created_postgres" -eq 1 ] && rm -f .secrets/postgres_password
  [ "$secret_created_replication" -eq 1 ] && rm -f .secrets/replication_password
  [ "$secret_created_pgbouncer" -eq 1 ] && rm -f .secrets/pgbouncer_users
  return 0
}
trap cleanup EXIT
for f in compose/*.yml; do docker compose --env-file .env -f "$f" config >/dev/null; done
./tests/shell/render-patroni.sh
docker buildx bake --print | python3 -c 'import json, sys; d=json.load(sys.stdin); v=dict(line.strip().split("=", 1) for line in open("versions.env", encoding="utf8") if line.strip() and not line.startswith("#")); assert d["target"]["postgres"]["tags"] == ["brotal/postgres:" + v["POSTGRES_MAJOR"] + "-bundle", "brotal/postgres:candidate"]; assert d["target"]["pgbouncer"]["tags"] == ["brotal/pgbouncer:" + v["PGBOUNCER_VERSION"], "brotal/pgbouncer:candidate"]'
docker buildx build --file docker/postgres/Dockerfile --call=outline . >/dev/null
docker buildx build --file docker/pgbouncer/Dockerfile --call=outline . >/dev/null
printf '%s\n' 'static validation passed'
