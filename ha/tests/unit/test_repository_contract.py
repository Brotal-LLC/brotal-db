"""Source-shape contracts for the canonical PostgreSQL HA repository."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_required_project_files_exist() -> None:
    required = {
        ".pre-commit-config.yaml",
        ".gitignore",
        "scripts/pre-commit.sh",
        "pyproject.toml",
        "README.md",
    }
    tracked_files = set(
        subprocess.run(
            ["git", "ls-files"],
            check=True,
            capture_output=True,
            cwd=ROOT,
            text=True,
        ).stdout.splitlines()
    )

    assert required <= tracked_files


def test_validation_is_tracked_and_fails_closed() -> None:
    config = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    script = (ROOT / "scripts/pre-commit.sh").read_text(encoding="utf-8")

    for validator in (
        "ruff",
        "yamllint",
        "shellcheck",
        "hadolint",
        "check-yaml",
        "detect-private-key",
        "pytest",
        "docker compose",
    ):
        assert validator in config or validator in script

    assert "set -euo pipefail" in script
    assert "|| true" not in script


def test_compose_validation_uses_the_committed_non_secret_fixture() -> None:
    runner = (ROOT / "scripts/pre-commit.sh").read_text(encoding="utf-8")

    assert "tests/fixtures/test.env" in runner
    assert 'docker compose "${compose_args[@]}" -f "$compose_file" config --quiet' in runner
    fixture = (ROOT / "tests" / "fixtures" / "test.env").read_text(encoding="utf-8")
    assert "PASSWORD=" not in fixture


def test_secret_and_generated_material_is_not_tracked_or_allowed() -> None:
    forbidden_names = {".env", "id_rsa", "server.key", "client.key", "ca.key"}
    forbidden_suffixes = (".secret", ".secrets.yaml", ".secrets.yml")
    tracked_files = subprocess.run(
        ["git", "ls-files"],
        check=True,
        capture_output=True,
        cwd=ROOT,
        text=True,
    ).stdout.splitlines()
    leaked_files = [
        path
        for path in tracked_files
        if Path(path).name in forbidden_names or path.endswith(forbidden_suffixes)
    ]

    assert not leaked_files

    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in (".env", "*.key", "*.pem", "*.secret", "rendered/"):
        assert pattern in gitignore
