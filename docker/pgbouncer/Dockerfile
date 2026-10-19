ARG DEBIAN_BOOKWORM_IMAGE=debian:bookworm@sha256:6ebd97fa83deb272194a2cf015b3d26a4d538e9ad3a7a79d544c8af5b0a01443
ARG DEBIAN_BOOKWORM_SLIM_IMAGE=debian:bookworm-slim@sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171
FROM ${DEBIAN_BOOKWORM_IMAGE} AS build
ARG PGBOUNCER_VERSION=1.25.2 PGBOUNCER_SHA256=924ad35113fd0a71c8e2dbe85b5d03445532e2b7b37a9f8a48983beea238b332
RUN apt-get update && apt-get install -y --no-install-recommends build-essential ca-certificates libevent-dev libssl-dev libpq-dev pkg-config wget tar python3 pandoc && rm -rf /var/lib/apt/lists/*
WORKDIR /tmp
RUN wget -q -O pgbouncer.tar.gz https://www.pgbouncer.org/downloads/files/${PGBOUNCER_VERSION}/pgbouncer-${PGBOUNCER_VERSION}.tar.gz && echo "${PGBOUNCER_SHA256}  pgbouncer.tar.gz" | sha256sum -c - && tar -xzf pgbouncer.tar.gz && cd pgbouncer-${PGBOUNCER_VERSION} && ./configure --prefix=/usr && make -j"$(nproc)" && make DESTDIR=/out install
FROM ${DEBIAN_BOOKWORM_SLIM_IMAGE}
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends libevent-2.1-7 libpq5 libssl3 ca-certificates util-linux netcat-openbsd && rm -rf /var/lib/apt/lists/* && useradd --system --home-dir /var/lib/pgbouncer pgbouncer && mkdir -p /var/run/pgbouncer /etc/pgbouncer /run/pgbouncer && chown -R pgbouncer:pgbouncer /var/run/pgbouncer /etc/pgbouncer /run/pgbouncer
COPY --from=build /out/usr/bin/pgbouncer /usr/sbin/pgbouncer
COPY --chmod=0755 docker/pgbouncer/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY --chmod=0644 docker/pgbouncer/pgbouncer.ini /etc/pgbouncer/pgbouncer.ini
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
