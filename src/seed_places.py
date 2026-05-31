"""
GRA — Place Authority CSV Seeder
Loads a place_authority CSV directly into the foundational layer.
Designed for two use cases:
  1. Importing a CSV produced by fetch_places.py (logainm-fetched data)
  2. Importing manually-authored entries for entities not in logainm
     (e.g. church parishes, historically-named features)

CLI usage:
    python -m src.db seed-places --file PATH [--db PATH]

CSV schema: matches place_authority table columns exactly.
Required columns: place_id, name_en, place_type
All other columns are optional.

Operation is idempotent: rows whose logainm_id is already present are
skipped. Rows without a logainm_id (manually-added) are inserted on every
call unless place_id already exists — use with care for manual entries.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.fetch_places import (
    VALID_PLACE_TYPES, CSV_FIELDNAMES,
    load_from_csv, write_to_db, PlaceRow,
)


def seed_places(
    conn: sqlite3.Connection,
    csv_path: str,
) -> dict:
    """
    Load place_authority rows from CSV and insert into the database.
    Returns a summary dict.
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: '{csv_path}'")

    try:
        rows = load_from_csv(csv_path)
    except ValueError as e:
        return {"ok": False, "errors": [str(e)], "inserted": 0, "skipped": 0}

    if not rows:
        return {"ok": True, "errors": [], "inserted": 0, "skipped": 0, "rows_in_csv": 0}

    inserted, skipped = write_to_db(conn, rows)
    return {
        "ok": True,
        "errors": [],
        "rows_in_csv": len(rows),
        "inserted": inserted,
        "skipped": skipped,
    }


def print_seed_places_report(result: dict) -> None:
    if not result["ok"]:
        print("\n  SEED-PLACES FAILED:")
        for e in result["errors"]:
            print(f"    {e}")
        return

    print(f"\n  PLACE AUTHORITY SEEDING")
    print(f"    Rows in CSV:      {result.get('rows_in_csv', 0):>6}")
    print(f"    Inserted:         {result['inserted']:>6}")
    skipped = result['skipped']
    if skipped:
        print(f"    Already present:  {skipped:>6}  (idempotent skip)")
