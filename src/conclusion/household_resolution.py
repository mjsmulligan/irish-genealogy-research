"""
GRA — Conclusion Layer: Household Resolution

Creates Person conclusions for RecordedPersons who remain unlinked after
person_resolution and relationship_resolution, using intra-household
RecordedRelationship rows as justification. This is Step 3 of the
conclusion pipeline.

Design:
  - An existing Person in a household acts as an anchor.
  - Any unlinked RecordedPerson connected to that anchor via a
    RecordedRelationship (created at ingest time by role_relationships.py)
    is created as a new Person.
  - Co-presence in a household alone is NOT sufficient — a RecordedRelationship
    path to the anchor is required (excludes visitor, boarder, etc.).
  - Operates within a single census only; cross-census anchoring is handled
    by relationship_resolution.
  - After Person creation, Relationship conclusions are derived from the
    now-fuller household using the shared household_utils helpers.

Cases handled:
  Case A: Anchor is head — creates Persons for unlinked spouse, children.
  Case B: Anchor is a child — creates Person for unlinked head (and spouse
          if connected).
  Case C: Anchor is spouse — creates Person for unlinked head.
  Case D: Multiple anchors — each unlinked member gets one Person, linked
          to the household via any RecordedRelationship to any anchor.

Entry point:
    run_household_resolution(conn) -> HouseholdResolutionResult
"""

from __future__ import annotations

from dataclasses import dataclass, field

import psycopg2.extensions

from src.constants import SCORE_VERSION_HOUSEHOLD_EXTENSION
from src.conclusion.household_utils import (
    get_household_members,
    create_relationships_from_household,
)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class HouseholdResolutionResult:
    records_examined: int = 0        # Records with at least one anchor
    persons_created: int = 0         # New Person conclusions minted
    linkages_created: int = 0        # person_recorded_person rows written
    relationships_created: int = 0   # New Relationship conclusions derived
    skipped_no_anchor: int = 0       # Records with no existing Person (skipped)
    skipped_no_rr: int = 0           # Unlinked members skipped — no RecordedRelationship to anchor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_anchored_person_ids(members: list[dict]) -> set[int]:
    """Return the set of Person IDs already assigned in this household."""
    return {m["person_id"] for m in members if m.get("person_id")}


def _get_unlinked_members(members: list[dict]) -> list[dict]:
    """Return members with no Person linkage yet."""
    return [m for m in members if not m.get("person_id")]


def _get_rr_to_anchor(
    conn: psycopg2.extensions.connection,
    unlinked_rp_id: int,
    anchor_person_ids: set[int],
) -> dict | None:
    """
    Find a RecordedRelationship connecting the unlinked RecordedPerson to any
    anchored Person's RecordedPerson(s).

    Returns the first matching RecordedRelationship row (with score), or None
    if no path exists.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT rr.recorded_relationship_id, rr.type, rr.score
            FROM recorded_relationship rr
            JOIN person_recorded_person prp
                ON prp.recorded_person_id IN (rr.recorded_person_id_1, rr.recorded_person_id_2)
            WHERE
                (rr.recorded_person_id_1 = %s OR rr.recorded_person_id_2 = %s)
                AND prp.person_id = ANY(%s)
            LIMIT 1
            """,
            (unlinked_rp_id, unlinked_rp_id, list(anchor_person_ids)),
        )
        return cur.fetchone()


