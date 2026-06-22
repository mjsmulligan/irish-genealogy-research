"""
GRA — Census Ingest
Evidence layer step [1/5].

Loads an NAI census download CSV (1901, 1911, or 1926 — sources 3, 4, 5)
into the evidence layer: one Record per household (`image_group`) and one
RecordedPerson per household member.

This is distinct from src/evidence/features/census.py, which extracts
Splink linkage features from already-ingested evidence (stage 4 input).
This module is the only thing that writes the evidence layer; all SQL is
delegated to src/dal/record_repo.py and src/dal/source_repo.py.

Entry point: ingest_census(conn, file_path, source_id) -> dict
"""

from __future__ import annotations

import ast
import csv
import io
import json
from pathlib import Path

import psycopg2.extensions

from src.dal.record_repo import (
    insert_record,
    insert_recorded_person,
    next_record_id,
    next_recorded_person_id,
)
from src.dal.source_repo import get_source

INGEST_VERSION = "census_v1.0"

# ---------------------------------------------------------------------------
# Per-source column mapping
#
# 1901 and 1911 share the same NAI download schema. 1926 is a different
# download schema (no occupation/house_number/education; age and relation
# columns carry different names) — see docs/repositories.md §Source 5.
# ---------------------------------------------------------------------------

_SOURCE_CONFIG: dict[int, dict] = {
    3: {  # Census 1901
        "census_date": "1901-03-31",
        "date_as_recorded": "1901",
        "forename_col": "firstname",
        "surname_col": "surname",
        "age_col": "age",
        "sex_col": "sex",
        "occupation_col": "occupation_updated",
        "occupation_fallback_col": "occupation",
        "relation_col": "relation_to_head_updated",
        "relation_fallback_col": "relation_to_head",
        "townland_col": "townland_clean",
        "townland_fallback_col": "townland",
        "birthplace_col": "birthplace",
        "household_col": "image_group",
        "images_col": "images",
        "document_id_col": None,
    },
    4: {  # Census 1911
        "census_date": "1911-04-02",
        "date_as_recorded": "1911",
        "forename_col": "firstname",
        "surname_col": "surname",
        "age_col": "age",
        "sex_col": "sex",
        "occupation_col": "occupation_updated",
        "occupation_fallback_col": "occupation",
        "relation_col": "relation_to_head_updated",
        "relation_fallback_col": "relation_to_head",
        "townland_col": "townland_clean",
        "townland_fallback_col": "townland",
        "birthplace_col": "birthplace",
        "household_col": "image_group",
        "images_col": "images",
        "document_id_col": None,
    },
    5: {  # Census 1926
        "census_date": "1926-04-18",
        "date_as_recorded": "1926",
        "forename_col": "first_name",
        "surname_col": "surname",
        "age_col": "updated_age",
        "sex_col": "updated_sex",
        "occupation_col": None,
        "occupation_fallback_col": None,
        "relation_col": "updated_relationship_to_head",
        "relation_fallback_col": "relationship_to_head",
        "townland_col": "townland",
        "townland_fallback_col": None,
        "birthplace_col": "birthplace_county",
        "household_col": "image_group",
        "images_col": None,
        "document_id_col": "aform_name",
    },
}

# ---------------------------------------------------------------------------
# Role mapping — NAI relation-to-head vocabulary -> recorded_person.role
# (data_dictionary.md §6.4). Keys are normalised: lowercased, apostrophes
# stripped, internal whitespace collapsed to single spaces.
# ---------------------------------------------------------------------------

_ROLE_MAP: dict[str, str] = {
    "head of family": "head",
    "head": "head",
    "wife": "spouse",
    "husband": "spouse",
    "son": "son",
    "step son": "son",
    "stepson": "son",
    "daughter": "daughter",
    "step daughter": "daughter",
    "stepdaughter": "daughter",
    "sister": "sibling",
    "brother": "sibling",
    "grand son": "grandchild",
    "grandson": "grandchild",
    "grand daughter": "grandchild",
    "granddaughter": "grandchild",
    "grand child": "grandchild",
    "grandchild": "grandchild",
    "daughter in law": "in_law",
    "son in law": "in_law",
    "mother in law": "in_law",
    "father in law": "in_law",
    "sister in law": "in_law",
    "brother in law": "in_law",
    "niece in law": "in_law",
    "sons wife": "in_law",
    "son wife": "in_law",
    "brothers wife": "in_law",
    "nephews wife": "in_law",
    "niece": "niece_nephew",
    "nephew": "niece_nephew",
    "nice": "niece_nephew",  # observed misspelling of 'Niece' in NAI data
    "aunt": "aunt_uncle",
    "uncle": "aunt_uncle",
    "cousin": "cousin",
    "mother": "mother",
    "father": "father",
    "servant": "servant",
    "farm servant": "servant",
    "house keeper": "servant",
    "visitor": "visitor",
    "boarder": "boarder",
    "lodger": "boarder",
}


