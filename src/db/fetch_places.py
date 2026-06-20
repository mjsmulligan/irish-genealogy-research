"""
GRA — Logainm Place Authority Fetcher
Fetches place data from the logainm.ie API and writes directly to the
place_authority table in the GRA database.

Can also export to CSV for inspection or manual editing before DB import.

CLI usage:
    # Fetch and write directly to DB
    python -m src.cli fetch-places --logainm-id 111482 --db genealogy.db

    # Fetch and export to CSV only (no DB write)
    python -m src.cli fetch-places --logainm-id 111482 --csv output.csv

    # Fetch, export CSV, and write to DB
    python -m src.cli fetch-places --logainm-id 111482 --db genealogy.db --csv output.csv

The logainm ID is the numeric ID from the logainm.ie URL, e.g.:
    https://www.logainm.ie/en/111482  →  111482 (Tullynaught DED)

API rate limiting: 0.05s delay between townland detail requests.
Requires LOGAINM_API_KEY environment variable or --api-key argument.
"""

from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, field

import requests

BASE_URL = "https://www.logainm.ie/api/v1.1/"

# ---------------------------------------------------------------------------
# API type string → GRA place_type controlled vocabulary
# ---------------------------------------------------------------------------

_API_TYPE_MAP: dict[str, str] = {
    "electoral division":   "ded",
    "townland":             "townland",
    "civil parish":         "civil_parish",
    "barony":               "barony",
    "county":               "county",
    "province":             "province",
    "town":                 "town",
    "village":              "town",
}

VALID_PLACE_TYPES = {
    "province", "county", "barony", "civil_parish",
    "ded", "townland", "church_parish", "town",
}

CSV_FIELDNAMES = [
    "place_id", "logainm_id", "name_en", "place_type",
    "parent_name", "parent_id", "parent_type",
    "ded_name", "ded_id",
    "county_name", "county_id",
    "barony_name", "barony_id",
    "civil_parish_name", "civil_parish_id",
    "latitude", "longitude",
    "logainm_url", "notes",
]


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class PlaceRow:
    place_id:          int
    logainm_id:        int
    name_en:           str
    place_type:        str
    parent_name:       str
    parent_id:         int | None
    parent_type:       str
    ded_name:          str
    ded_id:            int | None
    county_name:       str
    county_id:         int | None
    barony_name:       str
    barony_id:         int | None
    civil_parish_name: str
    civil_parish_id:   int | None
    latitude:          float | None
    longitude:         float | None
    logainm_url:       str
    notes:             str = ""

    def as_csv_row(self) -> dict:
        return {
            "place_id":          self.place_id,
            "logainm_id":        self.logainm_id,
            "name_en":           self.name_en,
            "place_type":        self.place_type,
            "parent_name":       self.parent_name,
            "parent_id":         self.parent_id or "",
            "parent_type":       self.parent_type,
            "ded_name":          self.ded_name,
            "ded_id":            self.ded_id or "",
            "county_name":       self.county_name,
            "county_id":         self.county_id or "",
            "barony_name":       self.barony_name,
            "barony_id":         self.barony_id or "",
            "civil_parish_name": self.civil_parish_name,
            "civil_parish_id":   self.civil_parish_id or "",
            "latitude":          "" if self.latitude is None else self.latitude,
            "longitude":         "" if self.longitude is None else self.longitude,
            "logainm_url":       self.logainm_url,
            "notes":             self.notes,
        }

    def as_db_tuple(self) -> tuple:
        return (
            self.place_id, self.logainm_id, self.name_en, self.place_type,
            self.parent_name or None, self.parent_id, self.parent_type or None,
            self.ded_name or None, self.ded_id,
            self.county_name or None, self.county_id,
            self.barony_name or None, self.barony_id,
            self.civil_parish_name or None, self.civil_parish_id,
            self.latitude, self.longitude,
            self.logainm_url or None, self.notes or None,
        )


@dataclass
class FetchResult:
    rows: list[PlaceRow] = field(default_factory=list)
    inserted: int = 0
    skipped: int = 0          # already in DB (idempotent)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# API helpers (adapted from getplaces.py)
