#!/bin/bash
# Validate production sources without starting services or touching stateful volumes.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export UV_LINK_MODE=copy

uv run --locked --directory ha ruff check .
uv run --locked --directory ha ruff format --check .
mapfile -t yaml_files < <(git ls-files 'ha/*.yml' 'ha/*.yaml' 'ha/**/*.yml' 'ha/**/*.yaml')
uv run --locked --project ha yamllint --strict "${yaml_files[@]}"
uv run --locked --directory ha pytest tests/unit tests/integration/test_lab_contract.py -q
ha/scripts/pre-commit.sh --compose-only

mapfile -t shell_files < <(git ls-files 'ha/*.sh' 'ha/**/*.sh')
shellcheck "${shell_files[@]}"
for dockerfile in ha/images/patroni/Dockerfile ha/images/pgbouncer/Dockerfile; do
  docker run --rm -i ghcr.io/hadolint/hadolint:v2.12.0-debian < "$dockerfile"
done

uv run --locked --directory ha pre-commit run detect-private-key \
  --all-files --config ha/.pre-commit-config.yaml
