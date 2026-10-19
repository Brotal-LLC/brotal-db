"""Static contracts for the disposable Patroni failover lab."""

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import PatroniLab, active_server_names

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "tests" / "integration" / "lab"


def test_lab_defines_complete_isolated_topology() -> None:
    model = yaml.safe_load((LAB / "compose.yaml").read_text(encoding="utf-8"))
    services = model["services"]
    assert {
        "etcd",
        "armadillo",
        "rogue",
        "fluffy",
        "armadillo-pgbouncer",
        "rogue-pgbouncer",
        "fluffy-pgbouncer",
        "haproxy",
        "client",
        "armadillo-net",
        "rogue-net",
        "fluffy-net",
    } <= set(services)
    assert not model.get("volumes")
    assert all("ports" not in service for service in services.values())
    for node in ("armadillo", "rogue", "fluffy"):
        anchor = services[f"{node}-net"]
        assert anchor["user"] == "1000:1000"
        assert anchor["read_only"] is True
        assert services[node]["user"] == "999:999"
        assert services[node]["network_mode"] == f"service:{node}-net"
        assert services[node]["tmpfs"][0].startswith("/var/lib/postgresql/data:")
    for node in ("armadillo", "rogue", "fluffy"):
        pooler = services[f"{node}-pgbouncer"]
        assert pooler["user"] == "6433:6433"
        assert pooler["network_mode"] == f"service:{node}-net"
    assert services["haproxy"]["user"] == "99:99"
    assert services["client"]["user"] == "1000:1000"


def test_lab_haproxy_requires_both_patroni_primary_and_pgbouncer() -> None:
    config = (LAB / "haproxy.cfg").read_text(encoding="utf-8")
    assert "http-check connect port 8008" in config
    assert "http-check send meth GET uri /primary ver HTTP/1.1 hdr host patroni" in config
    assert "http-check expect status 200" in config
    assert "http-check connect port 6433" in config


def test_lab_compose_resolves_all_repository_bind_mounts(tmp_path: Path) -> None:
    env = {**os.environ, "LAB_SECRETS_DIR": str(tmp_path)}
    result = subprocess.run(
        ["docker", "compose", "-f", str(LAB / "compose.yaml"), "config", "--format", "json"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    model = json.loads(result.stdout)
    secret_root = tmp_path.resolve()
    sources = {
        mount["source"]
        for service in model["services"].values()
        for mount in service.get("volumes", [])
        if mount["type"] == "bind"
        and not Path(mount["source"]).resolve().is_relative_to(secret_root)
    }
    assert all(Path(source).exists() for source in sources)


def test_lab_runtime_fixture_overrides_render_only_secret_default() -> None:
    compose = (LAB / "compose.yaml").read_text(encoding="utf-8")
    fixture = (ROOT / "tests" / "integration" / "conftest.py").read_text(encoding="utf-8")
    assert "${LAB_SECRETS_DIR:-/tmp/postgres-ha-lab-render-secrets}" in compose
    assert 'os.environ["LAB_SECRETS_DIR"] = str(secret_dir)' in fixture


def test_lab_configs_encode_ordered_synchronous_failover() -> None:
    configs = {
        node: yaml.safe_load((LAB / "patroni" / f"{node}.yml").read_text(encoding="utf-8"))
        for node in ("armadillo", "rogue", "fluffy")
    }
    bootstrap = configs["armadillo"]["bootstrap"]["dcs"]
    assert bootstrap["synchronous_mode"] is True
    assert bootstrap["synchronous_node_count"] == 1
    assert bootstrap["postgresql"]["use_pg_rewind"] is True
    assert configs["armadillo"]["tags"]["failover_priority"] == 100
    assert configs["rogue"]["tags"]["failover_priority"] == 90
    assert configs["fluffy"]["tags"]["failover_priority"] == 10
    assert configs["rogue"]["tags"]["sync_priority"] > configs["fluffy"]["tags"]["sync_priority"]
    for config in configs.values():
        assert config["etcd3"]["host"] == "etcd:2379"
        assert config["postgresql"]["remove_data_directory_on_rewind_failure"] is False
        assert config["postgresql"]["remove_data_directory_on_diverged_timelines"] is False


def test_heavy_partition_suite_is_explicitly_opt_in() -> None:
    heavy = (ROOT / "tests" / "heavy" / "test_network_partitions.py").read_text(encoding="utf-8")
    assert "POSTGRES_HA_HEAVY" in heavy
    assert "pytest.skip" in heavy


def test_haproxy_stats_parser_excludes_aggregate_backend_row() -> None:
    def row(name: str, status: str) -> str:
        fields = ["patroni_primary", name, *("" for _ in range(15)), status]
        return ",".join(fields)

    stats = "\n".join((row("rogue", "UP"), row("fluffy", "DOWN"), row("BACKEND", "UP")))
    assert active_server_names(stats) == ["rogue"]


def test_proxy_psql_uses_quiet_tuple_only_output() -> None:
    class RecordingCompose:
        def exec_in_container(self, command, service):
            assert service == "client"
            assert "-q" in command
            assert "-At" in command
            return "expected-row\n", "", 0

    assert PatroniLab(RecordingCompose()).psql("select 'expected-row'") == "expected-row"


def test_rejoined_replica_contract_requires_streaming_state() -> None:
    source = (ROOT / "tests" / "integration" / "test_patroni_failover.py").read_text(
        encoding="utf-8"
    )
    assert 'members["armadillo"]["State"] == "streaming"' in source
    assert 'members["armadillo"]["Role"] == "Sync Standby"' in source


def test_switchover_uses_authenticated_rest_mutation_and_checks_response() -> None:
    class RecordingLab(PatroniLab):
        def exec(self, service, *command):
            assert service == "rogue"
            rendered = " ".join(command)
            assert "/switchover" in rendered
            assert "patroni_restapi_username" in rendered
            assert "patroni_restapi_password" in rendered
            assert command[-2:] == ("rogue", "armadillo")
            return '200|Successfully switched over to "armadillo"'

    RecordingLab(None).switchover("rogue", "armadillo")


def test_transition_writes_use_bounded_retry() -> None:
    source = (ROOT / "tests" / "integration" / "test_patroni_failover.py").read_text(
        encoding="utf-8"
    )
    assert 'lambda: _assert_proxy_write(lab, 3, "controlled-return", "armadillo")' in source


def test_container_exec_normalizes_subprocess_failures_for_bounded_retry() -> None:
    class FailingCompose:
        def exec_in_container(self, command, service):
            raise subprocess.CalledProcessError(2, command, stderr=b"transient disconnect")

    with pytest.raises(RuntimeError, match="transient disconnect"):
        PatroniLab(FailingCompose()).exec("client", "psql")
