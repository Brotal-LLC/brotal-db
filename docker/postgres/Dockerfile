ARG POSTGRES_IMAGE=postgres:18.6-bookworm@sha256:1c59e2c3c818eaa0f0628f695b36e7c9e362d6b219b36a54a32df645cbd7e1af
FROM ${POSTGRES_IMAGE} AS builder
ARG PGVECTOR_VERSION=0.8.6 POSTGIS_VERSION=3.6.1 PG_TEXTSEARCH_VERSION=1.4.0 TIMESCALEDB_VERSION=2.29.2
ARG PGVECTOR_SHA256=10bf9938906e5d643bbc4a7eea104b6f57ba4898e5b76b20e60484ea1d5a7f8f POSTGIS_SHA256=ec0cfaab475630106211d180d71df46782e41e10b6dffe91d79ca818ecd2cbb4 PG_TEXTSEARCH_SHA256=cab02b4e8af11f98b428d17cca9c5235ab55e12d79c20fa8fbb950708c4a1e92 TIMESCALEDB_SHA256=3817f8acb8e167bf22b873a4c4e17d801089ed5a34c232eedd4f86dc222c8dc6
RUN apt-get update && apt-get install -y --no-install-recommends build-essential postgresql-server-dev-18 patch ca-certificates pkg-config cmake ninja-build libgeos-dev libproj-dev libprotobuf-c-dev libxml2-dev libjson-c-dev libgdal-dev libicu-dev libpcre2-dev libcurl4-openssl-dev libssl-dev libtool autoconf automake flex bison gettext protobuf-c-compiler liblz4-dev libzstd-dev python3-dev python3-pip wget curl tar && rm -rf /var/lib/apt/lists/*
WORKDIR /tmp/src
RUN set -eux; for spec in "pgvector ${PGVECTOR_VERSION} ${PGVECTOR_SHA256} https://github.com/pgvector/pgvector/archive/refs/tags/v${PGVECTOR_VERSION}.tar.gz" "pg_textsearch ${PG_TEXTSEARCH_VERSION} ${PG_TEXTSEARCH_SHA256} https://github.com/timescale/pg_textsearch/archive/refs/tags/v${PG_TEXTSEARCH_VERSION}.tar.gz" "timescaledb ${TIMESCALEDB_VERSION} ${TIMESCALEDB_SHA256} https://github.com/timescale/timescaledb/archive/refs/tags/${TIMESCALEDB_VERSION}.tar.gz"; do set -- $spec; wget -q -O /tmp/$1.tar.gz $4; echo "$3  /tmp/$1.tar.gz" | sha256sum -c -; mkdir -p $1; tar -xzf /tmp/$1.tar.gz --strip-components=1 -C $1; done
RUN wget -q -O /tmp/postgis.tar.gz https://download.osgeo.org/postgis/source/postgis-${POSTGIS_VERSION}.tar.gz && echo "${POSTGIS_SHA256}  /tmp/postgis.tar.gz" | sha256sum -c - && mkdir postgis && tar -xzf /tmp/postgis.tar.gz --strip-components=1 -C postgis
RUN cd pgvector && make -j"$(nproc)" && make DESTDIR=/opt/install install
COPY patches/postgis-3.6.1-pg18-raster.patch /tmp/postgis-3.6.1-pg18-raster.patch
RUN cd postgis && patch -p1 < /tmp/postgis-3.6.1-pg18-raster.patch && ./autogen.sh && ./configure --with-raster --with-topology --without-address-standardizer --without-sfcgal && make -j"$(nproc)" && make DESTDIR=/opt/install install
RUN cd pg_textsearch && make -j"$(nproc)" && make DESTDIR=/opt/install install
RUN cd timescaledb && ./bootstrap -DAPACHE_ONLY=ON -DSEND_TELEMETRY_DEFAULT=OFF -DUSE_TELEMETRY=OFF -DREGRESS_CHECKS=OFF && cd build && make -j"$(nproc)" && make DESTDIR=/opt/install install
FROM ${POSTGRES_IMAGE} AS runtime
ARG PATRONI_VERSION=4.1.5
ARG PSYCOPG_VERSION=3.3.4
ENV PGDATA=/var/lib/postgresql/18/data PATH=/usr/lib/postgresql/18/bin:$PATH PYTHONDONTWRITEBYTECODE=1
COPY --from=builder /opt/install/ /
COPY --chmod=0644 docker/postgres/requirements.lock /tmp/requirements.lock
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip curl libgeos-c1t64 libproj25 libgdal39 libprotobuf-c1 libjson-c5 libicu72 libpcre2-8-0 libcurl4 liblz4-1 libzstd1 util-linux && rm -f /usr/local/bin/gosu && sed -i 's|exec gosu postgres "\$BASH_SOURCE" "\$@"|exec setpriv --reuid postgres --regid "$(id -g postgres)" --init-groups -- "\$BASH_SOURCE" "\$@"|' /usr/local/bin/docker-entrypoint.sh && grep -q "^patroni==${PATRONI_VERSION} " /tmp/requirements.lock && grep -q "^psycopg==${PSYCOPG_VERSION} " /tmp/requirements.lock && pip3 install --no-cache-dir --break-system-packages --require-hashes -r /tmp/requirements.lock && rm -f /tmp/requirements.lock && rm -rf /var/lib/apt/lists/*
COPY --chmod=0755 docker/postgres/entrypoint.sh /usr/local/bin/brotal-entrypoint.sh
COPY --chmod=0755 docker/postgres/post_bootstrap.sh /usr/local/bin/post_bootstrap.sh
COPY --chmod=0755 docker/postgres/init-extensions.sh /docker-entrypoint-initdb.d/10-extensions.sh
COPY --chmod=0755 docker/postgres/render-patroni.sh /usr/local/bin/render-patroni.sh
COPY --chmod=0644 docker/postgres/patroni.yml /usr/share/doc/brotal/patroni.example.yml
COPY THIRD_PARTY_NOTICES /usr/share/doc/brotal/THIRD_PARTY_NOTICES
RUN mkdir -p /etc/patroni /var/lib/postgresql/18/data && chown -R postgres:postgres /etc/patroni /var/lib/postgresql && chmod 0700 /var/lib/postgresql/18/data
ENTRYPOINT ["/usr/local/bin/brotal-entrypoint.sh"]
CMD ["postgres"]
