"""Adopt an already-streaming PostgreSQL 18 topology without replacing PGDATA."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "tests" / "integration" / "existing_data_lab"
NODES = ("armadillo", "rogue", "fluffy")


def run(command: list[str], *, env: dict[str, str], check: bool = True) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result.stdout.strip()


def eventually(assertion, timeout: float = 120, interval: float = 1) -> None:
    deadline = time.monotonic() + timeout
    error: BaseException | None = None
    while time.monotonic() < deadline:
        try:
            assertion()
            return
        except (AssertionError, RuntimeError) as exc:
            error = exc
            time.sleep(interval)
    raise AssertionError(f"condition not met within {timeout}s") from error


def write_secret(root: Path, name: str, value: str) -> None:
    path = root / name
    path.write_text(value + "\n", encoding="utf-8")
    path.chmod(0o444)


def create_lab(tmp_path: Path) -> ExistingDataLab:
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir(mode=0o755)
    generated = {
        "postgres_password": secrets.token_hex(24),
        "legacy_replication_password": secrets.token_hex(24),
        "patroni_superuser_username": "patroni_superuser",
        "patroni_superuser_password": secrets.token_hex(24),
        "patroni_replication_username": "patroni_replication",
        "patroni_replication_password": secrets.token_hex(24),
        "patroni_rewind_username": "patroni_rewind",
        "patroni_rewind_password": secrets.token_hex(24),
        "patroni_restapi_username": "patroni_restapi",
        "patroni_restapi_password": secrets.token_hex(24),
    }
    for name, value in generated.items():
        write_secret(secret_dir, name, value)

    project = f"postgres-ha-existing-{secrets.token_hex(4)}"
    env = {**os.environ, "LAB_SECRETS_DIR": str(secret_dir)}
    return ExistingDataLab(project, env)


class ExistingDataLab:
    def __init__(self, project: str, env: dict[str, str]) -> None:
        self.project = project
        self.env = env
        self.base = [
            "docker",
            "compose",
            "--project-name",
            project,
            "--file",
            str(LAB / "compose.yaml"),
        ]

    def compose(self, *args: str, adoption: bool = False, check: bool = True) -> str:
        command = [*self.base]
        if adoption:
            command.extend(("--profile", "adoption"))
        command.extend(args)
        return run(command, env=self.env, check=check)

    def exec(self, service: str, *command: str) -> str:
        return self.compose("exec", "-T", service, *command)

    def psql(self, service: str, sql: str) -> str:
        return self.exec(
            service,
            "psql",
            "-X",
            "-U",
            "postgres",
            "-d",
            "postgres",
            "-Atqc",
            sql,
        )

    def patronictl(self, service: str, *args: str) -> str:
        shell = (
            "export PATRONI_RESTAPI_USERNAME=$(cat /run/secrets/patroni_restapi_username); "
            "export PATRONI_RESTAPI_PASSWORD=$(cat /run/secrets/patroni_restapi_password); "
            'exec /opt/patroni/bin/patronictl -c /config/patroni.yml "$@"'
        )
        return self.exec(service, "sh", "-eu", "-c", shell, "patronictl", *args)

    def adopt(self, node: str) -> None:
        legacy = f"{node}-legacy"
        patroni = f"{node}-patroni"
        self.compose("stop", legacy)
        self.compose("rm", "-f", legacy)
        self.compose("up", "-d", "--no-deps", patroni, adoption=True)

    def enter_steady_state(self, node: str) -> None:
        patroni = f"{node}-patroni"
        steady = f"{node}-steady"
        self.compose("stop", patroni, adoption=True)
        self.compose("rm", "-f", patroni, adoption=True)
        self.compose("up", "-d", "--no-deps", steady, adoption=True)

    def rollback_primary_before_ownership_transfer(self) -> None:
        self.compose("stop", "armadillo-patroni", adoption=True)
        self.compose("rm", "-f", "armadillo-patroni", adoption=True)
        self.exec(
            "etcd",
            "/usr/local/bin/etcdctl",
            "--endpoints=http://127.0.0.1:2379",
            "del",
            "--prefix",
            "/service/postgres-ha-existing-data-lab",
        )
        self.compose("up", "-d", "--no-deps", "armadillo-legacy")

    def postmaster_identity(self, service: str) -> tuple[int, int, int]:
        source = (
            "from pathlib import Path;"
            "pid=int(Path('/var/lib/postgresql/data/postmaster.pid').read_text().splitlines()[0]);"
            "stat=Path(f'/proc/{pid}/stat').read_text().split();"
            "patroni=[int(p.name) for p in Path('/proc').iterdir() "
            "if p.name.isdigit() and '/opt/patroni/bin/python' in "
            "Path(p/'cmdline').read_bytes().replace(b'\\0',b' ').decode(errors='ignore')][0];"
            "pstat=Path(f'/proc/{patroni}/stat').read_text().split();"
            "print(f'{pid}|{stat[3]}|{pstat[3]}')"
        )
        output = self.exec(service, "/opt/patroni/bin/python", "-c", source)
        return tuple(int(value) for value in output.split("|"))


def assert_member(lab: ExistingDataLab, via: str, node: str, role: str) -> None:
    config_path = "/etc/patroni/patroni.yml" if via.endswith("-steady") else "/config/patroni.yml"
    members = json.loads(
        lab.exec(
            via,
            "/opt/patroni/bin/patronictl",
            "-c",
            config_path,
            "list",
            "--format",
            "json",
        )
    )
    member = next((item for item in members if item["Member"] == node), None)
    assert member is not None, f"Patroni member {node} has not registered yet"
    assert member["Role"] == role


def assert_patroni_replica_health(lab: ExistingDataLab, service: str) -> None:
    source = """
