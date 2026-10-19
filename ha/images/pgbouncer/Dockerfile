# syntax=docker/dockerfile:1
# Resolved from docker buildx imagetools inspect debian:bookworm-slim on 2026-08-12.
ARG DEBIAN_IMAGE=debian:bookworm-slim@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241
ARG PGBOUNCER_VERSION=1.25.2
ARG PGBOUNCER_SHA256=924ad35113fd0a71c8e2dbe85b5d03445532e2b7b37a9f8a48983beea238b332
ARG PGBOUNCER_URL=https://www.pgbouncer.org/downloads/files/${PGBOUNCER_VERSION}/pgbouncer-${PGBOUNCER_VERSION}.tar.gz

# The global ARG above pins both the release and digest.
# hadolint ignore=DL3006
FROM ${DEBIAN_IMAGE} AS build
ARG PGBOUNCER_VERSION
ARG PGBOUNCER_SHA256
ARG PGBOUNCER_URL

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
 && apt-get install --no-install-recommends -y \
      build-essential=12.9 \
      ca-certificates=20250419~deb12u1 \
      curl=7.88.1-10+deb12u15 \
      libevent-dev=2.1.12-stable-8 \
      libssl-dev=3.0.20-1~deb12u2 \
      pandoc=2.17.1.1-2~deb12u1 \
      pkg-config=1.8.1-1 \
      python3=3.11.2-1+b1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src
RUN curl --fail --location --retry 3 --retry-all-errors --silent --show-error \
      --output pgbouncer.tar.gz "$PGBOUNCER_URL" \
 && printf '%s  %s\n' "$PGBOUNCER_SHA256" pgbouncer.tar.gz | sha256sum --check --strict - \
 && tar --extract --gzip --file pgbouncer.tar.gz

WORKDIR /usr/src/pgbouncer-${PGBOUNCER_VERSION}
RUN ./configure --prefix=/usr/local --sysconfdir=/etc \
 && make -j"$(nproc)" \
 && make install

# hadolint ignore=DL3006
FROM ${DEBIAN_IMAGE}

RUN apt-get update \
 && apt-get install --no-install-recommends -y \
      ca-certificates=20250419~deb12u1 \
      libevent-2.1-7=2.1.12-stable-8 \
      libssl3=3.0.20-1~deb12u2 \
 && rm -rf /var/lib/apt/lists/* \
 && addgroup --system --gid 6433 pgbouncer \
 && adduser --system --uid 6433 --ingroup pgbouncer --home /var/lib/pgbouncer --no-create-home pgbouncer \
 && install --directory --owner=pgbouncer --group=pgbouncer --mode=0750 \
      /var/lib/pgbouncer /var/run/pgbouncer

COPY --from=build /usr/local/bin/pgbouncer /usr/local/bin/pgbouncer

USER 6433:6433
EXPOSE 6433
ENTRYPOINT ["/usr/local/bin/pgbouncer"]
CMD ["/etc/pgbouncer/pgbouncer.ini"]
