#!/bin/sh
set -eu

if [ "$(id -u)" -eq 0 ]; then
    printf '%s\n' 'patroni must not run as root' >&2
    exit 1
fi

load_secret() {
    variable=$1
    secret_file=$2
    secret_path="/run/secrets/$secret_file"

    if [ ! -r "$secret_path" ]; then
        printf '%s\n' "required secret is unreadable: $secret_path" >&2
        exit 1
    fi

    value=$(cat "$secret_path")
    if [ -z "$value" ]; then
        printf '%s\n' "required secret is empty: $secret_path" >&2
        exit 1
    fi

    export "$variable=$value"
}

load_secret PATRONI_SUPERUSER_USERNAME patroni_superuser_username
load_secret PATRONI_SUPERUSER_PASSWORD patroni_superuser_password
load_secret PATRONI_REPLICATION_USERNAME patroni_replication_username
load_secret PATRONI_REPLICATION_PASSWORD patroni_replication_password
load_secret PATRONI_REWIND_USERNAME patroni_rewind_username
load_secret PATRONI_REWIND_PASSWORD patroni_rewind_password
load_secret PATRONI_RESTAPI_USERNAME patroni_restapi_username
load_secret PATRONI_RESTAPI_PASSWORD patroni_restapi_password

exec "${PATRONI_EXECUTABLE:-/opt/patroni/bin/patroni}" "$@"
