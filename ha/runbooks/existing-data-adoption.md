# Existing-data Patroni adoption

## Hard gate

Do not replace the legacy PostgreSQL container with a Patroni-only container as the first adoption step.

Patroni's supported existing-data procedure requires Patroni to **observe the already-running PostgreSQL primary** before Patroni owns its startup procedure. It detects the existing system identifier, registers the member and leader state in DCS, and only then takes startup ownership through a controlled `patronictl restart`.

The current production layout runs PostgreSQL and its supervisor in one container. A separate replacement Patroni container cannot observe the PostgreSQL process that was running in the removed container, even when it mounts the same PGDATA. The transitional supervisor path must therefore be proven before another maintenance attempt.

## Required transitional design

Create and test a transitional entrypoint that, in one container and one network/PGDATA context:

1. starts the existing PostgreSQL primary with its current configuration and HBA;
2. waits for writable readiness and validates the existing system identifier;
3. starts Patroni so it can observe and monitor that already-running process;
4. verifies Patroni acquires the initial leader lock without creating `standby.signal`;
5. transfers startup ownership only through `patronictl restart`;
6. preserves the stable container name, volume, direct port, Docker aliases, and rollback source.

Do not deploy that transitional entrypoint until an **existing-PGDATA regression lab** proves the exact production sequence with a primary and two already-streaming standbys. An empty-PGDATA bootstrap lab is necessary but not sufficient.

## Compatibility required during mixed supervision

Until Rogue and Fluffy are themselves Patroni-managed:

- keep permanent physical slots `rogue` and `nest1` in DCS;
- permit the legacy replication user `replicator` from the existing private-site CIDRs;
- permit `patroni_replication` over IPv4 and IPv6 loopback so Patroni can query its own timeline;
- permit `patroni_replication` from each possible leader's Docker bridge CIDR when published
  Tailnet ports SNAT remote members to that bridge gateway; prove every directed member-to-member
  `IDENTIFY_SYSTEM` path before enabling failover;
- preserve `max_connections: 1000` in bootstrap DCS parameters and verify it in live
  `patronictl show-config` before the first ownership restart; if it is absent, apply it through
  `patronictl edit-config` before restarting because Patroni's default is 100;
- keep synchronous mode disabled until the preferred standby is under Patroni.

A bind-mounted configuration file is inode-bound inside the running container. Do not atomically
replace its host path and assume Patroni can reload the new file: the container may retain the
unlinked old inode. Write in place before the first mount, or sequentially force-recreate one
replica at a time and prove it has rejoined before recreating the next member.

Remove legacy slots and HBA compatibility only after the Patroni member slots have equal-or-newer `restart_lsn` and the old clients no longer connect.

## 2026-08-12 production adoption attempt

All pre-adoption gates passed:

- fresh checksum-verified backup `20260812T111016Z`;
- isolated restore marker `restore-test=pass databases=22`;
- pgvector `0.8.5` restored;
- encrypted login-role verifier recovery;
- identical system identifier and PostgreSQL binaries across all nodes;
- both standbys caught up through the final write checkpoint;
- three-member etcd quorum healthy and Patroni scope empty;
- local Hermes gateway guarded against restart.

The first Armadillo handoff stopped and removed only the legacy `postgres` container and created the Patroni container against the same `postgres-data` volume. Patroni registered the existing system identifier but started PostgreSQL as an unlocked replica and created `standby.signal`. It could not determine the local timeline because generated HBA lacked loopback replication access. Existing replicas were also rejected because they still used the legacy `replicator` role.

No Patroni leader was elected, no PostgreSQL node was promoted, and no timeline changed. Forward adoption was halted.

Boundary-2 rollback then:

1. stopped and removed only the Patroni Armadillo container;
2. removed only the `standby.signal` created during the failed handoff;
3. recreated the original `databases/postgres` service against the same volume;
4. verified Armadillo writable on timeline 1 with the original system identifier and 22 databases;
5. verified Rogue and Fluffy streaming on timeline 1 and both legacy slots active;
6. removed the single verified unleased DCS `initialize` residue and returned the Patroni scope to empty.

