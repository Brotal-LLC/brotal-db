"""Contracts for complete, host-specific PostgreSQL HA Compose deployments.

These tests render every deployable file with deliberately non-secret fixtures.  They
pin mount and service topology so the Patroni migration cannot accidentally replace
existing PostgreSQL data or silently drop the host-specific MongoDB/Redis services.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
FIXTURE_ENV = ROOT / "tests" / "fixtures" / "test.env"

DATABASE_HOSTS = {
    "armadillo": "100.64.0.5",
    "rogue": "100.64.0.4",
    "fluffy": "100.64.0.2",
}
ARMADILLO_LAN_ADDRESS = "10.63.0.10"
HAPROXY_IMAGE = (
    "haproxy:3.2-alpine@sha256:79799e8b2977e60802774fa53d29e6b54e045402cdd8a8b9fe43923e7095a047"
)
ALL_HOSTS = (*DATABASE_HOSTS, "pi1")
NUMERIC_USER = re.compile(r"^(?P<uid>[1-9][0-9]*):(?P<gid>[1-9][0-9]*)$")


def compose_path(host: str) -> Path:
    return DEPLOY / host / "compose.yaml"


def render(host: str) -> dict[str, Any]:
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(FIXTURE_ENV),
            "-f",
            str(compose_path(host)),
            "config",
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        cwd=ROOT,
        text=True,
    )
    return json.loads(result.stdout)


def render_adoption(host: str) -> dict[str, Any]:
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(FIXTURE_ENV),
            "-f",
            str(compose_path(host)),
            "-f",
            str(DEPLOY / host / "compose.adoption.yaml"),
            "config",
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        cwd=ROOT,
        text=True,
    )
    return json.loads(result.stdout)


def rendered_volume(service: dict[str, Any], target: str) -> dict[str, Any]:
    return next(volume for volume in service["volumes"] if volume["target"] == target)


def published_port(service: dict[str, Any], target: int) -> dict[str, Any]:
    return next(port for port in service["ports"] if int(port["target"]) == target)


def test_complete_host_specific_compose_files_and_fixture_exist() -> None:
    assert FIXTURE_ENV.is_file(), "Compose rendering must use a committed non-secret fixture env"
    assert {host for host in ALL_HOSTS if compose_path(host).is_file()} == set(ALL_HOSTS)


@pytest.mark.parametrize("host", ALL_HOSTS)
def test_all_deployments_render_with_fixture_values(host: str) -> None:
    render(host)


@pytest.mark.parametrize("host", DATABASE_HOSTS)
def test_database_hosts_include_full_ha_service_set(host: str) -> None:
    model = render(host)

    assert set(model["services"]) == {"postgres", "mongo", "redis", "pgbouncer", "haproxy"}


@pytest.mark.parametrize("host", DATABASE_HOSTS)
def test_postgres_preserves_data_and_direct_port_while_becoming_patroni_managed(host: str) -> None:
    model = render(host)
    postgres = model["services"]["postgres"]

    assert postgres["image"] == "postgres-ha-patroni:test"
    assert postgres["container_name"] == "postgres"
    assert postgres["environment"] == {"PGDATA": "/var/lib/postgresql/data"}
    assert postgres.get("entrypoint") is None
    assert "PATRONI_EXISTING_DATA_EXPECT_ROLE" not in postgres["environment"]
    assert published_port(postgres, 5432)["published"] == "5432"
    assert published_port(postgres, 8008) == {
        "mode": "ingress",
        "host_ip": DATABASE_HOSTS[host],
        "target": 8008,
        "published": "8008",
        "protocol": "tcp",
    }

    data = rendered_volume(postgres, "/var/lib/postgresql/data")
    if host == "armadillo":
        assert data["type"] == "volume"
        assert data["source"] == "postgres-data"
        assert model["volumes"]["postgres-data"]["name"] == "postgres-data"
        assert model["volumes"]["postgres-data"]["external"] is True
    else:
        expected_source = (
            "/data/containers/postgres/data" if host == "rogue" else "/mnt/ts/postgres-data"
        )
        assert data == {
            "type": "bind",
            "source": expected_source,
            "target": "/var/lib/postgresql/data",
            "bind": {"create_host_path": False},
        }
        assert "postgres-data" not in model.get("volumes", {})

    patroni_config = rendered_volume(postgres, "/etc/patroni/patroni.yml")
    assert patroni_config["type"] == "bind"
    assert patroni_config["read_only"] is True
    assert patroni_config["bind"] == {"create_host_path": False}


@pytest.mark.parametrize(
    ("host", "expected_role"),
    (("armadillo", "primary"), ("rogue", "replica"), ("fluffy", "replica")),
)
def test_one_time_adoption_overlay_is_explicit_and_preserves_steady_state(
    host: str, expected_role: str
) -> None:
    base = render(host)
    adopted = render_adoption(host)
    postgres = adopted["services"]["postgres"]

    assert set(adopted["services"]) == set(base["services"])
    assert postgres["entrypoint"] == ["/usr/local/bin/patroni-existing-data-entrypoint"]
    assert postgres["environment"] == {
        "PATRONI_EXISTING_DATA_CONFIG": "/etc/patroni/patroni.yml",
        "PATRONI_EXISTING_DATA_EXPECT_ROLE": expected_role,
        "PGDATA": "/var/lib/postgresql/data",
    }
    assert postgres["container_name"] == "postgres"
    assert postgres["user"] == "999:999"
    assert rendered_volume(postgres, "/var/lib/postgresql/data") == rendered_volume(
        base["services"]["postgres"], "/var/lib/postgresql/data"
    )
    for target, source in (
        ("/etc/postgresql/postgresql.conf", "config/postgresql.conf"),
        ("/etc/postgresql/pg_hba.conf", "config/pg_hba.conf"),
    ):
        mount = rendered_volume(postgres, target)
        assert mount["type"] == "bind"
        assert mount["source"].endswith(source)
        assert mount["read_only"] is True
        assert mount["bind"] == {"create_host_path": False}


@pytest.mark.parametrize("host", DATABASE_HOSTS)
def test_database_access_plane_uses_verified_tailnet_host_bindings(host: str) -> None:
    model = render(host)
    pgbouncer = model["services"]["pgbouncer"]
    haproxy = model["services"]["haproxy"]

    for service, port in ((pgbouncer, 6433), (haproxy, 6432)):
        binding = published_port(service, port)
        assert binding["host_ip"] == DATABASE_HOSTS[host]
        assert binding["published"] == str(port)

    aliases = haproxy["networks"]["database"]["aliases"]
    assert aliases == ["postgres-ha"]
    assert model["networks"]["database"]["name"] == "database"
    assert model["networks"]["database"]["external"] is True
    assert haproxy["image"] == HAPROXY_IMAGE
    assert haproxy["read_only"] is True
    assert haproxy["tmpfs"] == ["/var/run/haproxy:rw,uid=99,gid=99,mode=0750"]
    assert haproxy["cap_drop"] == ["ALL"]
    assert haproxy["security_opt"] == ["no-new-privileges:true"]
    assert pgbouncer["cap_drop"] == ["ALL"]
    assert pgbouncer["security_opt"] == ["no-new-privileges:true"]


def test_armadillo_haproxy_is_also_published_on_its_client_lan() -> None:
    """LAN clients without Tailscale still use the Patroni-aware write frontend."""
    haproxy = render("armadillo")["services"]["haproxy"]
    write_bindings = {
        (port["host_ip"], port["published"])
        for port in haproxy["ports"]
        if int(port["target"]) == 6432
    }

    assert write_bindings == {
        (DATABASE_HOSTS["armadillo"], "6432"),
        (ARMADILLO_LAN_ADDRESS, "6432"),
    }


@pytest.mark.parametrize("host", DATABASE_HOSTS)
def test_new_database_services_use_read_only_config_and_file_secrets(host: str) -> None:
    model = render(host)

    for service_name, config_target in (
        ("postgres", "/etc/patroni/patroni.yml"),
        ("pgbouncer", "/etc/pgbouncer/pgbouncer.ini"),
        ("haproxy", "/usr/local/etc/haproxy/haproxy.cfg"),
    ):
        service = model["services"][service_name]
        config = rendered_volume(service, config_target)
        assert config["type"] == "bind"
        assert config["read_only"] is True
        assert config["bind"] == {"create_host_path": False}

    pgbouncer_hba = rendered_volume(
        model["services"]["pgbouncer"], "/etc/pgbouncer/pgbouncer-hba.conf"
    )
    assert pgbouncer_hba["read_only"] is True
    assert pgbouncer_hba["bind"] == {"create_host_path": False}
    assert model["services"]["pgbouncer"]["read_only"] is True
    assert model["services"]["pgbouncer"]["tmpfs"] == [
        "/var/run/pgbouncer:rw,uid=6433,gid=6433,mode=0750"
    ]
    assert model["services"]["pgbouncer"]["ulimits"]["nofile"] == {
        "soft": 4096,
        "hard": 8192,
    }

    for service_name in ("postgres", "pgbouncer"):
        secret_mount = rendered_volume(model["services"][service_name], "/run/secrets")
        assert secret_mount["type"] == "bind"
        assert secret_mount["read_only"] is True
        assert secret_mount["bind"] == {"create_host_path": False}

    rendered = json.dumps(model)
    assert "test-only-secret" not in rendered
    assert "POSTGRES_PASSWORD" not in rendered
    assert "REPLICATION_PASSWORD" not in rendered
    assert "PATRONI_" not in rendered


@pytest.mark.parametrize("host", ALL_HOSTS)
def test_all_steady_state_containers_use_numeric_non_root_users(host: str) -> None:
    model = render(host)

    for service_name, service in model["services"].items():
        match = NUMERIC_USER.fullmatch(service["user"])
        assert match, f"{host}/{service_name} must declare a numeric non-root user"
        assert match.group("uid") != "0"


@pytest.mark.parametrize("host", DATABASE_HOSTS)
def test_mongo_and_redis_host_specific_legacy_contracts_are_retained(host: str) -> None:
    model = render(host)
    mongo = model["services"]["mongo"]
    redis = model["services"]["redis"]

    assert mongo["image"] == "mongo"
    assert mongo["hostname"] == "mongo"
    assert mongo["container_name"] == "mongo"
    assert mongo["labels"] == {"komodo.skip": "true"}
    assert published_port(mongo, 27017)["published"] == "27017"
    assert rendered_volume(mongo, "/data/db")["source"] == "mongo-data"
    assert rendered_volume(mongo, "/data/configdb")["source"] == "mongo-config"
    assert model["volumes"]["mongo-data"]["name"] == "mongo-data"
    assert model["volumes"]["mongo-config"]["name"] == "mongo-config"
    assert mongo["environment"].get("GLIBC_TUNABLES") == (
        "glibc.pthread.rseq=1" if host == "armadillo" else None
    )

    assert redis["image"] == "docker.io/redis:alpine"
    assert redis["hostname"] == "redis"
    assert redis["container_name"] == "redis"
    assert published_port(redis, 6379)["published"] == "6379"
    if host == "rogue":
        assert redis["command"] == [
            "redis-server",
            "--replicaof",
            "10.63.0.10",
            "6379",
            "--appendonly",
            "yes",
        ]
        assert rendered_volume(redis, "/data")["source"] == "redis-data"
        assert model["volumes"]["redis-data"]["name"] == "redis-data"
    else:
        assert redis.get("command") is None
        assert redis.get("volumes") is None
        assert "redis-data" not in model.get("volumes", {})


def test_pi1_is_access_only_haproxy_without_database_processes() -> None:
    model = render("pi1")

    assert set(model["services"]) == {"haproxy"}
    haproxy = model["services"]["haproxy"]
    assert haproxy["image"] == HAPROXY_IMAGE
    assert published_port(haproxy, 6432)["published"] == "6432"
    assert haproxy["networks"]["database"]["aliases"] == ["postgres-ha"]
    assert model["networks"]["database"]["name"] == "database"
    assert model["networks"]["database"]["external"] is True
    assert haproxy["read_only"] is True
    assert haproxy["tmpfs"] == ["/var/run/haproxy:rw,uid=99,gid=99,mode=0750"]
    assert haproxy["cap_drop"] == ["ALL"]
    assert haproxy["security_opt"] == ["no-new-privileges:true"]


def test_deploy_example_has_no_live_secrets_and_declares_deploy_paths() -> None:
    example = (DEPLOY / ".env.example").read_text(encoding="utf-8")

    assert "CONFIG_ROOT=./config" in example
    assert "SECRETS_DIR=./secrets" in example
    assert "PASSWORD=" not in example
    assert "postgres-ha-patroni:4.1.4" in example
    assert "postgres-ha-pgbouncer:1.25.2" in example


def test_no_deployment_or_script_can_delete_stateful_volumes() -> None:
    forbidden = "docker compose down -v"
    candidates = [*DEPLOY.rglob("*"), *(ROOT / "scripts").rglob("*")]
    assert not [
        path
        for path in candidates
        if path.is_file()
        and "__pycache__" not in path.parts
        and forbidden in path.read_text(encoding="utf-8")
    ]


def test_existing_data_adoption_runbook_requires_monitor_before_restart() -> None:
    runbook = (ROOT / "runbooks" / "existing-data-adoption.md").read_text(encoding="utf-8")
    for required in (
        "observe the already-running PostgreSQL primary",
        "patronictl restart",
        "transitional entrypoint",
        "Do not replace the legacy PostgreSQL container",
        "existing-PGDATA regression lab",
    ):
        assert required in runbook


def test_patroni_image_contains_fail_closed_existing_data_supervisor() -> None:
    dockerfile = (ROOT / "images" / "patroni" / "Dockerfile").read_text(encoding="utf-8")
    supervisor = (ROOT / "images" / "patroni" / "existing-data-supervisor.py").read_text(
        encoding="utf-8"
    )

    assert "COPY --chown=postgres:postgres existing-data-supervisor.py" in dockerfile
    assert "patroni-existing-data-entrypoint" in dockerfile
    for required in (
        "PG_VERSION",
        "postmaster.pid",
        "standby.signal",
        "PATRONI_EXISTING_DATA_EXPECT_ROLE",
        "docker-entrypoint.sh",
        "config_file=/etc/postgresql/postgresql.conf",
        "hba_file=/etc/postgresql/pg_hba.conf",
        "/usr/local/bin/patroni-entrypoint",
    ):
        assert required in supervisor
    for forbidden in ("initdb", "pg_basebackup", "shutil.rmtree", "standby_path.touch"):
        assert forbidden not in supervisor


def test_existing_data_lab_starts_as_legacy_streaming_topology() -> None:
    lab = ROOT / "tests" / "integration" / "existing_data_lab"
    compose = (lab / "compose.yaml").read_text(encoding="utf-8")
    test_source = (ROOT / "tests" / "integration" / "test_existing_data_adoption.py").read_text(
        encoding="utf-8"
    )

    for service in (
        "etcd",
        "armadillo-legacy",
        "rogue-legacy",
        "fluffy-legacy",
        "armadillo-patroni",
    ):
        assert service in compose
    assert "profiles: [adoption]" in compose
    assert "patroni-existing-data-entrypoint" in compose
    for required in (
        "pg_stat_replication",
        "standbys_at_checkpoint",
        "database_system_identifier",
        "postmaster.pid",
        "standby.signal",
        "patronictl",
        "restart",
    ):
        assert required in test_source
