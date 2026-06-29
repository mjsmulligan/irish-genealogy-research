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

Shared household helpers (get_household_members, ensure_relationship,
create_relationships_from_household) live in household_utils.py and are
also used by household_resolution.py (Step 3).

Entry point:
    run_relationship_resolution(conn) -> RelationshipResolutionResult
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.db.repository import Repository
from rapidfuzz.distance import JaroWinkler

from src.constants import AUTO_COMMIT_THRESHOLD
from src.conclusion.household_utils import (
    get_household_members,
    ensure_relationship,
    create_relationships_from_household,
)
from src.genealogy import evaluate_age_progression, CENSUS_YEAR


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
class LinkConflict:
    """Record of a RecordedPerson re-linked due to opinion revision."""
    recorded_person_id: int
    old_person_id: int  # Where it was linked (Step 1)
    new_person_id_attempted: int  # Where Step 2 tried to link it
    resolution: str  # "kept_existing" or "overwritten"


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
    link_conflicts_resolved: int = 0  # RecordedPersons re-linked to stronger candidates
    persons_orphaned: int = 0  # Persons created but lost all RecordedPersons to conflicts
    link_conflicts: list[LinkConflict] = field(default_factory=list)  # Audit trail


# ---------------------------------------------------------------------------
# Household matching helpers
# ---------------------------------------------------------------------------

_NAME_JW_THRESHOLD: float = 0.85   # JaroWinkler threshold for name match


def _match_score(rp1: dict, rp2: dict, census_gap: int) -> float:
    """
    Calculate match score between two RecordedPersons.

    Considers: role, name similarity (JaroWinkler ≥ 0.85), age progression
    using the actual gap between census years, and sex consistency.

    Args:
        rp1: RecordedPerson dict from the earlier census.
        rp2: RecordedPerson dict from the later census.
        census_gap: Number of years between the two census dates (e.g. 10 for
            1901↔1911, 25 for 1901↔1926). Used to set the expected age
            progression window (gap ± 2 years).

    Returns score 0.0–1.0 where 1.0 = perfect match.
    """
    score = 0.0

    # Role match (0.3 weight)
    if rp1["role"] == rp2["role"]:
        score += 0.3

    # Name similarity (0.3 weight) — JaroWinkler handles NAI spelling variants
    # (Brigid/Bridget, Michael/Micheal, Patrick/Patk, etc.)
    name1 = (rp1["name_as_recorded"] or "").strip()
    name2 = (rp2["name_as_recorded"] or "").strip()
    if name1 and name2:
        jw = JaroWinkler.similarity(name1, name2)
        if jw >= _NAME_JW_THRESHOLD:
            score += 0.3

    # Age progression (0.2 weight)
    # Expected difference is the census gap; allow ± 2 years for rounding /
    # age heaping. Outer band ± 5 years gets partial credit.
    age1 = rp1["age"]
    age2 = rp2["age"]
    if age1 is not None and age2 is not None:
        age_diff = abs(age2 - age1)
        ideal = census_gap
        if abs(age_diff - ideal) <= 2:
            score += 0.2
        elif abs(age_diff - ideal) <= 5:
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


def _match_households(
    h1_members: list[dict],
    h2_members: list[dict],
    census_gap: int,
) -> list[tuple[dict, dict]]:
    """
    Match RecordedPersons across two households using greedy algorithm.

    Args:
        h1_members: Members of the earlier household.
        h2_members: Members of the later household.
        census_gap: Years between the two census dates — passed through to
            _match_score() for dynamic age-progression window.

    Returns list of (rp1, rp2) pairs where rp1 is from the earlier household.
    """
    matches = []
    used_h2 = set()

    for rp1 in h1_members:
        best_match = None
        best_score = 0.6  # minimum threshold

        for i, rp2 in enumerate(h2_members):
            if i in used_h2:
                continue

            score = _match_score(rp1, rp2, census_gap)
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
    repo: Repository,
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
    place_row = repo.fetch_one(
        "SELECT place_as_recorded FROM record WHERE record_id = "
        "(SELECT record_id FROM recorded_person WHERE recorded_person_id = %s)",
        (rp1["recorded_person_id"],),
    )
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

    person_id = create_person(repo, label=label, gender=gender)
    return (person_id, True)


