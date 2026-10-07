"""
GRA — Genealogy Research Assistant
Review layer: priority scoring.

Takes a list[ReportItem] with priority=0 placeholders and assigns integer
priority scores (1 = highest).  Items are then sorted ascending.

Scoring model
-------------
Three inputs collapse to a single score; lower = higher priority.

1. Certainty tier — how definitively the schema can detect this class of error:
   Schema-state findings (singularity violations, merge error candidates) are
   highest certainty; inferred findings (sequence violations, lifespan) are
   medium; research prompts (unlinked, single appearance) are lowest.

2. Severity — degree to which this finding contaminates downstream conclusions:
   A merge error corrupts every relationship and event inferred from it, so it
   scores highest within its tier.

3. Scope — number of linked RecordedPersons across distinct census sources
   for the anchoring Person (where known).  Persons evidenced across multiple
   censuses have more downstream impact.

The exact weights are held loosely pending the first training session.
The current model is: base_score(finding_type) × scope_multiplier, then
rank by that score (lower = higher priority), then assign rank as priority.

Weights and tiers are centralised here as module-level constants so they can
be tuned without hunting through logic.
"""

from __future__ import annotations

from src.db.repository import Repository

from src.review.report import ReportItem

# ---------------------------------------------------------------------------
# Tier base scores — lower = higher priority within ranking
# ---------------------------------------------------------------------------

# Schema-state findings: high certainty, high downstream impact
_TIER_SCHEMA_STATE: int = 100

# Constraint violations: high certainty, may indicate merge error
_TIER_CONSTRAINT: int = 200

# Research prompts: lower certainty, lower severity
_TIER_RESEARCH_PROMPT: int = 300

# Per-finding-type base scores within tiers
_BASE_SCORE: dict[str, int] = {
    "merge_error_candidate":              _TIER_SCHEMA_STATE + 0,   # highest — corrupts everything
    "birth_singularity_violation":        _TIER_SCHEMA_STATE + 10,
    "death_singularity_violation":        _TIER_SCHEMA_STATE + 10,
    "parent_age_regression":              _TIER_CONSTRAINT - 10,   # age regression is critical merge error
    "split_person_candidate":             _TIER_CONSTRAINT + 0,    # very high — suggests split needed
    "life_event_sequence_violation":      _TIER_CONSTRAINT + 5,
    "parent_age_implausible":             _TIER_CONSTRAINT + 10,
    "marriage_age_implausible":           _TIER_CONSTRAINT + 20,
    "lifespan_boundary_violated":         _TIER_CONSTRAINT + 30,
    "unlinked_in_populated_household":    _TIER_RESEARCH_PROMPT - 10,  # high priority: likely valid linkages
    "unlinked_recorded_person":           _TIER_RESEARCH_PROMPT + 0,
    "single_census_appearance":           _TIER_RESEARCH_PROMPT + 10,
}

_DEFAULT_BASE_SCORE: int = _TIER_RESEARCH_PROMPT + 50  # fallback for unknown types


# ---------------------------------------------------------------------------
# Scope weight
# ---------------------------------------------------------------------------

def _scope_weight(
    repo: Repository,
    person_id: int | None,
) -> float:
    """
    Return a multiplier < 1.0 that lowers the raw score (= raises priority)
    for Persons with more census evidence.

    Persons linked to 3 distinct census sources → weight 0.80
    Persons linked to 2 distinct census sources → weight 0.90
    Persons linked to 1 or fewer               → weight 1.00
    No person_id (e.g. unlinked RecordedPerson)→ weight 1.00
    """
    if person_id is None:
        return 1.0

    row = repo.fetch_one(
        """
        SELECT COUNT(DISTINCT r.source_id) AS source_count
        FROM person_recorded_person prp
        JOIN recorded_person rp ON rp.recorded_person_id = prp.recorded_person_id
        JOIN record r ON r.record_id = rp.record_id
        JOIN source s ON s.source_id = r.source_id
        WHERE prp.person_id = %s AND s.type = 'census'
        """,
        (person_id,),
    )

    source_count = row["source_count"] if row else 0
    if source_count >= 3:
        return 0.80
    if source_count == 2:
        return 0.90
    return 1.00


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def assign_priorities(
    repo: Repository,
    items: list[ReportItem],
) -> list[ReportItem]:
    """
    Assign integer priority scores to all items in-place, then sort ascending
    (priority=1 = highest priority).

    Returns the sorted list (same list object, mutated).
    """
    if not items:
        return items

    # Step 1: compute raw float score for each item
    raw_scores: list[float] = []
    for item in items:
        base = _BASE_SCORE.get(item.finding_type, _DEFAULT_BASE_SCORE)
        weight = _scope_weight(repo, item.person_id)
        raw_scores.append(base * weight)

    # Step 2: sort items by raw score ascending (lower = higher priority)
    paired = sorted(zip(raw_scores, range(len(items))), key=lambda x: (x[0], x[1]))

    # Step 3: assign integer priority ranks 1..N
    sorted_items: list[ReportItem] = []
    for rank, (_, original_idx) in enumerate(paired, start=1):
        item = items[original_idx]
        item.priority = rank
        sorted_items.append(item)

    return sorted_items
