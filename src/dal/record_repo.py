"""
GRA — DAL: record and recorded_person queries (evidence layer, read-only).

All SQL touching the record and recorded_person tables lives here.
The evidence layer is never written by the pipeline after ingest.
"""

from __future__ import annotations

import sqlite3


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
