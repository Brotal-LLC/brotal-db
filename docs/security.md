# Security

Use TLS for client, replication, Patroni REST and etcd in production; bind services to private networks and rotate generated secrets. Keep remote/client-facing authentication on SCRAM, do not deliberately configure `trust`, and scope extension allowlists. PgBouncer uses `auth_type = scram-sha-256`; its private mode-0600 auth file contains the generated password in plaintext at rest so PgBouncer can answer SCRAM, therefore protect the host and use TLS for non-local clients. Restrict PgBouncer admin access and mount auth files read-only.

Base images, extension archives, and CI actions are version/digest pinned; Python runtime dependencies are transitively version- and hash-locked. Debian and PGDG APT dependencies intentionally resolve current security packages at build time rather than a frozen repository snapshot; the generated SBOM records exact installed versions. Organizations requiring byte-for-byte rebuilds should build from controlled Debian/PGDG snapshot mirrors.