# ---------------------------------------------------------------------------

def _safe_get(data: dict, key: str, default=None):
    if not isinstance(data, dict):
        return default
    for k, v in data.items():
        if k.lower() == key.lower():
            return v
    return default


def _get_name_en(place_data: dict) -> str:
    name = _safe_get(place_data, "nameEN") or _safe_get(place_data, "defaultName") or ""
    if not name:
        for pn in _safe_get(place_data, "placenames", []):
            if _safe_get(pn, "language", "") == "en":
                name = _safe_get(pn, "wording", "") or ""
                if name:
                    break
        if not name:
            placenames = _safe_get(place_data, "placenames", [])
            if placenames:
                name = _safe_get(placenames[0], "wording", "") or ""
    return name.strip()


def _get_place_type(place_data: dict) -> str:
    categories = _safe_get(place_data, "categories", [])
    if categories and isinstance(categories, list):
        raw = _safe_get(categories[0], "nameEN", "").lower().strip()
        return _API_TYPE_MAP.get(raw, raw)
    return "townland"


def _get_geography(place_data: dict) -> tuple[float | None, float | None]:
    geo = _safe_get(place_data, "geography", {})
    coords = _safe_get(geo, "coordinates", [])
    if isinstance(coords, list) and coords:
        coords = coords[0]
    lat = _safe_get(coords, "latitude")
    lon = _safe_get(coords, "longitude")
    try:
        return float(lat) if lat else None, float(lon) if lon else None
    except (TypeError, ValueError):
        return None, None


def _get_relationships(place_data: dict) -> dict:
    result = {
        "county_name": "", "county_id": None,
        "barony_name": "", "barony_id": None,
        "civil_parish_name": "", "civil_parish_id": None,
        "ded_name": "", "ded_id": None,
    }
    for item in _safe_get(place_data, "includedIn", []):
        category = _safe_get(item, "category", {})
        cat_id = str(_safe_get(category, "id", "")).upper()
        cat_name = _safe_get(category, "nameEN", "").lower()
        item_id_raw = _safe_get(item, "id")
        try:
            item_id = int(item_id_raw) if item_id_raw else None
        except (TypeError, ValueError):
            item_id = None
        item_name = _get_name_en(item)

        if cat_id == "CON" or cat_name == "county":
            result["county_name"], result["county_id"] = item_name, item_id
        elif cat_id == "BAR" or cat_name == "barony":
            result["barony_name"], result["barony_id"] = item_name, item_id
        elif cat_id == "PAR" or cat_name == "civil parish":
            result["civil_parish_name"], result["civil_parish_id"] = item_name, item_id
        elif cat_id in ("TR", "ED") or cat_name == "electoral division":
            result["ded_name"], result["ded_id"] = item_name, item_id
    return result


def _get_place_details(session: requests.Session, logainm_id: int) -> dict:
    url = f"{BASE_URL}{logainm_id}"
    response = session.get(url)
    response.raise_for_status()
    return response.json()


def _get_child_townlands(session: requests.Session, parent_id: int) -> list[dict]:
    """Fetch all child townlands, handling pagination via API count field."""
    params = {"PlaceID": parent_id, "CategoryID": "BF", "Page": 1}
    townlands = []
    while True:
        response = session.get(BASE_URL, params=params)
        response.raise_for_status()
        data = response.json()
        results = _safe_get(data, "results", []) or []
        if not results:
            break
        townlands.extend(results)
        # Use API-reported total count if available; fall back to page-size heuristic
        total = _safe_get(data, "count") or _safe_get(data, "total")
        if total is not None:
            try:
                if len(townlands) >= int(total):
                    break
            except (TypeError, ValueError):
                pass
        # Heuristic: if we got fewer results than a full page, we are done.
        # logainm API default page size is 1000.
        if len(results) < 1000:
            break
        params["Page"] += 1
    return townlands


# ---------------------------------------------------------------------------
# Core fetch
# ---------------------------------------------------------------------------

