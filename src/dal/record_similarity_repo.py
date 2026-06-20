"""
GRA — DAL: record_similarity queries (evidence layer).

All SQL touching record_similarity lives here.

RecordSimilarity records an algorithmic measurement between two Records.
It has no conclusion-layer counterpart by design — it captures a measurement,
not an assertion. Neither source record is marked 'verified'.
"""

from __future__ import annotations

import psycopg2.extensions


def insert_record_similarity(
    conn: psycopg2.extensions.connection,
    record_id_1: int,
    record_id_2: int,
    score: float,
    score_version: str,
    notes: str | None = None,
) -> int:
    """
    Insert a RecordSimilarity row and return the generated record_similarity_id.

    record_id_1 must differ from record_id_2 (enforced by schema CHECK).
    Caller is responsible for canonical ordering (e.g. lower id first) to
    avoid duplicate measurements from different orderings.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO record_similarity "
            "(record_id_1, record_id_2, score, score_version, notes) "
            "VALUES (%s, %s, %s, %s, %s) "
            "RETURNING record_similarity_id",
            (record_id_1, record_id_2, score, score_version, notes),
        )
        return cur.fetchone()["record_similarity_id"]


def get_similarities_for_record(
    conn: psycopg2.extensions.connection,
    record_id: int,
    min_score: float = 0.0,
) -> list[dict]:
    """
    Return all RecordSimilarity rows that reference record_id on either side,
    filtered to score >= min_score, ordered by score descending.

    Row keys: record_similarity_id, record_id_1, record_id_2,
              score, score_version, notes
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT record_similarity_id, record_id_1, record_id_2,
                   score, score_version, notes
            FROM record_similarity
            WHERE (record_id_1 = %s OR record_id_2 = %s)
              AND score >= %s
            ORDER BY score DESC
            """,
            (record_id, record_id, min_score),
        )
        return cur.fetchall()


def get_top_pairs(
    conn: psycopg2.extensions.connection,
    min_score: float = 0.0,
    limit: int = 1000,
) -> list[dict]:
    """
    Return the highest-scoring RecordSimilarity pairs above min_score.
    Used for exploratory analysis and linkage bootstrapping.

    Row keys: record_similarity_id, record_id_1, record_id_2,
              score, score_version
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT record_similarity_id, record_id_1, record_id_2,
                   score, score_version
            FROM record_similarity
            WHERE score >= %s
            ORDER BY score DESC
            LIMIT %s
            """,
            (min_score, limit),
        )
        return cur.fetchall()