import base64
from pathlib import Path
from urllib.request import Request, urlopen

username = Path('/run/secrets/patroni_restapi_username').read_text().strip()
password = Path('/run/secrets/patroni_restapi_password').read_text().strip()
token = base64.b64encode(f'{username}:{password}'.encode()).decode()
request = Request('http://127.0.0.1:8008/replica', headers={'Authorization': f'Basic {token}'})
with urlopen(request, timeout=5) as response:
    assert response.status == 200
"""
    lab.exec(service, "/opt/patroni/bin/python", "-c", source)


@pytest.mark.integration
def test_failure_before_ownership_transfer_restores_legacy_primary(tmp_path: Path) -> None:
    lab = create_lab(tmp_path)
    try:
        lab.compose("up", "-d", "--wait", "--wait-timeout", "180")

        def assert_legacy_streaming() -> None:
            assert (
                lab.psql(
                    "armadillo-legacy",
                    "select count(*) from pg_stat_replication where state='streaming'",
                )
                == "2"
            )

        eventually(assert_legacy_streaming, timeout=180)
        database_system_identifier = lab.psql(
            "armadillo-legacy", "select (pg_control_system()).system_identifier"
        )
        original_timeline = lab.psql(
            "armadillo-legacy", "select (pg_control_checkpoint()).timeline_id"
        )

        lab.adopt("armadillo")

        def assert_observed_before_fault() -> None:
            assert_member(lab, "armadillo-patroni", "armadillo", "Leader")
            assert lab.psql("armadillo-patroni", "select pg_is_in_recovery()") == "f"

        eventually(assert_observed_before_fault, timeout=180)
        lab.rollback_primary_before_ownership_transfer()

        def assert_legacy_restored() -> None:
            assert lab.psql("armadillo-legacy", "select pg_is_in_recovery()") == "f"
            assert (
                lab.psql("armadillo-legacy", "select (pg_control_system()).system_identifier")
                == database_system_identifier
            )
            assert (
                lab.psql("armadillo-legacy", "select (pg_control_checkpoint()).timeline_id")
                == original_timeline
            )
            assert (
                lab.exec(
                    "armadillo-legacy",
                    "test",
                    "!",
                    "-e",
                    "/var/lib/postgresql/data/standby.signal",
                )
                == ""
            )
            assert (
                lab.psql(
                    "armadillo-legacy",
                    "select count(*) from pg_stat_replication where state='streaming'",
                )
                == "2"
            )

        eventually(assert_legacy_restored, timeout=180)
        remaining = lab.exec(
            "etcd",
            "/usr/local/bin/etcdctl",
            "--endpoints=http://127.0.0.1:2379",
            "get",
            "--prefix",
            "/service/postgres-ha-existing-data-lab",
        )
        assert remaining == ""
    finally:
        lab.compose("down", "--volumes", "--remove-orphans", adoption=True, check=False)


@pytest.mark.integration
def test_existing_primary_and_two_standbys_adopt_before_patroni_restart(tmp_path: Path) -> None:
    lab = create_lab(tmp_path)
    try:
        lab.compose("up", "-d", "--wait", "--wait-timeout", "180")

        def assert_legacy_streaming() -> None:
            assert (
                lab.psql(
                    "armadillo-legacy",
                    "select count(*) from pg_stat_replication where state='streaming'",
                )
                == "2"
            )
            for node in ("rogue", "fluffy"):
                assert lab.psql(f"{node}-legacy", "select pg_is_in_recovery()") == "t"

        eventually(assert_legacy_streaming, timeout=180)
        lab.psql("armadillo-legacy", "checkpoint")
        checkpoint = lab.psql("armadillo-legacy", "select pg_current_wal_lsn()")

        def standbys_at_checkpoint() -> None:
            for node in ("rogue", "fluffy"):
                replay = lab.psql(f"{node}-legacy", "select pg_last_wal_replay_lsn()")
                reached = lab.psql(
                    f"{node}-legacy",
                    f"select '{replay}'::pg_lsn >= '{checkpoint}'::pg_lsn",
                )
                assert reached == "t"

        eventually(standbys_at_checkpoint)
        database_system_identifier = lab.psql(
            "armadillo-legacy", "select (pg_control_system()).system_identifier"
        )
        original_timeline = lab.psql(
            "armadillo-legacy", "select (pg_control_checkpoint()).timeline_id"
        )

        lab.adopt("armadillo")

        def assert_primary_observed() -> None:
            assert_member(lab, "armadillo-patroni", "armadillo", "Leader")
            assert lab.psql("armadillo-patroni", "select pg_is_in_recovery()") == "f"
            assert (
                lab.psql("armadillo-patroni", "select (pg_control_system()).system_identifier")
                == database_system_identifier
            )
            assert (
                lab.psql("armadillo-patroni", "select (pg_control_checkpoint()).timeline_id")
                == original_timeline
            )
            assert (
                lab.exec(
                    "armadillo-patroni",
                    "test",
                    "!",
                    "-e",
                    "/var/lib/postgresql/data/standby.signal",
                )
                == ""
            )
            postmaster, postmaster_parent, patroni_parent = lab.postmaster_identity(
                "armadillo-patroni"
            )
            assert postmaster > 1
            assert postmaster_parent == 1
            assert patroni_parent == 1
            assert (
                lab.psql(
                    "armadillo-patroni",
                    "select count(*) from pg_stat_replication where state='streaming'",
                )
                == "2"
            )

        eventually(assert_primary_observed, timeout=180)
        before_restart = lab.postmaster_identity("armadillo-patroni")[0]
        lab.patronictl(
            "armadillo-patroni",
            "restart",
            "postgres-ha-existing-data-lab",
            "armadillo",
            "--force",
        )

        def assert_primary_owned_after_restart() -> None:
            assert_member(lab, "armadillo-patroni", "armadillo", "Leader")
            after_restart = lab.postmaster_identity("armadillo-patroni")[0]
            assert after_restart != before_restart
            assert lab.psql("armadillo-patroni", "select pg_is_in_recovery()") == "f"
            assert (
                lab.psql("armadillo-patroni", "select note from adoption_markers where id=1")
                == "legacy-primary"
            )

        eventually(assert_primary_owned_after_restart, timeout=180)
        lab.enter_steady_state("armadillo")

        def assert_primary_steady() -> None:
            assert_member(lab, "armadillo-steady", "armadillo", "Leader")
            assert lab.psql("armadillo-steady", "select pg_is_in_recovery()") == "f"
            assert (
                lab.psql("armadillo-steady", "select note from adoption_markers where id=1")
                == "legacy-primary"
            )

        eventually(assert_primary_steady, timeout=180)

        for node in ("rogue", "fluffy"):
            lab.adopt(node)

            def assert_replica_observed(node: str = node) -> None:
                assert_member(lab, f"{node}-patroni", node, "Replica")
                assert_patroni_replica_health(lab, f"{node}-patroni")
                assert lab.psql(f"{node}-patroni", "select pg_is_in_recovery()") == "t"
                assert (
                    lab.exec(
                        f"{node}-patroni",
                        "test",
                        "-f",
                        "/var/lib/postgresql/data/standby.signal",
                    )
                    == ""
                )
                postmaster, postmaster_parent, patroni_parent = lab.postmaster_identity(
                    f"{node}-patroni"
                )
                assert postmaster > 1
                assert postmaster_parent == 1
                assert patroni_parent == 1

            eventually(assert_replica_observed, timeout=180)
            before_restart = lab.postmaster_identity(f"{node}-patroni")[0]
            lab.patronictl(
                f"{node}-patroni",
                "restart",
                "postgres-ha-existing-data-lab",
                node,
                "--force",
            )

            def assert_replica_owned_after_restart(
                node: str = node, previous_pid: int = before_restart
            ) -> None:
                assert_member(lab, f"{node}-patroni", node, "Replica")
                assert_patroni_replica_health(lab, f"{node}-patroni")
                assert lab.postmaster_identity(f"{node}-patroni")[0] != previous_pid
                assert lab.psql(f"{node}-patroni", "select pg_is_in_recovery()") == "t"
                assert (
                    lab.psql(f"{node}-patroni", "select note from adoption_markers where id=1")
                    == "legacy-primary"
                )

            eventually(assert_replica_owned_after_restart, timeout=180)
            lab.enter_steady_state(node)

            def assert_replica_steady(node: str = node) -> None:
                service = f"{node}-steady"
                assert_member(lab, service, node, "Replica")
                assert_patroni_replica_health(lab, service)
                assert lab.psql(service, "select pg_is_in_recovery()") == "t"
                assert lab.psql(service, "select note from adoption_markers where id=1") == (
                    "legacy-primary"
                )

            eventually(assert_replica_steady, timeout=180)

        assert (
            lab.psql(
                "armadillo-steady",
                "select count(*) from pg_stat_replication where state='streaming'",
            )
            == "2"
        )
    finally:
        lab.compose("down", "--volumes", "--remove-orphans", adoption=True, check=False)
