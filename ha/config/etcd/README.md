# PostgreSQL DCS topology

The etcd control plane has exactly three voting members in independent host/site failure domains:

| Member | Host | Private Tailnet address | Persistent state |
|---|---|---:|---|
| `etcd-hm` | Fluffy | `100.64.0.2` | `/srv/state/postgres-etcd` |
| `etcd-of` | pi1 | `100.64.0.1` | `/srv/state/postgres-etcd` |
| `etcd-witness` | sv1-sg | `100.64.0.3` | `/srv/state/postgres-etcd` |

Database Patroni clients are Armadillo (`100.64.0.5`), Rogue (`100.64.0.4`), and Fluffy (`100.64.0.2`). All peer and client traffic is mTLS on the private Tailnet. No etcd port is published on a public address.

## Route gate

Automatic failover is forbidden until every database node and DCS member can reach all three private client endpoints and all three DCS members can reach each peer endpoint. Verify with `tailscale ping` and an authenticated `etcdctl endpoint health --cluster`. Ordinary ICMP is not sufficient evidence because Tailnet policy and userspace routing may differ.

The production Compose service uses host networking and binds only its own
Tailnet address. Docker bridge publishing SNATs inter-host peer traffic to the
bridge gateway address; etcd 3.7 peer certificate authentication then rejects
the connection because that gateway address is not the presenting member's
certificate SAN. Host networking preserves the authenticated Tailnet source
identity while the explicit listen addresses prevent exposure on non-Tailnet
interfaces.

The witness is intentionally independent of Armadillo and Rogue. Losing either database site must leave the surviving database side plus the third-site witness with DCS quorum. Losing two etcd members must fail closed: an existing PostgreSQL primary may continue under the configured DCS failsafe policy only after that policy is separately tested; a new leader must not be elected without quorum.

## Host-specific environment

Each host deploys `compose/compose.etcd.yaml` with:

- `ETCD_MEMBER_NAME`: one of `etcd-hm`, `etcd-of`, `etcd-witness`;
- `ETCD_ADVERTISE_ADDRESS`: that member's Tailnet address;
- `ETCD_HM_PRIVATE_ADDRESS=100.64.0.2`;
- `ETCD_OF_PRIVATE_ADDRESS=100.64.0.1`;
- `ETCD_WITNESS_PRIVATE_ADDRESS=100.64.0.3`;
- `ETCD_DATA_DIR=/srv/state/postgres-etcd`;
- `ETCD_SECRETS_DIR=/srv/stacks/postgres-dcs/secrets`.

Prepare the state directory as UID/GID `1000:1000` mode `0700`. Deploy the dedicated CA and member certificate from `scripts/generate-etcd-pki.sh`; keys are mode `0400` and never committed.
