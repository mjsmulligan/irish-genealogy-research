"""
GRA — Conclusion Layer: Household Utilities

Shared helpers used by both relationship_resolution.py and
household_resolution.py. Extracted to avoid duplication.

Functions:
    get_household_members   — fetch RecordedPersons + Person linkage for a Record
    ensure_relationship     — idempotently create Relationship + provenance
    create_relationships_from_household — derive couple/parent_child/sibling conclusions
"""

from __future__ import annotations

from typing import Optional

from src.db.repository import Repository
from src.constants import SCORE_VERSION_ROLE_PAIR


# ---------------------------------------------------------------------------
# Household member fetch
# ---------------------------------------------------------------------------

def get_household_members(
    repo: Repository,
    record_id: int,
) -> list[dict]:
    """
    Get all RecordedPersons in a household with their Person linkage if it exists.

    Returns list of dicts with keys: recorded_person_id, name_as_recorded, role,
    age, sex_as_recorded, person_id (or None if orphan).
    """
    return repo.fetch_all(
        """
        SELECT
            rp.recorded_person_id,
            rp.name_as_recorded,
            rp.role,
            rp.age,
            rp.sex_as_recorded,
            prp.person_id
        FROM recorded_person rp
        LEFT JOIN person_recorded_person prp
            ON prp.recorded_person_id = rp.recorded_person_id
        WHERE rp.record_id = %s
        ORDER BY
            CASE rp.role
                WHEN 'head' THEN 1
                WHEN 'spouse' THEN 2
                WHEN 'son' THEN 3
                WHEN 'daughter' THEN 4
                ELSE 5
            END,
            rp.age DESC NULLS LAST
        """,
        (record_id,),
    )


# ---------------------------------------------------------------------------
# Relationship creation
# ---------------------------------------------------------------------------

def ensure_relationship(
    repo: Repository,
    person_id_1: int,
    person_id_2: int,
    rel_type: str,
) -> Optional[int]:
    """
    Ensure a Relationship exists between two Persons and populate its evidence
    provenance in relationship_recorded_relationship.

    Evidence lookup: find all RecordedRelationships of matching type whose two
    RecordedPersons are linked to person_id_1 and person_id_2 respectively (in
    either order). These are the ingest-time role-pair rows created by
    role_relationships.py.

    Returns relationship_id if newly created, None if it already existed.
    (Provenance rows are written either way for any new RecordedRelationships
    not yet linked.)
    """
    from src.dal.relationship_repo import insert_relationship_recorded_relationship

    # Check if relationship already exists (either direction)
    existing = repo.fetch_one(
        """
        SELECT relationship_id
        FROM relationship
        WHERE type = %s
          AND ((person_id_1 = %s AND person_id_2 = %s)
            OR (person_id_1 = %s AND person_id_2 = %s))
        """,
        (rel_type, person_id_1, person_id_2, person_id_2, person_id_1),
    )

    if existing:
        rel_id = existing["relationship_id"]
        created = False
    else:
        result = repo.execute_returning(
            """
            INSERT INTO relationship (type, person_id_1, person_id_2)
            VALUES (%s, %s, %s)
            RETURNING relationship_id
            """,
            (rel_type, person_id_1, person_id_2),
        )
        rel_id = result["relationship_id"]
        created = True

    # Populate provenance: find RecordedRelationships of this type linking the
    # two Persons' RecordedPersons, then write to relationship_recorded_relationship.
    # ON CONFLICT DO NOTHING in the DAL function makes this idempotent.
    rr_rows = repo.fetch_all(
        """
        SELECT rr.recorded_relationship_id, rr.score
        FROM recorded_relationship rr
        JOIN person_recorded_person prp1
            ON prp1.recorded_person_id = rr.recorded_person_id_1
        JOIN person_recorded_person prp2
            ON prp2.recorded_person_id = rr.recorded_person_id_2
        WHERE rr.type = %s
          AND (
              (prp1.person_id = %s AND prp2.person_id = %s)
           OR (prp1.person_id = %s AND prp2.person_id = %s)
          )
        """,
        (rel_type, person_id_1, person_id_2, person_id_2, person_id_1),
    )

    for rr in rr_rows:
        insert_relationship_recorded_relationship(
            repo,
            relationship_id=rel_id,
            recorded_relationship_id=rr["recorded_relationship_id"],
            score=rr["score"] if rr["score"] is not None else 0.0,
            score_version=SCORE_VERSION_ROLE_PAIR,
        )

    return rel_id if created else None


def create_relationships_from_household(
    repo: Repository,
    household_members: list[dict],
) -> int:
    """
    Create Relationships based on household roles.

    Only creates Relationships for members who have Persons.

    Returns count of Relationships created.
    """
    count = 0

    members_with_persons = [m for m in household_members if m.get("person_id")]

    if len(members_with_persons) < 2:
        return 0

    head = next((m for m in members_with_persons if m["role"] == "head"), None)
    spouse = next((m for m in members_with_persons if m["role"] == "spouse"), None)

    # Couple
    if head and spouse and head["person_id"] != spouse["person_id"]:
        rel_id = ensure_relationship(repo, head["person_id"], spouse["person_id"], "couple")
        if rel_id:
            count += 1

    # Parent-child
    children = [m for m in members_with_persons if m["role"] in ("son", "daughter")]
    for child in children:
        if head and head["person_id"] != child["person_id"]:
            rel_id = ensure_relationship(repo, head["person_id"], child["person_id"], "parent_child")
            if rel_id:
                count += 1
        if spouse and spouse["person_id"] != child["person_id"]:
            rel_id = ensure_relationship(repo, spouse["person_id"], child["person_id"], "parent_child")
            if rel_id:
                count += 1

    # Sibling
    for i, child1 in enumerate(children):
        for child2 in children[i + 1:]:
            if child1["person_id"] == child2["person_id"]:
                continue
            rel_id = ensure_relationship(repo, child1["person_id"], child2["person_id"], "sibling")
            if rel_id:
                count += 1

    return count
