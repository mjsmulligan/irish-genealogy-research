"""
GRA — DAL: source queries (foundational layer).

All SQL touching the source table lives here.
"""

from __future__ import annotations

from src.db.repository import Repository


def get_source(repo: Repository, source_id: int) -> dict | None:
    """
    Return the source row for source_id, or None if it does not exist.

    Row keys: source_id, repository_id, title, type, coverage_from,
    coverage_to, source_url, record_url_template, source_parameters,
    record_parameter_names, column_schema, citation, notes
    """
    return repo.fetch_one("SELECT * FROM source WHERE source_id = %s", (source_id,))
