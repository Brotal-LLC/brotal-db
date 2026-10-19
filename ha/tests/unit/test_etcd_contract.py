from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "compose" / "compose.etcd.yaml"
README = ROOT / "config" / "etcd" / "README.md"
QUORUM_CHECK = ROOT / "scripts" / "check-etcd-quorum.sh"


EXPECTED_MEMBERS = {"etcd-hm", "etcd-of", "etcd-witness"}


def read(path: Path) -> str:
    assert path.is_file(), f"missing required file: {path.relative_to(ROOT)}"
    return path.read_text(encoding="utf-8")


def test_etcd_compose_defines_only_the_three_planned_members() -> None:
    compose = read(COMPOSE)
    for member in EXPECTED_MEMBERS:
        assert member in compose

    # The DCS is deliberately placed on Fluffy, pi1, and the third-site witness;
    # Armadillo and Rogue must not secretly become DCS members.
    assert "armadillo" not in compose.lower()
    assert "rogue" not in compose.lower()


def test_etcd_is_digest_pinned_tls_only_and_non_root() -> None:
    compose = read(COMPOSE)
    digest = "a9983dd6d9283138ab926daa307c6c25623636703ecf5645d5df4d666ce9eba2"
    assert f"gcr.io/etcd-development/etcd:v3.7.1@sha256:{digest}" in compose
    assert 'user: "1000:1000"' in compose
    assert "http://" not in compose
    for required_flag in (
        "--client-cert-auth=true",
        "--peer-client-cert-auth=true",
        "--trusted-ca-file=/run/secrets/etcd/ca.crt",
        "--cert-file=/run/secrets/etcd/member.crt",
        "--key-file=/run/secrets/etcd/member.key",
        "--peer-trusted-ca-file=/run/secrets/etcd/ca.crt",
        "--peer-cert-file=/run/secrets/etcd/member.crt",
        "--peer-key-file=/run/secrets/etcd/member.key",
    ):
        assert required_flag in compose


def test_etcd_requires_private_advertisement_and_persistent_member_state() -> None:
    compose = read(COMPOSE)
    for required in (
        "${ETCD_MEMBER_NAME:?ETCD_MEMBER_NAME must be one of etcd-hm, etcd-of, or etcd-witness}",
        "${ETCD_ADVERTISE_ADDRESS:?ETCD_ADVERTISE_ADDRESS must be this member's private address}",
        "${ETCD_HM_PRIVATE_ADDRESS:?ETCD_HM_PRIVATE_ADDRESS is required}",
        "${ETCD_OF_PRIVATE_ADDRESS:?ETCD_OF_PRIVATE_ADDRESS is required}",
        "${ETCD_WITNESS_PRIVATE_ADDRESS:?ETCD_WITNESS_PRIVATE_ADDRESS is required}",
        "${ETCD_DATA_DIR:?ETCD_DATA_DIR must be a persistent host path}",
        "type: bind",
        "target: /var/lib/etcd",
        "--advertise-client-urls=https://${ETCD_ADVERTISE_ADDRESS",
        "--initial-advertise-peer-urls=https://${ETCD_ADVERTISE_ADDRESS",
        "network_mode: host",
        "--listen-client-urls=https://${ETCD_ADVERTISE_ADDRESS",
        "--listen-peer-urls=https://${ETCD_ADVERTISE_ADDRESS",
        "--endpoints=https://${ETCD_ADVERTISE_ADDRESS",
    ):
        assert required in compose
    assert "0.0.0.0:2379" not in compose
    assert "0.0.0.0:2380" not in compose
    assert "127.0.0.1:2379" not in compose
    assert "ports:" not in compose


def test_etcd_healthcheck_and_quorum_probe_use_authenticated_etcdctl() -> None:
    compose = read(COMPOSE)
    script = read(QUORUM_CHECK)
    assert "/usr/local/bin/etcdctl" in compose
    assert "endpoint\n        - health" in compose
    for required in (
        "ETCDCTL_API=3",
        "ETCDCTL_CACERT",
        "ETCDCTL_CERT",
        "ETCDCTL_KEY",
        "endpoint health --cluster",
        "endpoint status --cluster -w json",
        "expected exactly three DCS members",
    ):
        assert required in script


def test_etcd_documentation_gates_witness_on_private_routing() -> None:
    readme = read(README)
    for required in (
        "etcd-hm",
        "Fluffy",
        "100.64.0.2",
        "etcd-of",
        "pi1",
        "100.64.0.1",
        "etcd-witness",
        "sv1-sg",
        "100.64.0.3",
        "route gate",
        "private",
        "automatic failover",
    ):
        assert required.lower() in readme.lower()

    # The formerly planned public x1-sg witness is not part of the verified DCS topology.
    for retired_endpoint in ("x1-sg", "217.216.110.195"):
        assert retired_endpoint not in readme.lower()


def test_etcd_documentation_records_the_database_tailnet_members() -> None:
    readme = read(README)
    for required in (
        "Armadillo",
        "100.64.0.5",
        "Rogue",
        "100.64.0.4",
        "Fluffy",
        "100.64.0.2",
    ):
        assert required.lower() in readme.lower()
