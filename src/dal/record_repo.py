"""
GRA — DAL: record and recorded_person queries (evidence layer).

All SQL touching the record and recorded_person tables lives here,
including the ingest-time writes that populate the evidence layer.
The evidence layer is never written by the pipeline after ingest —
only by the insert functions below, called from src/evidence/census.py.
"""

from __future__ import annotations

from src.constants import CENSUS_SOURCE_IDS
from src.db.repository import Repository


# ---------------------------------------------------------------------------
# Reads (used by pipeline stages, post-ingest)
# ---------------------------------------------------------------------------


def get_active_census_source_ids(repo: Repository) -> list[int]:
    """
    Return the census source_ids that have at least one ingested record.
    Sources not yet ingested are excluded.
    """
    placeholders = ",".join(["%s"] * len(CENSUS_SOURCE_IDS))
    rows = repo.fetch_all(
        f"SELECT DISTINCT source_id FROM record WHERE source_id IN ({placeholders})",
        CENSUS_SOURCE_IDS,
    )
    return [row["source_id"] for row in rows]


def get_unprocessed_census_records(
    repo: Repository,
    source_id: int,
) -> list[dict]:
    """
    Return all Records for source_id that have not yet been processed by
    household inference (i.e. no RecordedPerson in the record has been linked
    to a Person via person_recorded_person).

    Row keys: record_id, date, place_as_recorded

    Implementation note: uses NOT EXISTS with a correlated subquery joining
    recorded_person → person_recorded_person on recorded_person_id (not
    record_id, which person_recorded_person does not have).  This is
    correct and performs acceptably at Donegal scale (avoids the N² scan of
    the previous NOT IN approach).
    """
    return repo.fetch_all(
        """
        SELECT r.record_id, r.date, r.place_as_recorded
        FROM record r
        WHERE r.source_id = %s
          AND NOT EXISTS (
              SELECT 1
              FROM recorded_person rp
              JOIN person_recorded_person prp
                ON prp.recorded_person_id = rp.recorded_person_id
              WHERE rp.record_id = r.record_id
          )
        ORDER BY r.record_id
        """,
        (source_id,),
    )




# ---------------------------------------------------------------------------
# Writes (ingest-time only)
# ---------------------------------------------------------------------------


def next_record_id(repo: Repository) -> int:
    """Return the next available record_id (MAX + 1)."""
    result = repo.fetch_one("SELECT COALESCE(MAX(record_id), 0) + 1 AS next_id FROM record")
    return result["next_id"]


def next_recorded_person_id(repo: Repository) -> int:
    """Return the next available recorded_person_id (MAX + 1)."""
    result = repo.fetch_one(
        "SELECT COALESCE(MAX(recorded_person_id), 0) + 1 AS next_id FROM recorded_person"
    )
    return result["next_id"]


def insert_record(
    repo: Repository,
    record_id: int,
    source_id: int,
    record_parameters: str | None,
    raw_text: str,
    event_type: str,
    date_as_recorded: str | None,
    date: str | None,
    date_qualifier: str | None,
    place_as_recorded: str | None,
    notes: str | None = None,
) -> None:
    """Insert a single Record (evidence layer). Called only from ingest."""
    repo.execute(
        "INSERT INTO record "
        "(record_id, source_id, record_parameters, raw_text, event_type, "
        " date_as_recorded, date, date_qualifier, place_as_recorded, notes) "
        "OVERRIDING SYSTEM VALUE "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            record_id, source_id, record_parameters, raw_text, event_type,
            date_as_recorded, date, date_qualifier, place_as_recorded, notes,
        ),
    )


def insert_recorded_person(
    repo: Repository,
    recorded_person_id: int,
    record_id: int,
    name_as_recorded: str,
    role: str | None,
    age_as_recorded: str | None,
    age: int | None,
    sex_as_recorded: str | None,
    occupation_as_recorded: str | None,
    place_as_recorded: str | None,
    notes: str | None = None,
) -> None:
    """Insert a single RecordedPerson (evidence layer). Called only from ingest."""
    repo.execute(
        "INSERT INTO recorded_person "
        "(recorded_person_id, record_id, name_as_recorded, role, "
        " age_as_recorded, age, sex_as_recorded, occupation_as_recorded, "
        " place_as_recorded, notes) "
        "OVERRIDING SYSTEM VALUE "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            recorded_person_id, record_id, name_as_recorded, role,
            age_as_recorded, age, sex_as_recorded, occupation_as_recorded,
            place_as_recorded, notes,
        ),
    )


def bulk_insert_records(
    repo: Repository,
    records: list[dict],
) -> None:
    """
    Bulk insert multiple Records in one statement.

    Each dict must have keys: record_id, source_id, record_parameters, raw_text,
    event_type, date_as_recorded, date, date_qualifier, place_as_recorded, notes
    """
    if not records:
        return

    # Build VALUES clause with placeholders
    values_template = "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    values_clause = ", ".join([values_template] * len(records))

    # Flatten all record values into a single tuple
    values = []
    for r in records:
        values.extend([
            r["record_id"], r["source_id"], r["record_parameters"],
            r["raw_text"], r["event_type"], r["date_as_recorded"],
            r["date"], r["date_qualifier"], r["place_as_recorded"],
            r["notes"]
        ])

    repo.execute(
        f"INSERT INTO record "
        f"(record_id, source_id, record_parameters, raw_text, event_type, "
        f" date_as_recorded, date, date_qualifier, place_as_recorded, notes) "
        f"OVERRIDING SYSTEM VALUE "
        f"VALUES {values_clause}",
        values
    )


def bulk_insert_recorded_persons(
    repo: Repository,
    persons: list[dict],
) -> None:
    """
    Bulk insert multiple RecordedPersons in one statement.

    Each dict must have keys: recorded_person_id, record_id, name_as_recorded,
    role, age_as_recorded, age, sex_as_recorded, occupation_as_recorded,
    place_as_recorded, notes
    """
    if not persons:
        return

    values_template = "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    values_clause = ", ".join([values_template] * len(persons))

    values = []
    for p in persons:
        values.extend([
            p["recorded_person_id"], p["record_id"], p["name_as_recorded"],
            p["role"], p["age_as_recorded"], p["age"], p["sex_as_recorded"],
            p["occupation_as_recorded"], p["place_as_recorded"], p["notes"]
        ])

    repo.execute(
        f"INSERT INTO recorded_person "
        f"(recorded_person_id, record_id, name_as_recorded, role, "
        f" age_as_recorded, age, sex_as_recorded, occupation_as_recorded, "
        f" place_as_recorded, notes) "
        f"OVERRIDING SYSTEM VALUE "
        f"VALUES {values_clause}",
        values
    )


def get_recorded_persons_for_record(
    repo: Repository,
    record_id: int,
) -> list[dict]:
    """
    Return all RecordedPerson rows for a given record_id, ordered by
    recorded_person_id (i.e. ingest order within the household).

    Row keys: recorded_person_id, record_id, name_as_recorded, role,
              age_as_recorded, age, sex_as_recorded,
              occupation_as_recorded, place_as_recorded, notes
    """
    return repo.fetch_all(
        "SELECT recorded_person_id, record_id, name_as_recorded, role, "
        "       age_as_recorded, age, sex_as_recorded, "
        "       occupation_as_recorded, place_as_recorded, notes "
        "FROM recorded_person "
        "WHERE record_id = %s "
        "ORDER BY recorded_person_id",
        (record_id,),
    )
