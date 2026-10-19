# Lagbe Naki PostgreSQL bundle rollout

The existing cluster scope is `brotal-postgres`; its system identifier is
`7599356858936012842`. Keep the independent three-member etcd quorum, session
pooling, client addresses and all existing databases/roles. The reviewed bundle
is PostgreSQL 18.6, Patroni 4.1.5 and pg_textsearch 1.5.1 at revision
`fa142d049d08eac45a263f5abc250c8877ae076e`.

## Recovery gate

Run `scripts/backup-cluster.py` against the current primary into a new private
directory. Supply a public CMS recovery certificate; keep its private key off the
hosts. The helper captures every database, encrypted role passwords, database
ownership/locales, grants and database-specific settings. A progress receipt is
not a completed checkpoint. Failed/partial archives must never be restored.

Copy the completed checkpoint over the direct private LAN with a bandwidth cap.
Validate every registered SHA-256. Decrypt `roles.cms` only into the stdin of
`scripts/restore-cluster-checkpoint.py`, using the exact pinned image. The restore
uses a fresh task-owned volume and no network, validates recovered credential
fingerprints and restores every database with its original owner and locale.
Retain the checkpoint, restoration receipt and isolated restored volume through
acceptance. Verify representative data and client authentication as well.

Build pgvector with `OPTFLAGS=""` so the image does not inherit the build
machine's CPU instructions. Run the bundle smoke suite on every target CPU
class before promotion, including a 768-dimension cosine query and HNSW index.
An image that passes on a newer CPU can still crash PostgreSQL on an older host.

Do not replace/recreate live PostgreSQL until this gate passes. Stop if the next
step would require an extended shared-service outage.

## Rolling replacement

1. Save private copies of both host Compose definitions, environment/configuration,
   container inspections and current DCS configuration. Record the exact image ID.
2. Preserve armadillo's original `postgres-data` volume. Stop only its broken
   replica. Seed a **new empty** directory from rogue using the replication role,
   streaming WAL and the existing armadillo slot. Use the direct LAN with a rate
   cap; do not bulk-copy data over the DCS VPN path. Do not reset cluster identity.
3. Install the reviewed secret-loading entrypoint and `deploy/compose.bundle.yaml`.
   Supply `BROTAL_IMAGE` as the tested immutable image ID, `NODE_NAME=armadillo`
   and `BUNDLE_PGDATA` as the new directory. Layer over the saved host definition.
   Validate the complete configuration before starting only PostgreSQL. Never
   recreate unrelated services or mount the old PGDATA into the new deployment.
   Persist the validated PostgreSQL/PgBouncer definitions in the host's canonical
   Compose source so a later ordinary redeploy cannot return to the old PGDATA.
4. Wait for actual streaming, catch-up and DCS synchronous-standby eligibility.
   Restore armadillo's missing PgBouncer with its original session-pooling and
   authentication configuration. The overlay bounds PostgreSQL to 8 GiB/4 CPUs,
   reservation 2 GiB and shared memory 1 GiB, and PgBouncer to 512 MiB/1 CPU.
5. Perform an authenticated Patroni switchover to armadillo. Confirm the DCS leader,
   local primary status, read/write probes and primary-aware HAProxy routing.
6. Confirm rogue follows armadillo on the new timeline, then stop it cleanly and
   replace only its container using the same pinned image and overlay. This is a
   PostgreSQL 18 minor update: retain its current, synchronized data directory
   `/data/containers/postgres/data`. Keep the verified checkpoints and previous
   image/configuration. Wait for actual synchronous replication before acceptance.
7. Merge `config/upgrade/bundle-target.yml` into DCS without replacing unrelated
   settings. Preserve fail-closed quorum behavior with `failsafe_mode: false`;
   the reusable bundle's permissive default must not replace this fleet policy.
   Do not introduce a preload library into an old-image primary's
   configuration before that image contains it. Both upgraded nodes must load
   pg_textsearch and pg_stat_statements. Keep synchronous mode and one standby;
   verify real WAL flush acknowledgement rather than only replica connectivity.
8. Install `check-ha-health.py` and its bounded systemd service/timer on both
   hosts. Check `/var/lib/postgres-ha/health.json` and failed-unit/journal output.
   A missing/stalled member, lost slot or retained WAL over 8 GiB needs attention.
   Permanent member slots, a retention cap and member TTL prevent unbounded WAL.

## Application and rollback

Prepare the same signed external-dependency release on both hosts. Initialize only
Lagbe Naki's dedicated commerce/analytics databases from the verified grocery copy;
retain its source and media bytes. Coordinate migration/checkpoints through the
leased deployment lock. The supervisors activate only with an approved release,
linearizable DCS ownership and matching local Patroni identity. Redis database 12
is reserved for this store and disposable; shared authentication keys live in its
replicated database. Keep manual providers and background side effects disabled.

A failed application deployment stays in maintenance. Never restore an old dump
automatically or rewind post-launch writes. Roll back application images only
against a compatible current schema. Database recovery requires a separately
reviewed forward recovery/failover operation. Old PGDATA is a recovery artifact,
not an automatic replacement for the current primary.

Before acceptance, prove rogue activation and public recovery within 120 seconds,
media readability, one worker owner, quorum loss fencing and armadillo's replica
rejoin without automatic failback. Any return to armadillo is a controlled manual
switchover. Keep the previous release/configuration and recovery records.
