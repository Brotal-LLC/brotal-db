#!/usr/bin/env bash
# Run the same repository checks locally or validate a rendered Compose file in pre-commit.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

validate_compose() {
  shopt -s nullglob globstar
  local compose_files=(compose*.yaml compose*.yml **/compose*.yaml **/compose*.yml)
  local compose_args=()

  if [[ -f tests/fixtures/test.env ]]; then
    compose_args=(--env-file tests/fixtures/test.env)
  fi

  for compose_file in "${compose_files[@]}"; do
    if [[ "$compose_file" == deploy/compose.bundle.yaml ]]; then
      for bundle_host in armadillo rogue; do
        NODE_NAME="$bundle_host" docker compose "${compose_args[@]}" \
          -f "deploy/$bundle_host/compose.yaml" -f "$compose_file" config --quiet
      done
      continue
    fi
    docker compose "${compose_args[@]}" -f "$compose_file" config --quiet
  done
}

case "${1:---all}" in
  --all)
    # .pre-commit-config.yaml owns YAML, shell, Dockerfile, Python, key-scan, test,
    # and rendered-Compose validators. Do not add failure-masking operators here.
    pre-commit run --all-files --config ha/.pre-commit-config.yaml
    ;;
  --compose-only)
    validate_compose
    ;;
  *)
    printf 'Usage: %s [--all|--compose-only]\n' "$0" >&2
    exit 2
    ;;
esac
