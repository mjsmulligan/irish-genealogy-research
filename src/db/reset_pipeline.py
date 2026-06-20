"""
DEPRECATED (v3.1) — superseded by:
    python -m src.cli clear-evidence
    python -m src.cli clear-conclusions
Retained for reference only. Do not use against a Postgres/Supabase database.
---
GRA — Reconstruction Reset
Clears all reconstruction-layer outputs from the database, leaving:
  - place_authority  (logainm seed data)
  - repository, source  (seed data)
  - record, recorded_person  (ingested evidence)
  - name_variant  (derived from evidence; cheap to regenerate)

Deleted tables (reconstruction outputs):
  - person, person_name
  - relationship, relationship_record
  - event, event_record, person_event
  - person_record
  - place_record

Use this to iterate on household_inference.py and linkage.py without
re-running the stable ingest and place-seeding steps.

CLI usage:
    python reset_pipeline.py [--db PATH] [--dry-run]

Defaults to genealogy.db in the current directory.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


DEFAULT_DB = "genealogy.db"

# Deletion order respects FK constraints:
# junction tables before their parent conclusion tables.
_DELETE_STEPS = [
    # Linkage junctions
    ("place_record",        "place → record linkages"),
    ("person_record",       "person → record linkages"),
    ("event_record",        "event → record linkages"),
    ("relationship_record", "relationship → record linkages"),
    ("person_event",        "person → event linkages"),
    # Conclusion tables
    ("person_name",         "person name entries"),
    ("relationship",        "relationship conclusions"),
    ("event",               "event conclusions"),
    ("person",              "person conclusions"),
    # name_variant is evidence-derived; included so Splink feature
    # extraction always starts from a clean slate.
    ("name_variant",        "name variant index"),
]

_KEEP = [
    "repository",
    "source",
    "place_authority",
    "record",
    "recorded_person",
]


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def reset_reconstruction(db_path: str, dry_run: bool = False) -> None:
    path = Path(db_path)
    if not path.exists():
        print(f"Error: database not found at '{db_path}'", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    print()
    print("=" * 60)
    print("  GRA — Reconstruction Reset")
    print(f"  Database: {db_path}")
    if dry_run:
        print("  Mode: DRY RUN (no changes written)")
    print("=" * 60)

    print("\n  TABLES TO CLEAR:")
    totals: dict[str, int] = {}
    for table, label in _DELETE_STEPS:
        n = _count(conn, table)
        totals[table] = n
        flag = "  (empty)" if n == 0 else ""
        print(f"    {label:<40} {n:>7} rows{flag}")

    print("\n  TABLES TO PRESERVE:")
    for table in _KEEP:
        n = _count(conn, table)
        print(f"    {table:<40} {n:>7} rows")

    if dry_run:
        print("\n  Dry run complete — no rows deleted.")
        conn.close()
        return

    print()
    confirm = input("  Proceed? This cannot be undone. [y/N] ").strip().lower()
    if confirm != "y":
        print("  Aborted.")
        conn.close()
        return

    with conn:
        for table, label in _DELETE_STEPS:
            conn.execute(f"DELETE FROM {table}")
            print(f"  Cleared {totals[table]:>7} rows from {table}")

    # Verify keeps are intact
    print("\n  Verifying preserved tables...")
    all_ok = True
    for table in _KEEP:
        n = _count(conn, table)
        expected = _count(conn, table)  # recount post-delete
        status = "OK" if n > 0 else "WARN (empty)"
        print(f"    {table:<30} {n:>7} rows  [{status}]")
        if n == 0 and table in ("record", "recorded_person", "place_authority"):
            all_ok = False

    conn.close()

    print()
    if all_ok:
        print("  Reset complete. Ready for reconstruction:")
        print("    python -m src.db reconstruct")
        print("    python -m src.db link")
    else:
        print("  Reset complete with warnings — check preserved tables above.")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python reset_reconstruction.py",
        description="Clear GRA reconstruction outputs, preserving evidence and place authority.",
    )
    parser.add_argument(
        "--db", default=DEFAULT_DB,
        help=f"Database path (default: {DEFAULT_DB})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be deleted without making any changes.",
    )
    args = parser.parse_args()
    reset_reconstruction(args.db, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
