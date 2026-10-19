"""Contracts for the live PostgreSQL consumer migration inventory."""

from pathlib import Path

import pytest

from scripts.inventory_consumers import InventoryError, reconcile

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "artifacts" / "consumer-inventory.tsv"

REQUIRED_COLUMNS = {
    "database",
    "role",
    "owner_host",
    "config_path",
    "driver_pool",
    "session_features",
    "retry_behavior",
    "recreate_command",
    "smoke_test",
    "rollback_command",
    "wave",
    "status",
}


def test_inventory_has_complete_operational_fields_and_no_secrets() -> None:
    text = INVENTORY.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert set(lines[0].split("\t")) == REQUIRED_COLUMNS
    assert "password=" not in text.lower()
    assert "postgresql://" not in text.lower()
    assert "[redacted]" not in text.lower()
    for line in lines[1:]:
        fields = line.split("\t")
        assert len(fields) == len(REQUIRED_COLUMNS)
        assert all(fields)


def test_every_live_application_pair_is_owned_or_explicitly_blocked(tmp_path: Path) -> None:
    activity = tmp_path / "activity.tsv"
    activity.write_text(
        "penpot|penpot_app|172.19.0.1/32|60\n"
        "pixu-memories|pixu|10.63.0.7/32|65\n"
        "penpot|zbx_monitor|172.19.0.1/32|1\n",
        encoding="utf-8",
    )
    assert len(reconcile(activity, INVENTORY)) == 3


def test_unowned_live_pair_fails_closed(tmp_path: Path) -> None:
    activity = tmp_path / "activity.tsv"
    activity.write_text("new_database|new_role|10.0.0.9/32|2\n", encoding="utf-8")
    with pytest.raises(InventoryError, match="new_database/new_role"):
        reconcile(activity, INVENTORY)


def test_known_high_risk_and_memory_consumers_have_specific_rows() -> None:
    text = INVENTORY.read_text(encoding="utf-8")
    for pair in (
        "penpot\tpenpot_app",
        "pixu-memories\tpixu",
        "snoop-memories\tsnoop",
        "astream\tastream",
        "iptv_prod\tpostgres",
        "zabbix\tzabbix",
    ):
        assert pair in text
    assert "*\tzbx_monitor" in text


def test_unknown_compatibility_is_a_blocking_test_requirement_not_an_assumption() -> None:
    rows = INVENTORY.read_text(encoding="utf-8").splitlines()[1:]
    for row in rows:
        fields = row.split("\t")
        status = fields[-1]
        driver_pool = fields[4]
        session_features = fields[5]
        if "unknown" in driver_pool.lower() or "unknown" in session_features.lower():
            assert status == "blocked-pending-test"
