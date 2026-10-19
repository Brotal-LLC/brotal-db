"""Locally scheduled Patroni partition and churn drills."""

import os

import pytest


@pytest.mark.heavy
def test_network_partitions_are_exercised_by_the_opt_in_lab() -> None:
    if os.environ.get("POSTGRES_HA_HEAVY") != "1":
        pytest.skip("set POSTGRES_HA_HEAVY=1 for destructive local partition drills")
    pytest.skip("partition matrix is implemented after the deterministic failover lab is green")
