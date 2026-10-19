\set ON_ERROR_STOP on

\if :{?patroni_superuser_password}
\else
  \echo 'patroni_superuser_password is required' >&2
  \quit 3
\endif
\if :{?patroni_replication_password}
\else
  \echo 'patroni_replication_password is required' >&2
  \quit 3
\endif
\if :{?patroni_rewind_password}
\else
  \echo 'patroni_rewind_password is required' >&2
  \quit 3
\endif

SELECT format(
  'CREATE ROLE patroni_superuser LOGIN SUPERUSER PASSWORD %L',
  :'patroni_superuser_password'
)
WHERE NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'patroni_superuser')
\gexec
ALTER ROLE patroni_superuser LOGIN SUPERUSER INHERIT CREATEROLE CREATEDB REPLICATION BYPASSRLS
  PASSWORD :'patroni_superuser_password';

SELECT format(
  'CREATE ROLE patroni_replication LOGIN REPLICATION PASSWORD %L',
  :'patroni_replication_password'
)
WHERE NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'patroni_replication')
\gexec
ALTER ROLE patroni_replication LOGIN NOSUPERUSER INHERIT NOCREATEROLE NOCREATEDB REPLICATION NOBYPASSRLS
  PASSWORD :'patroni_replication_password';

SELECT format(
  'CREATE ROLE patroni_rewind LOGIN NOSUPERUSER NOREPLICATION PASSWORD %L',
  :'patroni_rewind_password'
)
WHERE NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'patroni_rewind')
\gexec
ALTER ROLE patroni_rewind LOGIN NOSUPERUSER INHERIT NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS
  PASSWORD :'patroni_rewind_password';

GRANT EXECUTE ON FUNCTION pg_catalog.pg_ls_dir(text, boolean, boolean) TO patroni_rewind;
GRANT EXECUTE ON FUNCTION pg_catalog.pg_stat_file(text, boolean) TO patroni_rewind;
GRANT EXECUTE ON FUNCTION pg_catalog.pg_read_binary_file(text) TO patroni_rewind;
GRANT EXECUTE ON FUNCTION pg_catalog.pg_read_binary_file(text, bigint, bigint, boolean) TO patroni_rewind;
