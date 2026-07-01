"""
GRA — DAL: event, event_record, and person_event queries (conclusion layer).

All SQL touching event, event_record, and person_event lives here.
"""

from __future__ import annotations

from src.db.repository import Repository


def insert_event_record(
    repo: Repository,
    event_id: int,
    record_id: int,
    score: float,
    score_version: str,
) -> None:
    """Link an Event to a Record in the event_record junction table."""
    repo.execute(
        "INSERT INTO event_record "
        "(event_id, record_id, score, score_version, verified) "
        "VALUES (%s, %s, %s, %s, 0)",
        (event_id, record_id, score, score_version),
    )


def insert_person_event(
    repo: Repository,
    person_id: int,
    event_id: int,
) -> None:
    """Link a Person to an Event in the person_event junction table."""
    repo.execute(
        "INSERT INTO person_event (person_id, event_id) VALUES (%s, %s)",
        (person_id, event_id),
    )


def get_events_for_person(
    repo: Repository,
    person_id: int,
) -> list[dict]:
    """
    Return all Events for a Person via the person_event junction.
    Row keys: event_id, type
    Ordered by type then event_id (stable ordering for consensus arbitration).
    """
    return repo.fetch_all(
        """
        SELECT e.event_id, e.type
        FROM event e
        JOIN person_event pe ON pe.event_id = e.event_id
        WHERE pe.person_id = %s
        ORDER BY e.type, e.event_id
        """,
        (person_id,),
    )


def get_vote_count_single(
    repo: Repository,
    event_id: int,
) -> int:
    """
    Return the number of event_record rows for a single event_id.
    Used to detect orphaned events (vote_count == 0).
    """
    result = repo.fetch_one(
        "SELECT COUNT(*) FROM event_record WHERE event_id = %s",
        (event_id,),
    )
    return result["count"]


def get_vote_counts(
    repo: Repository,
    event_ids: list[int],
) -> list[dict]:
    """
    For a list of event_ids, return vote counts from event_record.
    Row keys: event_id, vote_count
    Ordered by vote_count DESC, event_id ASC (tiebreak: lower event_id wins).

    Used by rebuild_consensus to arbitrate is_primary among multiple events
    of the same type for a single person.
    """
    # Build parameterised IN clause dynamically. The f-string controls only the
    # number of %s placeholders (safe); actual values are passed as parameters
    # to repo.fetch_all() and never interpolated directly into the SQL string.
    placeholders = ",".join(["%s"] * len(event_ids))
    return repo.fetch_all(
        f"""
        SELECT e.event_id,
               COUNT(er.record_id) AS vote_count
        FROM event e
        LEFT JOIN event_record er ON er.event_id = e.event_id
        WHERE e.event_id IN ({placeholders})
        GROUP BY e.event_id
        ORDER BY vote_count DESC, e.event_id ASC
        """,
        event_ids,
    )


def set_is_primary(
    repo: Repository,
    event_id: int,
    is_primary: int,
) -> None:
    """Set the is_primary flag on an Event row (1 = primary, 0 = alternative)."""
    repo.execute(
        "UPDATE event SET is_primary = %s WHERE event_id = %s",
        (is_primary, event_id),
    )
