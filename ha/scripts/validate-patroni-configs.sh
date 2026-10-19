#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
tmp=$(mktemp -d)
listener_pid=
cleanup() {
  if [[ -n $listener_pid ]]; then
    kill "$listener_pid" >/dev/null 2>&1 || true
  fi
  sudo rm -rf "$tmp"
}
trap cleanup EXIT

uv run --project "$root" python -m http.server 12379 --bind 127.0.0.1 \
  >"$tmp/reachability-listener.log" 2>&1 &
listener_pid=$!
for _ in $(seq 1 30); do
  curl --fail --silent http://127.0.0.1:12379/ >/dev/null 2>&1 && break
  sleep 0.1
done
curl --fail --silent http://127.0.0.1:12379/ >/dev/null

sudo env PATRONI_RUNTIME_UID=999 PATRONI_RUNTIME_GID=999 \
  "$root/scripts/generate-secrets.sh" "$tmp/secrets" >/dev/null
"$root/scripts/generate-etcd-pki.sh" "$tmp/pki" >/dev/null
sudo mkdir -p "$tmp/secrets/etcd"
sudo chmod 0755 "$tmp" "$tmp/secrets" "$tmp/secrets/etcd" "$tmp/pki"

for node in armadillo rogue fluffy; do
  case "$node" in
    armadillo) cert=postgres-armadillo ;;
    rogue) cert=postgres-rogue ;;
    fluffy) cert=fluffy ;;
  esac
  for file in ca.crt tls.crt tls.key; do
    sudo install -o 999 -g 999 -m 0400 \
      "$tmp/pki/$cert/$file" "$tmp/secrets/etcd/$file"
  done
  uv run --project "$root" python - \
    "$root/config/patroni/$node.yml" "$tmp/$node.yml" <<'PY'
import sys
import yaml
source, target = sys.argv[1:]
with open(source, encoding="utf-8") as stream:
    config = yaml.safe_load(stream)
config["etcd3"]["hosts"] = ["127.0.0.1:12379"]
config["etcd3"]["protocol"] = "http"
config["etcd3"].pop("cacert")
config["etcd3"].pop("cert")
config["etcd3"].pop("key")
with open(target, "w", encoding="utf-8") as stream:
    yaml.safe_dump(config, stream, sort_keys=False)
PY
  docker run --rm --network host --user 999:999 \
    --mount "type=bind,src=$tmp/$node.yml,dst=/config/patroni.yml,readonly" \
    --mount "type=bind,src=$tmp/secrets,dst=/run/secrets,readonly" \
    postgres-ha-patroni:test \
    --validate-config --ignore-listen-port /config/patroni.yml
  printf 'patroni-executable-validation=%s pass\n' "$node"
done
