"""Contracts for Patroni-aware HAProxy write routing and its safe probe."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "haproxy" / "haproxy.cfg"
PROBE = ROOT / "scripts" / "test-haproxy-write-endpoint.sh"

PRIMARY_NODES = {
    "armadillo": "100.64.0.5",
    "rogue": "100.64.0.4",
    "fluffy": "100.64.0.2",
}


def read(path: Path) -> str:
    assert path.is_file(), f"missing required HAProxy source: {path.relative_to(ROOT)}"
    return path.read_text(encoding="utf-8")


def backend(config: str, name: str) -> str:
    match = re.search(
        rf"^backend {re.escape(name)}\s*$([\s\S]*?)(?=^\S|\Z)",
        config,
        flags=re.MULTILINE,
    )
    assert match, f"missing backend {name}"
    return match.group(1)


def test_write_listener_routes_postgresql_tcp_to_the_patroni_primary_backend() -> None:
    config = read(CONFIG)

    assert re.search(r"^frontend postgresql_write\s*$", config, flags=re.MULTILINE)
    assert re.search(r"^\s+bind :6432\s*$", config, flags=re.MULTILINE)
    assert re.search(r"^\s+mode tcp\s*$", config, flags=re.MULTILINE)
    assert re.search(r"^\s+default_backend patroni_primary\s*$", config, flags=re.MULTILINE)


def test_primary_backend_requires_patroni_leadership_and_a_live_pgbouncer_port() -> None:
    config = read(CONFIG)
    primary = backend(config, "patroni_primary")

    assert re.search(r"^\s+mode tcp\s*$", primary, flags=re.MULTILINE)
    assert re.search(r"^\s+option httpchk\s*$", primary, flags=re.MULTILINE)
    assert re.search(r"^\s+http-check connect port 8008\s*$", primary, flags=re.MULTILINE)
    assert re.search(
        r"^\s+http-check send meth GET uri /primary ver HTTP/1\.1 hdr host patroni\s*$",
        primary,
        flags=re.MULTILINE,
    )
    assert re.search(r"^\s+http-check expect status 200\s*$", primary, flags=re.MULTILINE)
    assert re.search(r"^\s+http-check connect port 6433\s*$", primary, flags=re.MULTILINE)

    for node, address in PRIMARY_NODES.items():
        assert re.search(
            rf"^\s+server {node} {re.escape(address)}:6433 check\s*$",
            primary,
            flags=re.MULTILINE,
        )

    assert "default-server inter 2s fall 3 rise 2 on-marked-down shutdown-sessions" in primary


def test_timeouts_are_explicit_and_stats_socket_is_local_only() -> None:
    config = read(CONFIG)
    for required in (
        "timeout connect 5s",
        "timeout client 30m",
        "timeout server 30m",
        "timeout check 3s",
        "stats socket /var/run/haproxy/admin.sock mode 660 level admin",
    ):
        assert required in config
    assert "stats bind" not in config


def test_write_probe_defaults_to_the_haproxy_write_endpoint_and_uses_a_rolled_back_write() -> None:
    probe = read(PROBE)

    assert "${PGHOST:-postgres-ha}" in probe
    assert "${PGPORT:-6432}" in probe
    assert "BEGIN;" in probe
    assert "CREATE TEMPORARY TABLE" in probe
    assert "INSERT INTO" in probe
    assert "pg_is_in_recovery()" in probe
    assert "ROLLBACK;" in probe
    assert "primary-write-ok" in probe
    assert "psql -q -X -w -v ON_ERROR_STOP=1" in probe
    assert "PGPASSWORD=" not in probe


def test_write_probe_reports_success_only_when_psql_confirms_a_primary_write(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    captured_endpoint = tmp_path / "endpoint"
    captured_sql = tmp_path / "query.sql"
    fake_psql = fake_bin / "psql"
    fake_psql.write_text(
        "#!/bin/sh\n"
        'printf \'%s:%s\\n\' "$PGHOST" "$PGPORT" > "$PROBE_CAPTURE_ENDPOINT"\n'
        'cat > "$PROBE_CAPTURE_SQL"\n'
        "printf '%s\\n' \"${PSQL_RESULT:?}\"\n",
        encoding="utf-8",
    )
    fake_psql.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "PGUSER": "probe_user",
        "PGDATABASE": "postgres",
        "PROBE_CAPTURE_ENDPOINT": str(captured_endpoint),
        "PROBE_CAPTURE_SQL": str(captured_sql),
        "PSQL_RESULT": "primary-write-ok",
    }

    result = subprocess.run(
        [str(PROBE)],
        check=False,
        capture_output=True,
        cwd=ROOT,
        env=environment,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert captured_endpoint.read_text(encoding="utf-8") == "postgres-ha:6432\n"
    sql = captured_sql.read_text(encoding="utf-8")
    assert "BEGIN;" in sql
    assert "ROLLBACK;" in sql


def test_write_probe_fails_closed_when_the_database_does_not_confirm_primary_write(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_psql = fake_bin / "psql"
    fake_psql.write_text("#!/bin/sh\nprintf '%s\\n' \"${PSQL_RESULT:?}\"\n", encoding="utf-8")
    fake_psql.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "PGUSER": "probe_user",
        "PGDATABASE": "postgres",
        "PSQL_RESULT": "standby",
    }

    result = subprocess.run(
        [str(PROBE)],
        check=False,
        capture_output=True,
        cwd=ROOT,
        env=environment,
        text=True,
    )

    assert result.returncode != 0
    assert "did not confirm a primary write" in result.stderr
