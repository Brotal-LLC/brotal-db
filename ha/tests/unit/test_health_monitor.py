"""Detect stalled streaming even while PostgreSQL still reports running."""

import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / "scripts/check-ha-health.py"
spec = importlib.util.spec_from_file_location("ha_health", SOURCE)
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


def inspect(sql_state):
    members = [
        {"name": "armadillo", "role": "leader", "state": "running"},
        {"name": "rogue", "role": "replica", "state": "running"},
    ]
    with (
        patch.object(
            monitor, "urlopen", return_value=io.BytesIO(json.dumps({"members": members}).encode())
        ),
        patch.object(
            monitor.subprocess, "check_output", return_value=json.dumps(sql_state).encode()
        ),
    ):
        return monitor.check("http://local:8008")


def test_primary_detects_disconnected_replica_before_slot_retention_grows():
    result = inspect({"inRecovery": False, "slots": [], "replication": [], "receivers": []})
    assert not result["healthy"]
    assert any("no streaming" in p for p in result["problems"])


def test_running_replica_requires_a_live_wal_receiver():
    result = inspect({"inRecovery": True, "slots": [], "replication": [], "receivers": []})
    assert not result["healthy"]
    assert any("WAL receiver" in p for p in result["problems"])


def test_primary_requires_synchronous_flush_acknowledgment():
    state = {
        "inRecovery": False,
        "slots": [],
        "receivers": [],
        "replication": [
            {"name": "rogue", "state": "streaming", "syncState": "async", "lagBytes": 0}
        ],
    }
    assert not inspect(state)["healthy"]
    state["replication"][0]["syncState"] = "sync"
    assert inspect(state)["healthy"]
    state["replication"][0]["lagBytes"] = 65 * 1024**2
    assert not inspect(state)["healthy"]
