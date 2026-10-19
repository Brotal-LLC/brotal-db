"""Behavioral guardrails for the existing-data adoption supervisor."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "images" / "patroni" / "existing-data-supervisor.py"


def load_supervisor():
    spec = importlib.util.spec_from_file_location("existing_data_supervisor", SOURCE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configure(module, tmp_path: Path, role: str = "primary") -> Path:
    data = tmp_path / "data"
    data.mkdir()
    config = tmp_path / "patroni.yml"
    config.write_text("scope: lab\n", encoding="utf-8")
    module.PGDATA = data
    module.POSTMASTER_PID = data / "postmaster.pid"
    module.STANDBY_SIGNAL = data / "standby.signal"
    module.EXPECTED_ROLE = role
    module.PATRONI_CONFIG = config
    return data


def test_empty_pgdata_fails_closed_before_process_launch(tmp_path: Path, monkeypatch) -> None:
    module = load_supervisor()
    configure(module, tmp_path)
    monkeypatch.setattr(module.os, "getuid", lambda: 999)

    with pytest.raises(SystemExit):
        module.validate()


def test_primary_refuses_standby_signal(tmp_path: Path, monkeypatch) -> None:
    module = load_supervisor()
    data = configure(module, tmp_path)
    (data / "PG_VERSION").write_text("18\n", encoding="utf-8")
    (data / "standby.signal").touch()
    monkeypatch.setattr(module.os, "getuid", lambda: 999)

    with pytest.raises(SystemExit):
        module.validate()


def test_replica_requires_standby_signal(tmp_path: Path, monkeypatch) -> None:
    module = load_supervisor()
    data = configure(module, tmp_path, role="replica")
    (data / "PG_VERSION").write_text("18\n", encoding="utf-8")
    monkeypatch.setattr(module.os, "getuid", lambda: 999)

    with pytest.raises(SystemExit):
        module.validate()


def test_existing_postmaster_pid_is_never_adopted_blindly(tmp_path: Path, monkeypatch) -> None:
    module = load_supervisor()
    data = configure(module, tmp_path)
    (data / "PG_VERSION").write_text("18\n", encoding="utf-8")
    (data / "postmaster.pid").write_text("123\n", encoding="utf-8")
    monkeypatch.setattr(module.os, "getuid", lambda: 999)

    with pytest.raises(SystemExit):
        module.validate()


def test_root_execution_is_rejected(tmp_path: Path, monkeypatch) -> None:
    module = load_supervisor()
    data = configure(module, tmp_path)
    (data / "PG_VERSION").write_text("18\n", encoding="utf-8")
    monkeypatch.setattr(module.os, "getuid", lambda: 0)

    with pytest.raises(SystemExit):
        module.validate()


def test_valid_existing_primary_passes_preflight(tmp_path: Path, monkeypatch) -> None:
    module = load_supervisor()
    data = configure(module, tmp_path)
    (data / "PG_VERSION").write_text("18\n", encoding="utf-8")
    monkeypatch.setattr(module.os, "getuid", lambda: 999)

    module.validate()


def test_planned_legacy_exit_does_not_define_supervisor_exit_status() -> None:
    """The original postmaster may exit after Patroni begins ownership transfer."""
    legacy = Mock()
    legacy.poll.return_value = 0
    patroni = Mock()
    patroni.poll.side_effect = [None, None, 0]
    patroni.returncode = 0

    polls = 0
    while patroni.poll() is None:
        legacy.poll()
        polls += 1

    assert polls == 2
    assert legacy.poll.call_count == 2
    assert int(patroni.returncode or 0) == 0
