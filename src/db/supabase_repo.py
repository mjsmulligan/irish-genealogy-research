"""Supabase repository implementation using REST API."""

from __future__ import annotations

from typing import Optional

from supabase import Client

from src.db.repository import Repository


class SupabaseRepository(Repository):
    """Database access layer for Supabase via REST API."""

    def __init__(self, client: Client):
        self._client = client

    def fetch_one(self, query: str, params: tuple | None = None) -> Optional[dict]:
        """Fetch a single row."""
        rows = self.fetch_all(query, params)
        return rows[0] if rows else None

    def fetch_all(self, query: str, params: tuple | None = None) -> list[dict]:
        """Fetch all rows via SQL RPC."""
        query_normalized = " ".join(query.split())
        query_with_params = self._substitute_params(query_normalized, params)

        result = self._client.rpc("execute_query", {"sql_text": query_with_params}).execute()
        return result.data if result.data else []

    def execute(self, query: str, params: tuple | None = None) -> None:
        """Execute a query (no results)."""
        query_normalized = " ".join(query.split())
        query_with_params = self._substitute_params(query_normalized, params)

        self._client.rpc("execute_sql", {"sql_text": query_with_params}).execute()

    def execute_returning(self, query: str, params: tuple | None = None) -> Optional[dict]:
        """Execute and return first row (INSERT...RETURNING, UPDATE...RETURNING, etc.)."""
        query_normalized = " ".join(query.split())
        query_with_params = self._substitute_params(query_normalized, params)

        # For INSERT...RETURNING, use execute_returning RPC which doesn't wrap the query
        try:
            result = self._client.rpc("execute_returning", {"sql_text": query_with_params}).execute()
            return result.data[0] if result.data else None
        except Exception:
            # Fallback: try with execute_query (wraps in subquery)
            result = self._client.rpc("execute_query", {"sql_text": query_with_params}).execute()
            return result.data[0] if result.data else None

    def commit(self) -> None:
        """Commit (no-op for Supabase)."""
        pass

    def rollback(self) -> None:
        """Rollback (no-op for Supabase)."""
        pass

    def close(self) -> None:
        """Close connection (no-op for Supabase)."""
        pass

    @staticmethod
    def _substitute_params(query: str, params: tuple | None = None) -> str:
        """Substitute %s placeholders with actual values."""
        if not params:
            return query

        # Flatten if nested tuple
        if len(params) == 1 and isinstance(params[0], (tuple, list)):
            params = params[0]

        formatted = []
        for param in params:
            if param is None:
                formatted.append("NULL")
            elif isinstance(param, str):
                escaped = param.replace("'", "''")
                formatted.append(f"'{escaped}'")
            elif isinstance(param, bool):
                formatted.append("true" if param else "false")
            else:
                formatted.append(str(param))

        result = query
        for val in formatted:
            result = result.replace("%s", val, 1)

        return result
