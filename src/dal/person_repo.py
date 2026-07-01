"""
GRA — DAL: person, person_name, and person_recorded_person queries (conclusion layer).

All SQL touching person, person_name, and person_recorded_person lives here.

Note: junction table renamed person_record → person_recorded_person (v3.1).
FK target is recorded_person_id, not record_id (Rule 2 evidence correspondence).
"""

from __future__ import annotations

from src.db.repository import Repository


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


def merge_persons(
    repo: Repository,
    keep_person_id: int,
    merge_person_id: int,
) -> None:
    """
    Merge two Persons by moving all RecordedPersons from merge_person_id to
    keep_person_id, then deleting the now-empty Person.

    Relationships of the merge_person are set to pending_delete for cleanup in a later pass.

    Used when household continuity detects that confirmed household heads were
    already linked to different Persons — this fixes the split.
    """
    # Delete person_events from merge_person that would conflict with keep_person
    repo.execute(
        """
        DELETE FROM person_event
        WHERE person_id = %s
          AND event_id IN (
            SELECT event_id FROM person_event WHERE person_id = %s
          )
        """,
        (merge_person_id, keep_person_id),
    )

    # Move remaining person_event references
    repo.execute(
        "UPDATE person_event SET person_id = %s WHERE person_id = %s",
        (keep_person_id, merge_person_id),
    )

    # Delete event references in order: event_record, person_event, then events
    # Get all event IDs from relationships to be cleaned up
    repo.execute(
        """
        DELETE FROM event_record
        WHERE event_id IN (
          SELECT event_id FROM event
          WHERE relationship_id IN (
            SELECT relationship_id FROM relationship
            WHERE person_id_1 = %s OR person_id_2 = %s
          )
        )
        """,
        (merge_person_id, merge_person_id),
    )

    repo.execute(
        """
        DELETE FROM person_event
        WHERE event_id IN (
          SELECT event_id FROM event
          WHERE relationship_id IN (
            SELECT relationship_id FROM relationship
            WHERE person_id_1 = %s OR person_id_2 = %s
          )
        )
        """,
        (merge_person_id, merge_person_id),
    )

    repo.execute(
        """
        DELETE FROM event
        WHERE relationship_id IN (
          SELECT relationship_id FROM relationship
          WHERE person_id_1 = %s OR person_id_2 = %s
        )
        """,
        (merge_person_id, merge_person_id),
    )

    repo.execute(
        """
        UPDATE relationship
        SET status = 'pending_delete', pending_delete_at = NOW()
        WHERE person_id_1 = %s OR person_id_2 = %s
        """,
        (merge_person_id, merge_person_id),
    )

    # Move all RecordedPersons from merge_person to keep_person
    repo.execute(
        """
        UPDATE person_recorded_person
        SET person_id = %s
        WHERE person_id = %s
          AND recorded_person_id NOT IN (
            SELECT recorded_person_id FROM person_recorded_person
            WHERE person_id = %s
          )
        """,
        (keep_person_id, merge_person_id, keep_person_id),
    )

    # Delete duplicate person_recorded_person rows (if any RecordedPerson was linked to both)
    repo.execute(
        "DELETE FROM person_recorded_person WHERE person_id = %s",
        (merge_person_id,),
    )

    # Note: We cannot delete the Person directly because relationships still reference it
    # (they have status='pending_delete'). These orphaned Persons will be cleaned up
    # by a separate maintenance step that handles relationship cleanup first.