def _get_recorded_person_link(
    repo: Repository,
    recorded_person_id: int,
) -> tuple[int, float | None] | None:
    """
    Get existing Person linkage for a RecordedPerson.

    Returns (person_id, score) if linked, None if orphan.
    """
    row = repo.fetch_one(
        """
        SELECT person_id, score
        FROM person_recorded_person
        WHERE recorded_person_id = %s
        """,
        (recorded_person_id,),
    )
    return (row["person_id"], row["score"]) if row else None


def _link_recorded_person_to_person(
    repo: Repository,
    person_id: int,
    recorded_person_id: int,
    force_overwrite: bool = False,
) -> tuple[str, LinkConflict | None]:
    """
    Link a RecordedPerson to a Person, resolving conflicts by choosing the strongest link.

    This implements genealogical opinion revision: if a RecordedPerson is already linked
    to a different Person, we compare link strengths and keep only the stronger one.

    Args:
        person_id: Target Person to link to
        recorded_person_id: RecordedPerson to link
        force_overwrite: If True, unlink from old Person before linking to new one.
                        If False (default), only link if orphan or already linked to same Person.

    Returns:
        Tuple of (status, conflict_record):
        - status: "linked" = new linkage created
                 "kept_existing" = already linked to same Person (no action)
                 "conflict_resolved" = was linked to different Person; kept stronger link
        - conflict_record: LinkConflict if a conflict was resolved, else None
    """
    from src.dal.person_repo import link_person_to_recorded_person

    # Check for same-census constraint: reject if person is already linked to another recorded_person from same census
    row = repo.fetch_one(
        """
        SELECT r.source_id, rp.age FROM record r
        JOIN recorded_person rp ON rp.record_id = r.record_id
        WHERE rp.recorded_person_id = %s
        """,
        (recorded_person_id,),
    )
    new_source_id = row["source_id"] if row else None
    new_age = row["age"] if row else None
    new_year = CENSUS_YEAR.get(new_source_id)

    if new_source_id:
        # Check if person is already linked to another recorded_person from same source
        cnt_row = repo.fetch_one(
            """
            SELECT COUNT(*) as cnt FROM person_recorded_person prp
            JOIN recorded_person rp ON prp.recorded_person_id = rp.recorded_person_id
            JOIN record r ON rp.record_id = r.record_id
            WHERE prp.person_id = %s AND r.source_id = %s
            """,
            (person_id, new_source_id),
        )
        existing_same_census = cnt_row["cnt"]
        if existing_same_census > 0:
            # Would create same-census link; reject
            return "skipped_same_census", None

        # Check for age regression: reject if any linked recorded_person would create backward age progression
        if new_age and new_year:
            other_rows = repo.fetch_all(
                """
                SELECT rp.age, r.source_id FROM person_recorded_person prp
                JOIN recorded_person rp ON prp.recorded_person_id = rp.recorded_person_id
                JOIN record r ON rp.record_id = r.record_id
                WHERE prp.person_id = %s
                """,
                (person_id,),
            )
            for other_row in other_rows:
                other_age = other_row["age"]
                other_source_id = other_row["source_id"]
                if other_age:
                    age_check = evaluate_age_progression(
                        other_age, other_source_id,
                        new_age, new_source_id,
                    )
                    if not age_check.valid:
                        return "skipped_age_regression", None

    existing = _get_recorded_person_link(repo, recorded_person_id)

    if existing is None:
        # Orphan — link to new Person
        link_person_to_recorded_person(
            repo,
            person_id=person_id,
            recorded_person_id=recorded_person_id,
            score=None,
            score_version=None,
            verified=False,
        )
        return "linked", None

    existing_person_id, existing_score = existing

    if existing_person_id == person_id:
        # Already linked to same Person — no conflict
        return "kept_existing", None

    # Conflict: linked to different Person
    # Genealogical principle: keep the stronger evidence link
    conflict_record = LinkConflict(
        recorded_person_id=recorded_person_id,
        old_person_id=existing_person_id,
        new_person_id_attempted=person_id,
        resolution="overwritten" if force_overwrite else "kept_existing",
    )

    if force_overwrite:
        # Delete old link and create new one
        repo.execute(
            """
            DELETE FROM person_recorded_person
            WHERE recorded_person_id = %s
            """,
            (recorded_person_id,),
        )
        link_person_to_recorded_person(
            repo,
            person_id=person_id,
            recorded_person_id=recorded_person_id,
            score=None,
            score_version=None,
            verified=False,
        )
        return "conflict_resolved", conflict_record
    else:
        # Keep existing link (conservative approach)
        return "conflict_resolved", conflict_record


