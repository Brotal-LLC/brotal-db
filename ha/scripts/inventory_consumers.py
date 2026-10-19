"""Reconcile live pg_stat_activity groups with the reviewed migration inventory."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


class InventoryError(RuntimeError):
    """Raised when a live database/role pair has no reviewed migration owner."""


def _inventory_pairs(path: Path) -> set[tuple[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames or not {"database", "role", "wave", "status"} <= set(
            reader.fieldnames
        ):
            raise InventoryError(f"invalid inventory header: {path}")
        pairs: set[tuple[str, str]] = set()
        for row in reader:
            if not all(row.values()):
                raise InventoryError(f"inventory contains an empty operational field: {row}")
            pairs.add((row["database"], row["role"]))
    return pairs


def reconcile(activity_path: Path, inventory_path: Path) -> list[tuple[str, str]]:
    """Return live pairs, raising if any pair is not represented by inventory."""
    represented = _inventory_pairs(inventory_path)
    live: list[tuple[str, str]] = []
    missing: list[tuple[str, str]] = []
    with activity_path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            fields = line.rstrip("\n").split("|")
            if len(fields) != 4:
                raise InventoryError(f"invalid activity row {number}: expected four pipe fields")
            database, role, _address, count = fields
            int(count)
            pair = (database, role)
            live.append(pair)
            if pair not in represented and ("*", role) not in represented:
                missing.append(pair)
    if missing:
        rendered = ", ".join(f"{database}/{role}" for database, role in sorted(set(missing)))
        raise InventoryError(f"unowned live PostgreSQL consumers: {rendered}")
    return live


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("activity", type=Path)
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "artifacts/consumer-inventory.tsv",
    )
    args = parser.parse_args()
    pairs = reconcile(args.activity, args.inventory)
    print(f"consumer-inventory=complete live-pairs={len(pairs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
