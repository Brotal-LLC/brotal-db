#!/usr/bin/env bash
set -euo pipefail

: "${ETCDCTL_CACERT:?ETCDCTL_CACERT is required}"
: "${ETCDCTL_CERT:?ETCDCTL_CERT is required}"
: "${ETCDCTL_KEY:?ETCDCTL_KEY is required}"
: "${ETCDCTL_ENDPOINTS:=https://100.64.0.2:2379,https://100.64.0.1:2379,https://100.64.0.3:2379}"
export ETCDCTL_API=3 ETCDCTL_CACERT ETCDCTL_CERT ETCDCTL_KEY ETCDCTL_ENDPOINTS

etcdctl endpoint health --cluster
status=$(etcdctl endpoint status --cluster -w json)

members=$(jq 'length' <<<"$status")
leaders=$(jq '[.[].Status.leader] | unique | length' <<<"$status")
if [[ $members -ne 3 ]]; then
  printf 'expected exactly three DCS members; found %s\n' "$members" >&2
  exit 1
fi
if [[ $leaders -ne 1 ]]; then
  printf 'expected exactly one DCS leader; found %s distinct leader IDs\n' "$leaders" >&2
  exit 1
fi
if jq -e 'any(.[]; .Status.errors | length > 0)' <<<"$status" >/dev/null; then
  printf 'one or more DCS members report errors\n' >&2
  exit 1
fi
printf 'etcd-quorum=healthy members=%s leaders=%s\n' "$members" "$leaders"
