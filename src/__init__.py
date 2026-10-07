"""
GRA — Genealogy Research Assistant

Two-layer pipeline:

Evidence layer (cli add-evidence, per CSV):
    [1/5] Ingest           — src.evidence.census.ingest_census
    [2/5] Relationships    — src.evidence.role_relationships
    [3/5] Place resolution — src.evidence.place_resolution
    [4/5] Record similarity — src.evidence.similarity.run_record_similarity
    [5/5] Person similarity — src.evidence.similarity.run_person_similarity

Conclusion layer (cli conclude):
    [1/3] Person resolution      — src.conclusion.person_resolution
    [2/3] Relationship resolution — src.conclusion.relationship_resolution
    [3/3] Event resolution        — src.conclusion.event_resolution

Review layer (cli review — planned):
    Researcher-facing report module. Uses genealogical rules to surface areas
    needing attention rather than enforcing hard constraints. Separate from the
    pipeline; run independently after conclude.
    — src.review.validator  (PostgreSQL port + redesign pending)
"""
