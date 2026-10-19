"""Regression contracts for .NET connection-string client cutovers."""

from scripts.dotnet_connection_cutover import (
    externalize_compose_environment_key,
    parse_connection_string,
    update_connection_endpoint,
)


def test_endpoint_update_preserves_multiword_npgsql_option() -> None:
    original = (
        "Host=10.63.0.10;Database=iptv_prod;Username=postgres;"
        "Password=not-a-real-secret;Include Error Detail=true"
    )

    updated = update_connection_endpoint(original, "100.64.0.4", 6432)
    fields = parse_connection_string(updated)

    assert fields["host"] == "100.64.0.4"
    assert fields["port"] == "6432"
    assert fields["database"] == "iptv_prod"
    assert fields["username"] == "postgres"
    assert fields["password"] == "not-a-real-secret"
    assert fields["include error detail"] == "true"
    assert "include;port" not in updated.lower()


def test_wrapped_yaml_scalar_is_removed_as_one_environment_value() -> None:
    compose = """services:
  tv:
    image: example.invalid/tv:latest
    environment:
      IPTV_SOURCES_PATH: /app/sources.json
      IPTV_DB_CONNECTION: "Host=10.63.0.10;Database=iptv_prod;Username=postgres;
        Password=not-a-real-secret;Include Error Detail=true"
      IPTV_AUTH_SECRET: still-in-compose
    networks:
      - ingress
"""

    updated = externalize_compose_environment_key(
        compose,
        service="tv",
        key="IPTV_DB_CONNECTION",
        env_path=".env.runtime",
    )

    assert "IPTV_DB_CONNECTION" not in updated
    assert "Password=not-a-real-secret" not in updated
    assert "Include Error Detail=true" not in updated
    assert "    env_file:\n      - path: .env.runtime\n        format: raw\n" in updated
    assert "      IPTV_AUTH_SECRET: still-in-compose\n" in updated
    assert "    networks:\n" in updated
