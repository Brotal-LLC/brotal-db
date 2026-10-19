#!/usr/bin/env python3
"""Record replica and retained-WAL health without changing cluster state."""

import argparse
import json
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen


def check(url):
    with urlopen(url + "/cluster", timeout=5) as response:
        cluster = json.load(response)
    members = cluster.get("members", [])
    problems = []
    if len([m for m in members if m["role"] == "leader"]) != 1:
        problems.append("Expected exactly one leader.")
    for name in ("armadillo", "rogue"):
        member = next((m for m in members if m["name"] == name), None)
        if not member or member.get("state") not in ("running", "streaming"):
            problems.append(name + " is not healthy/streaming.")
    query = """
    SELECT json_build_object('inRecovery',pg_is_in_recovery(),
      'slots',coalesce((SELECT json_agg(json_build_object(
        'slot',slot_name,'active',active,'walStatus',wal_status,
        'bytes',CASE WHEN pg_is_in_recovery() THEN NULL
          ELSE pg_wal_lsn_diff(pg_current_wal_lsn(),restart_lsn) END))
        FROM pg_replication_slots),'[]'),
      'replication',coalesce((SELECT json_agg(json_build_object(
        'name',application_name,'state',state,'syncState',sync_state,
        'lagBytes',CASE WHEN pg_is_in_recovery() THEN NULL
          ELSE pg_wal_lsn_diff(pg_current_wal_lsn(),flush_lsn) END))
        FROM pg_stat_replication),'[]'),
      'receivers',coalesce((SELECT json_agg(status) FROM pg_stat_wal_receiver),'[]'));
    """
    sql_state = json.loads(
        subprocess.check_output(
            [
                "docker",
                "exec",
                "-u",
                "postgres",
                "postgres",
                "psql",
                "-X",
                "-At",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                query,
            ],
            timeout=10,
        )
    )
    slots = sql_state["slots"]
    if sql_state["inRecovery"]:
        if sql_state["receivers"] != ["streaming"]:
            problems.append("Replica WAL receiver is disconnected or not streaming.")
    else:
        leader = next((m["name"] for m in members if m["role"] == "leader"), None)
        for name in {"armadillo", "rogue"} - {leader}:
            peer = next((p for p in sql_state["replication"] if p["name"] == name), None)
            if not peer or peer["state"] != "streaming":
                problems.append(name + " has no streaming replication connection.")
            elif peer["syncState"] not in ("sync", "quorum"):
                problems.append(name + " is not acknowledging synchronous WAL.")
            elif peer["lagBytes"] is None or peer["lagBytes"] > 64 * 1024**2:
                problems.append(name + " has excessive WAL flush lag.")
    for slot in slots:
        if slot["walStatus"] == "lost" or (slot["bytes"] or 0) > 8 * 1024**3:
            problems.append("WAL retention needs attention: " + slot["slot"])
    return {
        "checkedAt": int(time.time()),
        "members": members,
        "slots": slots,
        "inRecovery": sql_state["inRecovery"],
        "replication": sql_state["replication"],
        "receivers": sql_state["receivers"],
        "healthy": not problems,
        "problems": problems,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patroni-url", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        result = check(args.patroni_url)
    except (OSError, ValueError, subprocess.SubprocessError):
        result = {
            "checkedAt": int(time.time()),
            "healthy": False,
            "problems": ["Cluster/SQL health probe failed."],
        }
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n")
    temporary.replace(path)
    print(json.dumps(result))
    raise SystemExit(0 if result["healthy"] else 1)
