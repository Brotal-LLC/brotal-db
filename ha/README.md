# PostgreSQL HA Infrastructure

Canonical, version-controlled infrastructure for migrating the Brotal PostgreSQL fleet to a
Patroni-managed HA cluster. This directory in `Brotal-LLC/brotal-db` is the source of truth; rendered host-specific
configuration is deployed from here to `/srv/stacks/` and is never edited in place.

## Scope

The migration introduces:

- Patroni-supervised PostgreSQL physical replication;
- a three-member, TLS-authenticated etcd control plane in independent failure domains;
- PgBouncer for dynamic SCRAM authentication and connection pooling; and
- HAProxy role-aware routing to the current primary.

The repository deliberately contains templates, source configuration, tests, and runbooks—not
production credentials, private keys, certificates, `.env` files, or rendered deployment output.

## Layout

```text
compose/       Compose definitions for deployable services
config/        Version-controlled service configuration
images/        Reproducible image definitions
scripts/       Tracked validation and operational scripts
sql/           Replicated database bootstrap SQL
tests/unit/    Fast source and configuration contract tests
tests/integration/ Disposable Testcontainers Patroni failover lab
tests/heavy/   Opt-in local partition/churn drills; never run in CI
```

Directories are added with the task that first needs them. Do not create or deploy configuration
outside this repository without adding its source and validation contract here first.

## Local validation

Prerequisites: Python 3.11+, Docker Compose v2, and `pre-commit`. The pre-commit environments
provide `ruff`, `yamllint`, `shellcheck`, `hadolint`, standard YAML/file checks, private-key
scanning, and the repository contract tests.

```bash
make ha-check
```

Run the fast contract test directly while developing:

```bash
uv run --locked --directory ha pytest tests/unit -v
```

Run the disposable three-node failover lab locally:

```bash
make ha-integration
```

The lab uses Testcontainers and an isolated Compose project with tmpfs PostgreSQL data. It proves
ordered synchronous promotion, HAProxy-to-PgBouncer writes, old-primary rewind/rejoin without
automatic failback, authenticated controlled switchover, and final promotion of the lower-priority
standby after sequential node loss. It publishes no host ports, mounts no live `PGDATA`, runs every
service non-root, and removes all containers and networks after the test.

When Compose definitions exist, the hook renders each one with `docker compose config --quiet`.
This catches invalid interpolation and merged Compose structure before deployment.

## Secret and deployment policy

- Keep live secrets in the target platform's secret store or a local ignored `secrets/` directory.
- Never commit `.env`, certificate/key material, generated secret files, or host-rendered output.
- Do not run `docker compose down -v`; PostgreSQL and etcd stateful volumes must be preserved.
- Runtime and development containers must run as non-root users.
- Deploy copies from this repository into `/srv/stacks/`; the live deployment path is not canonical.

See the approved migration plan for rollout, quorum gates, backups, rollback, and failover tests.

The commands above run from the Brotal DB repository root. The original source was
imported from `postgres-ha` revision `13b6946`, together with the previously
uncommitted Zabbix pool sizing, armadillo LAN listener, rogue PGDATA correction and
the .NET consumer-cutover helper/tests. The former checkout is retained for local
history and recovery; publish subsequent infrastructure changes here.

The preserved non-root image definitions and adoption configurations describe the
earlier fleet migration. For the current PostgreSQL 18.6 bundle, use the immutable
image selected by `BROTAL_IMAGE` and layer `deploy/compose.bundle.yaml` as described
in `runbooks/lagbenaki-bundle-rollout.md`; do not build the older adoption image as
a substitute for the reviewed bundle.
