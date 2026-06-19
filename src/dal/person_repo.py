"""
GRA — DAL: person, person_name, and person_record queries (conclusion layer).

All SQL touching person, person_name, and person_record lives here.
"""

from __future__ import annotations

import sqlite3


def next_ids(conn: sqlite3.Connection) -> dict[str, int]:
    """
    Return the next available primary key for each conclusion-layer table
    that the household inference stage inserts into.

    Keys: "person", "relationship", "event", "person_name"
    """
    return {
        "person": conn.execute(
            "SELECT COALESCE(MAX(person_id), 0) + 1 FROM person"
        ).fetchone()[0],
        "relationship": conn.execute(
            "SELECT COALESCE(MAX(relationship_id), 0) + 1 FROM relationship"
        ).fetchone()[0],
        "event": conn.execute(
            "SELECT COALESCE(MAX(event_id), 0) + 1 FROM event"
        ).fetchone()[0],
        "person_name": conn.execute(
            "SELECT COALESCE(MAX(person_name_id), 0) + 1 FROM person_name"
        ).fetchone()[0],
    }


def insert_person(
    conn: sqlite3.Connection,
    person_id: int,
    label: str,
    gender: str | None,
) -> None:
    """Insert a new Person conclusion row."""
    conn.execute(
        "INSERT INTO person (person_id, label, gender) VALUES (?, ?, ?)",
        (person_id, label, gender),
    )


def insert_person_name(
    conn: sqlite3.Connection,
    person_name_id: int,
    person_id: int,
    value: str,
    name_type: str,
) -> None:
    """Insert a PersonName row (e.g. birth_name from census)."""
    conn.execute(
        "INSERT INTO person_name (person_name_id, person_id, value, type) "
        "VALUES (?, ?, ?, ?)",
        (person_name_id, person_id, value, name_type),
    )


def insert_person_record(
    conn: sqlite3.Connection,
    person_id: int,
    record_id: int,
    score: float,
    score_version: str,
) -> None:
    """
    Link a Person to a Record in the person_record junction table.
    Uses INSERT OR IGNORE — safe to call multiple times for the same pair.
    """
    conn.execute(
        "INSERT OR IGNORE INTO person_record "
        "(person_id, record_id, score, score_version, verified) VALUES (?, ?, ?, ?, 0)",
        (person_id, record_id, score, score_version),
    )


def get_existing_person_ids(
    conn: sqlite3.Connection,
    id1: int,
    id2: int,
) -> set[int]:
    """
    Return the subset of {id1, id2} that exist in the person table.
    Used by linkage to detect persons that have already been merged (vanished).
    """
    return {
        row[0]
        for row in conn.execute(
            "SELECT person_id FROM person WHERE person_id IN (?, ?)",
            (id1, id2),
        ).fetchall()
    }


def get_all_person_ids(conn: sqlite3.Connection) -> list[int]:
    """Return all person_ids in ascending order. Used by scoring and validator."""
    return [
        row[0]
        for row in conn.execute(
            "SELECT person_id FROM person ORDER BY person_id"
        ).fetchall()
    ]
