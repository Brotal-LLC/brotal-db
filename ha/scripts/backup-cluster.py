#!/usr/bin/env python3
"""Create a new, private logical checkpoint with encrypted credential recovery."""

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path


def capture(container, *args):
    return subprocess.check_output(["docker", "exec", "-u", "postgres", container, *args])


def recovery_metadata(container):
    def sql(query):
        return capture(container, "psql", "-X", "-At", "-c", query).decode().strip()

    fingerprint = sql(
        "SELECT encode(sha256(convert_to(string_agg(rolname || E'\\t' || "
        "coalesce(rolpassword,''), E'\\n' ORDER BY rolname COLLATE \"C\"),"
        "'UTF8')),'hex') FROM pg_authid WHERE rolname !~ '^pg_';"
    )
    properties = sql("""
        SELECT string_agg(command, E'\n') FROM (
          SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC;',datname) command
            FROM pg_database WHERE NOT datistemplate
          UNION ALL
          SELECT format('GRANT %s ON DATABASE %I TO %s%s;',a.privilege_type,d.datname,
            CASE WHEN a.grantee=0 THEN 'PUBLIC'
              ELSE quote_ident(pg_get_userbyid(a.grantee)) END,
            CASE WHEN a.is_grantable THEN ' WITH GRANT OPTION' ELSE '' END)
            FROM pg_database d CROSS JOIN LATERAL
              aclexplode(coalesce(d.datacl,acldefault('d',d.datdba))) a
            WHERE NOT d.datistemplate
          UNION ALL
          SELECT format('ALTER DATABASE %I CONNECTION LIMIT %s;',datname,datconnlimit)
            FROM pg_database WHERE NOT datistemplate
          UNION ALL
          SELECT CASE WHEN s.setrole=0
            THEN format('DO %L; ALTER DATABASE %I SET %I FROM CURRENT;',
              format('BEGIN PERFORM pg_catalog.set_config(%L,%L,false); END',
                split_part(v,'=',1),substr(v,strpos(v,'=')+1)),
              d.datname,split_part(v,'=',1))
            ELSE format('DO %L; ALTER ROLE %I IN DATABASE %I SET %I FROM CURRENT;',
              format('BEGIN PERFORM pg_catalog.set_config(%L,%L,false); END',
                split_part(v,'=',1),substr(v,strpos(v,'=')+1)),
              pg_get_userbyid(s.setrole),d.datname,split_part(v,'=',1)) END
            FROM pg_db_role_setting s JOIN pg_database d ON d.oid=s.setdatabase
              CROSS JOIN LATERAL unnest(s.setconfig) v WHERE NOT d.datistemplate
        ) commands
    """)
    databases = json.loads(
        sql(
            "SELECT json_object_agg(datname,json_build_object('owner',"
            "pg_get_userbyid(datdba),'encoding',pg_encoding_to_char(encoding),"
            "'collation',datcollate,'ctype',datctype)) FROM pg_database "
            "WHERE NOT datistemplate"
        )
    )
    return {
        "credentialFingerprint": fingerprint,
        "databases": databases,
        "databasePropertiesSql": properties,
    }


def backup(destination, recipient, container, resume=False):
    os.umask(0o077)
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=resume)
    databases = (
        capture(
            container,
            "psql",
            "-X",
            "-At",
            "-c",
            "SELECT datname FROM pg_database WHERE NOT datistemplate "
            "ORDER BY pg_database_size(oid), datname",
        )
        .decode()
        .splitlines()
    )
    progress_path = root / "checkpoint-progress.json"
    identifier = (
        capture(
            container,
            "psql",
            "-X",
            "-At",
            "-c",
            "SELECT system_identifier FROM pg_control_system()",
        )
        .decode()
        .strip()
    )
    if resume:
        progress = json.loads(progress_path.read_text())
        if progress["systemIdentifier"] != identifier or set(progress["databaseNames"]) != set(
            databases
        ):
            raise ValueError("Resume requires the same cluster and database inventory.")
    else:
        secret = capture(container, "pg_dumpall", "--globals-only")
        subprocess.run(
            [
                "openssl",
                "cms",
                "-encrypt",
                "-aes256",
                "-binary",
                "-outform",
                "DER",
                "-out",
                str(root / "roles.cms"),
                recipient,
            ],
            input=secret,
            check=True,
        )
        del secret
        (root / "globals.sql").write_bytes(
            capture(container, "pg_dumpall", "--globals-only", "--no-role-passwords")
        )
        progress = {"systemIdentifier": identifier, "databaseNames": databases, "databases": {}}
        progress_path.write_text(json.dumps(progress, indent=2) + "\n")
    databases = progress["databaseNames"]
    catalog = progress["databases"]
    for index, name in enumerate(databases):
        filename = f"{index:03d}.dump"
        if name in catalog:
            if not (root / filename).is_file():
                raise ValueError("A completed checkpoint file is missing.")
            continue
        partial = root / (filename + ".partial")
        for attempt in range(3):
            try:
                with partial.open("wb") as stream:
                    subprocess.run(
                        [
                            "docker",
                            "exec",
                            "-u",
                            "postgres",
                            container,
                            "pg_dump",
                            "-Fc",
                            "--compress=zstd:level=1",
                            "--lock-wait-timeout=30s",
                            "--dbname",
                            name,
                        ],
                        stdout=stream,
                        check=True,
                    )
                partial.replace(root / filename)
                break
            except subprocess.CalledProcessError:
                if partial.exists():
                    partial.rename(root / (filename + f".failed-{time.time_ns()}"))
                if attempt == 2:
                    raise
                print(f"retrying {name} after interrupted checkpoint", flush=True)
                time.sleep(20)
        subprocess.run(
            ["docker", "exec", "-i", container, "pg_restore", "--list"],
            stdin=(root / filename).open("rb"),
            stdout=subprocess.DEVNULL,
            check=True,
        )
        extensions = (
            capture(
                container,
                "psql",
                "-X",
                "-At",
                "-d",
                name,
                "-c",
                "SELECT extname || '=' || extversion FROM pg_extension ORDER BY extname",
            )
            .decode()
            .splitlines()
        )
        catalog[name] = {"file": filename, "extensions": extensions}
        progress_path.write_text(json.dumps(progress, indent=2) + "\n")
        print(f"checkpoint {index + 1}/{len(databases)}: {name}", flush=True)
    metadata = recovery_metadata(container)
    metadata["systemIdentifier"] = identifier
    (root / "recovery-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    checksums = {}
    paths = [
        root / "roles.cms",
        root / "globals.sql",
        root / "recovery-metadata.json",
        *[root / v["file"] for v in catalog.values()],
    ]
    for path in sorted(paths):
        value = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                value.update(block)
        checksums[path.name] = {"sha256": value.hexdigest(), "bytes": path.stat().st_size}
    result = {
        "systemIdentifier": identifier,
        "databases": catalog,
        "files": checksums,
        "restoreVerified": False,
    }
    (root / "checkpoint.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--recipient", required=True)
    parser.add_argument("--container", default="postgres")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    backup(args.destination, args.recipient, args.container, args.resume)
