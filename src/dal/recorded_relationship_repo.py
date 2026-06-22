"""
GRA — DAL: recorded_relationship queries (evidence layer).

All SQL touching recorded_relationship lives here.

RecordedRelationship captures intra-household role pairs and cross-census
similarity candidates at the evidence layer. It has no conclusion-layer
counterpart by design — it is linked to the Relationship conclusion via
the relationship_recorded_relationship junction table.
"""

from __future__ import annotations

import psycopg2.extensions


def insert_recorded_relationship(
    conn: psycopg2.extensions.connection,
    recorded_person_id_1: int,
    recorded_person_id_2: int,
    rel_type: str,
    score: float | None = None,
    score_version: str | None = None,
    notes: str | None = None,
) -> int:
    """
    Insert a RecordedRelationship row and return the generated
    recorded_relationship_id.

    rel_type vocabulary: 'couple', 'parent_child', 'sibling', 'similarity'
    score: Prior score for role-pair types (0.75-0.90), Splink score for 'similarity'
    score_version: Algorithm identifier for provenance tracking
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO recorded_relationship "
            "(recorded_person_id_1, recorded_person_id_2, type, score, score_version, notes) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "RETURNING recorded_relationship_id",
            (recorded_person_id_1, recorded_person_id_2, rel_type,
             score, score_version, notes),
        )
        return cur.fetchone()["recorded_relationship_id"]


def get_recorded_relationships_for_record(
    conn: psycopg2.extensions.connection,
    record_id: int,
) -> list[dict]:
    """
    Return all RecordedRelationship rows where both endpoints belong to
    the given record_id.

    Row keys: recorded_relationship_id, recorded_person_id_1,
              recorded_person_id_2, type, score, score_version, notes
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT rr.*
            FROM recorded_relationship rr
            JOIN recorded_person rp1
              ON rp1.recorded_person_id = rr.recorded_person_id_1
            JOIN recorded_person rp2
              ON rp2.recorded_person_id = rr.recorded_person_id_2
            WHERE rp1.record_id = %s
              AND rp2.record_id = %s
            ORDER BY rr.recorded_relationship_id
            """,
            (record_id, record_id),
        )
        return cur.fetchall()


def get_similarity_pairs(
    conn: psycopg2.extensions.connection,
    min_score: float = 0.0,
) -> list[dict]:
    """
    Return all recorded_relationship rows of type 'similarity' above
    min_score, ordered by score descending.

    Used by the linkage pipeline to retrieve cross-census candidate pairs
    without re-running Splink.

    Row keys: recorded_relationship_id, recorded_person_id_1,
              recorded_person_id_2, score, score_version
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT recorded_relationship_id,
                   recorded_person_id_1,
                   recorded_person_id_2,
                   score,
                   score_version
            FROM recorded_relationship
            WHERE type = 'similarity'
              AND score >= %s
            ORDER BY score DESC
            """,
            (min_score,),
        )
        return cur.fetchall()
