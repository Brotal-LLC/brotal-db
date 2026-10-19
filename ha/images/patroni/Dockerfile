# syntax=docker/dockerfile:1
# Historical adoption base; the production bundle uses deploy/compose.bundle.yaml.
ARG PGVECTOR_IMAGE=pgvector/pgvector:0.8.5-pg18@sha256:12a379b47ad65289572ea0756efc11b7c241a6662833e8af7038cd3b73d647e0
# The global ARG above pins both the release and digest.
# hadolint ignore=DL3006
FROM ${PGVECTOR_IMAGE}

USER 0

RUN apt-get update \
 && apt-get install --no-install-recommends -y \
      ca-certificates=20250419~deb12u1 \
      python3=3.11.2-1+b1 \
      python3-venv=3.11.2-1+b1 \
 && python3 -m venv /opt/patroni \
 && /opt/patroni/bin/pip install --no-cache-dir "patroni[etcd3,psycopg3]==4.1.4" \
 && rm -rf /var/lib/apt/lists/*

COPY --chown=postgres:postgres entrypoint.sh /usr/local/bin/patroni-entrypoint
COPY --chown=postgres:postgres existing-data-supervisor.py /usr/local/bin/patroni-existing-data-entrypoint
RUN chmod 0755 /usr/local/bin/patroni-entrypoint /usr/local/bin/patroni-existing-data-entrypoint

USER 999:999
ENTRYPOINT ["/usr/local/bin/patroni-entrypoint"]
CMD ["/etc/patroni/patroni.yml"]
