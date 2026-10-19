\set ON_ERROR_STOP on

\if :{?pgbouncer_auth_password}
\else
  \echo 'pgbouncer_auth_password is required' >&2
  \quit 3
\endif

SELECT format(
  'CREATE ROLE pgbouncer_auth LOGIN NOSUPERUSER NOINHERIT NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS PASSWORD %L',
  :'pgbouncer_auth_password'
)
WHERE NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'pgbouncer_auth')
\gexec
ALTER ROLE pgbouncer_auth LOGIN NOSUPERUSER NOINHERIT NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS
  PASSWORD :'pgbouncer_auth_password';

CREATE SCHEMA IF NOT EXISTS pgbouncer AUTHORIZATION postgres;
ALTER SCHEMA pgbouncer OWNER TO postgres;
REVOKE ALL ON SCHEMA pgbouncer FROM PUBLIC;

CREATE OR REPLACE FUNCTION pgbouncer.get_auth(p_username text)
RETURNS TABLE(username text, password text)
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
  SELECT rolname::text, rolpassword::text
  FROM pg_authid
  WHERE rolname = p_username
    AND rolcanlogin;
$$;
ALTER FUNCTION pgbouncer.get_auth(text) OWNER TO postgres;
REVOKE ALL ON FUNCTION pgbouncer.get_auth(text) FROM PUBLIC;
GRANT USAGE ON SCHEMA pgbouncer TO pgbouncer_auth;
GRANT EXECUTE ON FUNCTION pgbouncer.get_auth(text) TO pgbouncer_auth;
REVOKE ALL ON TABLE pg_authid FROM pgbouncer_auth;
