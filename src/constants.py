"""
GRA — Centralised constants.

All hardcoded values that were previously scattered across pipeline modules
live here. Import from this module rather than redefining locally.

Usage:
    from src.constants import CENSUS_SOURCE_IDS, AUTO_COMMIT_THRESHOLD
"""

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_VERSION: int = 40

# ---------------------------------------------------------------------------
# Source IDs (matches seed.sql)
# ---------------------------------------------------------------------------

CENSUS_SOURCE_IDS: tuple[int, ...] = (3, 4, 5)   # 1901, 1911, 1926
SOURCE_ID_1901: int = 3
SOURCE_ID_1911: int = 4
SOURCE_ID_1926: int = 5
SOURCE_ID_PLACE_AUTHORITY: int = 13

# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

# Age threshold for child departure prior (reconstruction_algorithms.md §5.7).
# Children aged <= this are treated as young dependents (primary continuity
# signal). Children aged > this are the spinster/bachelor pattern (softer
# signal; absence expected across census span).
CHILD_DEPARTURE_AGE: int = 20

# ---------------------------------------------------------------------------
# Linkage thresholds
# ---------------------------------------------------------------------------

AUTO_COMMIT_THRESHOLD: float = 0.85   # score >= this → auto-merge (legacy linkage)
PROPOSE_FLOOR: float = 0.30           # score >= this → queue as proposal

# ---------------------------------------------------------------------------
# Conclusion layer thresholds
# ---------------------------------------------------------------------------

# Person Resolution: clustering threshold for person-level similarity.
# v1.1: Lowered from 0.65 to 0.60
# Rationale: Splink name matching with TF adjustment downweights common names significantly
# (e.g., "Robert Bustard" scores 0.528 despite being exact matches). Analysis shows
# many valid cross-census matches fall in 0.50-0.65 range due to TF penalty on common names.
# Threshold 0.60 captures these without requiring Splink changes that cause double-linking.
PERSON_RESOLUTION_THRESHOLD: float = 0.60

# ---------------------------------------------------------------------------
# Score versions — identify the algorithm run that produced a score
# ---------------------------------------------------------------------------

SCORE_VERSION_PERSON: str = "census_linkage_v1.0"
SCORE_VERSION_HH: str = "household_linkage_v1.0"
SCORE_VERSION_HOUSEHOLD_INGEST: str = "household_v1.0"
SCORE_VERSION_CONSENSUS: str = "consensus_v1.0"
SCORE_VERSION_PLACE: str = "place_v2.0"
SCORE_VERSION_ROLE_PAIR: str = "role_pair_v1.0"
SCORE_VERSION_RECORD_SIMILARITY: str = "record_similarity_v1.0"
SCORE_VERSION_PERSON_SIMILARITY: str = "person_similarity_v1.0"
SCORE_VERSION_PERSON_SIMILARITY_V1_1: str = "person_similarity_v1.1_with_household_context"

# ---------------------------------------------------------------------------
# Ingest-time assertion scores
# These are assigned at ingest/household-inference time, not by Splink.
# They represent high-confidence structural assertions rather than
# probabilistic similarity scores.
# ---------------------------------------------------------------------------

SCORE_PERSON_RECORD_INGEST: float = 0.90   # person_recorded_person at ingest
SCORE_EVENT_RECORD_INGEST: float = 0.90    # event_record at ingest

# ---------------------------------------------------------------------------
# Role-pair prior scores for RecordedRelationship (evidence layer)
# Source: reconstruction_algorithms.md §6.1 (census role-pair table)
# These are stored on recorded_relationship.score at ingest time.
# ---------------------------------------------------------------------------

# Census household role-pair priors
SCORE_ROLE_COUPLE: float = 0.90          # head + spouse
SCORE_ROLE_PARENT_CHILD_HEAD: float = 0.85    # head + son/daughter, head + mother/father
SCORE_ROLE_PARENT_CHILD_SPOUSE: float = 0.80  # spouse + son/daughter
SCORE_ROLE_SIBLING_DIRECT: float = 0.80      # head + sibling
SCORE_ROLE_SIBLING_INFERRED: float = 0.75    # son+son, daughter+daughter, son+daughter

# ---------------------------------------------------------------------------
# Record similarity (evidence-layer Splink)
# ---------------------------------------------------------------------------

# Maximum pairs to commit per transaction within a source-pair run.
# None = unbatched (commit all pairs for a source-pair in one transaction).
# Set to an integer (e.g. 5000) for large datasets to reduce transaction size.
BATCH_SIZE_RECORD_SIMILARITY: int | None = 5000

# ---------------------------------------------------------------------------
# Person similarity (evidence-layer Splink)
# ---------------------------------------------------------------------------

# Maximum pairs to commit per transaction within a source-pair run.
# None = unbatched (commit all pairs for a source-pair in one transaction).
# Set to an integer (e.g. 5000) for large datasets to reduce transaction size.
BATCH_SIZE_PERSON_SIMILARITY: int | None = 5000
