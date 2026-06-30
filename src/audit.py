"""Audit logging for conclusion layer changes."""

from __future__ import annotations
from src.db.repository import Repository
from typing import Any, Optional
import uuid


class AuditLog:
    """Record changes to person, relationship, and event entities."""

    REVIEWER_SYSTEM = 1  # System reviewer ID for automated changes

    @staticmethod
    def log_create(
        repo: Repository,
        entity_type: str,
        entity_id: int,
        values: dict[str, Any],
        reason: str = "",
        reviewer_id: int = REVIEWER_SYSTEM,
        change_group_id: Optional[str] = None,
    ) -> None:
        """Log creation of an entity."""
        if not change_group_id:
            change_group_id = str(uuid.uuid4())

        for field_name, new_value in values.items():
            repo.execute(
                """
                INSERT INTO conclusion_log
                (reviewer_id, action, entity_type, entity_id, field_name, old_value, new_value, reason, change_group_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    reviewer_id,
                    "create",
                    entity_type,
                    entity_id,
                    field_name,
                    None,
                    str(new_value),
                    reason,
                    change_group_id,
                ),
            )

    @staticmethod
    def log_update(
        repo: Repository,
        entity_type: str,
        entity_id: int,
        field_name: str,
        old_value: Any,
        new_value: Any,
        reason: str = "",
        reviewer_id: int = REVIEWER_SYSTEM,
        change_group_id: Optional[str] = None,
    ) -> None:
        """Log update to an entity field."""
        if not change_group_id:
            change_group_id = str(uuid.uuid4())

        repo.execute(
            """
            INSERT INTO conclusion_log
            (reviewer_id, action, entity_type, entity_id, field_name, old_value, new_value, reason, change_group_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                reviewer_id,
                "update",
                entity_type,
                entity_id,
                field_name,
                str(old_value) if old_value is not None else None,
                str(new_value),
                reason,
                change_group_id,
            ),
        )

    @staticmethod
    def log_delete(
        repo: Repository,
        entity_type: str,
        entity_id: int,
        reason: str = "",
        reviewer_id: int = REVIEWER_SYSTEM,
        change_group_id: Optional[str] = None,
    ) -> None:
        """Log deletion of an entity."""
        if not change_group_id:
            change_group_id = str(uuid.uuid4())

        repo.execute(
            """
            INSERT INTO conclusion_log
            (reviewer_id, action, entity_type, entity_id, field_name, old_value, new_value, reason, change_group_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                reviewer_id,
                "delete",
                entity_type,
                entity_id,
                None,
                None,
                None,
                reason,
                change_group_id,
            ),
        )

    @staticmethod
    def get_logs(
        repo: Repository,
        entity_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Retrieve audit logs."""
        query = "SELECT * FROM conclusion_log WHERE 1=1"
        params = []

        if entity_type:
            query += " AND entity_type = %s"
            params.append(entity_type)

        if entity_id:
            query += " AND entity_id = %s"
            params.append(entity_id)

        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)

        return repo.fetch_all(query, tuple(params))
