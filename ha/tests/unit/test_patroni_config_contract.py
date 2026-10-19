"""Semantic contracts for the Patroni 4.1.4 node configurations."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config" / "patroni"
NODES = {
    "armadillo": {
        "address": "100.64.0.5",
        "failover": 100,
        "sync": 100,
        "shared_buffers": "2GB",
        "maintenance_work_mem": "256MB",
        "work_mem": "64MB",
        "wal_keep_size": "4GB",
    },
    "rogue": {
        "address": "100.64.0.4",
        "failover": 50,
        "sync": 50,
        "shared_buffers": "1GB",
        "maintenance_work_mem": "256MB",
        "work_mem": "64MB",
        "wal_keep_size": "4GB",
    },
    "fluffy": {
        "address": "100.64.0.2",
        "failover": 10,
        "sync": 10,
        "shared_buffers": "128MB",
        "maintenance_work_mem": "64MB",
        "work_mem": "16MB",
        "wal_keep_size": "1GB",
    },
}
ETCD_HOSTS = ["100.64.0.2:2379", "100.64.0.1:2379", "100.64.0.3:2379"]


def load(name: str) -> dict:
    path = CONFIG_DIR / f"{name}.yml"
    assert path.is_file(), f"missing Patroni config: {path.relative_to(ROOT)}"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_complete_source_set_exists() -> None:
    expected = {"common", "dynamic-target", *NODES}
    assert {path.stem for path in CONFIG_DIR.glob("*.yml")} == expected


def test_migration_bootstrap_and_final_dynamic_policy_are_distinct() -> None:
    common = load("common")
    target = load("dynamic-target")
    dcs = common["bootstrap"]["dcs"]

    assert dcs["synchronous_mode"] is False
    assert target["synchronous_mode"] is True
    for policy in (dcs, target):
        assert policy["synchronous_mode_strict"] is False
        assert policy["synchronous_node_count"] == 1
        assert policy["maximum_lag_on_failover"] == 16_777_216
        assert policy["maximum_lag_on_syncnode"] == 16_777_216
        assert policy["check_timeline"] is True
    assert dcs["ttl"] > dcs["loop_wait"] + 2 * dcs["retry_timeout"]


def test_migration_bootstrap_preserves_legacy_replica_slots() -> None:
    expected = {
        "rogue": {"type": "physical"},
        "nest1": {"type": "physical"},
    }
    assert load("common")["bootstrap"]["dcs"]["slots"] == expected
    for name in NODES:
        assert load(name)["bootstrap"]["dcs"]["slots"] == expected


def test_migration_bootstrap_preserves_live_connection_capacity() -> None:
    assert load("common")["bootstrap"]["dcs"]["postgresql"]["parameters"]["max_connections"] == 1000
    for name in NODES:
        dcs_parameters = load(name)["bootstrap"]["dcs"]["postgresql"]["parameters"]
        assert dcs_parameters["max_connections"] == 1000


def test_nodes_use_private_advertised_addresses_but_container_listeners() -> None:
    for name, expected in NODES.items():
        config = load(name)
        address = expected["address"]
        assert config["name"] == name
        assert config["scope"] == "brotal-postgres"
        assert config["namespace"] == "/service/"
        assert config["restapi"]["listen"] == "0.0.0.0:8008"
        assert config["restapi"]["connect_address"] == f"{address}:8008"
        assert config["postgresql"]["listen"] == "0.0.0.0:5432"
        assert config["postgresql"]["connect_address"] == f"{address}:5432"
        assert config["postgresql"]["data_dir"] == "/var/lib/postgresql/data"


def test_etcd_uses_three_tls_endpoints_and_runtime_client_certificates() -> None:
    for name in NODES:
        etcd = load(name)["etcd3"]
        assert etcd["hosts"] == ETCD_HOSTS
        assert etcd["protocol"] == "https"
        assert etcd["cacert"] == "/run/secrets/etcd/ca.crt"
        assert etcd["cert"] == "/run/secrets/etcd/tls.crt"
        assert etcd["key"] == "/run/secrets/etcd/tls.key"


def test_rewind_slots_hba_and_divergence_are_fail_safe() -> None:
    for name in NODES:
        postgres = load(name)["postgresql"]
        assert postgres["use_pg_rewind"] is True
        assert postgres["use_slots"] is True
        assert postgres["remove_data_directory_on_rewind_failure"] is False
        assert postgres["remove_data_directory_on_diverged_timelines"] is False
        assert postgres["parameters"]["wal_log_hints"] == "on"
        hba = "\n".join(postgres["pg_hba"])
        assert "0.0.0.0/0" not in hba
        assert "::/0" not in hba
        assert "host replication patroni_replication 127.0.0.1/32 scram-sha-256" in hba
        assert "host replication patroni_replication ::1/128 scram-sha-256" in hba
        assert "host all all ::1/128 scram-sha-256" in hba
        for cidr in ("10.49.0.0/16", "10.63.0.0/16"):
            assert f"host replication replicator {cidr} scram-sha-256" in hba
        for cidr in ("10.49.0.0/16", "10.63.0.0/16", "100.64.0.0/10"):
            assert cidr in hba

        # Docker-published Tailnet ports SNAT remote Patroni replication
        # probes to the destination host's database bridge gateway.
        bridge_cidr = "172.19.0.0/16" if name == "armadillo" else "172.18.0.0/16"
        assert f"host replication patroni_replication {bridge_cidr} scram-sha-256" in hba


def test_priorities_and_live_memory_overlays_are_exact() -> None:
    for name, expected in NODES.items():
        config = load(name)
        tags = config["tags"]
        assert tags["failover_priority"] == expected["failover"]
        assert tags["sync_priority"] == expected["sync"]
        assert "nofailover" not in tags
        assert "nosync" not in tags
        parameters = config["postgresql"]["parameters"]
        for setting in (
            "shared_buffers",
            "maintenance_work_mem",
            "work_mem",
            "wal_keep_size",
        ):
            assert parameters[setting] == expected[setting]
        assert parameters["max_connections"] == 1000


def test_credentials_are_not_embedded_in_yaml() -> None:
    for path in CONFIG_DIR.glob("*.yml"):
        source = path.read_text(encoding="utf-8")
        assert "!env" not in source.lower()
        assert "password:" not in source.lower()
        assert "test-only-secret" not in source
