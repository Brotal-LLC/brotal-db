# PostgreSQL HA rollback

Rollback behavior changes at timeline boundaries. Identify the current Patroni leader, timeline, DCS health, and client wave before touching a container.

## Universal prohibitions

- Never run `docker compose down -v`.
- Never delete, reinitialize, or replace PGDATA as a first response.
- Never start an old manual-primary configuration after failover without proving that node is the current timeline leader.
- Preserve the failed data directory and inspect LSN/timeline ancestry; prefer `pg_rewind` where valid.

## Capture before change

On each database host:

```bash
sudo ./scripts/capture-rollback-state.sh
```

This records image/Compose/configuration checksums, mounts, ports, aliases, system identifier, timeline, slots, and replication state. `.env` contributes key names only—never credential values.

## Boundary 1 — before Patroni adoption

PostgreSQL PGDATA and its process are untouched. Stop/remove only the new etcd, PgBouncer, and HAProxy services. Direct clients on port 5432 continue unchanged. Persistent etcd state may be preserved for diagnosis but must not be confused with PostgreSQL data.

## Boundary 2 — after Armadillo adoption, before failover

If no promotion or timeline change occurred:

1. Stop only the Patroni-managed `postgres` container.
2. Restore the captured Compose/config files.
3. Recreate the old pinned `pgvector/pgvector` service against the exact captured PGDATA mount: Armadillo's `postgres-data` volume, Rogue's `/data/containers/postgres/data` bind path, or Fluffy's `/mnt/ts/postgres-data` bind path.
4. Verify the captured system identifier and databases.
5. Verify Rogue and Fluffy resume streaming and slots are active.

Do not use `down -v`, and do not change the mount while troubleshooting.

## Boundary 3 — after a Patroni failover

The former primary may be on an older timeline. Do not blindly start its old manual-primary config. Keep the current leader serving, then use Patroni rejoin/`pg_rewind` after validating DCS quorum and timeline ancestry. If rewind is unsafe or impossible, preserve the directory and restore/reseed from the verified backup under an approved procedure.

## Boundary 4 — after client migration

Roll back one consumer wave at a time. A direct-primary rollback is allowed only when Armadillo is verified as the current writable Patroni leader. Otherwise point the consumer at the HA endpoint or the current verified leader; writing to a recovered stale Armadillo creates split-brain with extra steps.

For each service restore its captured connection configuration, recreate only that service, verify login/read/write/background jobs, and monitor errors before moving to another service.

## Evidence before declaring rollback complete

- exactly one writable PostgreSQL node;
- system identifier unchanged;
- timeline and leader recorded;
- both replicas streaming or explicitly fenced;
- slots and retained WAL bounded;
- representative application read/write checks pass;
- direct and HA endpoints, if both remain enabled, resolve to the same leader;
- backup and rollback artifacts retained through the agreed soak period.
