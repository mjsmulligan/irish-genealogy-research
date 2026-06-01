"""
GRA — Genealogy Research Assistant
Database layer: connection management, schema initialisation, ingest, summary.

CLI usage:
    python -m src.db init [--db PATH]
    python -m src.db ingest --source SOURCE_ID --file CSV_PATH [--db PATH]
    python -m src.db seed-places --file CSV_PATH [--db PATH]
    python -m src.db summary [--db PATH]
    python -m src.db reconstruct --source SOURCE_ID [--db PATH]

Default database path: genealogy.db
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.reconstruction.linkage import run_census_linkage
from src.reconstruction.linkage import print_census_linkage_report

SCHEMA_VERSION = 27
DEFAULT_DB = "genealogy.db"
SCHEMA_SQL = Path(__file__).parent / "db" / "schema.sql"
SEED_SQL = Path(__file__).parent / "db" / "seed.sql"

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


def open_db(path: str = DEFAULT_DB) -> sqlite3.Connection:
    """Open a connection with required PRAGMAs set."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    return conn


def init_db(path: str = DEFAULT_DB) -> sqlite3.Connection:
    """Initialise a fresh database: create schema then insert seed data."""
    if Path(path).exists():
        raise FileExistsError(
            f"Database already exists at '{path}'. "
            "Delete it manually before reinitialising."
        )
    conn = open_db(path)
    conn.executescript(SCHEMA_SQL.read_text())
    conn.executescript(SEED_SQL.read_text())
    conn.commit()
    print(f"Initialised database at '{path}' (schema v{SCHEMA_VERSION // 10}.{SCHEMA_VERSION % 10}).")
    return conn