def fetch_places(
    logainm_id: int,
    api_key: str,
    rate_delay: float = 0.05,
) -> FetchResult:
    """
    Fetch a parent place and all its child townlands from the logainm API.
    Returns a FetchResult containing PlaceRow objects ready for DB insert or CSV write.
    """
    result = FetchResult()

    with requests.Session() as session:
        session.headers.update({
            "Accept": "application/json",
            "X-Api-Key": api_key,
        })

        # Fetch parent
        print(f"  Fetching parent place {logainm_id}...")
        parent_data = _get_place_details(session, logainm_id)
        parent_name = _get_name_en(parent_data)
        parent_type = _get_place_type(parent_data)
        parent_lat, parent_lon = _get_geography(parent_data)
        parent_rels = _get_relationships(parent_data)

        parent_row = PlaceRow(
            place_id=1,
            logainm_id=logainm_id,
            name_en=parent_name,
            place_type=parent_type,
            parent_name="",     # root entity — no parent
            parent_id=None,
            parent_type="",
            ded_name=parent_rels["ded_name"],
            ded_id=parent_rels["ded_id"],
            county_name=parent_rels["county_name"],
            county_id=parent_rels["county_id"],
            barony_name=parent_rels["barony_name"],
            barony_id=parent_rels["barony_id"],
            civil_parish_name=parent_rels["civil_parish_name"],
            civil_parish_id=parent_rels["civil_parish_id"],
            latitude=parent_lat,
            longitude=parent_lon,
            logainm_url=f"https://www.logainm.ie/en/{logainm_id}",
        )
        result.rows.append(parent_row)

        # Fetch child townlands
        print(f"  Fetching child townlands for '{parent_name}'...")
        summaries = _get_child_townlands(session, logainm_id)
        total = len(summaries)
        print(f"  Found {total} townlands. Fetching details...")

        for idx, summary in enumerate(summaries, start=1):
            t_id_raw = _safe_get(summary, "id")
            try:
                t_id = int(t_id_raw)
            except (TypeError, ValueError):
                result.errors.append(f"  Skipped townland with unparseable id: {t_id_raw}")
                continue

            print(f"  {idx}/{total} (logainm_id={t_id})...", end="\r")
            try:
                t_data = _get_place_details(session, t_id)
            except Exception as e:
                result.errors.append(f"  Failed to fetch logainm_id={t_id}: {e}")
                continue

            t_name = _get_name_en(t_data)
            t_lat, t_lon = _get_geography(t_data)
            t_rels = _get_relationships(t_data)

            # If this is a DED fetch, the parent IS the DED — populate ded fields
            # from the parent if the townland doesn't have it from includedIn
            ded_name = t_rels["ded_name"] or (parent_name if parent_type == "ded" else "")
            ded_id   = t_rels["ded_id"]   or (logainm_id  if parent_type == "ded" else None)

            result.rows.append(PlaceRow(
                place_id=idx + 1,       # place_id assigned sequentially; overridden on DB insert
                logainm_id=t_id,
                name_en=t_name,
                place_type="townland",
                parent_name=parent_name,
                parent_id=logainm_id,
                parent_type=parent_type,
                ded_name=ded_name,
                ded_id=ded_id,
                county_name=t_rels["county_name"],
                county_id=t_rels["county_id"],
                barony_name=t_rels["barony_name"],
                barony_id=t_rels["barony_id"],
                civil_parish_name=t_rels["civil_parish_name"],
                civil_parish_id=t_rels["civil_parish_id"],
                latitude=t_lat,
                longitude=t_lon,
                logainm_url=f"https://www.logainm.ie/en/{t_id}",
            ))
            time.sleep(rate_delay)

        print()  # newline after progress
    return result


# ---------------------------------------------------------------------------
# CSV import (for loading existing CSV files)
# ---------------------------------------------------------------------------

def _coerce_int(val: str) -> int | None:
    v = str(val).strip() if val else ""
    return int(v) if v else None


