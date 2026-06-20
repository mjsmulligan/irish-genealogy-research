"""
GRA — DAL: record and recorded_person queries (evidence layer).

All SQL touching the record and recorded_person tables lives here,
including the ingest-time writes that populate the evidence layer.
The evidence layer is never written by the pipeline after ingest —
only by the insert functions below, called from src/ingest/.
"""

from __future__ import annotations

import psycopg2.extensions

from src.constants import CENSUS_SOURCE_IDS


# ---------------------------------------------------------------------------
# Reads (used by pipeline stages, post-ingest)
# ---------------------------------------------------------------------------


def get_active_census_source_ids(conn: psycopg2.extensions.connection) -> list[int]:
    """
    Return the census source_ids that have at least one ingested record.
    Sources not yet ingested are excluded.
    """
    placeholders = ",".join(["%s"] * len(CENSUS_SOURCE_IDS))
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT DISTINCT source_id FROM record WHERE source_id IN ({placeholders})",
            CENSUS_SOURCE_IDS,
        )
        return [row["source_id"] for row in cur.fetchall()]


def get_unprocessed_census_records(
    conn: psycopg2.extensions.connection,
    source_id: int,
) -> list[dict]:
    """
    Return all Records for source_id that have not yet been processed by
    household inference (i.e. not yet present in person_recorded_person).

    Row keys: record_id, date, place_as_recorded

    Performance note: the NOT IN correlated subquery is correct but will scan
    both junction tables on every call. At Donegal scale (168K records) this
    should be rewritten as NOT EXISTS or a LEFT JOIN ... WHERE IS NULL pattern.
    Acceptable at Tullynaught scale; flag for the evidence layer session.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.record_id, r.date, r.place_as_recorded
            FROM record r
            WHERE r.source_id = %s
              AND r.record_id NOT IN (
                  SELECT DISTINCT record_id
                  FROM recorded_person rp
                  JOIN person_recorded_person prp
                    ON prp.recorded_person_id = rp.recorded_person_id
              )
            ORDER BY r.record_id
            """,
            (source_id,),
        )
        return cur.fetchall()


def get_recorded_persons(
    conn: psycopg2.extensions.connection,
    record_id: int,
) -> list[dict]:
    """
    Return all RecordedPerson rows for a given record, ordered by
    recorded_person_id (i.e. original row order within the household).
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM recorded_person WHERE record_id = %s "
            "ORDER BY recorded_person_id",
            (record_id,),
        )
        return cur.fetchall()


# ---------------------------------------------------------------------------
# Writes (ingest-time only)
# ---------------------------------------------------------------------------


def next_record_id(conn: psycopg2.extensions.connection) -> int:
    """Return the next available record_id (MAX + 1)."""
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(record_id), 0) + 1 AS next_id FROM record")
        return cur.fetchone()["next_id"]


def next_recorded_person_id(conn: psycopg2.extensions.connection) -> int:
    """Return the next available recorded_person_id (MAX + 1)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(MAX(recorded_person_id), 0) + 1 AS next_id FROM recorded_person"
        )
        return cur.fetchone()["next_id"]


def insert_record(
    conn: psycopg2.extensions.connection,
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
    with conn.cursor() as cur:
        cur.execute(
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
    conn: psycopg2.extensions.connection,
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
    with conn.cursor() as cur:
        cur.execute(
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


def get_recorded_persons_for_record(
    conn: psycopg2.extensions.connection,
    record_id: int,
) -> list[dict]:
    """
    Return all RecordedPerson rows for a given record_id, ordered by
    recorded_person_id (i.e. ingest order within the household).

    Row keys: recorded_person_id, record_id, name_as_recorded, role,
              age_as_recorded, age, sex_as_recorded,
              occupation_as_recorded, place_as_recorded, notes
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT recorded_person_id, record_id, name_as_recorded, role, "
            "       age_as_recorded, age, sex_as_recorded, "
            "       occupation_as_recorded, place_as_recorded, notes "
            "FROM recorded_person "
            "WHERE record_id = %s "
            "ORDER BY recorded_person_id",
            (record_id,),
        )
        return cur.fetchall()
