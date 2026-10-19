"""Security contracts for PgBouncer's replicated SCRAM authentication path."""

from __future__ import annotations

import configparser
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PGBOUNCER_DIR = ROOT / "config" / "pgbouncer"
CONFIG = PGBOUNCER_DIR / "pgbouncer.ini"
AUTH_HBA = PGBOUNCER_DIR / "pgbouncer-hba.conf"
USERLIST_EXAMPLE = PGBOUNCER_DIR / "userlist.txt.example"
AUTH_SQL = ROOT / "sql" / "001-pgbouncer-auth.sql"


def read(path: Path) -> str:
    assert path.is_file(), f"missing required PgBouncer source: {path.relative_to(ROOT)}"
    return path.read_text(encoding="utf-8")


def settings() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(read(CONFIG))
    return parser


def test_dynamic_auth_uses_scram_hba_and_a_secret_backed_bootstrap_role() -> None:
    config = settings()["pgbouncer"]

    # PgBouncer consults auth_hba_file only when auth_type=hba; the HBA itself
    # requires SCRAM on every accepted private network.
    assert config["auth_type"] == "hba"
    assert config["auth_user"] == "pgbouncer_auth"
    assert config["auth_dbname"] == "postgres"
    assert config["auth_query"] == "SELECT * FROM pgbouncer.get_auth($1)"
    assert config["auth_file"] == "/run/secrets/pgbouncer_userlist"
    assert config["auth_hba_file"] == "/etc/pgbouncer/pgbouncer-hba.conf"

    rendered = read(CONFIG).lower()
    assert "auth_type = any" not in rendered
    assert "auth_type = trust" not in rendered

    hba = read(AUTH_HBA)
    accepted = [
        line
        for line in hba.splitlines()
        if line and not line.startswith("#") and "reject" not in line
    ]
    assert accepted
    assert all(line.endswith("scram-sha-256") for line in accepted)
    assert any("100.64.0.0/10" in line for line in accepted)
    assert any("172.16.0.0/12" in line for line in accepted)


def test_session_pooling_has_an_explicit_initial_safety_envelope() -> None:
    parser = settings()
    config = parser["pgbouncer"]

    assert config["pool_mode"] == "session"
    for name in (
        "max_client_conn",
        "default_pool_size",
        "reserve_pool_size",
        "max_db_connections",
        "query_wait_timeout",
        "server_connect_timeout",
        "client_login_timeout",
        "server_login_retry",
    ):
        assert int(config[name]) > 0

    # Session-pooled services with many long-lived workers need dedicated pools. Keeping
    # them on the 40+10 default makes PgBouncer reject startup sessions and the service
    # cleanly restart in a loop after query_wait_timeout.
    for database, minimum_pool_size in (("penpot", 140), ("zabbix", 100)):
        assert database in parser["databases"]
        connection = parser["databases"][database]
        for setting in ("pool_size", "reserve_pool_size", "max_db_connections"):
            assert f"{setting}=" in connection

        parsed = dict(part.split("=", 1) for part in connection.split() if "=" in part)
        assert int(parsed["pool_size"]) >= minimum_pool_size
        assert int(parsed["max_db_connections"]) >= (
            int(parsed["pool_size"]) + int(parsed["reserve_pool_size"])
        )


def test_admin_console_uses_dedicated_roles_and_private_network_hba_rules() -> None:
    config = settings()["pgbouncer"]
    hba = read(AUTH_HBA)

    assert config["admin_users"] == "pgbouncer_admin"
    assert config["stats_users"] == "pgbouncer_stats"
    for role in ("pgbouncer_admin", "pgbouncer_stats"):
        assert re.search(
            rf"^host\s+pgbouncer\s+{role}\s+100\.64\.0\.0/10\s+scram-sha-256$",
            hba,
            flags=re.MULTILINE,
        )
        assert re.search(
            rf"^host\s+pgbouncer\s+{role}\s+0\.0\.0\.0/0\s+reject$",
            hba,
            flags=re.MULTILINE,
        )


def test_tracked_userlist_example_contains_no_application_verifier() -> None:
    example = read(USERLIST_EXAMPLE)

    assert "application" not in example.lower()
    assert "SCRAM-SHA-256$" not in example
    assert "pgbouncer_auth" in example
    assert "/run/secrets/pgbouncer_userlist" in example


def test_auth_query_is_security_definer_hardened_and_never_exposes_catalog_access() -> None:
    sql = read(AUTH_SQL)

    for statement in (
        "CREATE SCHEMA IF NOT EXISTS pgbouncer AUTHORIZATION postgres;",
        "REVOKE ALL ON SCHEMA pgbouncer FROM PUBLIC;",
        "SECURITY DEFINER",
        "SET search_path = pg_catalog",
        "FROM pg_authid",
        "WHERE rolname = p_username",
        "AND rolcanlogin;",
        "REVOKE ALL ON FUNCTION pgbouncer.get_auth(text) FROM PUBLIC;",
        "GRANT USAGE ON SCHEMA pgbouncer TO pgbouncer_auth;",
        "GRANT EXECUTE ON FUNCTION pgbouncer.get_auth(text) TO pgbouncer_auth;",
        "REVOKE ALL ON TABLE pg_authid FROM pgbouncer_auth;",
    ):
        assert statement in sql

    assert "CREATE ROLE pgbouncer_auth" in sql
    assert "LOGIN" in sql
    assert "PASSWORD :'pgbouncer_auth_password'" in sql
    assert "pgbouncer_auth_password is required" in sql
    assert "PASSWORD '" not in sql
