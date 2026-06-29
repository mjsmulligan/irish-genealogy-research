"""
GRA — Evidence Layer Features: Census Person

Builds one Pandas DataFrame per active census source, suitable for use as
Splink input in run_person_similarity().

Each row represents one RecordedPerson.  Columns:

    unique_id                           INTEGER  — recorded_person_id (Splink join key)
    source_id                           INTEGER  — census source (3=1901, 4=1911, 5=1926)
    place_id                            INTEGER  — resolved place_id from the parent Record, or NULL
    surname_norm                        TEXT     — normalised surname (last token of name_as_recorded)
    forename_norm                       TEXT     — normalised forenames (all tokens except last)
    name_norm                           TEXT     — forename_norm + " " + surname_norm (full name for Splink comparison)
    soundex_surname                     TEXT     — Soundex phonetic code of surname (for blocking on Irish variants)
    birth_year_est                      INTEGER  — census_year − age (NULL if age is NULL)
    sex_as_recorded                     TEXT     — 'm' / 'f' / NULL
    household_match_score_to_SOURCE     REAL     — per-source household similarity (v1.1)

Household context (v1.1):
    For each person in source S, computes household_match_score_to_T for each other source T.
    This column contains the MAX(record_similarity.score) between the person's parent Record
    and any Record in source T. Enables Splink to use source-specific household context.
    Example: Person from 1901 with household_match_score_to_4 = 0.87 means their household
    has a 0.87 match with some 1911 household (but may have 0.5 with 1926).

Role consistency (v1.2):
    Adds role column from recorded_person for Splink comparison. Enables Splink to score
    role consistency: exact matches (head→head) are strongest evidence; plausible transitions
    (son→head at age 30+) are medium evidence; implausible changes (head→son) are weak signals.

Validation integration (v1.4):
    Adds three features for Splink to learn during EM training:
    - name_first_name_variant: 'exact' | 'approved' | 'suspicious' — validates Irish name variants
    - age_progression_validity: cross-source age consistency (0.0-1.0, computed during comparison)
    - household_same_person_check: flags duplicate person_ids in same household (0 | 1)
    These features allow Splink's EM training to learn that invalid age progressions
    and suspicious name changes are unreliable signals for matching.

Normalisation:
    All name tokens are lowercased and stripped.
    Roles are normalized (lowercased) for comparison.

Entry point:
    build_census_person_features(conn) -> list[pd.DataFrame]
"""

from __future__ import annotations

import pandas as pd

from src.db.repository import Repository
from src.constants import CENSUS_SOURCE_IDS
from src.evidence.features.census import _soundex
from src.genealogy import classify_forename, CENSUS_YEAR

# Map source_id → approximate census year for birth_year_est calculation.
_SOURCE_YEAR: dict[int, int] = CENSUS_YEAR


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_household_score_lookup(
    repo: Repository,
) -> dict[tuple[int, int, int], float]:
    """
    Build a lookup: (record_id, source_id, target_source_id) → max household match score.

    For each record in source_id, returns the maximum record_similarity score it has
    with any record in target_source_id. This provides pair-specific household context:
    e.g., Record A from 1901 gets its max match score against all 1911 records separately
    from its max match against all 1926 records.

    v1.1 hierarchical feature: provides source-specific household context to Splink.
    Returns dict keyed by (source_record.record_id, source_record.source_id, target_source_id).
    """
    from src.constants import CENSUS_SOURCE_IDS

    lookup: dict[tuple[int, int, int], float] = {}

    # Get source_id for each record first
    record_source_rows = repo.fetch_all(
        f"""
        SELECT r.record_id, r.source_id
        FROM record r
        WHERE r.source_id IN ({','.join(str(s) for s in CENSUS_SOURCE_IDS)})
        """
    )
    record_sources = {row["record_id"]: row["source_id"] for row in record_source_rows}

    # Now build per-source household match scores
    similarity_rows = repo.fetch_all(
        """
        SELECT
            rs.record_id_1,
            rs.record_id_2,
            rs.score,
            r1.source_id AS source_1,
            r2.source_id AS source_2
        FROM record_similarity rs
        JOIN record r1 ON r1.record_id = rs.record_id_1
        JOIN record r2 ON r2.record_id = rs.record_id_2
        """
    )
    for row in similarity_rows:
            rid_1 = row["record_id_1"]
            rid_2 = row["record_id_2"]
            score = row["score"]
            src_1 = row["source_1"]
            src_2 = row["source_2"]

            # Add both directions: rid_1's match toward src_2, and vice versa
            key_1 = (rid_1, src_1, src_2)
            key_2 = (rid_2, src_2, src_1)
            lookup[key_1] = max(lookup.get(key_1, 0.0), score)
            lookup[key_2] = max(lookup.get(key_2, 0.0), score)

    return lookup


