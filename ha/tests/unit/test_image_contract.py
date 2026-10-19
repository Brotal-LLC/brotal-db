"""Source-shape contracts for reproducible Patroni and PgBouncer images."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATRONI_DOCKERFILE = ROOT / "images/patroni/Dockerfile"
PATRONI_ENTRYPOINT = ROOT / "images/patroni/entrypoint.sh"
PGBOUNCER_DOCKERFILE = ROOT / "images/pgbouncer/Dockerfile"

PGVECTOR_DIGEST = "12a379b47ad65289572ea0756efc11b7c241a6662833e8af7038cd3b73d647e0"
DEBIAN_DIGEST = "abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241"
PGBOUNCER_SHA256 = "924ad35113fd0a71c8e2dbe85b5d03445532e2b7b37a9f8a48983beea238b332"


def read(path: Path) -> str:
    assert path.is_file(), f"missing required image source: {path.relative_to(ROOT)}"
    return path.read_text(encoding="utf-8")


def test_patroni_is_pinned_to_the_pgvector_postgres_18_base() -> None:
    dockerfile = read(PATRONI_DOCKERFILE)

    assert f"ARG PGVECTOR_IMAGE=pgvector/pgvector:0.8.5-pg18@sha256:{PGVECTOR_DIGEST}" in dockerfile
    assert "FROM ${PGVECTOR_IMAGE}" in dockerfile
    # The pgvector base, rather than a stock PostgreSQL image, preserves CREATE EXTENSION vector.
    assert "pgvector" in dockerfile
    assert '"patroni[etcd3,psycopg3]==4.1.4"' in dockerfile


def test_patroni_runtime_is_non_root_and_cleans_package_caches() -> None:
    dockerfile = read(PATRONI_DOCKERFILE)

    assert "USER 0" in dockerfile
    assert "USER 999:999" in dockerfile
    assert "rm -rf /var/lib/apt/lists/*" in dockerfile
    assert 'ENTRYPOINT ["/usr/local/bin/patroni-entrypoint"]' in dockerfile
    assert 'CMD ["/etc/patroni/patroni.yml"]' in dockerfile


def test_patroni_entrypoint_loads_only_named_secret_files_and_execs() -> None:
    entrypoint = read(PATRONI_ENTRYPOINT)

    for variable, filename in {
        "PATRONI_SUPERUSER_USERNAME": "patroni_superuser_username",
        "PATRONI_SUPERUSER_PASSWORD": "patroni_superuser_password",
        "PATRONI_REPLICATION_USERNAME": "patroni_replication_username",
        "PATRONI_REPLICATION_PASSWORD": "patroni_replication_password",
        "PATRONI_REWIND_USERNAME": "patroni_rewind_username",
        "PATRONI_REWIND_PASSWORD": "patroni_rewind_password",
        "PATRONI_RESTAPI_USERNAME": "patroni_restapi_username",
        "PATRONI_RESTAPI_PASSWORD": "patroni_restapi_password",
    }.items():
        assert f"load_secret {variable} {filename}" in entrypoint

    assert '"/run/secrets/$secret_file"' in entrypoint
    assert '"$(id -u)" -eq 0' in entrypoint
    assert entrypoint.rstrip().endswith(
        'exec "${PATRONI_EXECUTABLE:-/opt/patroni/bin/patroni}" "$@"'
    )


def test_pgbouncer_builds_the_official_pinned_release_from_source() -> None:
    dockerfile = read(PGBOUNCER_DOCKERFILE)

    assert f"ARG DEBIAN_IMAGE=debian:bookworm-slim@sha256:{DEBIAN_DIGEST}" in dockerfile
    assert "ARG PGBOUNCER_VERSION=1.25.2" in dockerfile
    assert f"ARG PGBOUNCER_SHA256={PGBOUNCER_SHA256}" in dockerfile
    assert (
        "ARG PGBOUNCER_URL=https://www.pgbouncer.org/downloads/files/"
        "${PGBOUNCER_VERSION}/pgbouncer-${PGBOUNCER_VERSION}.tar.gz"
    ) in dockerfile
    assert "sha256sum --check --strict -" in dockerfile
    assert "./configure --prefix=/usr/local --sysconfdir=/etc" in dockerfile
    assert "make install" in dockerfile
    # Upstream 1.25.2 generates its manpages during make via doc/filter.py.
    assert "python3" in dockerfile
    assert "pandoc" in dockerfile


def test_pgbouncer_final_runtime_is_slim_non_root_and_uses_exec_form() -> None:
    dockerfile = read(PGBOUNCER_DOCKERFILE)

    assert dockerfile.count("FROM ${DEBIAN_IMAGE}") == 2
    assert "COPY --from=build /usr/local/bin/pgbouncer /usr/local/bin/pgbouncer" in dockerfile
    assert "libevent-2.1-7" in dockerfile
    assert "libssl3" in dockerfile
    assert dockerfile.count("rm -rf /var/lib/apt/lists/*") == 2
    assert "adduser --system --uid 6433 --ingroup pgbouncer" in dockerfile
    assert "USER 6433:6433" in dockerfile
    assert "EXPOSE 6433" in dockerfile
    assert 'ENTRYPOINT ["/usr/local/bin/pgbouncer"]' in dockerfile
    assert 'CMD ["/etc/pgbouncer/pgbouncer.ini"]' in dockerfile
    assert not re.search(r"ENTRYPOINT\s+\[?\s*[\"'](?:sh|bash)", dockerfile)
