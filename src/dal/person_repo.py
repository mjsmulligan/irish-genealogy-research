"""
GRA — DAL: person, person_name, and person_recorded_person queries (conclusion layer).

All SQL touching person, person_name, and person_recorded_person lives here.

Note: junction table renamed person_record → person_recorded_person (v3.1).
FK target is recorded_person_id, not record_id (Rule 2 evidence correspondence).
"""

from __future__ import annotations

from src.db.repository import Repository


def insert_person(
    repo: Repository,
    person_id: int,
    label: str,
    gender: str | None,
) -> None:
    """Insert a new Person conclusion row."""
    repo.execute(
        "INSERT INTO person (person_id, label, gender) "
        "OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s)",
        (person_id, label, gender),
    )


def insert_person_name(
    repo: Repository,
    person_name_id: int,
    person_id: int,
    value: str,
    name_type: str,
) -> None:
    """Insert a PersonName row (e.g. birth_name from census)."""
    repo.execute(
        "INSERT INTO person_name (person_name_id, person_id, value, type) "
        "OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, %s)",
        (person_name_id, person_id, value, name_type),
    )


def insert_person_recorded_person(
    repo: Repository,
    person_id: int,
    recorded_person_id: int,
    score: float,
    score_version: str,
) -> None:
    """
    Link a Person to a RecordedPerson in the person_recorded_person junction table.
    ON CONFLICT DO NOTHING — safe to call for an existing pair (re-score passes).
    """
    repo.execute(
        "INSERT INTO person_recorded_person "
        "(person_id, recorded_person_id, score, score_version, verified) "
        "VALUES (%s, %s, %s, %s, 0) "
        "ON CONFLICT DO NOTHING",
        (person_id, recorded_person_id, score, score_version),
    )


def get_existing_person_ids(
    repo: Repository,
    id1: int,
    id2: int,
) -> set[int]:
    """
    Return the subset of {id1, id2} that exist in the person table.
    Used by linkage to detect persons that have already been merged (vanished).
    """
    rows = repo.fetch_all(
        "SELECT person_id FROM person WHERE person_id IN (%s, %s)",
        (id1, id2),
    )
    return {row["person_id"] for row in rows}


def get_all_person_ids(repo: Repository) -> list[int]:
    """Return all person_ids in ascending order. Used by scoring and validator."""
    rows = repo.fetch_all("SELECT person_id FROM person ORDER BY person_id")
    return [row["person_id"] for row in rows]


# ---------------------------------------------------------------------------
# Person Resolution functions (RETURNING pattern)
# ---------------------------------------------------------------------------

def create_person(
    repo: Repository,
    label: str,
    gender: str | None = None,
) -> int:
    """
    Create a new Person and return the generated person_id.

    Uses RETURNING pattern instead of pre-calculating IDs.
    Suitable for person resolution and other conclusion-layer operations.
    """
    result = repo.execute_returning(
        "INSERT INTO person (label, gender) "
        "VALUES (%s, %s) "
        "RETURNING person_id",
        (label, gender),
    )
    return result["person_id"]


def link_person_to_recorded_person(
    repo: Repository,
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
    repo.execute(
        "INSERT INTO person_recorded_person "
        "(person_id, recorded_person_id, score, score_version, verified) "
        "VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (person_id, recorded_person_id) DO NOTHING",
        (person_id, recorded_person_id, score, score_version, 1 if verified else 0),
    )