def _create_person_for_recorded_person(
    conn: psycopg2.extensions.connection,
    rp: dict,
    score: float,
) -> int:
    """
    Create a Person conclusion for an unlinked RecordedPerson and link them.

    Uses the RecordedRelationship's prior score as the linkage score, which
    reflects the strength of the ingest-time role-pair evidence.

    Returns the new person_id.
    """
    from src.dal.person_repo import create_person, link_person_to_recorded_person

    name = rp["name_as_recorded"] or "Unknown"

    # Resolve gender from census sex field
    gender = None
    sex = rp.get("sex_as_recorded")
    if sex and sex.upper() in ("M", "F"):
        gender = "male" if sex.upper() == "M" else "female"

    # Build label from name + place (fetched from parent Record)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT place_as_recorded FROM record
            WHERE record_id = (
                SELECT record_id FROM recorded_person
                WHERE recorded_person_id = %s
            )
            """,
            (rp["recorded_person_id"],),
        )
        place_row = cur.fetchone()
        place = place_row["place_as_recorded"] if place_row else "Unknown"

    label = f"{name} ({place})"

    person_id = create_person(conn, label=label, gender=gender)

    link_person_to_recorded_person(
        conn,
        person_id=person_id,
        recorded_person_id=rp["recorded_person_id"],
        score=score,
        score_version=SCORE_VERSION_HOUSEHOLD_EXTENSION,
        verified=False,
    )

    return person_id


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_household_resolution(
    conn: psycopg2.extensions.connection,
) -> HouseholdResolutionResult:
    """
    Run Household Resolution: for each Record that has at least one anchored
    Person, create Persons for any remaining unlinked RecordedPersons that
    have a RecordedRelationship path to an anchor.

    Algorithm:
      1. Find all Records containing at least one anchored RecordedPerson
         and at least one unlinked RecordedPerson.
      2. For each unlinked member, check for a RecordedRelationship to any
         anchor. If found, create a Person and link them, using the
         RecordedRelationship score as the linkage score.
      3. Re-fetch household members after all Person creation, then derive
         Relationship conclusions from the fuller household.

    Returns HouseholdResolutionResult with counts.
    """
    result = HouseholdResolutionResult()

    # Find Records with a mix of anchored and unlinked RecordedPersons.
    # Uses two subqueries to avoid fetching all Records.
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT rp.record_id
            FROM recorded_person rp
            WHERE EXISTS (
                SELECT 1 FROM person_recorded_person prp
                WHERE prp.recorded_person_id = rp.recorded_person_id
            )
            AND EXISTS (
                SELECT 1 FROM recorded_person rp2
                LEFT JOIN person_recorded_person prp2
                    ON prp2.recorded_person_id = rp2.recorded_person_id
                WHERE rp2.record_id = rp.record_id
                  AND prp2.person_id IS NULL
            )
            ORDER BY rp.record_id
            """
        )
        candidate_record_ids = [row["record_id"] for row in cur.fetchall()]

    for record_id in candidate_record_ids:
        members = get_household_members(conn, record_id)
        anchor_person_ids = _get_anchored_person_ids(members)
        unlinked = _get_unlinked_members(members)

        if not anchor_person_ids:
            result.skipped_no_anchor += 1
            continue

        result.records_examined += 1

        newly_created_this_record = 0

        with conn:
            for rp in unlinked:
                rr_row = _get_rr_to_anchor(conn, rp["recorded_person_id"], anchor_person_ids)

                if rr_row is None:
                    result.skipped_no_rr += 1
                    continue

                # Inherit the RecordedRelationship prior score; fall back to
                # a conservative 0.75 if the score is somehow null.
                score = rr_row["score"] if rr_row["score"] is not None else 0.75

                person_id = _create_person_for_recorded_person(conn, rp, score)

                # Add to anchor set so subsequent siblings in the same loop
                # can use this new Person as an anchor for one another.
                anchor_person_ids.add(person_id)

                result.persons_created += 1
                result.linkages_created += 1
                newly_created_this_record += 1

            if newly_created_this_record > 0:
                # Re-fetch so relationship creation sees the full updated household
                members_fresh = get_household_members(conn, record_id)
                rels_created = create_relationships_from_household(conn, members_fresh)
                result.relationships_created += rels_created

    return result


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

def print_household_resolution_report(result: HouseholdResolutionResult) -> None:
    print("\n  HOUSEHOLD RESOLUTION")
    print(f"    Records examined:        {result.records_examined:>6}  (had at least one anchor)")
    print(f"    Persons created:         {result.persons_created:>6}")
    print(f"    Linkages created:        {result.linkages_created:>6}")
    print(f"    Relationships created:   {result.relationships_created:>6}")
    print(f"    Skipped (no anchor):     {result.skipped_no_anchor:>6}")
    print(f"    Skipped (no RR path):    {result.skipped_no_rr:>6}")
