#!/usr/bin/env bash
set -euo pipefail
umask 077

output=${1:-./secrets}
runtime_uid=${PATRONI_RUNTIME_UID:-999}
runtime_gid=${PATRONI_RUNTIME_GID:-999}
pgbouncer_uid=${PGBOUNCER_RUNTIME_UID:-6433}
pgbouncer_gid=${PGBOUNCER_RUNTIME_GID:-6433}
mkdir -p "$output"
chmod 0711 "$output"

declare -A usernames=(
  [patroni_superuser_username]=patroni_superuser
  [patroni_replication_username]=patroni_replication
  [patroni_rewind_username]=patroni_rewind
  [patroni_restapi_username]=patroni_api
)
secrets=(
  patroni_superuser_password
  patroni_replication_password
  patroni_rewind_password
  patroni_restapi_password
  pgbouncer_auth_password
  pgbouncer_admin_password
  pgbouncer_stats_password
)

for name in "${!usernames[@]}"; do
  path="$output/$name"
  if [[ -e $path ]]; then
    printf 'refusing to overwrite existing secret: %s\n' "$path" >&2
    exit 1
  fi
  printf '%s\n' "${usernames[$name]}" >"$path"
  chmod 0400 "$path"
  chown "$runtime_uid:$runtime_gid" "$path"
done

for name in "${secrets[@]}"; do
  path="$output/$name"
  if [[ -e $path ]]; then
    printf 'refusing to overwrite existing secret: %s\n' "$path" >&2
    exit 1
  fi
  openssl rand -base64 48 | tr -d '\n' >"$path"
  printf '\n' >>"$path"
  chmod 0400 "$path"
  chown "$runtime_uid:$runtime_gid" "$path"
done

userlist="$output/pgbouncer_userlist"
if [[ -e $userlist ]]; then
  printf 'refusing to overwrite existing secret: %s\n' "$userlist" >&2
  exit 1
fi
{
  printf '"pgbouncer_auth" "'
  tr -d '\n' <"$output/pgbouncer_auth_password"
  printf '"\n"pgbouncer_admin" "'
  tr -d '\n' <"$output/pgbouncer_admin_password"
  printf '"\n"pgbouncer_stats" "'
  tr -d '\n' <"$output/pgbouncer_stats_password"
  printf '"\n'
} >"$userlist"
chmod 0400 "$userlist"
chown "$pgbouncer_uid:$pgbouncer_gid" "$userlist"

count=$((${#secrets[@]} + ${#usernames[@]} + 1))
printf 'generated %d mode-0400 secret files under %s (values not displayed)\n' \
  "$count" "$output"
