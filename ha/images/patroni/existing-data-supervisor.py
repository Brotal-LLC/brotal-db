#!/usr/bin/env python3
"""Supervise the one-time Patroni adoption of an existing PostgreSQL data directory.

The supervisor is PID 1 and launches the legacy PostgreSQL postmaster and Patroni as
siblings. Patroni 4.1 rejects a postmaster that is its direct child during discovery,
so a shell that backgrounds PostgreSQL and then execs Patroni is not safe.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Final, NoReturn

PGDATA: Final = Path(os.environ.get("PGDATA", "/var/lib/postgresql/data"))
POSTMASTER_PID: Final = PGDATA / "postmaster.pid"
STANDBY_SIGNAL: Final = PGDATA / "standby.signal"
EXPECTED_ROLE: Final = os.environ.get("PATRONI_EXISTING_DATA_EXPECT_ROLE", "")
PATRONI_CONFIG: Final = Path(
    os.environ.get("PATRONI_EXISTING_DATA_CONFIG", "/etc/patroni/patroni.yml")
)
START_TIMEOUT: Final = int(os.environ.get("PATRONI_EXISTING_DATA_START_TIMEOUT", "120"))

LEGACY_POSTGRES: Final = [
    "/usr/local/bin/docker-entrypoint.sh",
    "postgres",
    "-c",
    "config_file=/etc/postgresql/postgresql.conf",
    "-c",
    "hba_file=/etc/postgresql/pg_hba.conf",
]
PATRONI: Final = ["/usr/local/bin/patroni-entrypoint", str(PATRONI_CONFIG)]


def fail(message: str) -> NoReturn:
    print(f"existing-data-adoption: {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def validate() -> None:
    if os.getuid() == 0:
        fail("supervisor must not run as root")
    if EXPECTED_ROLE not in {"primary", "replica"}:
        fail("PATRONI_EXISTING_DATA_EXPECT_ROLE must be primary or replica")
    if not (PGDATA / "PG_VERSION").is_file():
        fail(f"refusing empty or uninitialized PGDATA: {PGDATA}")
    if POSTMASTER_PID.exists():
        fail(f"refusing PGDATA with a pre-existing postmaster.pid: {PGDATA}")
    if EXPECTED_ROLE == "primary" and STANDBY_SIGNAL.exists():
        fail("expected primary PGDATA contains standby.signal")
    if EXPECTED_ROLE == "replica" and not STANDBY_SIGNAL.is_file():
        fail("expected replica PGDATA does not contain standby.signal")
    if not PATRONI_CONFIG.is_file():
        fail(f"Patroni configuration is missing: {PATRONI_CONFIG}")


def wait_for_legacy_postgres(process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + START_TIMEOUT
    expected_recovery = "f" if EXPECTED_ROLE == "primary" else "t"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            fail(
                f"legacy PostgreSQL exited before Patroni observation (status={process.returncode})"
            )
        if POSTMASTER_PID.is_file():
            probe = subprocess.run(
                [
                    "psql",
                    "-X",
                    "-U",
                    "postgres",
                    "-d",
                    "postgres",
                    "-Atqc",
                    "select pg_is_in_recovery()",
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            if probe.returncode == 0 and probe.stdout.decode().strip() == expected_recovery:
                return
        time.sleep(1)
    fail(f"legacy PostgreSQL did not reach expected {EXPECTED_ROLE} role within {START_TIMEOUT}s")


def stop_postgres() -> None:
    if not POSTMASTER_PID.exists():
        return
    subprocess.run(
        ["pg_ctl", "-D", str(PGDATA), "stop", "-m", "fast", "-w", "-t", "30"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main() -> int:
    validate()
    postgres = subprocess.Popen(LEGACY_POSTGRES)
    patroni: subprocess.Popen[bytes] | None = None
    stopping = False

    def forward(signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True
        if patroni is not None and patroni.poll() is None:
            patroni.send_signal(signum)

    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)

    try:
        wait_for_legacy_postgres(postgres)
        patroni = subprocess.Popen(PATRONI)
        while patroni.poll() is None:
            # Reap the original postmaster when Patroni performs the ownership-transfer restart.
            postgres.poll()
            time.sleep(0.5)
        return int(patroni.returncode or 0)
    finally:
        if patroni is not None and patroni.poll() is None:
            patroni.terminate()
            try:
                patroni.wait(timeout=30)
            except subprocess.TimeoutExpired:
                patroni.kill()
                patroni.wait(timeout=10)
        if not stopping or POSTMASTER_PID.exists():
            stop_postgres()
        if postgres.poll() is None:
            postgres.terminate()
            try:
                postgres.wait(timeout=10)
            except subprocess.TimeoutExpired:
                postgres.kill()
                postgres.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
