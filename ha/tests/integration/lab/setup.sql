\set ON_ERROR_STOP on

\if :{?pgbouncer_auth_password}
\else
  \echo 'pgbouncer_auth_password is required' >&2
  \quit 3
\endif
\if :{?app_password}
\else
  \echo 'app_password is required' >&2
  \quit 3
\endif

CREATE ROLE postgres SUPERUSER NOLOGIN;
\ir /lab/sql/001-pgbouncer-auth.sql
CREATE ROLE lab_app LOGIN PASSWORD :'app_password';
CREATE TABLE lab_markers(id integer PRIMARY KEY, note text NOT NULL);
GRANT SELECT, INSERT ON lab_markers TO lab_app;
GRANT UPDATE(note) ON lab_markers TO lab_app;
