"""PostgreSQL repository implementation using psycopg2."""

from __future__ import annotations

from typing import Optional

import psycopg2
import psycopg2.extras

from src.db.repository import Repository


class PostgresRepository(Repository):
    """Database access layer for PostgreSQL via psycopg2."""

    def __init__(self, conn: psycopg2.extensions.connection):
        self._conn = conn

    def fetch_one(self, query: str, params: tuple | None = None) -> Optional[dict]:
        """Fetch a single row."""
        with self._conn.cursor() as cur:
            cur.execute(query, params or ())
            row = cur.fetchone()
            return dict(row) if row else None

    def fetch_all(self, query: str, params: tuple | None = None) -> list[dict]:
        """Fetch all rows."""
        with self._conn.cursor() as cur:
            cur.execute(query, params or ())
            return [dict(row) for row in cur.fetchall()]

    def execute(self, query: str, params: tuple | None = None) -> None:
        """Execute a query."""
        with self._conn.cursor() as cur:
            cur.execute(query, params or ())

    def execute_returning(self, query: str, params: tuple | None = None) -> Optional[dict]:
        """Execute and return first row."""
        with self._conn.cursor() as cur:
            cur.execute(query, params or ())
            row = cur.fetchone()
            return dict(row) if row else None

    def commit(self) -> None:
        """Commit transaction."""
        self._conn.commit()

    def rollback(self) -> None:
        """Rollback transaction."""
        self._conn.rollback()

    def close(self) -> None:
        """Close connection."""
        self._conn.close()
