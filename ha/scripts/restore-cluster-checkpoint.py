#!/usr/bin/env python3
"""Restore a checkpoint into a fresh, isolated named volume; receive role SQL on stdin."""

import argparse
import hashlib
import json
import secrets
import subprocess
import sys
import time
from pathlib import Path


def restore(root, image, name):
    if not name.startswith("lagbenaki-restore-"):
        raise ValueError("Use a task-owned disposable container name.")
    root = Path(root).resolve()
    receipt = json.loads((root / "checkpoint.json").read_text())
    for filename, expected in receipt["files"].items():
        value = hashlib.sha256()
        with (root / filename).open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                value.update(block)
        if value.hexdigest() != expected["sha256"]:
            raise ValueError("Checkpoint checksum mismatch.")
    if "recovery-metadata.json" not in receipt["files"]:
        raise ValueError("Checkpoint must include verified database and role metadata.")
    metadata = json.loads((root / "recovery-metadata.json").read_text())
    if set(metadata["databases"]) != set(receipt["databases"]):
        raise ValueError("Checkpoint must contain every source database.")
    # Consume the private pipe before any docker exec -i child can inherit it.
    roles = sys.stdin.buffer.read()
    if b"ALTER ROLE" not in roles or b"PASSWORD" not in roles:
        raise ValueError("Decrypt the credential-recovery artifact into stdin first.")
    for kind in ("container", "volume"):
        if subprocess.run(["docker", kind, "inspect", name], capture_output=True).returncode == 0:
            raise ValueError("Disposable names must be unused; never reset existing data.")
    subprocess.run(
        ["docker", "volume", "create", "--label", "purpose=lagbenaki-restore", name],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--network",
            "none",
            "--memory",
            "8g",
            "--shm-size",
            "1g",
            "--cpus",
            "2",
            "--user",
            "999:999",
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            "-e",
            "POSTGRES_PASSWORD=" + secrets.token_urlsafe(32),
            "-v",
            name + ":/var/lib/postgresql",
            "-v",
            str(root) + ":/backup:ro",
            "--entrypoint",
            "/usr/local/bin/docker-entrypoint.sh",
            image,
            "postgres",
            "-c",
            "shared_preload_libraries=pg_textsearch",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    prefix = ["docker", "exec", "-i", "--user", "0", name]
    for _ in range(120):
        if (
            subprocess.run(
                prefix + ["pg_isready", "-U", "postgres"], capture_output=True
            ).returncode
            == 0
        ):
            break
        time.sleep(1)
    # The disposable cluster already has postgres; retain its ALTER ROLE and verifier.
    roles = b"\n".join(
        line
        for line in roles.splitlines()
        if line not in (b"CREATE ROLE postgres;", b'CREATE ROLE "postgres";')
    )
    subprocess.run(
        prefix + ["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", "postgres"],
        input=roles,
        check=True,
    )
    del roles
    credential_query = (
        "SELECT encode(sha256(convert_to(string_agg(rolname || E'\\t' || "
        "coalesce(rolpassword,''), E'\\n' ORDER BY rolname COLLATE \"C\"),"
        "'UTF8')),'hex') FROM pg_authid WHERE rolname !~ '^pg_';"
    )
    fingerprint = (
        subprocess.check_output(
            prefix + ["psql", "-X", "-At", "-U", "postgres", "-c", credential_query]
        )
        .decode()
        .strip()
    )
    if fingerprint != metadata["credentialFingerprint"]:
        raise ValueError("Recovered role credentials do not match the source cluster.")
    counts, extensions = {}, {}
    for database, info in receipt["databases"].items():
        properties = metadata["databases"][database]
        if database == "postgres":
            # Only the uniquely named, network-isolated rehearsal cluster.
            subprocess.run(
                prefix + ["dropdb", "-U", "postgres", "--maintenance-db=template1", database],
                check=True,
            )
        subprocess.run(
            prefix
            + [
                "createdb",
                "-U",
                "postgres",
                "--maintenance-db=template1",
                "--template=template0",
                "--owner=" + properties["owner"],
                "--encoding=" + properties["encoding"],
                "--lc-collate=" + properties["collation"],
                "--lc-ctype=" + properties["ctype"],
                database,
            ],
            check=True,
        )
        subprocess.run(
            prefix
            + [
                "pg_restore",
                "--exit-on-error",
                "--jobs=2",
                "-U",
                "postgres",
                "-d",
                database,
                "/backup/" + info["file"],
            ],
            check=True,
        )
        query = "SELECT count(*) FROM pg_class WHERE relkind IN ('r','p');"
        counts[database] = int(
            subprocess.check_output(
                prefix + ["psql", "-X", "-At", "-U", "postgres", "-d", database, "-c", query]
            ).decode()
        )
        extensions[database] = (
            subprocess.check_output(
                prefix
                + [
                    "psql",
                    "-X",
                    "-At",
                    "-U",
                    "postgres",
                    "-d",
                    database,
                    "-c",
                    "SELECT extname || '=' || extversion FROM pg_extension ORDER BY extname",
                ]
            )
            .decode()
            .splitlines()
        )
        if {v.split("=")[0] for v in extensions[database]} != {
            v.split("=")[0] for v in info["extensions"]
        }:
            raise ValueError("Restored extension inventory differs from the checkpoint.")
        print("restored:", database, flush=True)
    subprocess.run(
        prefix + ["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", "template1"],
        input=metadata["databasePropertiesSql"].encode(),
        check=True,
    )
    result = {
        "restoredDatabases": len(counts),
        "tables": counts,
        "extensions": extensions,
        "image": image,
        "container": name,
        "volume": name,
        "network": "none",
        "credentialRecoveryRestored": True,
        "credentialFingerprintVerified": True,
        "restoreVerified": True,
    }
    (root / "restore-verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    restore(args.checkpoint, args.image, args.name)
