"""
GRA — DAL: place_authority and place_record queries.

All SQL touching place_authority or place_record lives here.
"""

from __future__ import annotations

import sqlite3


def get_authority_count(conn: sqlite3.Connection) -> int:
    """Return the number of rows in place_authority."""
    return conn.execute("SELECT COUNT(*) FROM place_authority").fetchone()[0]


def get_all_authorities(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """
    Return all place_authority rows as Row objects with keys:
        place_id, name_en, place_type
    """
    return conn.execute(
        "SELECT place_id, name_en, place_type FROM place_authority"
    ).fetchall()


def get_unlinked_place_tokens(
    conn: sqlite3.Connection,
) -> tuple[dict[str, dict], int]:
    """
    Collect all distinct place_as_recorded strings from record,
    grouped by normalised token. Normalisation is the caller's responsibility
    (place_resolution.py applies Jaro-Winkler normalisation before calling).

    Returns:
        token_map: {raw_string: {"raw": str, "record_ids": [int]}}
        blank_count: number of records with null/blank place_as_recorded
    """
    rows = conn.execute(
        "SELECT record_id, place_as_recorded FROM record "
        "WHERE place_as_recorded IS NOT NULL AND trim(place_as_recorded) != ''"
    ).fetchall()

    blank_count = conn.execute(
        "SELECT COUNT(*) FROM record "
        "WHERE place_as_recorded IS NULL OR trim(place_as_recorded) = ''"
    ).fetchone()[0]

    # Return raw strings grouped by raw value; caller normalises
    token_map: dict[str, dict] = {}
    for row in rows:
        raw = row["place_as_recorded"]
        if raw not in token_map:
            token_map[raw] = {"raw": raw, "record_ids": []}
        token_map[raw]["record_ids"].append(row["record_id"])

    return token_map, blank_count


def get_linked_record_ids(conn: sqlite3.Connection) -> set[int]:
    """Return the set of record_ids already present in place_record."""
    return {
        row[0]
        for row in conn.execute("SELECT record_id FROM place_record").fetchall()
    }


def get_place_for_records(conn: sqlite3.Connection) -> dict[int, int | None]:
    """
    Return a dict mapping record_id → place_id for all rows in place_record.
    Used by household_inference to attach a resolved place_id to each Event.
    """
    return {
        row["record_id"]: row["place_id"]
        for row in conn.execute(
            "SELECT record_id, place_id FROM place_record"
        ).fetchall()
    }


def insert_place_record(
    conn: sqlite3.Connection,
    place_id: int,
    record_id: int,
    score: float,
    score_version: str,
) -> None:
    """Insert a single place_record linkage row."""
    conn.execute(
        "INSERT INTO place_record "
        "(place_id, record_id, score, score_version, verified) "
        "VALUES (?, ?, ?, ?, 0)",
        (place_id, record_id, score, score_version),
    )
