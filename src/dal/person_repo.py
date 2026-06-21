"""
GRA — DAL: person, person_name, and person_recorded_person queries (conclusion layer).

All SQL touching person, person_name, and person_recorded_person lives here.

Note: junction table renamed person_record → person_recorded_person (v3.1).
FK target is recorded_person_id, not record_id (Rule 2 evidence correspondence).
"""

from __future__ import annotations

import psycopg2.extensions


def next_ids(conn: psycopg2.extensions.connection) -> dict[str, int]:
    """
    Return the next available primary key for each conclusion-layer table
    that the household inference stage inserts into.

    Keys: "person", "relationship", "event", "person_name"

    Note: with GENERATED ALWAYS AS IDENTITY, explicit ID insertion is only
    needed during bulk-load passes (household_inference). Normal single-row
    inserts should use RETURNING to get the generated ID instead. This
    function remains for compatibility with the current bulk-insert pattern.

    Concurrency note: MAX(...) + 1 is not safe under concurrent access — two
    callers can receive the same value. This is acceptable for the single-user
    CLI pattern. If concurrent access is ever introduced (agent tier, UI), this
    must be replaced with RETURNING or a sequence-backed approach.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(person_id), 0) + 1 FROM person")
        person = cur.fetchone()["coalesce"]
        cur.execute("SELECT COALESCE(MAX(relationship_id), 0) + 1 FROM relationship")
        relationship = cur.fetchone()["coalesce"]
        cur.execute("SELECT COALESCE(MAX(event_id), 0) + 1 FROM event")
        event = cur.fetchone()["coalesce"]
        cur.execute("SELECT COALESCE(MAX(person_name_id), 0) + 1 FROM person_name")
        person_name = cur.fetchone()["coalesce"]
    return {
        "person": person,
        "relationship": relationship,
        "event": event,
        "person_name": person_name,
    }


def insert_person(
    conn: psycopg2.extensions.connection,
    person_id: int,
    label: str,
    gender: str | None,
) -> None:
    """Insert a new Person conclusion row."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO person (person_id, label, gender) "
            "OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s)",
            (person_id, label, gender),
        )


def insert_person_name(
    conn: psycopg2.extensions.connection,
    person_name_id: int,
    person_id: int,
    value: str,
    name_type: str,
) -> None:
    """Insert a PersonName row (e.g. birth_name from census)."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO person_name (person_name_id, person_id, value, type) "
            "OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, %s)",
            (person_name_id, person_id, value, name_type),
        )


def insert_person_recorded_person(
    conn: psycopg2.extensions.connection,
    person_id: int,
    recorded_person_id: int,
    score: float,
    score_version: str,
) -> None:
    """
    Link a Person to a RecordedPerson in the person_recorded_person junction table.
    ON CONFLICT DO NOTHING — safe to call for an existing pair (re-score passes).
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO person_recorded_person "
            "(person_id, recorded_person_id, score, score_version, verified) "
            "VALUES (%s, %s, %s, %s, 0) "
            "ON CONFLICT DO NOTHING",
            (person_id, recorded_person_id, score, score_version),
        )


def get_existing_person_ids(
    conn: psycopg2.extensions.connection,
    id1: int,
    id2: int,
) -> set[int]:
    """
    Return the subset of {id1, id2} that exist in the person table.
    Used by linkage to detect persons that have already been merged (vanished).
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT person_id FROM person WHERE person_id IN (%s, %s)",
            (id1, id2),
        )
        return {row["person_id"] for row in cur.fetchall()}


def get_all_person_ids(conn: psycopg2.extensions.connection) -> list[int]:
    """Return all person_ids in ascending order. Used by scoring and validator."""
    with conn.cursor() as cur:
        cur.execute("SELECT person_id FROM person ORDER BY person_id")
        return [row["person_id"] for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Person Resolution functions (RETURNING pattern)
# ---------------------------------------------------------------------------

def create_person(
    conn: psycopg2.extensions.connection,
    label: str,
    gender: str | None = None,
) -> int:
    """
    Create a new Person and return the generated person_id.

    Uses RETURNING pattern instead of pre-calculating IDs.
    Suitable for person resolution and other conclusion-layer operations.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO person (label, gender) "
            "VALUES (%s, %s) "
            "RETURNING person_id",
            (label, gender),
        )
        return cur.fetchone()["person_id"]


def link_person_to_recorded_person(
    conn: psycopg2.extensions.connection,
    person_id: int,
    recorded_person_id: int,
    score: float | None,
    score_version: str | None,
    verified: bool = False,
) -> None:
    """
    Link a Person to a RecordedPerson via person_recorded_person junction table.

    score/score_version: Optional (None for clustering-based linkage)
    verified: False by default (algorithm assertion); True for researcher-verified

    ON CONFLICT DO NOTHING — safe for re-score passes or duplicate calls.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO person_recorded_person "
            "(person_id, recorded_person_id, score, score_version, verified) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (person_id, recorded_person_id) DO NOTHING",
            (person_id, recorded_person_id, score, score_version, 1 if verified else 0),
        )
