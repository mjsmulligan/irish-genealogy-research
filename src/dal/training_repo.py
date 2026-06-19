"""
GRA — DAL: training_labels queries.

All SQL touching training_labels lives here.

Key fix: get_proposals() queries WHERE decision = 'proposed', not verified = 0.
The bootstrap explicitly called this out as a deferred fix that lands here.
"""

from __future__ import annotations

import sqlite3


def write_proposal(
    conn: sqlite3.Connection,
    person_id_1: int,
    person_id_2: int,
    score: float,
    score_version: str,
) -> None:
    """
    Write a pending linkage proposal to training_labels.

    person_id_1 must be < person_id_2 (enforced by caller — linkage.py
    always passes min/max ordered ids).

    Uses INSERT OR IGNORE so duplicate proposals (same pair, different
    pipeline runs) are silently dropped.
    """
    conn.execute(
        """
        INSERT OR IGNORE INTO training_labels
            (person_id_1, person_id_2, score, score_version, decision)
        VALUES (?, ?, ?, ?, 'proposed')
        """,
        (person_id_1, person_id_2, score, score_version),
    )


def get_proposals(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """
    Return all pending linkage proposals awaiting researcher review.

    FIX: queries WHERE decision = 'proposed', not WHERE verified = 0.
    The verified column tracks researcher sign-off on committed conclusions;
    it is not the correct signal for proposal state. decision = 'proposed'
    is the correct predicate (set by write_proposal, cleared on accept/reject).

    Row keys: label_id, person_id_1, person_id_2, score, score_version,
              decision, note, created_at, reviewed_at
    """
    return conn.execute(
        """
        SELECT label_id, person_id_1, person_id_2, score, score_version,
               decision, note, created_at, reviewed_at
        FROM training_labels
        WHERE decision = 'proposed'
        ORDER BY score DESC
        """
    ).fetchall()


def delete_pair(
    conn: sqlite3.Connection,
    canonical_id: int,
    duplicate_id: int,
) -> None:
    """
    Delete the direct training_labels proposal between a pair being merged.
    Called during _merge_persons — the merge supersedes the proposal.
    Handles both orderings of the pair.
    """
    conn.execute(
        """
        DELETE FROM training_labels
        WHERE (person_id_1 = ? AND person_id_2 = ?)
           OR (person_id_1 = ? AND person_id_2 = ?)
        """,
        (canonical_id, duplicate_id, duplicate_id, canonical_id),
    )


def get_stale_rows(
    conn: sqlite3.Connection,
    duplicate_id: int,
) -> list[sqlite3.Row]:
    """
    Return all training_labels rows that reference duplicate_id on either side.
    Called during _merge_persons to find proposals that need repointing.

    Row keys: label_id, person_id_1, person_id_2, score, score_version,
              decision, note, created_at, reviewed_at
    """
    return conn.execute(
        """
        SELECT label_id, person_id_1, person_id_2, score, score_version,
               decision, note, created_at, reviewed_at
        FROM training_labels
        WHERE person_id_1 = ? OR person_id_2 = ?
        """,
        (duplicate_id, duplicate_id),
    ).fetchall()


def delete_by_ids(
    conn: sqlite3.Connection,
    label_ids: list[int],
) -> None:
    """Delete training_labels rows by label_id. Used during merge repointing."""
    if not label_ids:
        return
    placeholders = ",".join("?" * len(label_ids))
    conn.execute(
        f"DELETE FROM training_labels WHERE label_id IN ({placeholders})",
        label_ids,
    )


def reinsert_repointed(
    conn: sqlite3.Connection,
    stale_rows: list[sqlite3.Row],
    canonical_id: int,
    duplicate_id: int,
) -> None:
    """
    Reinsert training_labels rows with duplicate_id replaced by canonical_id.

    Endpoints are re-sorted (lo, hi) to maintain the person_id_1 < person_id_2
    invariant. Self-referential rows (lo == hi after substitution) are dropped.

    Called after delete_by_ids() during _merge_persons.
    """
    for row in stale_rows:
        p1 = canonical_id if row["person_id_1"] == duplicate_id else row["person_id_1"]
        p2 = canonical_id if row["person_id_2"] == duplicate_id else row["person_id_2"]
        lo, hi = min(p1, p2), max(p1, p2)
        if lo == hi:
            continue  # self-referential after substitution — drop
        conn.execute(
            """
            INSERT OR IGNORE INTO training_labels
                (person_id_1, person_id_2, score, score_version,
                 decision, note, created_at, reviewed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (lo, hi, row["score"], row["score_version"],
             row["decision"], row["note"], row["created_at"], row["reviewed_at"]),
        )
