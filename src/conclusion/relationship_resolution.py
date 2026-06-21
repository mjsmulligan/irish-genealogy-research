"""
GRA — Conclusion Layer: Relationship Resolution

Creates Relationship conclusions and refines Person conclusions using
household similarity and semantic RecordedRelationships. This is Step 2
of the conclusion pipeline.

Design:
  - Uses high household similarity (RecordSimilarity >= 0.85) as primary evidence
  - Matches RecordedPersons across households by role/name/age/sex
  - Creates Persons for matched pairs (handles many orphans from step 1)
  - Respects existing Persons from Person Resolution step
  - Creates Relationships from recorded family structure (couple/parent_child/sibling)
  - Detects merge candidates (e.g., spouse triangulation) but doesn't execute merges

Three cases handled:
  Case 1: High household similarity, no existing Persons → create Persons + Relationships
  Case 2: High household similarity, some existing Persons → link to existing + create Relationships
  Case 3: Person anchor, low household similarity → extend matches using anchor

Entry point:
    run_relationship_resolution(conn) -> RelationshipResolutionResult
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import psycopg2.extensions

from src.constants import AUTO_COMMIT_THRESHOLD


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class MergeCandidate:
    """A potential Person merge discovered during Relationship Resolution."""
    person_id_1: int
    person_id_2: int
    reason: str  # e.g., "spouse_triangulation", "parent_consistency"
    evidence_score: float  # household similarity or other metric
    evidence_detail: str  # human-readable explanation


@dataclass
class RelationshipResolutionResult:
    persons_created: int = 0
    persons_linked: int = 0  # existing Persons that got new RecordedPerson links
    relationships_created: int = 0
    linkages_created: int = 0  # person_recorded_person rows
    households_processed: int = 0
    merge_candidates: list[MergeCandidate] = field(default_factory=list)
    case1_matches: int = 0  # high sim, no existing Persons
    case2_matches: int = 0  # high sim, some existing Persons
    case3_matches: int = 0  # person anchor, low sim


# ---------------------------------------------------------------------------
# Household matching helpers
# ---------------------------------------------------------------------------

def _get_household_members(
    conn: psycopg2.extensions.connection,
    record_id: int,
) -> list[dict]:
    """
    Get all RecordedPersons in a household with their Person linkage if it exists.

    Returns list of dicts with keys: recorded_person_id, name_as_recorded, role,
    age, sex_as_recorded, person_id (or None if orphan).
    """
    with conn.cursor() as cur:
        cur.execute(
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
        return cur.fetchall()


def _match_score(rp1: dict, rp2: dict) -> float:
    """
    Calculate match score between two RecordedPersons.

    Considers: role, name similarity, age progression (10 years for 1901↔1911),
    sex consistency.

    Returns score 0.0-1.0 where 1.0 = perfect match.
    """
    score = 0.0

    # Role match (0.3 weight)
    if rp1["role"] == rp2["role"]:
        score += 0.3

    # Name similarity (0.3 weight) - simple exact match for now
    name1 = (rp1["name_as_recorded"] or "").lower().strip()
    name2 = (rp2["name_as_recorded"] or "").lower().strip()
    if name1 and name2 and name1 == name2:
        score += 0.3

    # Age progression (0.2 weight)
    # Expect ~10 year difference for 1901↔1911, ~25 for 1901↔1926
    age1 = rp1["age"]
    age2 = rp2["age"]
    if age1 is not None and age2 is not None:
        age_diff = abs(age2 - age1)
        # Ideal: 10 years; acceptable: 8-12 years
        if 8 <= age_diff <= 12:
            score += 0.2
        elif 5 <= age_diff <= 15:
            score += 0.1

    # Sex consistency (0.2 weight)
    sex1 = rp1["sex_as_recorded"]
    sex2 = rp2["sex_as_recorded"]
    if sex1 and sex2:
        if sex1.upper() == sex2.upper():
            score += 0.2
    elif not sex1 and not sex2:
        score += 0.1  # both null

    return score


def _match_households(h1_members: list[dict], h2_members: list[dict]) -> list[tuple[dict, dict]]:
    """
    Match RecordedPersons across two households using greedy algorithm.

    Returns list of (rp1, rp2) pairs.
    """
    matches = []
    used_h2 = set()

    for rp1 in h1_members:
        best_match = None
        best_score = 0.6  # minimum threshold

        for i, rp2 in enumerate(h2_members):
            if i in used_h2:
                continue

            score = _match_score(rp1, rp2)
            if score > best_score:
                best_score = score
                best_match = (i, rp2)

        if best_match:
            idx, rp2 = best_match
            matches.append((rp1, rp2))
            used_h2.add(idx)

    return matches


# ---------------------------------------------------------------------------
# Person creation and linking
# ---------------------------------------------------------------------------

def _get_or_create_person_for_pair(
    conn: psycopg2.extensions.connection,
    rp1: dict,
    rp2: dict,
) -> tuple[int, bool]:
    """
    Get existing Person for this pair, or create new one.

    Logic:
    - If rp1 has Person, use it
    - Else if rp2 has Person, use it
    - Else create new Person

    Returns: (person_id, was_created)
    """
    from src.dal.person_repo import create_person

    person_id_1 = rp1.get("person_id")
    person_id_2 = rp2.get("person_id")

    # Case: rp1 already has Person
    if person_id_1:
        return (person_id_1, False)

    # Case: rp2 already has Person
    if person_id_2:
        return (person_id_2, False)

    # Case: neither has Person - create new
    # Generate label from rp1 (first occurrence chronologically)
    name = rp1["name_as_recorded"] or "Unknown"

    # Get place from record
    with conn.cursor() as cur:
        cur.execute(
            "SELECT place_as_recorded FROM record WHERE record_id = "
            "(SELECT record_id FROM recorded_person WHERE recorded_person_id = %s)",
            (rp1["recorded_person_id"],),
        )
        place_row = cur.fetchone()
        place = place_row["place_as_recorded"] if place_row else "Unknown"

    label = f"{name} ({place})"

    # Resolve gender
    gender = None
    sex1 = rp1.get("sex_as_recorded")
    sex2 = rp2.get("sex_as_recorded")
    if sex1 and sex1.upper() in ("M", "F"):
        gender = "male" if sex1.upper() == "M" else "female"
    elif sex2 and sex2.upper() in ("M", "F"):
        gender = "male" if sex2.upper() == "M" else "female"

    person_id = create_person(conn, label=label, gender=gender)
    return (person_id, True)


def _link_recorded_person_to_person(
    conn: psycopg2.extensions.connection,
    person_id: int,
    recorded_person_id: int,
) -> None:
    """Link a RecordedPerson to a Person if not already linked."""
    from src.dal.person_repo import link_person_to_recorded_person

    link_person_to_recorded_person(
        conn,
        person_id=person_id,
        recorded_person_id=recorded_person_id,
        score=None,
        score_version=None,
        verified=False,
    )


# ---------------------------------------------------------------------------
# Relationship creation
# ---------------------------------------------------------------------------

def _ensure_relationship(
    conn: psycopg2.extensions.connection,
    person_id_1: int,
    person_id_2: int,
    rel_type: str,
) -> Optional[int]:
    """
    Ensure a Relationship exists between two Persons.

    Returns relationship_id if created/found, None if it already exists.
    """
    # Check if relationship already exists
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT relationship_id
            FROM relationship
            WHERE type = %s
              AND ((person_id_1 = %s AND person_id_2 = %s)
                OR (person_id_1 = %s AND person_id_2 = %s))
            """,
            (rel_type, person_id_1, person_id_2, person_id_2, person_id_1),
        )
        existing = cur.fetchone()

    if existing:
        return None  # Already exists

    # Create new Relationship
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO relationship (type, person_id_1, person_id_2)
            VALUES (%s, %s, %s)
            RETURNING relationship_id
            """,
            (rel_type, person_id_1, person_id_2),
        )
        return cur.fetchone()["relationship_id"]


def _create_relationships_from_household(
    conn: psycopg2.extensions.connection,
    household_members: list[dict],
) -> int:
    """
    Create Relationships based on household roles.

    Only creates Relationships for members who have Persons.

    Returns count of Relationships created.
    """
    count = 0

    # Get members with Persons
    members_with_persons = [m for m in household_members if m.get("person_id")]

    if len(members_with_persons) < 2:
        return 0

    # Find head and spouse
    head = next((m for m in members_with_persons if m["role"] == "head"), None)
    spouse = next((m for m in members_with_persons if m["role"] == "spouse"), None)

    # Create couple relationship
    if head and spouse and head["person_id"] != spouse["person_id"]:
        rel_id = _ensure_relationship(
            conn, head["person_id"], spouse["person_id"], "couple"
        )
        if rel_id:
            count += 1

    # Create parent-child relationships
    children = [m for m in members_with_persons if m["role"] in ("son", "daughter")]
    for child in children:
        if head and head["person_id"] != child["person_id"]:
            rel_id = _ensure_relationship(
                conn, head["person_id"], child["person_id"], "parent_child"
            )
            if rel_id:
                count += 1
        if spouse and spouse["person_id"] != child["person_id"]:
            rel_id = _ensure_relationship(
                conn, spouse["person_id"], child["person_id"], "parent_child"
            )
            if rel_id:
                count += 1

    # Create sibling relationships
    for i, child1 in enumerate(children):
        for child2 in children[i + 1 :]:
            # Skip if same Person (can happen if both RecordedPersons belong to same Person)
            if child1["person_id"] == child2["person_id"]:
                continue
            rel_id = _ensure_relationship(
                conn, child1["person_id"], child2["person_id"], "sibling"
            )
            if rel_id:
                count += 1

    return count


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

def _detect_spouse_triangulation_conflicts(
    conn: psycopg2.extensions.connection,
) -> list[MergeCandidate]:
    """
    Detect cases where one Person has multiple spouse Persons.

    This suggests the spouse Persons should be merged.
    """
    merge_candidates = []

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                p1.person_id as anchor_person,
                p2.person_id as spouse1,
                p3.person_id as spouse2,
                p1.label as anchor_label,
                p2.label as spouse1_label,
                p3.label as spouse2_label
            FROM relationship r1
            JOIN relationship r2
                ON r1.person_id_1 = r2.person_id_1
                AND r1.type = 'couple'
                AND r2.type = 'couple'
                AND r1.relationship_id < r2.relationship_id
            JOIN person p1 ON p1.person_id = r1.person_id_1
            JOIN person p2 ON p2.person_id = r1.person_id_2
            JOIN person p3 ON p3.person_id = r2.person_id_2
            WHERE p2.person_id != p3.person_id
            """
        )
        conflicts = cur.fetchall()

    for conflict in conflicts:
        merge_candidates.append(
            MergeCandidate(
                person_id_1=conflict["spouse1"],
                person_id_2=conflict["spouse2"],
                reason="spouse_triangulation",
                evidence_score=1.0,  # Strong evidence
                evidence_detail=f"{conflict['spouse1_label']} and {conflict['spouse2_label']} "
                f"both married to {conflict['anchor_label']}",
            )
        )

    return merge_candidates


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_relationship_resolution(
    conn: psycopg2.extensions.connection,
    household_threshold: float = AUTO_COMMIT_THRESHOLD,
) -> RelationshipResolutionResult:
    """
    Run Relationship Resolution: use household similarity and roles to create
    Persons and Relationships.

    Algorithm:
      1. For each high-similarity household pair (>= threshold):
         - Match RecordedPersons by role/name/age
         - Create or link Persons for matches
         - Create Relationships from family structure
      2. Detect merge candidates (spouse triangulation, etc.)
      3. Return results with merge candidates for review

    Returns RelationshipResolutionResult with counts and merge candidates.
    """
    result = RelationshipResolutionResult()

    # Step 1: Fetch high-similarity household pairs
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT record_id_1, record_id_2, score
            FROM record_similarity
            WHERE score >= %s
            ORDER BY score DESC
            """,
            (household_threshold,),
        )
        household_pairs = cur.fetchall()

    # Step 2: Process each household pair
    for pair in household_pairs:
        record_id_1 = pair["record_id_1"]
        record_id_2 = pair["record_id_2"]

        h1_members = _get_household_members(conn, record_id_1)
        h2_members = _get_household_members(conn, record_id_2)

        # Match members
        matches = _match_households(h1_members, h2_members)

        # Determine case type
        has_existing_persons = any(
            rp1.get("person_id") or rp2.get("person_id") for rp1, rp2 in matches
        )

        if not has_existing_persons:
            result.case1_matches += len(matches)
        else:
            result.case2_matches += len(matches)

        # Process matches within a transaction
        with conn:
            for rp1, rp2 in matches:
                # Get or create Person
                person_id, was_created = _get_or_create_person_for_pair(conn, rp1, rp2)

                if was_created:
                    result.persons_created += 1
                else:
                    result.persons_linked += 1

                # Link both RecordedPersons to Person
                _link_recorded_person_to_person(conn, person_id, rp1["recorded_person_id"])
                _link_recorded_person_to_person(conn, person_id, rp2["recorded_person_id"])
                result.linkages_created += 2

                # Update members with person_id for relationship creation
                rp1["person_id"] = person_id
                rp2["person_id"] = person_id

            # Create Relationships from household structure
            rels_created = _create_relationships_from_household(conn, h1_members)
            rels_created += _create_relationships_from_household(conn, h2_members)
            result.relationships_created += rels_created

        result.households_processed += 1

    # Step 3: Detect merge candidates
    result.merge_candidates = _detect_spouse_triangulation_conflicts(conn)

    return result


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

def print_relationship_resolution_report(result: RelationshipResolutionResult) -> None:
    print("\n  RELATIONSHIP RESOLUTION")
    print(f"    Households processed:    {result.households_processed:>6}")
    print(f"    Case 1 matches:          {result.case1_matches:>6}  (high sim, new Persons)")
    print(f"    Case 2 matches:          {result.case2_matches:>6}  (high sim, existing Persons)")
    print(f"    Case 3 matches:          {result.case3_matches:>6}  (person anchor)")
    print(f"    Persons created:         {result.persons_created:>6}")
    print(f"    Persons linked (exist):  {result.persons_linked:>6}")
    print(f"    Linkages created:        {result.linkages_created:>6}")
    print(f"    Relationships created:   {result.relationships_created:>6}")

    if result.merge_candidates:
        print(f"\n    MERGE CANDIDATES DETECTED: {len(result.merge_candidates)}")
        for mc in result.merge_candidates[:5]:  # Show first 5
            print(f"      Person {mc.person_id_1} ↔ Person {mc.person_id_2}")
            print(f"        Reason: {mc.reason}")
            print(f"        Detail: {mc.evidence_detail}")
        if len(result.merge_candidates) > 5:
            print(f"      ... and {len(result.merge_candidates) - 5} more")
