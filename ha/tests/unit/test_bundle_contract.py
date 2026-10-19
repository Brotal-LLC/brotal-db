"""Require an explicit reviewed data path and preserve unrelated services."""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("host", ["armadillo", "rogue"])
def test_bundle_uses_selected_data_path_and_preserves_existing_services(host):
    args = [
        "docker",
        "compose",
        "--env-file",
        "tests/fixtures/test.env",
        "-f",
        f"deploy/{host}/compose.yaml",
    ]
    baseline = json.loads(subprocess.check_output(args + ["config", "--format", "json"], cwd=ROOT))
    updated = json.loads(
        subprocess.check_output(
            args + ["-f", "deploy/compose.bundle.yaml", "config", "--format", "json"], cwd=ROOT
        )
    )
    postgres = updated["services"]["postgres"]
    storage = [v for v in postgres["volumes"] if v["target"] == "/var/lib/postgresql/data"]
    assert len(storage) == 1
    assert storage[0]["type"] == "bind"
    assert storage[0]["source"] == "/fixture/postgres-bundle"
    assert postgres["command"] == ["/etc/patroni/patroni.yml"]
    assert postgres["entrypoint"] == ["/usr/local/bin/patroni-existing-secrets"]
    assert postgres["user"] == "999:999"
    assert int(postgres["mem_limit"]) == 8 * 1024**3
    assert int(postgres["shm_size"]) == 1024**3
    assert int(postgres["mem_reservation"]) == 2 * 1024**3
    assert postgres["cpus"] == 4
    assert postgres["ports"] == baseline["services"]["postgres"]["ports"]
    for name, service in baseline["services"].items():
        if name not in ("postgres", "pgbouncer"):
            assert updated["services"][name] == service
    pgbouncer = updated["services"]["pgbouncer"]
    assert int(pgbouncer["mem_limit"]) == 512 * 1024**2
    assert pgbouncer["cpus"] == 1
