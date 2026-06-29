"""
GRA — Genealogy Research Assistant
DAL: conclusion_log and reviewer tables.

All conclusion-layer mutations (create, update, delete, verify, flag) are
recorded here via log_action(). This is the sole write path to conclusion_log
— no other module embeds SQL against these tables.

Reviewer IDs
------------
REVIEWER_PIPELINE = 1   pipeline:system  — automated pipeline conclusions
REVIEWER_UNKNOWN  = 2   human:unknown    — unattributed manual edits

These are seeded by seed.sql and stable across all databases.
"""

from __future__ import annotations

import uuid
from typing import Any

from src.db.repository import Repository

# Stable reviewer IDs — seeded at init time (seed.sql)
REVIEWER_PIPELINE: int = 1
REVIEWER_UNKNOWN: int  = 2


# ---------------------------------------------------------------------------
# Reviewer
# ---------------------------------------------------------------------------

def get_or_create_reviewer(
    repo: Repository,
    name: str,
    reviewer_type: str,
    notes: str | None = None,
) -> int:
    """
    Return reviewer_id for an existing Reviewer matching (name, type), or
    create a new one and return the new ID.

    reviewer_type must be one of: 'pipeline', 'human', 'ai'.
    """
    row = repo.fetch_one(
        "SELECT reviewer_id FROM reviewer WHERE name = %s AND type = %s",
        (name, reviewer_type),
    )
    if row:
        return row["reviewer_id"]

    result = repo.execute_returning(
        """
        INSERT INTO reviewer (name, type, notes)
        VALUES (%s, %s, %s)
        RETURNING reviewer_id
        """,
        (name, reviewer_type, notes),
    )
    return result["reviewer_id"]


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def new_change_group() -> str:
    """Return a fresh UUID string for grouping related log entries."""
    return str(uuid.uuid4())


def log_action(
    repo: Repository,
    reviewer_id: int,
    action: str,
    entity_type: str,
    entity_id: int,
    *,
    field_name: str | None = None,
    old_value: Any = None,
    new_value: Any = None,
    reason: str | None = None,
    change_group_id: str | None = None,
    session_ref: str | None = None,
) -> int:
    """
    Append one entry to conclusion_log. Returns the new log_id.

    Parameters
    ----------
    reviewer_id     : int   — who is making the change (use REVIEWER_PIPELINE
                              for automated pipeline steps)
    action          : str   — 'create' | 'update' | 'delete' | 'verify' | 'flag'
    entity_type     : str   — 'person' | 'relationship' | 'event' |
                              'person_recorded_person' |
                              'relationship_recorded_relationship' |
                              'event_record' | 'place_record'
    entity_id       : int   — primary key of the affected row
    field_name      : str   — required for 'update'; None for create/delete
    old_value       : any   — serialised to str; None on create
    new_value       : any   — serialised to str; None on delete
    reason          : str   — free-text explanation; encouraged for human/ai
    change_group_id : str   — UUID from new_change_group() grouping related entries
    session_ref     : str   — commit hash, Claude session ID, etc.
    """
    old_str = str(old_value) if old_value is not None else None
    new_str = str(new_value) if new_value is not None else None

    result = repo.execute_returning(
        """
        INSERT INTO conclusion_log (
            reviewer_id, action, entity_type, entity_id,
            field_name, old_value, new_value,
            reason, change_group_id, session_ref
        ) VALUES (
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s
        )
        RETURNING log_id
        """,
        (
            reviewer_id, action, entity_type, entity_id,
            field_name, old_str, new_str,
            reason, change_group_id, session_ref,
        ),
    )
    return result["log_id"]


def log_create(
    repo: Repository,
    reviewer_id: int,
    entity_type: str,
    entity_id: int,
    reason: str | None = None,
    change_group_id: str | None = None,
    session_ref: str | None = None,
) -> int:
    """Convenience wrapper: log a create action."""
    return log_action(
        repo, reviewer_id, "create", entity_type, entity_id,
        reason=reason,
        change_group_id=change_group_id,
        session_ref=session_ref,
    )


def log_update(
    repo: Repository,
    reviewer_id: int,
    entity_type: str,
    entity_id: int,
    field_name: str,
    old_value: Any,
    new_value: Any,
    reason: str | None = None,
    change_group_id: str | None = None,
    session_ref: str | None = None,
) -> int:
    """Convenience wrapper: log an update action."""
    return log_action(
        repo, reviewer_id, "update", entity_type, entity_id,
        field_name=field_name,
        old_value=old_value,
        new_value=new_value,
        reason=reason,
        change_group_id=change_group_id,
        session_ref=session_ref,
    )


def log_delete(
    repo: Repository,
    reviewer_id: int,
    entity_type: str,
    entity_id: int,
    reason: str | None = None,
    change_group_id: str | None = None,
    session_ref: str | None = None,
) -> int:
    """Convenience wrapper: log a delete action."""
    return log_action(
        repo, reviewer_id, "delete", entity_type, entity_id,
        reason=reason,
        change_group_id=change_group_id,
        session_ref=session_ref,
    )


def log_verify(
    repo: Repository,
    reviewer_id: int,
    entity_type: str,
    entity_id: int,
    reason: str | None = None,
    change_group_id: str | None = None,
    session_ref: str | None = None,
) -> int:
    """Convenience wrapper: log a verify action (junction row marked verified=1)."""
    return log_action(
        repo, reviewer_id, "verify", entity_type, entity_id,
        reason=reason,
        change_group_id=change_group_id,
        session_ref=session_ref,
    )


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_log_for_entity(
    repo: Repository,
    entity_type: str,
    entity_id: int,
) -> list[dict]:
    """Return all log entries for a given entity, oldest first."""
    return repo.fetch_all(
        """
        SELECT cl.*, r.name AS reviewer_name, r.type AS reviewer_type
        FROM conclusion_log cl
        JOIN reviewer r ON r.reviewer_id = cl.reviewer_id
        WHERE cl.entity_type = %s AND cl.entity_id = %s
        ORDER BY cl.created_at ASC
        """,
        (entity_type, entity_id),
    )


def get_log_for_change_group(
    repo: Repository,
    change_group_id: str,
) -> list[dict]:
    """Return all log entries belonging to a change group, oldest first."""
    return repo.fetch_all(
        """
        SELECT cl.*, r.name AS reviewer_name, r.type AS reviewer_type
        FROM conclusion_log cl
        JOIN reviewer r ON r.reviewer_id = cl.reviewer_id
        WHERE cl.change_group_id = %s
        ORDER BY cl.created_at ASC
        """,
        (change_group_id,),
    )
