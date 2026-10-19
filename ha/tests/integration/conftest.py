"""Testcontainers fixture for the isolated three-member Patroni lab."""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
from testcontainers.compose import DockerCompose

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "tests" / "integration" / "lab"
NODES = ("armadillo", "rogue", "fluffy")


def active_server_names(stats: str) -> list[str]:
    active = []
    for line in stats.splitlines():
        fields = line.split(",")
        if (
            len(fields) > 17
            and fields[0] == "patroni_primary"
            and fields[1] not in {"FRONTEND", "BACKEND"}
            and fields[17] == "UP"
        ):
            active.append(fields[1])
    return active


def eventually(assertion, timeout: float = 90, interval: float = 1) -> None:
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


@dataclass
class PatroniLab:
    compose: DockerCompose

    def exec(self, service: str, *command: str) -> str:
        try:
            stdout, stderr, status = self.compose.exec_in_container(list(command), service)
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b"").decode(errors="replace")
            stdout = (exc.stdout or b"").decode(errors="replace")
            raise RuntimeError(
                f"{service} command failed ({exc.returncode}): {stderr or stdout}"
            ) from exc
        if status != 0:
            raise RuntimeError(f"{service} command failed ({status}): {stderr or stdout}")
        return stdout.strip()

    def psql(self, sql: str, host: str = "haproxy", port: int = 6432) -> str:
        return self.exec(
            "client",
            "psql",
            "-X",
            "-q",
            "-v",
            "ON_ERROR_STOP=1",
            "-At",
            "-h",
            host,
            "-p",
            str(port),
            "-U",
            "lab_app",
            "-d",
            "postgres",
            "-c",
            sql,
        )

    def admin(self, node: str, sql: str) -> str:
        return self.exec(
            node,
            "psql",
            "-X",
            "-U",
            "patroni_superuser",
            "-d",
            "postgres",
            "-v",
            "ON_ERROR_STOP=1",
            "-At",
            "-c",
            sql,
        )

    def members(self, via: str = "armadillo") -> dict[str, dict]:
        import json

        output = self.exec(
            via,
            "/opt/patroni/bin/patronictl",
            "-c",
            "/config/patroni.yml",
            "list",
            "--format",
            "json",
        )
        return {member["Member"]: member for member in json.loads(output)}

    def stop(self, service: str) -> None:
        result = self.compose._run_command(
            [*self.compose.compose_command_property, "stop", service]
        )
        if result.returncode:
            raise RuntimeError(result.stderr.decode())

    def start(self, service: str) -> None:
        result = self.compose._run_command(
            [*self.compose.compose_command_property, "start", service]
        )
        if result.returncode:
            raise RuntimeError(result.stderr.decode())

    def active_backend(self) -> str:
        output = self.exec(
            "haproxy",
            "sh",
            "-c",
            "printf 'show stat\\n' | nc 127.0.0.1 9999",
        )
        active = active_server_names(output)
        assert len(active) == 1, f"expected one active write backend, got {active}"
        return active[0]

    def switchover(self, leader: str, candidate: str) -> None:
        code = (
            "import pathlib,requests,sys;"
            "read=lambda n:pathlib.Path('/run/secrets/'+n).read_text().strip();"
            "r=requests.post('http://127.0.0.1:8008/switchover',"
            "auth=(read('patroni_restapi_username'),read('patroni_restapi_password')),"
            "json={'leader':sys.argv[1],'candidate':sys.argv[2]},timeout=30);"
            "print(str(r.status_code)+'|'+r.text.strip());"
            "r.raise_for_status()"
        )
        response = self.exec(
            leader,
            "/opt/patroni/bin/python",
            "-c",
            code,
            leader,
            candidate,
        )
        status, body = response.split("|", 1)
        assert status == "200", response
        assert candidate in body, response


def write_secret(path: Path, value: str) -> None:
    path.write_text(value + "\n", encoding="utf-8")
    path.chmod(0o444)


@pytest.fixture(scope="module")
def patroni_lab(tmp_path_factory: pytest.TempPathFactory):
    secret_dir = tmp_path_factory.mktemp("patroni-lab-secrets")
    secret_dir.chmod(0o755)
    values = {
        "patroni_superuser_username": "patroni_superuser",
        "patroni_replication_username": "patroni_replication",
        "patroni_rewind_username": "patroni_rewind",
        "patroni_restapi_username": "patroni_restapi",
        "patroni_superuser_password": secrets.token_hex(24),
        "patroni_replication_password": secrets.token_hex(24),
        "patroni_rewind_password": secrets.token_hex(24),
        "patroni_restapi_password": secrets.token_hex(24),
    }
    for filename, value in values.items():
        write_secret(secret_dir / filename, value)
    app_password = secrets.token_hex(24)
    auth_password = secrets.token_hex(24)
    write_secret(secret_dir / "app_password", app_password)
    write_secret(secret_dir / "pgbouncer_auth_password", auth_password)
    write_secret(secret_dir / "pgpass", f"*:*:*:lab_app:{app_password}")
    (secret_dir / "pgpass").chmod(0o400)
    (secret_dir / "pgbouncer_userlist").write_text(
        f'"pgbouncer_auth" "{auth_password}"\n', encoding="utf-8"
    )
    (secret_dir / "pgbouncer_userlist").chmod(0o444)

    previous = os.environ.get("LAB_SECRETS_DIR")
    os.environ["LAB_SECRETS_DIR"] = str(secret_dir)
    compose = DockerCompose(LAB, compose_file_name="compose.yaml", wait=True)
    try:
        compose.start()
        lab = PatroniLab(compose)
        primary = lab.members()["armadillo"]
        assert primary["Role"] == "Leader"
        lab.exec(
            "armadillo",
            "sh",
            "-eu",
            "-c",
            "psql -X -U patroni_superuser -d postgres -v ON_ERROR_STOP=1 "
            '-v pgbouncer_auth_password="$(cat /run/secrets/pgbouncer_auth_password)" '
            '-v app_password="$(cat /run/secrets/app_password)" -f /lab/setup.sql',
        )
        for node in NODES:
            eventually(lambda node=node: _assert_query(lab, node))
        yield lab
    finally:
        compose.stop()
        if previous is None:
            os.environ.pop("LAB_SECRETS_DIR", None)
        else:
            os.environ["LAB_SECRETS_DIR"] = previous
        shutil.rmtree(secret_dir, ignore_errors=True)


def _assert_query(lab: PatroniLab, node: str) -> None:
    assert lab.admin(node, "select 1") == "1"
