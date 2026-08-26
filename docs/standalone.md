# Standalone

Run `make secrets standalone-up`; connect on localhost:5432. Set `POSTGRES_EXTENSIONS` to the allowlisted comma-separated extensions before first initialization. Restart is required after changing preload libraries. Persist the named volume and use archive/restore tooling for backups. The final amd64 PostgreSQL and PgBouncer images build locally. Fresh initialization of all eight requested extensions, the SQL smoke suite, and a PostgreSQL container restart have passed; CI additionally gates arm64 and release security metadata.
