# Backup and restore proof

This gate must pass before any live PostgreSQL container is recreated under Patroni. Replication is not a backup, and a dump that has never been restored is merely optimism with compression.

## 1. Create and verify the logical backup

On Armadillo:

```bash
cd /srv/stacks/databases
./scripts/backup-to-samsung.sh
stamp=$(find /mnt/netac2TB/backups/brotal_db/daily -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort | tail -1)
cd "/mnt/netac2TB/backups/brotal_db/daily/$stamp"
sha256sum -c SHA256SUMS
gzip -t globals.sql.gz
```

Record the stamp in the maintenance checklist. Do not modify or prune it until the migration soak period ends.

## 2. Preserve password-verifier recovery separately

The existing backup deliberately runs `pg_dumpall --globals-only --no-role-passwords`. It restores roles and role membership but **does not restore SCRAM password verifiers**, so it cannot prove application login recovery by itself.

Before adoption, create an encrypted, access-controlled role-verifier export in the approved secret backend. Never commit it or place it in the ordinary dump directory. One safe procedure is:

```bash
umask 077
docker exec postgres psql -U postgres -X -At -F $'\t' -c \
  "select rolname, rolpassword from pg_authid where rolcanlogin order by rolname" \
  | age -r "$BACKUP_RECIPIENT" > roles-with-verifiers.tsv.age
```

Verify decryptability in the restore rehearsal, apply verifiers with an audited script, and test representative application logins. If the encrypted verifier artifact is unavailable, rotate every login credential after restore; do not claim login recovery was proven.

## 3. Restore every dump into isolated PostgreSQL 18

Copy or run the tracked rehearsal on Armadillo:

```bash
sudo ./scripts/restore-logical-backup.sh \
  "/mnt/netac2TB/backups/brotal_db/daily/$stamp"
```

The harness:

- rechecks `SHA256SUMS` and gzip integrity;
- uses PostgreSQL 18.4 with pgvector 0.8.5 binaries;
- runs as UID/GID `999:999` with `--network none` and no published port;
- restores globals, every `.dump`, ownership, grants, and role membership;
- fails on the first `pg_restore` error;
- verifies database count, extension versions, and non-empty memberships;
- destroys only its disposable restore directory.

Expected final marker:

```text
restore-test=pass databases=<count> backup=<stamp>
```

## 4. Acceptance evidence

In addition to the automated marker, capture:

- database count equals dump count;
- extension versions, especially `vector`;
- representative schema/table counts and row counts for large databases;
- owners and role membership;
- representative application login using restored or deliberately rotated verifiers;
- no bind mount, network, or container name overlaps the live `postgres` service.

Keep the command output with the maintenance record. Never interpret an existing dump file as restore proof.

### 2026-08-12 count reconciliation

Backup `20260812T062340Z` contains exactly 22 `.dump` files and its
`SHA256SUMS` verification passes. The live cluster reports 23 databases with
`datallowconn = true` only because that predicate includes `template1`.
Filtering with the backup contract (`datallowconn AND NOT datistemplate`)
returns 22, matching both the dump count and the isolated restore result.
