# Defaults mirror versions.env; validation rejects drift and release builds inject versions.env values.
variable "POSTGRES_MAJOR" { default = "18" }
variable "POSTGRES_IMAGE" { default = "postgres:18.6-bookworm@sha256:1c59e2c3c818eaa0f0628f695b36e7c9e362d6b219b36a54a32df645cbd7e1af" }
variable "DEBIAN_BOOKWORM_IMAGE" { default = "debian:bookworm@sha256:6ebd97fa83deb272194a2cf015b3d26a4d538e9ad3a7a79d544c8af5b0a01443" }
variable "DEBIAN_BOOKWORM_SLIM_IMAGE" { default = "debian:bookworm-slim@sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171" }
variable "PGVECTOR_VERSION" { default = "0.8.6" }
variable "POSTGIS_VERSION" { default = "3.6.1" }
variable "PG_TEXTSEARCH_VERSION" { default = "1.4.0" }
variable "TIMESCALEDB_VERSION" { default = "2.29.2" }
variable "PATRONI_VERSION" { default = "4.1.5" }
variable "PSYCOPG_VERSION" { default = "3.3.4" }
variable "PGBOUNCER_VERSION" { default = "1.25.2" }
variable "PGVECTOR_SHA256" { default = "10bf9938906e5d643bbc4a7eea104b6f57ba4898e5b76b20e60484ea1d5a7f8f" }
variable "POSTGIS_SHA256" { default = "ec0cfaab475630106211d180d71df46782e41e10b6dffe91d79ca818ecd2cbb4" }
variable "PG_TEXTSEARCH_SHA256" { default = "cab02b4e8af11f98b428d17cca9c5235ab55e12d79c20fa8fbb950708c4a1e92" }
variable "TIMESCALEDB_SHA256" { default = "3817f8acb8e167bf22b873a4c4e17d801089ed5a34c232eedd4f86dc222c8dc6" }
variable "PGBOUNCER_SHA256" { default = "924ad35113fd0a71c8e2dbe85b5d03445532e2b7b37a9f8a48983beea238b332" }
group "default" { targets = ["postgres", "pgbouncer"] }
target "postgres" {
  context = "."
  dockerfile = "docker/postgres/Dockerfile"
  args = { POSTGRES_IMAGE=POSTGRES_IMAGE, PGVECTOR_VERSION=PGVECTOR_VERSION, POSTGIS_VERSION=POSTGIS_VERSION, PG_TEXTSEARCH_VERSION=PG_TEXTSEARCH_VERSION, TIMESCALEDB_VERSION=TIMESCALEDB_VERSION, PATRONI_VERSION=PATRONI_VERSION, PSYCOPG_VERSION=PSYCOPG_VERSION, PGVECTOR_SHA256=PGVECTOR_SHA256, POSTGIS_SHA256=POSTGIS_SHA256, PG_TEXTSEARCH_SHA256=PG_TEXTSEARCH_SHA256, TIMESCALEDB_SHA256=TIMESCALEDB_SHA256 }
  tags = ["brotal/postgres:${POSTGRES_MAJOR}-bundle", "brotal/postgres:candidate"]
}
target "pgbouncer" {
  context = "."
  dockerfile = "docker/pgbouncer/Dockerfile"
  args = { DEBIAN_BOOKWORM_IMAGE=DEBIAN_BOOKWORM_IMAGE, DEBIAN_BOOKWORM_SLIM_IMAGE=DEBIAN_BOOKWORM_SLIM_IMAGE, PGBOUNCER_VERSION=PGBOUNCER_VERSION, PGBOUNCER_SHA256=PGBOUNCER_SHA256 }
  tags = ["brotal/pgbouncer:${PGBOUNCER_VERSION}", "brotal/pgbouncer:candidate"]
}