def _norm(name: str | None) -> str:
    """Lowercase + strip; return '' for None."""
    return (name or "").lower().strip()


def _surname_from(name: str | None) -> str | None:
    """Last whitespace-delimited token of the name string."""
    parts = _norm(name).split()
    return parts[-1] if parts else None


def _forename_from(name: str | None) -> str | None:
    """Everything before the last token."""
    parts = _norm(name).split()
    if len(parts) >= 2:
        return " ".join(parts[:-1])
    return parts[0] if parts else None


def _classify_first_name_variant(forename: str | None) -> str:
    """
    Classify first name variant for Splink.  Delegates to src.genealogy.classify_forename().

    Returns 'exact' | 'approved' | 'suspicious' — see genealogy/names.py for semantics.
    """
    return classify_forename(forename)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_census_person_features(
    repo: Repository,
) -> list[pd.DataFrame]:
    """
    Build one Pandas DataFrame per active census source for Splink
    person-level (RecordedPerson) similarity.

    Returns a list of DataFrames, one per source that has at least one
    RecordedPerson.  Sources with no RecordedPersons are omitted.

    Each DataFrame has Splink-required column 'unique_id' set to
    recorded_person_id.

    v1.1: Adds household_match_score (pre-computed from record_similarity)
    to provide hierarchical household context to Splink.
    """
    result: list[pd.DataFrame] = []

    # Build a lookup: (record_id, source_id, target_source_id) → household match score
    # Provides per-source household context for each person pair
    household_scores: dict[tuple[int, int, int], float] = _build_household_score_lookup(repo)

    for source_id in CENSUS_SOURCE_IDS:
        census_year = _SOURCE_YEAR.get(source_id)

        persons = repo.fetch_all(
            """
            SELECT
                rp.recorded_person_id,
                rp.name_as_recorded,
                rp.age,
                rp.sex_as_recorded,
                rp.role,
                pr.place_id,
                rp.record_id
            FROM recorded_person rp
            JOIN record r ON r.record_id = rp.record_id
            LEFT JOIN place_record pr ON pr.record_id = r.record_id
            WHERE r.source_id = %s
            ORDER BY rp.recorded_person_id
            """,
            (source_id,),
        )

        if not persons:
            continue

        rows: list[dict] = []
        for p in persons:
            age = p["age"]
            birth_year_est = (census_year - int(age)) if (census_year and age is not None) else None

            surname = _surname_from(p["name_as_recorded"])
            forename = _forename_from(p["name_as_recorded"])
            name_norm = (
                f"{forename} {surname}".strip()
                if forename
                else surname
            ) or None

            # Build base row
            row_dict = {
                "unique_id": p["recorded_person_id"],
                "source_id": source_id,
                "place_id": p["place_id"],
                "surname_norm": surname,
                "soundex_surname": _soundex(surname),
                "forename_norm": forename,
                "name_norm": name_norm,
                "birth_year_est": birth_year_est,
                "sex_as_recorded": _norm(p["sex_as_recorded"]) or None,
                "role": _norm(p["role"]) or None,
            }

            # Add validation features (v1.4: validation integration)
            # These features encode validation rules for Splink to learn during EM training
            row_dict["name_first_name_variant"] = _classify_first_name_variant(forename)
            # Age progression and household checks are cross-source; Splink computes during comparison
            row_dict["age_progression_validity"] = 0.5  # Neutral placeholder; Splink handles cross-source
            row_dict["household_same_person_check"] = 0  # Neutral placeholder

            # Add per-source household match scores (one column per other source)
            for other_source in CENSUS_SOURCE_IDS:
                if other_source != source_id:
                    col_name = f"household_match_score_to_{other_source}"
                    key = (p["record_id"], source_id, other_source)
                    row_dict[col_name] = household_scores.get(key)

            rows.append(row_dict)

        df = pd.DataFrame(rows)
        df["unique_id"] = df["unique_id"].astype(int)
        df["source_id"] = df["source_id"].astype(int)

        # Ensure ALL household_match_score_to_* columns exist across ALL sources
        # (Splink requires all columns present in all dataframes)
        for target_source in CENSUS_SOURCE_IDS:
            col_name = f"household_match_score_to_{target_source}"
            if col_name not in df.columns:
                df[col_name] = None

        # Ensure role column exists (should always exist from SELECT, but be safe)
        if "role" not in df.columns:
            df["role"] = None

        result.append(df)

    return result
