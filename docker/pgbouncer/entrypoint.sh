#!/bin/sh
set -eu
mode="${PGBOUNCER_POOL_MODE:-session}"
case "$mode" in session|transaction|statement) ;; *) echo 'PGBOUNCER_POOL_MODE must be session, transaction, or statement' >&2; exit 64;; esac
if [ ! -r /run/secrets/pgbouncer_users ] || [ ! -s /run/secrets/pgbouncer_users ]; then
  echo 'missing or empty /run/secrets/pgbouncer_users' >&2
  exit 1
fi
install -o pgbouncer -g pgbouncer -m 600 /run/secrets/pgbouncer_users /run/pgbouncer/userlist.txt
sed -i "s/^pool_mode = .*/pool_mode = $mode/; s#^auth_file = .*#auth_file = /run/pgbouncer/userlist.txt#" /etc/pgbouncer/pgbouncer.ini
exec setpriv --reuid pgbouncer --regid "$(id -g pgbouncer)" --init-groups -- /usr/sbin/pgbouncer /etc/pgbouncer/pgbouncer.ini