def _normalise_relation(raw: str) -> str:
    s = raw.strip().lower().replace("'", "")
    return " ".join(s.split())


def _map_role(raw: str | None) -> tuple[str | None, str | None]:
    """
    Map a raw relation-to-head string to a recorded_person.role value.

    Returns (role, note). role is None for a blank source value (NULL =
    blank in source, per schema). role is 'unknown' for a non-blank value
    that doesn't match the controlled vocabulary, with a note explaining
    why; the original value is never lost (it remains in raw_text).
    """
    if raw is None or not raw.strip():
        return None, None

    norm = _normalise_relation(raw)
    role = _ROLE_MAP.get(norm)
    if role:
        return role, None

    # Heuristic fallbacks for variants not in the explicit table.
    if "in law" in norm:
        return "in_law", None
    if "grand" in norm:
        return "grandchild", None
    if "servant" in norm or "keeper" in norm:
        return "servant", None
    if "boarder" in norm or "lodger" in norm:
        return "boarder", None

    return "unknown", f"Unrecognised relation value '{raw}' mapped to role 'unknown'"


def _parse_age(raw: str | None) -> tuple[int | None, str | None]:
    """Parse an age string to an integer, per the int(float()) convention."""
    if raw is None or not raw.strip():
        return None, None
    try:
        return int(float(raw)), None
    except (ValueError, TypeError):
        return None, f"Could not parse age value '{raw}'"


def _first_image_id(images_raw: str | None) -> tuple[str | None, str | None]:
    """
    Extract the first image id from the NAI 'images' column, which holds a
    Python-literal list of dicts, e.g. "[{'form': 'Form A', 'id': '...'}]".
    """
    if not images_raw or not images_raw.strip():
        return None, "Empty 'images' field; document_id could not be derived"
    try:
        parsed = ast.literal_eval(images_raw)
        if not parsed:
            return None, "'images' field parsed to an empty list"
        return str(parsed[0]["id"]), None
    except (ValueError, SyntaxError, KeyError, IndexError, TypeError) as e:
        return None, f"Could not parse 'images' field ({e})"


