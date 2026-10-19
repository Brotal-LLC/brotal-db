"""Contracts for backup, PKI, secret, staging, and rollback tooling."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    path = ROOT / relative
    assert path.is_file(), f"missing operational source: {relative}"
    return path.read_text(encoding="utf-8")


def test_etcd_pki_script_uses_verified_tailnet_sans_and_strict_permissions() -> None:
    script = read("scripts/generate-etcd-pki.sh")
    for required in (
        "etcd-hm:fluffy:100.64.0.2",
        "etcd-of:pi1:100.64.0.1",
        "etcd-witness:sv1-sg:100.64.0.3",
        "postgres-armadillo:100.64.0.5",
        "postgres-rogue:100.64.0.4",
        "fluffy:100.64.0.2",
        "serverAuth",
        "clientAuth",
        "subjectAltName",
        "chmod 0400",
        "openssl verify",
    ):
        assert required in script
    assert "217.216.110.195" not in script


def test_secret_generator_creates_distinct_named_files_without_printing_values() -> None:
    script = read("scripts/generate-secrets.sh")
    for secret in (
        "patroni_superuser_username",
        "patroni_superuser_password",
        "patroni_replication_username",
        "patroni_replication_password",
        "patroni_rewind_username",
        "patroni_rewind_password",
        "patroni_restapi_username",
        "patroni_restapi_password",
        "pgbouncer_auth_password",
        "pgbouncer_admin_password",
        "pgbouncer_stats_password",
    ):
        assert secret in script
    assert "umask 077" in script
    assert "openssl rand" in script
    assert "chmod 0400" in script
    assert "PATRONI_RUNTIME_UID" in script
    assert "PGBOUNCER_RUNTIME_UID" in script
    assert 'chmod 0711 "$output"' in script
    assert "pgbouncer_userlist" in script
    assert "pgbouncer_auth" in script
    assert "pgbouncer_admin" in script
    assert "pgbouncer_stats" in script
    assert "chown" in script
    assert 'cat "$' not in script


def test_haproxy_mount_sources_exist_for_every_deployment() -> None:
    for host in ("armadillo", "rogue", "fluffy", "pi1"):
        assert (ROOT / "config" / "haproxy" / f"{host}.cfg").is_file()


def test_control_plane_stager_allows_only_explicit_non_postgres_services(tmp_path: Path) -> None:
    script = ROOT / "scripts" / "stage-control-plane.sh"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    record = tmp_path / "docker-argv"
    docker = fake_bin / "docker"
    docker.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$STAGE_RECORD"\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)
    compose = tmp_path / "compose.yaml"
    compose.write_text("services: {}\n", encoding="utf-8")
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "STAGE_RECORD": str(record),
    }

    result = subprocess.run(
        [str(script), "db", str(compose)],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    argv = record.read_text(encoding="utf-8").splitlines()
    assert argv[-4:] == ["--force-recreate", "--no-deps", "pgbouncer", "haproxy"]
    assert "postgres" not in argv

    result = subprocess.run(
        [str(script), "pool", str(compose)],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    argv = record.read_text(encoding="utf-8").splitlines()
    assert argv[-3:] == ["--force-recreate", "--no-deps", "pgbouncer"]
    assert "postgres" not in argv

    record.unlink()
    result = subprocess.run(
        [str(script), "postgres", str(compose)],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )
    assert result.returncode != 0
    assert not record.exists()


def test_restore_rehearsal_is_isolated_non_root_and_restores_every_dump() -> None:
    script = read("scripts/restore-logical-backup.sh")
    for required in (
        "--user 999:999",
        "--network none",
        "sha256sum -c SHA256SUMS",
        "pg_restore",
        "--exit-on-error",
        "globals.sql.gz",
        "CREATE ROLE postgres",
        "restore-test=pass",
    ):
        assert required in script
    assert "--privileged" not in script
    assert "docker compose down -v" not in script


def test_rollback_capture_records_state_without_copying_env_values() -> None:
    script = read("scripts/capture-rollback-state.sh")
    for required in (
        "docker inspect postgres",
        "pg_controldata",
        "pg_replication_slots",
        "pg_stat_replication",
        "sha256sum",
        "env-key-names.txt",
    ):
        assert required in script
    assert "cp .env" not in script


def test_runbooks_define_restore_proof_and_timeline_aware_rollback_boundaries() -> None:
    backup = read("runbooks/backup-restore.md")
    rollback = read("runbooks/rollback.md")
    for required in (
        "SHA256SUMS",
        "restore-logical-backup.sh",
        "database count",
        "extension",
        "role membership",
        "application login",
    ):
        assert required.lower() in backup.lower()
    for required in (
        "before patroni adoption",
        "after armadillo adoption",
        "after a patroni failover",
        "after client migration",
        "never run `docker compose down -v`",
        "timeline",
        "pg_rewind",
    ):
        assert required.lower() in rollback.lower()
