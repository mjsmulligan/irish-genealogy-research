"""
GRA — DAL: relationship and relationship_record queries (conclusion layer).

All SQL touching relationship and relationship_record lives here.
"""

from __future__ import annotations

import sqlite3


def insert_relationship(
    conn: sqlite3.Connection,
    relationship_id: int,
    rel_type: str,
    person_id_1: int,
    person_id_2: int,
    notes: str | None = None,
) -> None:
    """Insert a new Relationship conclusion row."""
    conn.execute(
        "INSERT INTO relationship "
        "(relationship_id, type, person_id_1, person_id_2, notes) "
        "VALUES (?, ?, ?, ?, ?)",
        (relationship_id, rel_type, person_id_1, person_id_2, notes),
    )


def insert_relationship_record(
    conn: sqlite3.Connection,
    relationship_id: int,
    record_id: int,
    score: float,
    score_version: str,
) -> None:
    """Link a Relationship to a Record in the relationship_record junction table."""
    conn.execute(
        "INSERT INTO relationship_record "
        "(relationship_id, record_id, score, score_version, verified) "
        "VALUES (?, ?, ?, ?, 0)",
        (relationship_id, record_id, score, score_version),
    )