def _row_to_line(fieldnames: list[str], row: dict) -> str:
    """Reconstruct a single CSV data line from a DictReader row dict."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([row.get(f, "") for f in fieldnames])
    return buf.getvalue().rstrip("\r\n")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def ingest_census(
    conn: psycopg2.extensions.connection,
    file_path: str,
    source_id: int,
) -> dict:
    """
    Ingest an NAI census CSV into the evidence layer for source_id (3, 4, or 5).

    Groups rows by household (`image_group`), writing one Record per
    household and one RecordedPerson per household member. Returns a
    summary dict:

        source_title       str
        rows_in_csv         int
        households           int
        records_committed    int
        persons_committed    int
        townland_count       int
        townlands             list[str]
        parse_notes           list[{"image_group", "name", "note"}]
    """
    if source_id not in _SOURCE_CONFIG:
        raise ValueError(
            f"No ingest handler for source_id {source_id}; "
            f"supported: {sorted(_SOURCE_CONFIG)}"
        )

    cfg = _SOURCE_CONFIG[source_id]

    source = get_source(conn, source_id)
    if source is None:
        raise ValueError(f"Source {source_id} not found in the database. Run 'init' first.")

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: '{file_path}'")

    expected_columns = json.loads(source["column_schema"]) if source["column_schema"] else []

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []

        missing = [c for c in expected_columns if c not in fieldnames]
        if missing:
            raise ValueError(
                f"CSV is missing expected columns for {source['title']}: {missing}"
            )

        # Group rows by household, preserving first-seen order. Household
        # rows are not guaranteed to be contiguous in the file, so this
        # groups by key value rather than assuming block structure.
        households: dict[str, list[dict]] = {}
        rows_in_csv = 0
        for row in reader:
            rows_in_csv += 1
            key = row[cfg["household_col"]]
            households.setdefault(key, []).append(row)

    parse_notes: list[dict] = []
    townlands: set[str] = set()
    record_id = next_record_id(conn)
    recorded_person_id = next_recorded_person_id(conn)
    records_committed = 0
    persons_committed = 0

    with conn:
        for household_key, rows in households.items():
            first_row = rows[0]

            townland = first_row.get(cfg["townland_col"]) or ""
            if not townland and cfg["townland_fallback_col"]:
                townland = first_row.get(cfg["townland_fallback_col"]) or ""
            townland = townland.strip()
            if townland:
                townlands.add(townland)

            document_id = None
            doc_note = None
            if cfg["document_id_col"]:
                document_id = (first_row.get(cfg["document_id_col"]) or "").strip() or None
                if document_id is None:
                    doc_note = "Empty document id column; document_id could not be derived"
            else:
                document_id, doc_note = _first_image_id(first_row.get(cfg["images_col"]))

            if document_id is None:
                document_id = f"household-{household_key}"

            if doc_note:
                parse_notes.append({
                    "image_group": household_key,
                    "name": "",
                    "note": doc_note,
                })

            raw_lines = [",".join(fieldnames)] + [_row_to_line(fieldnames, r) for r in rows]
            raw_text = "\n".join(raw_lines)

            this_record_id = record_id
            insert_record(
                conn,
                record_id=this_record_id,
                source_id=source_id,
                record_parameters=json.dumps({"document_id": document_id}),
                raw_text=raw_text,
                event_type="census",
                date_as_recorded=cfg["date_as_recorded"],
                date=cfg["census_date"],
                date_qualifier="exact",
                place_as_recorded=townland or None,
                notes=doc_note,
            )
            record_id += 1
            records_committed += 1

            for row in rows:
                forename = (row.get(cfg["forename_col"]) or "").strip()
                surname = (row.get(cfg["surname_col"]) or "").strip()
                name_as_recorded = f"{forename} {surname}".strip()

                person_notes: list[str] = []
                if not name_as_recorded:
                    name_as_recorded = "[unknown]"
                    person_notes.append("Both forename and surname were blank in source")

                relation_raw = row.get(cfg["relation_col"])
                if not relation_raw and cfg["relation_fallback_col"]:
                    relation_raw = row.get(cfg["relation_fallback_col"])
                role, role_note = _map_role(relation_raw)
                if role_note:
                    person_notes.append(role_note)
                    parse_notes.append({
                        "image_group": household_key,
                        "name": name_as_recorded,
                        "note": role_note,
                    })

                age_as_recorded = row.get(cfg["age_col"])
                age, age_note = _parse_age(age_as_recorded)
                if age_note:
                    person_notes.append(age_note)
                    parse_notes.append({
                        "image_group": household_key,
                        "name": name_as_recorded,
                        "note": age_note,
                    })

                occupation = None
                if cfg["occupation_col"]:
                    occupation = (row.get(cfg["occupation_col"]) or "").strip() or None
                if not occupation and cfg["occupation_fallback_col"]:
                    occupation = (row.get(cfg["occupation_fallback_col"]) or "").strip() or None

                birthplace = (row.get(cfg["birthplace_col"]) or "").strip() or None
                sex_as_recorded = (row.get(cfg["sex_col"]) or "").strip() or None

                insert_recorded_person(
                    conn,
                    recorded_person_id=recorded_person_id,
                    record_id=this_record_id,
                    name_as_recorded=name_as_recorded,
                    role=role,
                    age_as_recorded=age_as_recorded,
                    age=age,
                    sex_as_recorded=sex_as_recorded,
                    occupation_as_recorded=occupation,
                    place_as_recorded=birthplace,
                    notes="; ".join(person_notes) or None,
                )
                recorded_person_id += 1
                persons_committed += 1

    return {
        "source_title": source["title"],
        "rows_in_csv": rows_in_csv,
        "households": len(households),
        "records_committed": records_committed,
        "persons_committed": persons_committed,
        "townland_count": len(townlands),
        "townlands": sorted(townlands),
        "parse_notes": parse_notes,
    }
