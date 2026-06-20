"""
GRA — DAL: relationship and relationship_recorded_relationship queries (conclusion layer).

All SQL touching relationship and relationship_recorded_relationship lives here.

Note: junction table renamed relationship_record → relationship_recorded_relationship (v3.1).
FK target is recorded_relationship_id, not record_id (Rule 2 evidence correspondence).
"""

from __future__ import annotations

import psycopg2.extensions


def insert_relationship(
    conn: psycopg2.extensions.connection,
    relationship_id: int,
    rel_type: str,
    person_id_1: int,
    person_id_2: int,
    notes: str | None = None,
) -> None:
    """Insert a new Relationship conclusion row."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO relationship "
            "(relationship_id, type, person_id_1, person_id_2, notes) "
            "OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, %s, %s)",
            (relationship_id, rel_type, person_id_1, person_id_2, notes),
        )


def insert_relationship_recorded_relationship(
    conn: psycopg2.extensions.connection,
    relationship_id: int,
    recorded_relationship_id: int,
    score: float,
    score_version: str,
) -> None:
    """
    Link a Relationship to a RecordedRelationship in the
    relationship_recorded_relationship junction table.
    ON CONFLICT DO NOTHING — safe to call for an existing pair.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO relationship_recorded_relationship "
            "(relationship_id, recorded_relationship_id, score, score_version, verified) "
            "VALUES (%s, %s, %s, %s, 0) "
            "ON CONFLICT DO NOTHING",
            (relationship_id, recorded_relationship_id, score, score_version),
        )