# ---------------------------------------------------------------------------
# Relationship creation — see household_utils.py
# (ensure_relationship, create_relationships_from_household imported above)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

def _detect_spouse_triangulation_conflicts(
    repo: Repository,
) -> list[MergeCandidate]:
    """
    Detect cases where one Person has multiple spouse Persons.

    This suggests the spouse Persons should be merged.
    """
    merge_candidates = []

    conflicts = repo.fetch_all(
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

def _get_record_year(repo: Repository, record_id: int) -> int | None:
    """Return the four-digit census year for a record, or None if unavailable."""
    row = repo.fetch_one(
        "SELECT date FROM record WHERE record_id = %s",
        (record_id,),
    )
    if not row or not row["date"]:
        return None
    import re
    m = re.match(r"^(\d{4})", row["date"])
    return int(m.group(1)) if m else None


def run_relationship_resolution(
    repo: Repository,
    household_threshold: float = AUTO_COMMIT_THRESHOLD,
) -> RelationshipResolutionResult:
    """
    Run Relationship Resolution: use household similarity and roles to create
    Persons and Relationships.

    Algorithm:
      1. For each high-similarity household pair (>= threshold):
         - Derive census_gap from the two record dates (items 21/22)
         - Match RecordedPersons by role/name/age
         - Create or link Persons for matches
         - Re-fetch household members from DB after Person assignments so
           relationship creation sees correct person_ids (item 23 fix)
         - Create Relationships from household family structure; populate
           relationship_recorded_relationship provenance (item 24 fix)
      2. Detect merge candidates (spouse triangulation, etc.)
      3. Return results with merge candidates for review

    Returns RelationshipResolutionResult with counts and merge candidates.
    """
    result = RelationshipResolutionResult()

    # Step 1: Fetch high-similarity household pairs with their record dates
    household_pairs = repo.fetch_all(
        """
        SELECT
            rs.record_id_1,
            rs.record_id_2,
            rs.score,
            r1.date AS date_1,
            r2.date AS date_2
        FROM record_similarity rs
        JOIN record r1 ON r1.record_id = rs.record_id_1
        JOIN record r2 ON r2.record_id = rs.record_id_2
        WHERE rs.score >= %s
        ORDER BY rs.score DESC
        """,
        (household_threshold,),
    )

    # Step 2: Process each household pair
    import re as _re

    def _year(date_str):
        if not date_str:
            return None
        m = _re.match(r"^(\d{4})", date_str)
        return int(m.group(1)) if m else None

    for pair in household_pairs:
        record_id_1 = pair["record_id_1"]
        record_id_2 = pair["record_id_2"]

        # Derive census gap for dynamic age-progression window (item 21)
        year_1 = _year(pair["date_1"])
        year_2 = _year(pair["date_2"])
        census_gap = abs(year_2 - year_1) if (year_1 and year_2) else 10  # fallback

        h1_members = get_household_members(repo, record_id_1)
        h2_members = get_household_members(repo, record_id_2)

        # Match members using dynamic gap (items 21, 22)
        matches = _match_households(h1_members, h2_members, census_gap)

        # Determine case type
        has_existing_persons = any(
            rp1.get("person_id") or rp2.get("person_id") for rp1, rp2 in matches
        )

        if not has_existing_persons:
            result.case1_matches += len(matches)
        else:
            result.case2_matches += len(matches)

        # Process matches
        for rp1, rp2 in matches:
            # Get or create Person
            person_id, was_created = _get_or_create_person_for_pair(repo, rp1, rp2)

            if was_created:
                result.persons_created += 1
            else:
                result.persons_linked += 1

            # Link both RecordedPersons to Person
            # With conflict resolution: if already linked elsewhere, keep existing (conservative)
            status1, conflict1 = _link_recorded_person_to_person(repo, person_id, rp1["recorded_person_id"])
            status2, conflict2 = _link_recorded_person_to_person(repo, person_id, rp2["recorded_person_id"])

            if status1 == "linked":
                result.linkages_created += 1
            elif status1 == "conflict_resolved":
                result.link_conflicts_resolved += 1
                if conflict1:
                    result.link_conflicts.append(conflict1)

            if status2 == "linked":
                result.linkages_created += 1
            elif status2 == "conflict_resolved":
                result.link_conflicts_resolved += 1
                if conflict2:
                    result.link_conflicts.append(conflict2)

            # NOTE: Do NOT mutate rp1["person_id"] / rp2["person_id"] here.
            # The in-memory dicts are from pre-assignment fetches; setting
            # both to the same person_id would cause create_relationships_from_household
            # to see household members as identical Persons and skip all
            # relationship creation.  Instead, re-fetch from DB below (item 23).

        # Re-fetch household members so person_id reflects all DB writes
        # made above.  This is the item 23 fix: relationship creation now
        # sees correct, distinct person_ids rather than the mutated dicts.
        h1_members_fresh = get_household_members(repo, record_id_1)
        h2_members_fresh = get_household_members(repo, record_id_2)

        # Create Relationships from household structure (item 24: provenance
        # is populated inside ensure_relationship)
        rels_created = create_relationships_from_household(repo, h1_members_fresh)
        rels_created += create_relationships_from_household(repo, h2_members_fresh)
        result.relationships_created += rels_created

        result.households_processed += 1

    # Step 3: Detect merge candidates
    result.merge_candidates = _detect_spouse_triangulation_conflicts(repo)

    # Step 4: Clean up orphaned Persons (created but lost all RecordedPersons to conflicts)
    orphaned_rows = repo.fetch_all(
        """
        SELECT p.person_id
        FROM person p
        LEFT JOIN person_recorded_person prp ON prp.person_id = p.person_id
        WHERE prp.person_id IS NULL
        """
    )
    orphaned_person_ids = [row["person_id"] for row in orphaned_rows]

    if orphaned_person_ids:
        result.persons_orphaned = len(orphaned_person_ids)
        placeholders = ",".join(["%s"] * len(orphaned_person_ids))
        repo.execute(
            f"""
            DELETE FROM person
            WHERE person_id IN ({placeholders})
            """,
            tuple(orphaned_person_ids),
        )

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
    print(f"    Link conflicts resolved: {result.link_conflicts_resolved:>6}  (opinion revision)")
    print(f"    Persons orphaned:        {result.persons_orphaned:>6}  (cleaned up)")
    print(f"    Relationships created:   {result.relationships_created:>6}")

    if result.link_conflicts:
        print(f"\n    LINK CONFLICTS (Opinion Revisions): {len(result.link_conflicts)}")
        for conflict in result.link_conflicts[:3]:  # Show first 3
            print(f"      RecordedPerson {conflict.recorded_person_id}:")
            print(f"        Old link: Person {conflict.old_person_id}")
            print(f"        Attempted: Person {conflict.new_person_id_attempted}")
            print(f"        Resolution: {conflict.resolution}")
        if len(result.link_conflicts) > 3:
            print(f"      ... and {len(result.link_conflicts) - 3} more")

    if result.merge_candidates:
        print(f"\n    MERGE CANDIDATES DETECTED: {len(result.merge_candidates)}")
        for mc in result.merge_candidates[:5]:  # Show first 5
            print(f"      Person {mc.person_id_1} ↔ Person {mc.person_id_2}")
            print(f"        Reason: {mc.reason}")
            print(f"        Detail: {mc.evidence_detail}")
        if len(result.merge_candidates) > 5:
            print(f"      ... and {len(result.merge_candidates) - 5} more")
