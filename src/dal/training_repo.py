"""
GRA — DAL: training_labels queries.

All SQL touching training_labels lives here.

Note: training_labels is conceptually retired (see conceptual_model.md §4.9
and ROADMAP item 11). This DAL is retained pending implementation-phase removal.

Key fix: get_proposals() queries WHERE decision = 'proposed', not verified = 0.
The verified column tracks researcher sign-off on committed conclusions;
it is not the correct signal for proposal state.
"""

from __future__ import annotations

import psycopg2.extensions


def write_proposal(
    conn: psycopg2.extensions.connection,
    person_id_1: int,
    person_id_2: int,
    score: float,
    score_version: str,
) -> None:
    """
    Write a pending linkage proposal to training_labels.

    person_id_1 must be < person_id_2 (enforced by caller — linkage.py
    always passes min/max ordered ids).

    ON CONFLICT DO NOTHING — duplicate proposals (same pair, different
    pipeline runs) are silently dropped.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO training_labels
                (person_id_1, person_id_2, score, score_version, decision)
            VALUES (%s, %s, %s, %s, 'proposed')
            ON CONFLICT DO NOTHING
            """,
            (person_id_1, person_id_2, score, score_version),
        )


def get_proposals(conn: psycopg2.extensions.connection) -> list[dict]:
    """
    Return all pending linkage proposals awaiting researcher review.

    Queries WHERE decision = 'proposed' — the correct predicate for proposal
    state. The verified column is not the correct signal here.

    Row keys: label_id, person_id_1, person_id_2, score, score_version,
              decision, note, created_at, reviewed_at
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT label_id, person_id_1, person_id_2, score, score_version,
                   decision, note, created_at, reviewed_at
            FROM training_labels
            WHERE decision = 'proposed'
            ORDER BY score DESC
            """
        )
        return cur.fetchall()


def delete_pair(
    conn: psycopg2.extensions.connection,
    canonical_id: int,
    duplicate_id: int,
) -> None:
    """
    Delete the direct training_labels proposal between a pair being merged.
    Called during _merge_persons — the merge supersedes the proposal.
    Handles both orderings of the pair.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM training_labels
            WHERE (person_id_1 = %s AND person_id_2 = %s)
               OR (person_id_1 = %s AND person_id_2 = %s)
            """,
            (canonical_id, duplicate_id, duplicate_id, canonical_id),
        )


def get_stale_rows(
    conn: psycopg2.extensions.connection,
    duplicate_id: int,
) -> list[dict]:
    """
    Return all training_labels rows that reference duplicate_id on either side.
    Called during _merge_persons to find proposals that need repointing.

    Row keys: label_id, person_id_1, person_id_2, score, score_version,
              decision, note, created_at, reviewed_at
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT label_id, person_id_1, person_id_2, score, score_version,
                   decision, note, created_at, reviewed_at
            FROM training_labels
            WHERE person_id_1 = %s OR person_id_2 = %s
            """,
            (duplicate_id, duplicate_id),
        )
        return cur.fetchall()


def delete_by_ids(
    conn: psycopg2.extensions.connection,
    label_ids: list[int],
) -> None:
    """Delete training_labels rows by label_id. Used during merge repointing."""
    if not label_ids:
        return
    placeholders = ",".join(["%s"] * len(label_ids))
    with conn.cursor() as cur:
        cur.execute(
            f"DELETE FROM training_labels WHERE label_id IN ({placeholders})",
            label_ids,
        )


def reinsert_repointed(
    conn: psycopg2.extensions.connection,
    stale_rows: list[dict],
    canonical_id: int,
    duplicate_id: int,
) -> None:
    """
    Reinsert training_labels rows with duplicate_id replaced by canonical_id.

    Endpoints are re-sorted (lo, hi) to maintain the person_id_1 < person_id_2
    invariant. Self-referential rows (lo == hi after substitution) are dropped.

    Called after delete_by_ids() during _merge_persons.
    """
    with conn.cursor() as cur:
        for row in stale_rows:
            p1 = canonical_id if row["person_id_1"] == duplicate_id else row["person_id_1"]
            p2 = canonical_id if row["person_id_2"] == duplicate_id else row["person_id_2"]
            lo, hi = min(p1, p2), max(p1, p2)
            if lo == hi:
                continue  # self-referential after substitution — drop
            cur.execute(
                """
                INSERT INTO training_labels
                    (person_id_1, person_id_2, score, score_version,
                     decision, note, created_at, reviewed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (lo, hi, row["score"], row["score_version"],
                 row["decision"], row["note"], row["created_at"], row["reviewed_at"]),
            )
