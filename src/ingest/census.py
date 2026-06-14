"""
GRA — Census ingest for NAI downloads (Sources 3, 4, 5).

Extracted from src/db/__init__.py (Commit 2 refactor).

Public API
----------
ingest_census(conn, csv_path, source_id) → dict

The returned dict keys:
    source_id, source_title, csv_path, rows_in_csv, households,
    records_committed, persons_committed, parse_notes,
    townlands, townland_count, deds
"""

from __future__ import annotations

import ast
import csv
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from src.db.connection import check_version

# ---------------------------------------------------------------------------
# Vocabulary tables
# ---------------------------------------------------------------------------

_CENSUS_ROLE_MAP: dict[str, str] = {
    "Head of Family": "head",
    "Head":           "head",
    "Wife":           "spouse",
    "Husband":        "spouse",
    "Son":            "son",
    "Daughter":       "daughter",
    "Brother":        "sibling",
    "Sister":         "sibling",
    "Grand Son":      "grandchild",
    "Grandson":       "grandchild",
    "Grand Daughter": "grandchild",
    "Granddaughter":  "grandchild",
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

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_document_id(images_str: str) -> str | None:
    try:
        images = ast.literal_eval(images_str)
        if images and isinstance(images, list):
            url = images[0].get("url", "")
            stem = Path(url.split("?")[0]).stem
            return stem if stem else None
    except Exception:
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


def _map_role(relation: str) -> tuple[str | None, str | None]:
    """Map a raw census relationship string to a normalised role.

    Returns (role, warning_note) where:
      - role is None if the source field was blank (genuine data gap)
      - role is 'unknown' if a value was present but not in the vocabulary
      - warning_note is non-None only for the 'unknown' case
    """
    if not relation.strip():
        return None, None
    role = _CENSUS_ROLE_MAP.get(relation)
    if role:
        return role, None
    return "unknown", f"unmapped relation {relation!r}"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def ingest_census(
    conn: sqlite3.Connection,
    csv_path: str,
    source_id: int = 4,
) -> dict:
    """
    Ingest a census NAI download CSV into the evidence layer.
    Handles Census 1901 (source 3), 1911 (source 4), and 1926 (source 5).

    Creates one Record per household (with event fields inline) and one
    RecordedPerson per person row.
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
        def next_id(table: str, pk_col: str) -> int:
            result = conn.execute(f"SELECT MAX({pk_col}) FROM {table}").fetchone()[0]
            return (result or 0) + 1

        record_id = next_id("record", "record_id")
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

            townland = persons[0].get("townland_clean", "") or persons[0].get("townland", "")
            census_date = _CENSUS_DATES.get(source_id, "")

            # Single INSERT — event fields now live directly on record
            conn.execute(
                "INSERT INTO record "
                "(record_id, source_id, record_parameters, raw_text, "
                " event_type, date, date_qualifier, place_as_recorded) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (record_id, source_id, record_parameters, raw_text,
                 "census", census_date, "exact", townland),
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
