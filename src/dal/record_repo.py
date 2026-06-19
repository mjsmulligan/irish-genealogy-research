"""
GRA — DAL: record and recorded_person queries (evidence layer).

All SQL touching the record and recorded_person tables lives here,
including the ingest-time writes that populate the evidence layer.
The evidence layer is never written by the pipeline after ingest —
only by the insert functions below, called from src/ingest/.
"""

from __future__ import annotations

import sqlite3


# ---------------------------------------------------------------------------
# Reads (used by pipeline stages, post-ingest)
# ---------------------------------------------------------------------------


def get_active_census_source_ids(conn: sqlite3.Connection) -> list[int]:
    """
    Return the census source_ids (3, 4, 5) that have at least one ingested
    record. Sources not yet ingested are excluded.
    """
    return [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT source_id FROM record WHERE source_id IN (3, 4, 5)"
        ).fetchall()
    ]


def get_unprocessed_census_records(
    conn: sqlite3.Connection,
    source_id: int,
) -> list[sqlite3.Row]:
    """
    Return all Records for source_id that have not yet been processed by
    household inference (i.e. not yet present in person_record).

    Row keys: record_id, date, place_as_recorded
    """
    return conn.execute(
        """
        SELECT r.record_id, r.date, r.place_as_recorded
        FROM record r
        WHERE r.source_id = ?
          AND r.record_id NOT IN (SELECT DISTINCT record_id FROM person_record)
        ORDER BY r.record_id
        """,
        (source_id,),
    ).fetchall()


def get_recorded_persons(
    conn: sqlite3.Connection,
    record_id: int,
) -> list[sqlite3.Row]:
    """
    Return all RecordedPerson rows for a given record, ordered by
    recorded_person_id (i.e. original row order within the household).
    """
    return conn.execute(
        "SELECT * FROM recorded_person WHERE record_id = ? ORDER BY recorded_person_id",
        (record_id,),
    ).fetchall()


# ---------------------------------------------------------------------------
# Writes (ingest-time only)
# ---------------------------------------------------------------------------


def next_record_id(conn: sqlite3.Connection) -> int:
    """Return the next available record_id (MAX + 1)."""
    return conn.execute(
        "SELECT COALESCE(MAX(record_id), 0) + 1 FROM record"
    ).fetchone()[0]


def next_recorded_person_id(conn: sqlite3.Connection) -> int:
    """Return the next available recorded_person_id (MAX + 1)."""
    return conn.execute(
        "SELECT COALESCE(MAX(recorded_person_id), 0) + 1 FROM recorded_person"
    ).fetchone()[0]


def insert_record(
    conn: sqlite3.Connection,
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
    conn.execute(
        "INSERT INTO record "
        "(record_id, source_id, record_parameters, raw_text, event_type, "
        " date_as_recorded, date, date_qualifier, place_as_recorded, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            record_id, source_id, record_parameters, raw_text, event_type,
            date_as_recorded, date, date_qualifier, place_as_recorded, notes,
        ),
    )


def insert_recorded_person(
    conn: sqlite3.Connection,
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
    conn.execute(
        "INSERT INTO recorded_person "
        "(recorded_person_id, record_id, name_as_recorded, role, "
        " age_as_recorded, age, sex_as_recorded, occupation_as_recorded, "
        " place_as_recorded, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            recorded_person_id, record_id, name_as_recorded, role,
            age_as_recorded, age, sex_as_recorded, occupation_as_recorded,
            place_as_recorded, notes,
        ),
    )