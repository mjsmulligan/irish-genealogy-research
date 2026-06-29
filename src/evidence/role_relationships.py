"""
GRA — Evidence Layer: Role-Relationship Assignment

Derives RecordedRelationship rows from the role pairs within a census
household Record at ingest time. This replaces the relationship-creation
step that was previously bundled into household_inference.py, which wrote
Relationship *conclusions* too eagerly. RecordedRelationship is the correct
evidence-layer object for this: it captures the structural assertion from the
record before any Person conclusion exists.

The role-pair table is drawn from reconstruction_algorithms.md §6.1.
All prior scores come from src/constants.py.

Entry point:
    assign_role_relationships(conn, record_id) -> RoleRelationshipResult
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.constants import (
    SCORE_VERSION_ROLE_PAIR,
    SCORE_ROLE_COUPLE,
    SCORE_ROLE_PARENT_CHILD_HEAD,
    SCORE_ROLE_PARENT_CHILD_SPOUSE,
    SCORE_ROLE_SIBLING_DIRECT,
    SCORE_ROLE_SIBLING_INFERRED,
)
from src.db.repository import Repository
from src.dal.record_repo import get_recorded_persons_for_record
from src.dal.recorded_relationship_repo import insert_recorded_relationship


# ---------------------------------------------------------------------------
# Role-pair rule table
#
# Each entry: (role_1, role_2, rel_type, score, note)
# role_1 and role_2 are unordered — the matching logic checks both orderings.
# rel_type vocabulary: 'couple', 'parent_child', 'sibling'
# ---------------------------------------------------------------------------

_ROLE_PAIR_RULES: list[tuple[str, str, str, float, str]] = [
    # (role_1, role_2, rel_type, score, note)
    ("head",    "spouse",   "couple",       SCORE_ROLE_COUPLE,               "head+spouse → couple"),
    ("head",    "son",      "parent_child", SCORE_ROLE_PARENT_CHILD_HEAD,    "head+son → parent_child (head=parent)"),
    ("head",    "daughter", "parent_child", SCORE_ROLE_PARENT_CHILD_HEAD,    "head+daughter → parent_child (head=parent)"),
    ("head",    "mother",   "parent_child", SCORE_ROLE_PARENT_CHILD_HEAD,    "head+mother → parent_child (mother=parent)"),
    ("head",    "father",   "parent_child", SCORE_ROLE_PARENT_CHILD_HEAD,    "head+father → parent_child (father=parent)"),
    ("spouse",  "son",      "parent_child", SCORE_ROLE_PARENT_CHILD_SPOUSE,  "spouse+son → parent_child (spouse=parent)"),
    ("spouse",  "daughter", "parent_child", SCORE_ROLE_PARENT_CHILD_SPOUSE,  "spouse+daughter → parent_child (spouse=parent)"),
    ("head",    "sibling",  "sibling",      SCORE_ROLE_SIBLING_DIRECT,       "head+sibling → sibling"),
    ("son",     "son",      "sibling",      SCORE_ROLE_SIBLING_INFERRED,     "son+son → sibling (inferred)"),
    ("daughter","daughter", "sibling",      SCORE_ROLE_SIBLING_INFERRED,     "daughter+daughter → sibling (inferred)"),
    ("son",     "daughter", "sibling",      SCORE_ROLE_SIBLING_INFERRED,     "son+daughter → sibling (inferred)"),
]

# Pre-build lookup: frozenset({role_1, role_2}) → (rel_type, score, note)
# For same-role pairs (son+son etc.) we use a tuple key instead.
_RULE_LOOKUP: dict[tuple[str, str] | frozenset, tuple[str, float, str]] = {}
for _r1, _r2, _rtype, _score, _note in _ROLE_PAIR_RULES:
    key = (_r1, _r2) if _r1 == _r2 else frozenset((_r1, _r2))
    _RULE_LOOKUP[key] = (_rtype, _score, _note)


def _lookup_rule(
    role_a: str | None, role_b: str | None
) -> tuple[str, float, str] | None:
    """Return (rel_type, score, note) for a role pair, or None if no rule applies."""
    if role_a is None or role_b is None:
        return None
    if role_a == role_b:
        return _RULE_LOOKUP.get((role_a, role_b))
    return _RULE_LOOKUP.get(frozenset((role_a, role_b)))


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class RoleRelationshipResult:
    record_id: int
    relationships_created: int = 0
    skipped_null_role_pairs: int = 0
    skipped_no_rule: int = 0
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def assign_role_relationships(
    repo: Repository,
    record_id: int,
) -> RoleRelationshipResult:
    """
    For a single census Record, read all RecordedPersons and create
    RecordedRelationship rows for every role pair that matches a rule in §6.1.

    Called immediately after ingest_census commits each record.
    Must be called inside a transaction (the caller — add-evidence — owns
    the transaction boundary).

    Returns a RoleRelationshipResult with counts and any notes.
    """
    result = RoleRelationshipResult(record_id=record_id)

    persons = get_recorded_persons_for_record(repo, record_id)
    if len(persons) < 2:
        return result  # nothing to pair

    # Compare every ordered pair (i, j) where i < j to avoid duplicates.
    for i in range(len(persons)):
        for j in range(i + 1, len(persons)):
            rp_a = persons[i]
            rp_b = persons[j]

            role_a = rp_a["role"]
            role_b = rp_b["role"]

            if role_a is None or role_b is None:
                result.skipped_null_role_pairs += 1
                continue

            match = _lookup_rule(role_a, role_b)
            if match is None:
                result.skipped_no_rule += 1
                continue

            rel_type, score, note = match

            # All RecordedRelationships get scores — role-pair types use the
            # prior score from the rule table; similarity types use Splink scores.
            insert_recorded_relationship(
                repo,
                recorded_person_id_1=rp_a["recorded_person_id"],
                recorded_person_id_2=rp_b["recorded_person_id"],
                rel_type=rel_type,
                score=score,
                score_version=SCORE_VERSION_ROLE_PAIR,
                notes=note,
            )
            result.relationships_created += 1

    return result


# ---------------------------------------------------------------------------
# Batch entry point: process all records for a source
# ---------------------------------------------------------------------------

def assign_role_relationships_for_source(
    repo: Repository,
    source_id: int,
) -> list[RoleRelationshipResult]:
    """
    Run assign_role_relationships for every Record belonging to source_id.
    Used by the CLI when re-running the role-relationship step in isolation.
    Each record is processed within the caller's transaction.
    """
    record_ids = repo.fetch_all(
        "SELECT record_id FROM record WHERE source_id = %s ORDER BY record_id",
        (source_id,),
    )

    return [assign_role_relationships(repo, rid["record_id"]) for rid in record_ids]