def _coerce_float(val: str) -> float | None:
    v = str(val).strip() if val else ""
    try:
        return float(v) if v else None
    except ValueError:
        return None


def load_from_csv(csv_path: str) -> list[PlaceRow]:
    """
    Load PlaceRow objects from a CSV file matching the GRA place_authority schema.
    Used for importing previously-exported files and manually-edited CSVs
    (e.g. church parishes added by the researcher).
    """
    rows = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for i, raw in enumerate(csv.DictReader(f), start=2):
            place_id_raw = raw.get("place_id", "").strip()
            try:
                place_id = int(place_id_raw)
            except ValueError:
                raise ValueError(f"Row {i}: place_id '{place_id_raw}' is not an integer")

            name_en = raw.get("name_en", "").strip()
            if not name_en:
                raise ValueError(f"Row {i}: name_en is required")

            place_type = raw.get("place_type", "").strip()
            # Map API-style strings to controlled vocab
            place_type = _API_TYPE_MAP.get(place_type.lower(), place_type)
            if place_type not in VALID_PLACE_TYPES:
                raise ValueError(
                    f"Row {i}: place_type '{place_type}' not valid. "
                    f"Must be one of: {', '.join(sorted(VALID_PLACE_TYPES))}"
                )

            rows.append(PlaceRow(
                place_id=place_id,
                logainm_id=_coerce_int(raw.get("logainm_id", "")),
                name_en=name_en,
                place_type=place_type,
                parent_name=raw.get("parent_name", "").strip(),
                parent_id=_coerce_int(raw.get("parent_id", "")),
                parent_type=raw.get("parent_type", "").strip(),
                ded_name=raw.get("ded_name", "").strip(),
                ded_id=_coerce_int(raw.get("ded_id", "")),
                county_name=raw.get("county_name", "").strip(),
                county_id=_coerce_int(raw.get("county_id", "")),
                barony_name=raw.get("barony_name", "").strip(),
                barony_id=_coerce_int(raw.get("barony_id", "")),
                civil_parish_name=raw.get("civil_parish_name", "").strip(),
                civil_parish_id=_coerce_int(raw.get("civil_parish_id", "")),
                latitude=_coerce_float(raw.get("latitude", "")),
                longitude=_coerce_float(raw.get("longitude", "")),
                logainm_url=raw.get("logainm_url", "").strip(),
                notes=raw.get("notes", "").strip(),
            ))
    return rows


# ---------------------------------------------------------------------------
# DB write
# ---------------------------------------------------------------------------

