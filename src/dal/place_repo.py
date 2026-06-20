"""
GRA — DAL: place_authority and place_record queries.

All SQL touching place_authority or place_record lives here.
"""

from __future__ import annotations

import psycopg2.extensions


def get_authority_count(conn: psycopg2.extensions.connection) -> int:
    """Return the number of rows in place_authority."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM place_authority")
        return cur.fetchone()["count"]


def get_all_authorities(conn: psycopg2.extensions.connection) -> list[dict]:
    """
    Return all place_authority rows as dicts with keys:
        place_id, name_en, place_type
    """
    with conn.cursor() as cur:
        cur.execute("SELECT place_id, name_en, place_type FROM place_authority")
        return cur.fetchall()


def get_unlinked_place_tokens(
    conn: psycopg2.extensions.connection,
) -> tuple[dict[str, dict], int]:
    """
    Collect all distinct place_as_recorded strings from record,
    grouped by raw value. Normalisation is the caller's responsibility
    (place_resolution.py applies Jaro-Winkler normalisation before calling).

    Returns:
        token_map: {raw_string: {"raw": str, "record_ids": [int]}}
        blank_count: number of records with null/blank place_as_recorded
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT record_id, place_as_recorded FROM record "
            "WHERE place_as_recorded IS NOT NULL AND trim(place_as_recorded) != ''"
        )
        rows = cur.fetchall()

        cur.execute(
            "SELECT COUNT(*) FROM record "
            "WHERE place_as_recorded IS NULL OR trim(place_as_recorded) = ''"
        )
        blank_count = cur.fetchone()["count"]

    token_map: dict[str, dict] = {}
    for row in rows:
        raw = row["place_as_recorded"]
        if raw not in token_map:
            token_map[raw] = {"raw": raw, "record_ids": []}
        token_map[raw]["record_ids"].append(row["record_id"])

    return token_map, blank_count


def get_linked_record_ids(conn: psycopg2.extensions.connection) -> set[int]:
    """Return the set of record_ids already present in place_record."""
    with conn.cursor() as cur:
        cur.execute("SELECT record_id FROM place_record")
        return {row["record_id"] for row in cur.fetchall()}


def get_place_for_records(conn: psycopg2.extensions.connection) -> dict[int, int | None]:
    """
    Return a dict mapping record_id → place_id for all rows in place_record.
    Used by household_inference to attach a resolved place_id to each Event.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT record_id, place_id FROM place_record")
        return {row["record_id"]: row["place_id"] for row in cur.fetchall()}


def insert_place_record(
    conn: psycopg2.extensions.connection,
    place_id: int,
    record_id: int,
    score: float,
    score_version: str,
) -> None:
    """Insert a single place_record linkage row."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO place_record "
            "(place_id, record_id, score, score_version, verified) "
            "VALUES (%s, %s, %s, %s, 0)",
            (place_id, record_id, score, score_version),
        )
