"""Ordered failover and rejoin behavior in the disposable Patroni lab."""

from conftest import NODES, PatroniLab, eventually


def test_initial_primary_sync_order_and_replication(patroni_lab: PatroniLab) -> None:
    lab = patroni_lab

    def assert_topology() -> None:
        members = lab.members()
        assert members["armadillo"]["Role"] == "Leader"
        assert members["rogue"]["Role"] == "Sync Standby"
        assert members["fluffy"]["Role"] in {"Replica", "Standby Leader"}

    eventually(assert_topology, timeout=120)
    assert lab.psql("select current_user || '|' || pg_is_in_recovery()") == "lab_app|false"
    lab.psql("insert into lab_markers values (1, 'initial-sync') returning note")

    def assert_marker_everywhere() -> None:
        for node in NODES:
            assert lab.admin(node, "select note from lab_markers where id=1") == "initial-sync"

    eventually(assert_marker_everywhere, timeout=90)


def test_ordered_failover_rejoin_switchover_and_last_standing(
    patroni_lab: PatroniLab,
) -> None:
    lab = patroni_lab
    lab.stop("armadillo")

    def assert_rogue_promoted() -> None:
        members = lab.members(via="rogue")
        assert members["rogue"]["Role"] == "Leader"
        assert lab.active_backend() == "rogue"

    eventually(assert_rogue_promoted, timeout=60)
    eventually(
        lambda: _assert_proxy_write(lab, 2, "rogue-failover", "rogue"),
        timeout=30,
    )
    assert lab.admin("rogue", "select note from lab_markers where id=1") == "initial-sync"

    lab.start("armadillo")

    def assert_armadillo_rejoined_without_failback() -> None:
        members = lab.members(via="rogue")
        assert members["rogue"]["Role"] == "Leader"
        assert members["armadillo"]["Role"] == "Sync Standby"
        assert members["armadillo"]["State"] == "streaming"
        assert lab.active_backend() == "rogue"
        assert lab.admin("armadillo", "select note from lab_markers where id=2") == "rogue-failover"

    eventually(assert_armadillo_rejoined_without_failback, timeout=90)
    lab.switchover("rogue", "armadillo")

    def assert_controlled_return() -> None:
        members = lab.members(via="armadillo")
        assert members["armadillo"]["Role"] == "Leader"
        assert members["rogue"]["Role"] == "Sync Standby"
        assert lab.active_backend() == "armadillo"

    eventually(assert_controlled_return, timeout=60)
    eventually(
        lambda: _assert_proxy_write(lab, 3, "controlled-return", "armadillo"),
        timeout=30,
    )

    lab.stop("armadillo")

    def assert_sequential_rogue_then_fluffy_sync() -> None:
        members = lab.members(via="rogue")
        assert members["rogue"]["Role"] == "Leader"
        assert members["fluffy"]["Role"] == "Sync Standby"
        assert lab.active_backend() == "rogue"

    eventually(assert_sequential_rogue_then_fluffy_sync, timeout=60)
    eventually(
        lambda: _assert_proxy_write(lab, 4, "fluffy-synchronized", "rogue"),
        timeout=30,
    )
    lab.stop("rogue")

    def assert_fluffy_last_standing() -> None:
        members = lab.members(via="fluffy")
        assert members["fluffy"]["Role"] == "Leader"
        assert lab.active_backend() == "fluffy"

    eventually(assert_fluffy_last_standing, timeout=60)
    eventually(
        lambda: _assert_proxy_write(lab, 5, "last-standing", "fluffy"),
        timeout=30,
    )
    for marker_id, expected in {
        1: "initial-sync",
        2: "rogue-failover",
        3: "controlled-return",
        4: "fluffy-synchronized",
        5: "last-standing",
    }.items():
        assert lab.admin("fluffy", f"select note from lab_markers where id={marker_id}") == expected


def _assert_proxy_write(lab: PatroniLab, marker_id: int, note: str, expected: str) -> None:
    result = lab.psql(
        f"insert into lab_markers values ({marker_id}, '{note}') "
        "on conflict (id) do update set note = excluded.note "
        "returning current_setting('cluster_name') || '|' || note"
    )
    assert result == f"postgres-ha-lab|{note}"
    assert lab.active_backend() == expected
