"""
Database-agnostic repository pattern for GRA.

Defines interfaces for data access, with implementations for PostgreSQL and Supabase.
This abstracts away database choice so business logic is database-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class Repository(ABC):
    """Base repository interface — all database operations go through here."""

    @abstractmethod
    def fetch_one(self, query: str, params: tuple | None = None) -> Optional[dict]:
        """Fetch a single row as a dict."""
        pass

    @abstractmethod
    def fetch_all(self, query: str, params: tuple | None = None) -> list[dict]:
        """Fetch all rows as dicts."""
        pass

    @abstractmethod
    def execute(self, query: str, params: tuple | None = None) -> None:
        """Execute a query (INSERT/UPDATE/DELETE without RETURNING)."""
        pass

    @abstractmethod
    def execute_returning(self, query: str, params: tuple | None = None) -> Optional[dict]:
        """Execute and return first row (INSERT...RETURNING, UPDATE...RETURNING, etc.)."""
        pass

    @abstractmethod
    def commit(self) -> None:
        """Commit transaction."""
        pass

    @abstractmethod
    def rollback(self) -> None:
        """Rollback transaction."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close connection."""
        pass

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit: commit if no exception."""
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        # Don't close — allows reuse of the repository within a function
        return False