def write_to_db(
    conn,  # psycopg2.extensions.connection
    rows: list[PlaceRow],
) -> tuple[int, int]:
    """
    Insert PlaceRow objects into place_authority. Uses INSERT ON CONFLICT DO NOTHING
    for idempotency — rows with a logainm_id already in the table are skipped.

    place_id values are reassigned at insert time to avoid collisions with
    existing rows; the logainm_id is the stable external identifier.

    Returns (inserted_count, skipped_count).
    """
    inserted = 0
    skipped = 0

    with conn.cursor() as cur:
        # Idempotency sets:
        # - logainm_id for authority-backed rows
        # - (name_en_lower, place_type) for manually-added rows (no logainm_id)
        cur.execute("SELECT logainm_id FROM place_authority WHERE logainm_id IS NOT NULL")
        existing_logainm_ids: set[int] = {row['logainm_id'] for row in cur.fetchall()}

        cur.execute("SELECT name_en, place_type FROM place_authority WHERE logainm_id IS NULL")
        existing_manual: set[tuple] = {(row['name_en'].lower(), row['place_type']) for row in cur.fetchall()}

        for row in rows:
            if row.logainm_id and row.logainm_id in existing_logainm_ids:
                skipped += 1
                continue
            if not row.logainm_id and (row.name_en.lower(), row.place_type) in existing_manual:
                skipped += 1
                continue

            # PostgreSQL will auto-generate place_id
            db_row = PlaceRow(
                place_id=0,  # Will be auto-generated by PostgreSQL
                logainm_id=row.logainm_id,
                name_en=row.name_en,
                place_type=row.place_type,
                parent_name=row.parent_name,
                parent_id=row.parent_id,
                parent_type=row.parent_type,
                ded_name=row.ded_name,
                ded_id=row.ded_id,
                county_name=row.county_name,
                county_id=row.county_id,
                barony_name=row.barony_name,
                barony_id=row.barony_id,
                civil_parish_name=row.civil_parish_name,
                civil_parish_id=row.civil_parish_id,
                latitude=row.latitude,
                longitude=row.longitude,
                logainm_url=row.logainm_url,
                notes=row.notes,
            )
            # In PostgreSQL, place_id is auto-generated, so we skip it
            cur.execute(
                """
                INSERT INTO place_authority
                    (logainm_id, name_en, place_type,
                     parent_name, parent_id, parent_type,
                     ded_name, ded_id,
                     county_name, county_id,
                     barony_name, barony_id,
                     civil_parish_name, civil_parish_id,
                     latitude, longitude,
                     logainm_url, notes)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                db_row.as_db_tuple()[1:],  # Skip place_id
            )
            if row.logainm_id:
                existing_logainm_ids.add(row.logainm_id)
            else:
                existing_manual.add((row.name_en.lower(), row.place_type))
            inserted += 1

    conn.commit()
    return inserted, skipped


def write_to_csv(rows: list[PlaceRow], csv_path: str) -> None:
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        w.writeheader()
        for row in rows:
            w.writerow(row.as_csv_row())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m src.cli fetch-places",
        description="Fetch place authority data from logainm.ie and load into GRA database.",
    )
    parser.add_argument(
        "--logainm-id", required=False, type=int, default=None,
        help="Numeric logainm.ie place ID (e.g. 111482 for Tullynaught DED). Required unless --from-csv is used.",
    )
    parser.add_argument(
        "--db", default=None,
        help="Path to GRA database. If provided, fetched rows are written to place_authority.",
    )
    parser.add_argument(
        "--csv", default=None,
        help="Path to export CSV file. If provided, fetched rows are written to CSV.",
    )
    parser.add_argument(
        "--from-csv", default=None,
        help="Load from an existing CSV file instead of calling the API. "
             "Use with --db to import a previously-exported or manually-edited file.",
    )
    parser.add_argument(
        "--api-key", default=None,
        help="Logainm API key. Falls back to LOGAINM_API_KEY environment variable.",
    )
    parser.add_argument(
        "--rate-delay", type=float, default=0.05,
        help="Seconds to wait between API requests (default: 0.05).",
    )
    args = parser.parse_args()

    if not args.db and not args.csv:
        parser.error("At least one of --db or --csv is required.")
    if not args.from_csv and args.logainm_id is None:
        parser.error("--logainm-id is required when not using --from-csv.")

    # Load rows
    if args.from_csv:
        print(f"Loading from CSV: {args.from_csv}")
        rows = load_from_csv(args.from_csv)
        print(f"  Loaded {len(rows)} rows.")
        errors = []
    else:
        api_key = args.api_key or os.environ.get("LOGAINM_API_KEY")
        if not api_key:
            print(
                "Error: No API key provided. Use --api-key or set LOGAINM_API_KEY "
                "environment variable.",
                file=sys.stderr,
            )
            sys.exit(1)

        print(f"Fetching logainm ID {args.logainm_id}...")
        result = fetch_places(args.logainm_id, api_key, args.rate_delay)
        rows = result.rows
        errors = result.errors
        print(f"  Fetched {len(rows)} rows ({len(errors)} errors).")
        if errors:
            for e in errors:
                print(f"  WARNING: {e}")

    # Write CSV
    if args.csv:
        write_to_csv(rows, args.csv)
        print(f"  CSV written to: {args.csv}")

    # Write DB
    if args.db:
        from src.db.db import open_db, check_version
        conn = open_db(args.db)
        check_version(conn)
        inserted, skipped = write_to_db(conn, rows)
        print(f"  DB: {inserted} inserted, {skipped} skipped (already present).")


if __name__ == "__main__":
    main()
