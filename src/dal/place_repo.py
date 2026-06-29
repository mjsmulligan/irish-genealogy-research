"""
GRA — DAL: place_authority and place_record queries.

All SQL touching place_authority or place_record lives here.
"""

from __future__ import annotations

from src.db.repository import Repository


def get_authority_count(repo: Repository) -> int:
    """Return the number of rows in place_authority."""
    result = repo.fetch_one("SELECT COUNT(*) FROM place_authority")
    return result["count"]


def get_all_authorities(repo: Repository) -> list[dict]:
    """
    Return all place_authority rows as dicts with keys:
        place_id, name_en, place_type
    """
    return repo.fetch_all("SELECT place_id, name_en, place_type FROM place_authority")


def get_linked_record_ids(repo: Repository) -> set[int]:
    """Return the set of record_ids already present in place_record."""
    rows = repo.fetch_all("SELECT record_id FROM place_record")
    return {row["record_id"] for row in rows}


def get_place_for_records(repo: Repository) -> dict[int, int | None]:
    """
    Return a dict mapping record_id → place_id for all rows in place_record.
    Used by household_inference to attach a resolved place_id to each Event.
    """
    rows = repo.fetch_all("SELECT record_id, place_id FROM place_record")
    return {row["record_id"]: row["place_id"] for row in rows}


def insert_place_record(
    repo: Repository,
    place_id: int,
    record_id: int,
    score: float,
    score_version: str,
) -> None:
    """Insert a single place_record linkage row."""
    repo.execute(
        "INSERT INTO place_record "
        "(place_id, record_id, score, score_version, verified) "
        "VALUES (%s, %s, %s, %s, 0)",
        (place_id, record_id, score, score_version),
    )
