#!/usr/bin/env python3
"""Safely migrate .NET connection strings without exposing credentials."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
from pathlib import Path


def _items(connection_string: str) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for raw_item in connection_string.split(";"):
        item = raw_item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"invalid bare connection-string field: {item!r}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError("empty connection-string key")
        items.append((key, value.strip()))
    return items


def parse_connection_string(connection_string: str) -> dict[str, str]:
    """Parse a semicolon-delimited .NET connection string by normalized key."""
    parsed: dict[str, str] = {}
    for key, value in _items(connection_string):
        normalized = key.casefold()
        if normalized in parsed:
            raise ValueError(f"duplicate connection-string key: {key}")
        parsed[normalized] = value
    return parsed


def update_connection_endpoint(connection_string: str, host: str, port: int) -> str:
    """Change only Host/Server and Port while preserving every other field."""
    if not host or not 1 <= port <= 65535:
        raise ValueError("invalid target endpoint")
    items = _items(connection_string)
    host_found = False
    port_found = False
    updated: list[tuple[str, str]] = []
    for key, value in items:
        normalized = key.casefold()
        if normalized in {"host", "server"}:
            if host_found:
                raise ValueError("multiple host/server fields")
            updated.append((key, host))
            host_found = True
        elif normalized == "port":
            if port_found:
                raise ValueError("multiple port fields")
            updated.append((key, str(port)))
            port_found = True
        else:
            updated.append((key, value))
    if not host_found:
        raise ValueError("connection string has no Host/Server field")
    if not port_found:
        updated.append(("Port", str(port)))
    return ";".join(f"{key}={value}" for key, value in updated)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def externalize_compose_environment_key(
    compose_text: str,
    *,
    service: str,
    key: str,
    env_path: str,
) -> str:
    """Remove one possibly wrapped YAML environment scalar and add raw env_file."""
    lines = compose_text.splitlines(keepends=True)
    services_index = next(
        (index for index, line in enumerate(lines) if line.strip() == "services:"), None
    )
    if services_index is None:
        raise ValueError("Compose services mapping not found")
    service_indent = _indent(lines[services_index]) + 2
    service_index = next(
        (
            index
            for index in range(services_index + 1, len(lines))
            if _indent(lines[index]) == service_indent and lines[index].strip() == f"{service}:"
        ),
        None,
    )
    if service_index is None:
        raise ValueError(f"Compose service not found: {service}")
    service_end = next(
        (
            index
            for index in range(service_index + 1, len(lines))
            if lines[index].strip()
            and not lines[index].lstrip().startswith("#")
            and _indent(lines[index]) <= service_indent
        ),
        len(lines),
    )
    child_indent = service_indent + 2
    environment_index = next(
        (
            index
            for index in range(service_index + 1, service_end)
            if _indent(lines[index]) == child_indent and lines[index].strip() == "environment:"
        ),
        None,
    )
    if environment_index is None:
        raise ValueError(f"environment mapping not found for {service}")
    environment_end = next(
        (
            index
            for index in range(environment_index + 1, service_end)
            if lines[index].strip()
            and not lines[index].lstrip().startswith("#")
            and _indent(lines[index]) <= child_indent
        ),
        service_end,
    )
    key_indent = child_indent + 2
    key_index = next(
        (
            index
            for index in range(environment_index + 1, environment_end)
            if _indent(lines[index]) == key_indent and lines[index].lstrip().startswith(f"{key}:")
        ),
        None,
    )
    if key_index is None:
        raise ValueError(f"environment key not found: {key}")
    key_end = next(
        (
            index
            for index in range(key_index + 1, environment_end)
            if lines[index].strip() and _indent(lines[index]) <= key_indent
        ),
        environment_end,
    )
    del lines[key_index:key_end]

    current = "".join(lines)
    if key in current:
        raise ValueError(f"environment key still present after extraction: {key}")

    service_end -= key_end - key_index
    existing_env_file = next(
        (
            index
            for index in range(service_index + 1, service_end)
            if _indent(lines[index]) == child_indent and lines[index].strip() == "env_file:"
        ),
        None,
    )
    if existing_env_file is not None:
        raise ValueError("existing env_file requires explicit merge")
    insertion = (
        " " * child_indent
        + "env_file:\n"
        + " " * (child_indent + 2)
        + f"- path: {env_path}\n"
        + " " * (child_indent + 4)
        + "format: raw\n"
    )
    lines[environment_index:environment_index] = [insertion]
    return "".join(lines)


def _runtime_value(container: str, key: str) -> str:
    inspected = subprocess.run(
        ["docker", "inspect", container],
        check=True,
        text=True,
        capture_output=True,
    )
    data = json.loads(inspected.stdout)[0]
    prefix = key + "="
    values = [
        item[len(prefix) :] for item in data["Config"].get("Env", []) if item.startswith(prefix)
    ]
    if len(values) != 1:
        raise ValueError(f"expected one runtime {key}, found {len(values)}")
    return values[0]


def _backup(path: Path) -> Path:
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.pre-ha8-{stamp}")
    shutil.copy2(path, backup)
    return backup


def _write_env_value(path: Path, key: str, value: str) -> Path | None:
    backup = _backup(path) if path.exists() else None
    lines = path.read_text().splitlines(keepends=True) if path.exists() else []
    matches = [index for index, line in enumerate(lines) if line.startswith(key + "=")]
    if len(matches) > 1:
        raise ValueError(f"duplicate {key} in {path}")
    ending = "\n"
    replacement = f"{key}={value}{ending}"
    if matches:
        lines[matches[0]] = replacement
    else:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(replacement)
    path.write_text("".join(lines))
    os.chmod(path, 0o600)
    return backup


def _migrate_compose(args: argparse.Namespace) -> None:
    compose = Path(args.compose)
    env_file = compose.parent / args.env_file
    runtime = _runtime_value(args.container, args.key)
    updated_value = update_connection_endpoint(runtime, args.host, args.port)
    fields = parse_connection_string(updated_value)
    required = {"host", "database", "username", "password", "include error detail", "port"}
    if not required <= fields.keys():
        missing = sorted(required - fields.keys())
        raise ValueError(f"required fields missing after update: {missing}")
    compose_backup = _backup(compose)
    env_backup = _write_env_value(env_file, args.key, updated_value)
    updated_compose = externalize_compose_environment_key(
        compose.read_text(), service=args.service, key=args.key, env_path=args.env_file
    )
    compose.write_text(updated_compose)
    print(
        f"migration=pass endpoint={fields['host']}:{fields['port']}/{fields['database']} "
        f"compose_backup={compose_backup} env_backup={env_backup or 'none'} env_mode=0o600"
    )


def _migrate_env(args: argparse.Namespace) -> None:
    env_file = Path(args.env)
    runtime = _runtime_value(args.container, args.key)
    updated_value = update_connection_endpoint(runtime, args.host, args.port)
    fields = parse_connection_string(updated_value)
    backup = _write_env_value(env_file, args.key, updated_value)
    print(
        f"migration=pass endpoint={fields['host']}:{fields['port']}/{fields['database']} "
        f"env_backup={backup or 'none'} env_mode=0o600"
    )


def _probe_runtime(args: argparse.Namespace) -> None:
    runtime = _runtime_value(args.container, args.key)
    fields = parse_connection_string(runtime)
    host = args.host or fields.get("host") or fields.get("server")
    port = args.port or int(fields.get("port", "5432"))
    database = fields.get("database")
    user = fields.get("username") or fields.get("user id") or fields.get("user")
    password = fields.get("password")
    if host is None or database is None or user is None or password is None:
        raise ValueError("runtime connection string is missing probe fields")
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-e",
            f"PGPASSWORD={password}",
            args.postgres_container,
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-h",
            host,
            "-p",
            str(port),
            "-U",
            user,
            "-d",
            database,
            "-Atqc",
            "select current_database(),current_user,pg_is_in_recovery()",
        ],
        text=True,
        capture_output=True,
    )
    if result.returncode:
        print(result.stderr.strip())
        raise SystemExit(result.returncode)
    print(f"probe=pass endpoint={host}:{port}/{database} result={result.stdout.strip()}")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)
    compose_parser = subparsers.add_parser("migrate-compose")
    compose_parser.add_argument("--compose", required=True)
    compose_parser.add_argument("--service", required=True)
    compose_parser.add_argument("--container", required=True)
    compose_parser.add_argument("--key", required=True)
    compose_parser.add_argument("--env-file", required=True)
    compose_parser.add_argument("--host", required=True)
    compose_parser.add_argument("--port", required=True, type=int)
    compose_parser.set_defaults(handler=_migrate_compose)
    env_parser = subparsers.add_parser("migrate-env")
    env_parser.add_argument("--env", required=True)
    env_parser.add_argument("--container", required=True)
    env_parser.add_argument("--key", required=True)
    env_parser.add_argument("--host", required=True)
    env_parser.add_argument("--port", required=True, type=int)
    env_parser.set_defaults(handler=_migrate_env)
    probe_parser = subparsers.add_parser("probe-runtime")
    probe_parser.add_argument("--container", required=True)
    probe_parser.add_argument("--key", required=True)
    probe_parser.add_argument("--postgres-container", default="postgres")
    probe_parser.add_argument("--host")
    probe_parser.add_argument("--port", type=int)
    probe_parser.set_defaults(handler=_probe_runtime)
    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
