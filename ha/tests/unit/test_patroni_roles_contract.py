"""Idempotent SQL contracts for Patroni adoption roles and pg_rewind privileges."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL = ROOT / "sql" / "002-patroni-roles.sql"


def test_patroni_roles_sql_uses_psql_variables_without_literal_passwords() -> None:
    sql = SQL.read_text(encoding="utf-8")
    for variable in (
        "patroni_superuser_password",
        "patroni_replication_password",
        "patroni_rewind_password",
    ):
        assert f"\\if :{{?{variable}}}" in sql
        assert f":'{variable}'" in sql
    assert "PASSWORD '" not in sql


def test_roles_are_created_or_altered_idempotently_with_minimum_required_attributes() -> None:
    sql = SQL.read_text(encoding="utf-8")
    for role in ("patroni_superuser", "patroni_replication", "patroni_rewind"):
        assert f"WHERE rolname = '{role}'" in sql
        assert f"ALTER ROLE {role}" in sql
    assert "CREATE ROLE patroni_superuser LOGIN SUPERUSER" in sql
    assert "CREATE ROLE patroni_replication LOGIN REPLICATION" in sql
    assert "CREATE ROLE patroni_rewind LOGIN NOSUPERUSER NOREPLICATION" in sql


def test_rewind_role_has_exact_postgresql_18_catalog_function_grants() -> None:
    sql = SQL.read_text(encoding="utf-8")
    for signature in (
        "pg_catalog.pg_ls_dir(text, boolean, boolean)",
        "pg_catalog.pg_stat_file(text, boolean)",
        "pg_catalog.pg_read_binary_file(text)",
        "pg_catalog.pg_read_binary_file(text, bigint, bigint, boolean)",
    ):
        assert f"GRANT EXECUTE ON FUNCTION {signature} TO patroni_rewind;" in sql
    assert "GRANT pg_read_all_settings TO patroni_rewind;" not in sql
    rewind_alter = sql.split("ALTER ROLE patroni_rewind", 1)[1].split(";", 1)[0]
    assert " LOGIN SUPERUSER" not in rewind_alter