## Hermes/mem0 boundary proof

The local Hermes gateway process was never restarted and retained the same PID throughout the PostgreSQL restart and rollback. Its existing psycopg pool sockets were severed. The first post-restart mem0 operation failed with `connection is lost`; an immediate retry succeeded after the pool discarded and replaced the dead connection.

Therefore PostgreSQL maintenance does not inherently require a Hermes gateway restart, and active agent sessions can survive. It is not a transparent hot swap: one memory operation at the connection-reset boundary can fail and must be retried.

## Next production gate

The transitional regression gate passed on 2026-08-12 with PostgreSQL 18 and Patroni 4.1.4:

- the primary and two named-slot standbys began under legacy supervision;
- Patroni observed each already-running postmaster as a sibling process;
- the primary retained its system identifier, timeline, writeability, marker data, and two streams;
- each `patronictl restart` changed the postmaster PID without stopping the container;
- Patroni's `/replica` readiness endpoint remained healthy for both standbys;
- each node was then recreated with the normal Patroni entrypoint and rejoined healthy;
- an injected failure after leader registration but before ownership transfer restored the legacy
  primary with the same system identifier and timeline, two streaming replicas, no
  `standby.signal`, and an empty DCS scope.

This clears the technical lab gate. It does **not** authorize production disruption. Obtain an
explicit maintenance-window approval before continuing.

## Production sequence after approval

Use the staged control tree `/srv/stacks/postgres-ha-control` and the untouched rollback source
`/srv/stacks/databases`. Never use `down`, `down -v`, `restart`, or an unqualified Compose command.

For each node, render both files before mutation:

```bash
docker compose -f compose.yaml -f compose.adoption.yaml config --quiet
docker compose -f compose.yaml config --quiet
```

Adopt Armadillo first:

1. Reconfirm the gateway PID guard, checksum-verified backup/restore proof, empty DCS scope,
   timeline 1, expected system identifier, two active slots, and two streaming replicas.
2. Checkpoint and prove both standbys have replayed through the write boundary.
3. Capture the legacy postmaster PID and credential-free rollback state.
4. Stop/remove only the legacy `databases/postgres` container.
5. Recreate only `postgres` with `compose.yaml` plus `compose.adoption.yaml`, using
   `--force-recreate --no-deps`. The overlay selects the non-root sibling supervisor and mounts
   the exact legacy PostgreSQL configuration read-only.
6. Before any `patronictl restart`, require Armadillo to be the DCS leader, `/primary` HTTP 200,
   writable SQL, unchanged system identifier/timeline, absent `standby.signal`, the original
   legacy postmaster PID parented by PID 1, and two streaming replicas.
7. Run `patronictl restart` for Armadillo. Require a changed postmaster PID, `/primary` HTTP 200,
   marker/data/database/slot parity, and two streams.
8. Recreate only `postgres` from base `compose.yaml` without the adoption overlay. Verify the
   running entrypoint is `/usr/local/bin/patroni-entrypoint`, no adoption environment remains,
   and Armadillo is still leader/writable.

Adopt Rogue and then Fluffy with the same observe-first/restart-second/base-only sequence. Before
and after each restart require `pg_is_in_recovery() = true`, Patroni `/replica` HTTP 200, unchanged
system identifier, correct timeline, and primary-side streaming state.

### Automatic rollback boundary

Before `patronictl restart`, a failed gate remains pre-divergence and may restore legacy
supervision only after rechecking the expected system identifier and timeline. Stop/remove only
the transitional `postgres`, clear only the verified unleased Patroni scope, recreate only the
original `databases/postgres`, and prove the original topology. Never remove `standby.signal`
unless the exact failed transitional attempt created it and the system identifier/timeline still
match the captured boundary.

After `patronictl restart`, rollback is no longer this automatic path. Re-evaluate timeline and
DCS leadership before changing supervision; never blindly restore the former topology.

Throughout all PostgreSQL restarts, keep `hermes-gateway.service` on the existing PID. Retry one
failed mem0 operation after a stale pooled socket is discarded; do not restart the gateway.
