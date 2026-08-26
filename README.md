# Brotal PostgreSQL 18 bundle

A version-pinned PostgreSQL 18 Debian/bookworm image with pgvector, PostGIS (core/raster/topology), Timescale pg_textsearch, Apache-only TimescaleDB, Patroni, HAProxy and PgBouncer. Extension creation is opt-in and scoped to `POSTGRES_DB`; template1 is never modified.

## Quick start

`make secrets && make standalone-up`, then run `make smoke`. Only standalone PostgreSQL (5432) or HA PgBouncer (6432) binds localhost. Generated credentials live in ignored `.secrets/` files.

## Published images

Packages are published to GHCR as `ghcr.io/brotal-llc/brotal-db` and `ghcr.io/brotal-llc/brotal-db-pgbouncer`. Pushing an `18.*-bundle` tag publishes a signed multi-arch release.

## HA demo

`make ha-up` starts three Patroni nodes, three etcd v3 members, HAProxy and PgBouncer. This is a **single-host reference/demo, not production HA**: use separate failure domains, TLS, firewalling and resource limits in production. HA is not backup. Integrate WAL archiving (S3/object storage), scheduled base backups (pgBackRest/WAL-G), restore verification and a documented RPO/RTO.

HAProxy sends TCP traffic only to Patroni `/primary`; REST and etcd stay internal. PgBouncer defaults to session pooling, preserving transaction/session semantics; transaction pooling requires application validation.

## Compatibility and security

Versions are centralized in `versions.env`; the image builds exact PostgreSQL 18 extension releases. TimescaleDB is built with `APACHE_ONLY=ON` and telemetry disabled; TSL-only features are intentionally absent. `pg_trgm` is the correct spelling (not “pg_tgrm”). Passwords use strict `*_FILE` expansion; client-facing paths use SCRAM, and database clusters enable data checksums. Never commit `.env` or `.secrets`.

## Verification status

Verified locally on amd64: both final images build and load; standalone initializes all eight requested extensions, passes the SQL smoke suite, and restarts cleanly; the three-node Patroni stack bootstraps, serves the extension suite through PgBouncer/HAProxy, promotes a replica after leader loss, and rejoins the old leader with replicated data. Static validation also covers YAML/Compose rendering, Dockerfile outlines, shell syntax, and Patroni rendering. CI remains the gate for arm64 builds, vulnerability policy, release manifests, provenance, SBOMs, and signing.

## Operations

Standalone delegates initialization/startup to the official entrypoint. Patroni exclusively owns init/start and runs an idempotent leader-only post-bootstrap callback. Patroni uses async replication, bounded failover lag, `pg_rewind`, replication slots and failsafe mode. See `docs/standalone.md`, `docs/ha.md`, `docs/security.md`, and `docs/upgrades.md`.