def check_version(conn: sqlite3.Connection) -> None:
    """Raise if the database schema version does not match the expected version."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version != SCHEMA_VERSION:
        raise RuntimeError(
            f"Schema version mismatch: expected {SCHEMA_VERSION}, got {version}. "
            "Run migrations before using this database."
        )


# ---------------------------------------------------------------------------
# URL builder
# ---------------------------------------------------------------------------


def build_record_url(source: dict, record: dict) -> str | None:
    """
    Construct a deep link URL for a Record by merging source_parameters
    (Source-level constants) with record_parameters (Record-level values)
    and substituting into the record_url_template.

    Returns None if the source has no record_url_template.
    Raises ValueError if any placeholder remains unresolved after the merge.
    """
    template = source.get("record_url_template")
    if not template:
        return None

    params: dict[str, Any] = {}

    raw_sp = source.get("source_parameters")
    if raw_sp:
        sp = json.loads(raw_sp) if isinstance(raw_sp, str) else raw_sp
        if sp:
            params.update(sp)

    raw_rp = record.get("record_parameters")
    if raw_rp:
        rp = json.loads(raw_rp) if isinstance(raw_rp, str) else raw_rp
        if rp:
            params.update(rp)

    try:
        return template.format(**params)
    except KeyError as e:
        raise ValueError(
            f"Unresolved placeholder {e} in URL template '{template}' "
            f"after merging source_parameters and record_parameters."
        ) from e


# ---------------------------------------------------------------------------
# Census ingest (Sources 3, 4, 5)
# ---------------------------------------------------------------------------

_CENSUS_ROLE_MAP: dict[str, str] = {
    "Head of Family": "head",
    "Wife":           "spouse",
    "Son":            "son",
    "Daughter":       "daughter",
    "Brother":        "sibling",
    "Sister":         "sibling",
    "Grand Son":      "grandchild",
    "Grand Daughter": "grandchild",
    "Son in Law":     "in_law",
    "Daughter in Law":"in_law",
    "Mother in Law":  "in_law",
    "Father in Law":  "in_law",
    "Brother In Law": "in_law",
    "Sister In Law":  "in_law",
    "Niece in Law":   "in_law",
    "Niece":          "niece_nephew",
    "Nephew":         "niece_nephew",
    "Nice":           "niece_nephew",
    "Aunt":           "aunt_uncle",
    "Uncle":          "aunt_uncle",
    "Cousin":         "cousin",
    "Mother":         "mother",
    "Father":         "father",
    "Servant":        "servant",
    "Visitor":        "visitor",
    "Boarder":        "boarder",
    "Lodger":         "boarder",
}

_SEX_MAP = {"M": "male", "F": "female", "m": "male", "f": "female"}

_CENSUS_DATES: dict[int, str] = {
    3: "1901-03-31",
    4: "1911-04-02",
    5: "1926-04-18",
}


def _extract_document_id(images_str: str) -> str | None:
    """
    Extract the first Form A image ID from the NAI images field.
    """
    if not images_str:
        return None
    try:
        images = ast.literal_eval(images_str)
        if images and isinstance(images, list):
            url = images[0].get("url", "")
            stem = Path(url.split("?")[0]).stem
            return stem if stem else None
    except (ValueError, SyntaxError):
        return None
    return None


def _get_document_id(person: dict) -> str | None:
    doc_id = None
    if person.get("images"):
        doc_id = _extract_document_id(person.get("images", ""))
    if not doc_id:
        doc_id = person.get("aform_name")
    return doc_id


def _normalize_census_1926_row(row: dict) -> dict:
    return {
        "id": row.get("aform_name", ""),
        "census_year": "1926",
        "county": row.get("county", ""),
        "surname": row.get("surname", ""),
        "firstname": row.get("first_name", ""),
        "townland": row.get("townland", ""),
        "townland_clean": row.get("townland", ""),
        "ded": row.get("ded", ""),
        "age": row.get("updated_age", ""),
        "sex": row.get("updated_sex", ""),
        "house_number": "",
        "relation_to_head": row.get("relationship_to_head", ""),
        "religion": "",
        "education": "",
        "occupation": "",
        "marriage_status": row.get("updated_marriage", ""),
        "marriage_years": row.get("years_married", ""),
        "children_born": row.get("children_born_alive", ""),
        "children_living": row.get("children_living", ""),
        "birthplace": row.get("birthplace_county", ""),
        "language": row.get("irish_or_english", ""),
        "deafdumb": "",
        "image_group": row.get("image_group", ""),
        "religion_updated": row.get("updated_religion", ""),
        "occupation_updated": "",
        "relation_to_head_updated": row.get("updated_relationship_to_head", ""),
        "language_updated": row.get("updated_irish_language", ""),
        "images": "",
        "aform_name": row.get("aform_name", ""),
        "geocode": row.get("geocode", ""),
        "institution_name": row.get("institution_name", ""),
        "institution_type": row.get("institution_type", ""),
        "a_id": row.get("a_id", ""),
        "ded_clean": row.get("ded", ""),
    }


def _map_role(relation: str) -> tuple[str, str | None]:
    role = _CENSUS_ROLE_MAP.get(relation)
    if role:
        return role, None
    if not relation.strip():
        return "principal", "blank relation_to_head; mapped to principal"
    return "principal", f"unmapped relation '{relation}'; mapped to principal"


def ingest_census(
    conn: sqlite3.Connection,
    csv_path: str,
    source_id: int = 4,
) -> dict:
    """
    Ingest a census NAI download CSV into the evidence layer.
    Handles Census 1901 (source 3), 1911 (source 4), and 1926 (source 5).
    """
    check_version(conn)

    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: '{csv_path}'")

    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        raise ValueError("CSV file is empty.")

    if source_id == 5:
        rows = [_normalize_census_1926_row(row) for row in rows]

    source_row = conn.execute(
        "SELECT * FROM source WHERE source_id = ?", (source_id,)
    ).fetchone()
    if not source_row:
        raise ValueError(f"Source {source_id} not found in database.")

    households: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        households[row["image_group"]].append(row)

    parse_notes: list[dict] = []
    records_committed = 0
    persons_committed = 0

    with conn:
        # IDs computed inside the transaction so concurrent writes cannot
        # cause collisions (SQLite WAL serialises writers, but this is
        # cleaner and explicit).
        def next_id(table: str, pk_col: str) -> int:
            result = conn.execute(f"SELECT MAX({pk_col}) FROM {table}").fetchone()[0]
            return (result or 0) + 1

        record_id = next_id("record", "record_id")
        re_id     = next_id("recorded_event", "recorded_event_id")
        rp_id     = next_id("recorded_person", "recorded_person_id")
        for image_group, persons in households.items():
            document_id = _get_document_id(persons[0])

            if source_id == 5:
                raw_columns = [
                    "id", "census_year", "county", "surname", "firstname",
                    "townland", "townland_clean", "ded", "ded_clean", "age", "sex",
                    "house_number", "relation_to_head", "relation_to_head_updated",
                    "religion", "religion_updated", "occupation", "occupation_updated",
                    "marriage_status", "marriage_years", "children_born", "children_living",
                    "birthplace", "language", "language_updated", "deafdumb",
                    "image_group", "geocode", "institution_name", "institution_type",
                    "a_id",
                ]
            else:
                raw_columns = [
                    "id", "census_year", "county", "surname", "firstname",
                    "townland_clean", "ded_clean", "age", "sex", "house_number",
                    "relation_to_head_updated", "religion_updated",
                    "occupation_updated", "marriage_status", "marriage_years",
                    "children_born", "children_living", "birthplace",
                    "language_updated", "deafdumb",
                ]
            raw_lines = [
                ",".join(str(p.get(col, "")) for col in raw_columns)
                for p in persons
            ]
            raw_text = "\n".join(raw_lines)
            record_parameters = json.dumps(
                {"document_id": document_id} if document_id else {}
            )

            conn.execute(
                "INSERT INTO record (record_id, source_id, record_parameters, raw_text) "
                "VALUES (?, ?, ?, ?)",
                (record_id, source_id, record_parameters, raw_text),
            )

            townland = persons[0].get("townland_clean", "") or persons[0].get("townland", "")
            census_date = _CENSUS_DATES.get(source_id, "")
            conn.execute(
                "INSERT INTO recorded_event "
                "(recorded_event_id, record_id, type, date, date_qualifier, place_as_recorded) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (re_id, record_id, "census", census_date, "exact", townland),
            )

            for person in persons:
                relation_raw = (
                    person.get("relation_to_head_updated")
                    or person.get("relation_to_head")
                    or ""
                ).strip()

                role, note = _map_role(relation_raw)

                if note:
                    parse_notes.append({
                        "image_group": image_group,
                        "name": f"{person.get('firstname', '')} {person.get('surname', '')}".strip(),
                        "relation_raw": relation_raw,
                        "note": note,
                    })

                age_raw = person.get("age", "").strip()
                try:
                    age_int = int(float(age_raw)) if age_raw else None
                except ValueError:
                    age_int = None
                    parse_notes.append({
                        "image_group": image_group,
                        "name": f"{person.get('firstname', '')} {person.get('surname', '')}".strip(),
                        "note": f"non-integer age '{age_raw}'; stored as null",
                    })

                sex_raw = person.get("sex", "").strip()
                sex_norm = _SEX_MAP.get(sex_raw, sex_raw) or None

                name = f"{person.get('firstname', '').strip()} {person.get('surname', '').strip()}".strip()
                if not name:
                    name = "Unknown"

                occupation = person.get("occupation_updated") or person.get("occupation") or None
                if occupation:
                    occupation = occupation.strip() or None

                conn.execute(
                    "INSERT INTO recorded_person "
                    "(recorded_person_id, record_id, name_as_recorded, role, "
                    "age_as_recorded, age, sex_as_recorded, occupation_as_recorded, place_as_recorded) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        rp_id, record_id, name, role,
                        age_raw, age_int, sex_raw, occupation, townland,
                    ),
                )
                rp_id += 1
                persons_committed += 1

            re_id += 1
            record_id += 1
            records_committed += 1

    townlands = sorted({
        p.get("townland_clean") or p.get("townland", "")
        for p in rows
        if p.get("townland_clean") or p.get("townland")
    })
    deds = sorted({
        p.get("ded_clean") or p.get("ded", "")
        for p in rows
        if p.get("ded_clean") or p.get("ded")
    })

    source_titles = {3: "Census 1901", 4: "Census 1911", 5: "Census 1926"}

    return {
        "source_id": source_id,
        "source_title": source_titles.get(source_id, "Census"),
        "csv_path": str(path),
        "rows_in_csv": len(rows),
        "households": len(households),
        "records_committed": records_committed,
        "persons_committed": persons_committed,
        "parse_notes": parse_notes,
        "townlands": townlands,
        "townland_count": len(townlands),
        "deds": deds,
    }


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def print_summary(conn: sqlite3.Connection) -> None:
    """Print a knowledge base summary to stdout."""
    check_version(conn)

    def q(sql: str) -> int:
        return conn.execute(sql).fetchone()[0]

    print()
    print("=" * 60)
    print("  GRA — Knowledge Base Summary")
    print("=" * 60)

    print("\n  FOUNDATIONAL LAYER")
    print(f"    Repositories:              {q('SELECT COUNT(*) FROM repository'):>6}")
    print(f"    Sources:                   {q('SELECT COUNT(*) FROM source'):>6}")

    # Place authority breakdown
    pa_total = q("SELECT COUNT(*) FROM place_authority")
    print(f"    Place authorities:         {pa_total:>6}")
    if pa_total:
        type_counts = conn.execute(
            "SELECT place_type, COUNT(*) AS n FROM place_authority GROUP BY place_type ORDER BY n DESC"
        ).fetchall()
        for tc in type_counts:
            print(f"      {tc['place_type']:<20}   {tc['n']:>4}")
        # place_membership retired in v2.7 — hierarchy is flat columns on place_authority

    print("\n  EVIDENCE LAYER")
    print(f"    Records:                   {q('SELECT COUNT(*) FROM record'):>6}")
    print(f"    Recorded Events:           {q('SELECT COUNT(*) FROM recorded_event'):>6}")
    print(f"    Recorded Persons:          {q('SELECT COUNT(*) FROM recorded_person'):>6}")

    # Place resolution coverage
    total_records = q("SELECT COUNT(*) FROM record")
    linked_records = q("SELECT COUNT(DISTINCT record_id) FROM place_record")
    if total_records:
        unlinked = total_records - linked_records
        print(f"    Records with place linked: {linked_records:>6}  ({unlinked} unresolved)")

    print("\n  CONCLUSION LAYER")
    couple_count  = q("SELECT COUNT(*) FROM relationship WHERE type='couple'")
    parent_count  = q("SELECT COUNT(*) FROM relationship WHERE type='parent_child'")
    sibling_count = q("SELECT COUNT(*) FROM relationship WHERE type='sibling'")

    print(f"    Persons:                   {q('SELECT COUNT(*) FROM person'):>6}")
    print(f"    Relationships:             {q('SELECT COUNT(*) FROM relationship'):>6}")
    print(f"      Couples:                 {couple_count:>6}")
    print(f"      Parent-child:            {parent_count:>6}")
    print(f"      Siblings:                {sibling_count:>6}")
    print(f"    Events:                    {q('SELECT COUNT(*) FROM event'):>6}")

    print("\n  LINKAGE")
    total_links = q("SELECT COUNT(*) FROM person_record")
    verified    = q("SELECT COUNT(*) FROM person_record WHERE verified=1")
    place_links = q("SELECT COUNT(*) FROM place_record")
    place_verified = q("SELECT COUNT(*) FROM place_record WHERE verified=1")
    print(f"    Person-Record links:       {total_links:>6}  ({verified} verified)")
    print(f"    Place-Record links:        {place_links:>6}  ({place_verified} verified)")

    source_counts = conn.execute("""
        SELECT s.title, COUNT(DISTINCT r.record_id) AS records,
               COUNT(rp.recorded_person_id) AS persons
        FROM source s
        JOIN record r ON r.source_id = s.source_id
        JOIN recorded_person rp ON rp.record_id = r.record_id
        GROUP BY s.source_id
        ORDER BY records DESC
    """).fetchall()

    if source_counts:
        print("\n  RECORDS BY SOURCE")
        for row in source_counts:
            print(f"    {row['title']:<34} {row['records']:>4} records  {row['persons']:>5} persons")

    print()
    print("=" * 60)
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_init(args: argparse.Namespace) -> None:
    init_db(args.db)


def _cmd_ingest(args: argparse.Namespace) -> None:
    conn = open_db(args.db)
    source_id = int(args.source)

    if source_id in (3, 4, 5):
        result = ingest_census(conn, args.file, source_id=source_id)
    else:
        print(f"No ingest handler implemented for source {source_id}.", file=sys.stderr)
        sys.exit(1)

    print(f"\nIngest complete — {result['source_title']}")
    print(f"  CSV rows:        {result['rows_in_csv']}")
    print(f"  Households:      {result['households']}")
    print(f"  Records:         {result['records_committed']}")
    print(f"  Persons:         {result['persons_committed']}")
    print(f"  Townlands ({result['townland_count']}): {', '.join(result['townlands'])}")

    notes = result["parse_notes"]
    if notes:
        print(f"\n  Parse notes ({len(notes)}):")
        for n in notes:
            name = n.get("name", "")
            print(f"    [{n['image_group']}] {name}: {n['note']}")
    else:
        print("\n  No parse notes — clean ingest.")


def _cmd_seed_places(args: argparse.Namespace) -> None:
    from src.seed_places import seed_places, print_seed_places_report
    conn = open_db(args.db)
    check_version(conn)
    result = seed_places(conn, args.file)
    print_seed_places_report(result)
    if not result["ok"]:
        sys.exit(1)


def _cmd_summary(args: argparse.Namespace) -> None:
    conn = open_db(args.db)
    print_summary(conn)


def _cmd_reconstruct(args: argparse.Namespace) -> None:
    from src.reconstruction import (
        run_place_resolution, print_place_resolution_report,
        run_household_inference, print_household_inference_report,
    )
    conn = open_db(args.db)
    check_version(conn)

    print("\nRunning reconstruction pipeline...")

    print("\n[1/2] Place resolution")
    place_result = run_place_resolution(conn)
    print_place_resolution_report(place_result)

    print("\n[2/2] Household structure inference")
    source_id = int(args.source)
    inference_result = run_household_inference(conn, source_id)
    print_household_inference_report(inference_result)

    print("\n[3/3] Cross-census linkage") # Added linkage execution
    linkage_result = run_census_linkage(conn)
    print_census_linkage_report(linkage_result)

    print("\nReconstruction complete. Running summary...\n")
    print_summary(conn)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m src.db",
        description="GRA database management",
    )
    parser.add_argument("--db", default=DEFAULT_DB, help=f"Database path (default: {DEFAULT_DB})")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Initialise a new database")

    p_ingest = sub.add_parser("ingest", help="Ingest a source CSV into the evidence layer")
    p_ingest.add_argument("--source", required=True, help="Source ID (e.g. 4 for Census 1911)")
    p_ingest.add_argument("--file", required=True, help="Path to the CSV file")

    p_seed = sub.add_parser("seed-places", help="Seed place_authority from a CSV file")
    p_seed.add_argument("--file", required=True, help="Path to place_authority CSV (logainm format)")

    sub.add_parser("summary", help="Print knowledge base summary")

    p_recon = sub.add_parser("reconstruct", help="Run place resolution and household inference")
    p_recon.add_argument("--source", required=True, help="Census source ID (e.g. 4 for Census 1911)")

    args = parser.parse_args()

    dispatch = {
        "init":         _cmd_init,
        "ingest":       _cmd_ingest,
        "seed-places":  _cmd_seed_places,
        "summary":      _cmd_summary,
        "reconstruct":  _cmd_reconstruct,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
