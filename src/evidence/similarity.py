"""
GRA — Evidence Layer: Record Similarity

Runs Splink across census Records (households) and writes the results as
RecordSimilarity rows. This is the evidence-layer complement to the
conclusion-layer household linkage pass in src/pipeline/linkage.py, which
that pass will eventually supersede.

Design decisions:
  - Unit of comparison: Record (household), not RecordedPerson. Households
    are richer in signal than individuals (all names + structure in one row)
    and fewer in number (efficiency).
  - Output table: record_similarity (record-to-record measurements).
  - Transaction boundary: one transaction per source-pair (e.g. 1901↔1911,
    1901↔1926, 1911↔1926). Within each source-pair, BATCH_SIZE_RECORD_SIMILARITY
    controls how many pairs are committed at once (None = all at once).
  - Only pairs above PROPOSE_FLOOR are written; pairs below are discarded.
  - Canonical ordering: record_id_1 < record_id_2 enforced before insert to
    prevent duplicate measurements from reversed orderings.

Splink settings mirror _build_household_settings() from pipeline/linkage.py:
  link_type = "link_only" — cross-source pairs only, never within-source.
  Blocking: place_id (primary), substr(household_surname_norm, 1, 4) (fallback).
  Comparisons: household_surname_norm (JaroWinkler + TF), adult_forenames_sorted
    (S–S), child_forenames_young (S–S), child_forenames_older (S–S), place_id
    (exact match).

Entry point:
    run_record_similarity(conn) -> RecordSimilarityResult
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import pandas as pd
import psycopg2.extensions
import splink.comparison_library as cl
import splink.comparison_level_library as cll
from splink import DuckDBAPI, Linker, SettingsCreator, block_on

from src.constants import (
    BATCH_SIZE_RECORD_SIMILARITY,
    CENSUS_SOURCE_IDS,
    PROPOSE_FLOOR,
    SCORE_VERSION_RECORD_SIMILARITY,
)
from src.dal.record_similarity_repo import insert_record_similarity
from src.pipeline.features.census import build_census_household_features


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class RecordSimilarityResult:
    source_pairs_run: int = 0
    pairs_written: int = 0
    pairs_below_floor: int = 0
    skipped: str = ""
    source_pair_counts: dict[str, int] = field(default_factory=dict)
    # e.g. {"1901↔1911": 47, "1901↔1926": 38, "1911↔1926": 52}


# ---------------------------------------------------------------------------
# Splink settings (household-level, evidence layer)
# ---------------------------------------------------------------------------

def _ss_sql(col: str) -> str:
    """
    DuckDB SQL for Szymkiewicz–Simpson on a pipe-joined string column.
    Returns |A∩B| / min(|A|, |B|). NULLIF prevents division by zero.
    The _l/_r suffix is applied by Splink automatically.
    """
    a = f"string_split(\"{col}_l\", '|')"
    b = f"string_split(\"{col}_r\", '|')"
    return (
        f"(len(list_intersect({a}, {b})) * 1.0) / "
        f"nullif(least(len({a}), len({b})), 0)"
    )


def _build_settings() -> SettingsCreator:
    """
    Splink settings for evidence-layer household similarity.

    Mirrors _build_household_settings() from pipeline/linkage.py. Using the
    same feature set ensures that similarity scores are comparable and that
    the conclusion layer can consume RecordSimilarity rows directly when the
    old household linkage pass is retired.

    link_type = "link_only": cross-source pairs only. Each census source is
    a separate DataFrame; Splink generates cross-DataFrame pairs only.

    Blocking:
      Primary:  same resolved place_id (strongest geographic anchor)
      Fallback: first 4 chars of household_surname_norm (phonetic-adjacent)

    Comparisons follow reconstruction_algorithms.md §5.7.
    """
    return SettingsCreator(
        link_type="link_only",
        blocking_rules_to_generate_predictions=[
            block_on("place_id"),
            block_on("substr(household_surname_norm, 1, 4)"),
        ],
        comparisons=[
            # Household surname — modal across all members; stable across head
            # changes. TF adjustment downweights dominant surnames.
            cl.JaroWinklerAtThresholds(
                "household_surname_norm", [0.92, 0.80],
            ).configure(term_frequency_adjustments=True),
            # Adult forename set — role-independent; S–S tolerates departed adults.
            cl.CustomComparison(
                comparison_levels=[
                    cll.NullLevel("adult_forenames_sorted"),
                    cll.CustomLevel(
                        f"({_ss_sql('adult_forenames_sorted')}) >= 1.0",
                        label_for_charts="adult_forenames_ss = 1.0 (full containment)",
                    ),
                    cll.CustomLevel(
                        f"({_ss_sql('adult_forenames_sorted')}) >= 0.5",
                        label_for_charts="adult_forenames_ss >= 0.5 (partial overlap)",
                    ),
                    cll.ElseLevel(),
                ],
                output_column_name="adult_forenames_sorted",
                comparison_description="Adult forename set Szymkiewicz–Simpson overlap",
            ),
            # Young child forename set (age <= CHILD_DEPARTURE_AGE) — primary
            # continuity signal. S–S measures containment of the smaller census
            # set in the larger; departed children reduce the later set without
            # penalising the match.
            cl.CustomComparison(
                comparison_levels=[
                    cll.NullLevel("child_forenames_young"),
                    cll.CustomLevel(
                        f"({_ss_sql('child_forenames_young')}) >= 1.0",
                        label_for_charts="child_young_ss = 1.0 (full containment)",
                    ),
                    cll.CustomLevel(
                        f"({_ss_sql('child_forenames_young')}) >= 0.5",
                        label_for_charts="child_young_ss >= 0.5 (partial overlap)",
                    ),
                    cll.ElseLevel(),
                ],
                output_column_name="child_forenames_young",
                comparison_description="Young child forename set S–S (age <= CHILD_DEPARTURE_AGE)",
            ),
            # Older resident child forename set (age > CHILD_DEPARTURE_AGE) —
            # spinster/bachelor pattern. Softer signal; absence expected.
            cl.CustomComparison(
                comparison_levels=[
                    cll.NullLevel("child_forenames_older"),
                    cll.CustomLevel(
                        f"({_ss_sql('child_forenames_older')}) >= 1.0",
                        label_for_charts="child_older_ss = 1.0 (full containment)",
                    ),
                    cll.CustomLevel(
                        f"({_ss_sql('child_forenames_older')}) >= 0.5",
                        label_for_charts="child_older_ss >= 0.5 (partial overlap)",
                    ),
                    cll.ElseLevel(),
                ],
                output_column_name="child_forenames_older",
                comparison_description="Older child forename set S–S (age > CHILD_DEPARTURE_AGE)",
            ),
            # Place ID — exact match; NullLevel for unresolved places.
            cl.CustomComparison(
                comparison_levels=[
                    cll.NullLevel("place_id"),
                    cll.ExactMatchLevel("place_id"),
                    cll.ElseLevel(),
                ],
                output_column_name="place_id",
                comparison_description="Place ID exact match (nulls treated as non-match)",
            ),
        ],
        retain_matching_columns=True,
        retain_intermediate_calculation_columns=False,
    )


# ---------------------------------------------------------------------------
# Source-pair label helper
# ---------------------------------------------------------------------------

_CENSUS_YEAR: dict[int, int] = {3: 1901, 4: 1911, 5: 1926}


def _pair_label(source_id_l: int, source_id_r: int) -> str:
    """Human-readable label for a source pair, e.g. '1901↔1911'."""
    year_l = _CENSUS_YEAR.get(source_id_l, source_id_l)
    year_r = _CENSUS_YEAR.get(source_id_r, source_id_r)
    lo, hi = min(year_l, year_r), max(year_l, year_r)
    return f"{lo}↔{hi}"


# ---------------------------------------------------------------------------
# Pair commit helper
# ---------------------------------------------------------------------------

def _commit_pairs(
    conn: psycopg2.extensions.connection,
    pairs: list[tuple[int, int, float]],
) -> None:
    """
    Insert a batch of (record_id_1, record_id_2, score) pairs into
    record_similarity within the caller's transaction.

    Canonical ordering (record_id_1 < record_id_2) is enforced here to
    prevent duplicate measurements from reversed orderings.
    """
    for rid_l, rid_r, score in pairs:
        lo, hi = min(rid_l, rid_r), max(rid_l, rid_r)
        insert_record_similarity(
            conn,
            record_id_1=lo,
            record_id_2=hi,
            score=score,
            score_version=SCORE_VERSION_RECORD_SIMILARITY,
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_record_similarity(
    conn: psycopg2.extensions.connection,
) -> RecordSimilarityResult:
    """
    Run Splink household similarity across all census source pairs present
    in the database and write results to record_similarity.

    Requires at least two census sources with Records. Skips gracefully if
    only one source is present.

    Transaction boundary: one transaction per source-pair. Within each
    source-pair, BATCH_SIZE_RECORD_SIMILARITY controls commit granularity
    (None = all pairs in one transaction).

    Only pairs with match_probability >= PROPOSE_FLOOR are written.
    Canonical ordering (record_id_1 < record_id_2) is enforced on insert.

    Returns a RecordSimilarityResult with counts per source-pair.
    """
    result = RecordSimilarityResult()

    # Build household feature DataFrames from evidence layer.
    hh_dfs = build_census_household_features(conn)

    if len(hh_dfs) < 2:
        result.skipped = (
            f"Only {len(hh_dfs)} census source(s) have Records; "
            "record similarity requires at least 2."
        )
        return result

    # Index DataFrames by source_id for pair iteration.
    # Each DataFrame has a 'source_id' column; all rows share the same value.
    df_by_source: dict[int, pd.DataFrame] = {}
    for df in hh_dfs:
        source_id = int(df["source_id"].iloc[0])
        df_by_source[source_id] = df

    active_sources = sorted(df_by_source.keys())

    # Iterate over all unordered source pairs.
    for source_id_l, source_id_r in itertools.combinations(active_sources, 2):
        df_l = df_by_source[source_id_l]
        df_r = df_by_source[source_id_r]
        label = _pair_label(source_id_l, source_id_r)

        # Run Splink for this source pair only.
        db_api   = DuckDBAPI()
        settings = _build_settings()
        linker   = Linker([df_l, df_r], settings, db_api=db_api)

        linker.training.estimate_u_using_random_sampling(max_pairs=1e5)

        linker.training.estimate_parameters_using_expectation_maximisation(
            block_on("substr(household_surname_norm, 1, 4)")
        )
        linker.training.estimate_parameters_using_expectation_maximisation(
            block_on("place_id")
        )

        predictions = linker.inference.predict(
            threshold_match_probability=PROPOSE_FLOOR
        )
        pred_df: pd.DataFrame = predictions.as_pandas_dataframe()

        if pred_df.empty:
            result.source_pair_counts[label] = 0
            result.source_pairs_run += 1
            continue

        pred_df = pred_df.sort_values("match_probability", ascending=False)

        # Collect pairs above floor; track pairs below for reporting.
        pairs_to_write: list[tuple[int, int, float]] = []
        for _, row in pred_df.iterrows():
            rid_l = int(row["unique_id_l"])
            rid_r = int(row["unique_id_r"])
            score = float(row["match_probability"])
            if rid_l == rid_r:
                continue
            if score >= PROPOSE_FLOOR:
                pairs_to_write.append((rid_l, rid_r, score))
            else:
                result.pairs_below_floor += 1

        # Commit within one transaction per source-pair, optionally batched.
        pair_count = 0
        if BATCH_SIZE_RECORD_SIMILARITY is None:
            # Single transaction for all pairs in this source-pair.
            with conn:
                _commit_pairs(conn, pairs_to_write)
            pair_count = len(pairs_to_write)
        else:
            # Batched commits within this source-pair.
            batch_size = BATCH_SIZE_RECORD_SIMILARITY
            for i in range(0, len(pairs_to_write), batch_size):
                batch = pairs_to_write[i : i + batch_size]
                with conn:
                    _commit_pairs(conn, batch)
                pair_count += len(batch)

        result.pairs_written += pair_count
        result.source_pair_counts[label] = pair_count
        result.source_pairs_run += 1

    return result


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

def print_record_similarity_report(result: RecordSimilarityResult) -> None:
    print("\n  RECORD SIMILARITY (evidence-layer Splink)")
    if result.skipped:
        print(f"    Skipped: {result.skipped}")
        return
    print(f"    Source pairs run:    {result.source_pairs_run:>6}")
    print(f"    Pairs written:       {result.pairs_written:>6}")
    print(f"    Pairs below floor:   {result.pairs_below_floor:>6}")
    if result.source_pair_counts:
        print("    Per source pair:")
        for label, count in sorted(result.source_pair_counts.items()):
            print(f"      {label}:  {count:>6}")


# ===========================================================================
# PERSON SIMILARITY (RecordedPerson-to-RecordedPerson)
# ===========================================================================

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class PersonSimilarityResult:
    source_pairs_run: int = 0
    pairs_written: int = 0
    pairs_below_floor: int = 0
    skipped: str = ""
    source_pair_counts: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Splink settings (person-level, evidence layer)
# ---------------------------------------------------------------------------

def _build_person_settings() -> SettingsCreator:
    """
    Splink settings for evidence-layer person similarity.

    link_type = "link_only": cross-source pairs only. Each census source is
    a separate DataFrame; Splink generates cross-DataFrame pairs only.

    Blocking:
      Primary:  same resolved place_id (strongest geographic anchor)
      Fallback: first 4 chars of surname_norm (phonetic-adjacent)

    Comparisons:
      - name_normalized (Jaro-Winkler with TF adjustment)
      - birth_year_est (absolute difference bands: 0, <=2, <=5)
      - sex_as_recorded (exact match)
      - place_id (exact match)

    Note: v1.0 does not include household similarity scores as a hierarchical
    feature. This will be added in a future version (see ROADMAP).
    """
    return SettingsCreator(
        link_type="link_only",
        blocking_rules_to_generate_predictions=[
            block_on("place_id"),
            block_on("substr(surname_norm, 1, 4)"),
        ],
        comparisons=[
            # Full name — JaroWinkler with TF adjustment for common names
            cl.JaroWinklerAtThresholds(
                "name_normalized", [0.92, 0.80],
            ).configure(term_frequency_adjustments=True),

            # Birth year — absolute difference bands
            cl.CustomComparison(
                comparison_levels=[
                    cll.NullLevel("birth_year_est"),
                    cll.ExactMatchLevel("birth_year_est"),
                    cll.CustomLevel(
                        "ABS(birth_year_est_l - birth_year_est_r) <= 2",
                        label_for_charts="birth_year ±2",
                    ),
                    cll.CustomLevel(
                        "ABS(birth_year_est_l - birth_year_est_r) <= 5",
                        label_for_charts="birth_year ±5",
                    ),
                    cll.ElseLevel(),
                ],
                output_column_name="birth_year_est",
                comparison_description="Birth year estimated from age",
            ),

            # Sex — exact match
            cl.CustomComparison(
                comparison_levels=[
                    cll.NullLevel("sex_as_recorded"),
                    cll.ExactMatchLevel("sex_as_recorded"),
                    cll.ElseLevel(),
                ],
                output_column_name="sex_as_recorded",
                comparison_description="Sex as recorded (M/F)",
            ),

            # Place ID — exact match
            cl.CustomComparison(
                comparison_levels=[
                    cll.NullLevel("place_id"),
                    cll.ExactMatchLevel("place_id"),
                    cll.ElseLevel(),
                ],
                output_column_name="place_id",
                comparison_description="Place ID exact match",
            ),
        ],
        retain_matching_columns=True,
        retain_intermediate_calculation_columns=False,
    )


# ---------------------------------------------------------------------------
# Pair commit helper
# ---------------------------------------------------------------------------

def _commit_person_pairs(
    conn: psycopg2.extensions.connection,
    pairs: list[tuple[int, int, float]],
    score_version: str,
) -> None:
    """
    Insert a batch of (recorded_person_id_1, recorded_person_id_2, score) pairs
    into recorded_relationship with type='similarity' within the caller's transaction.

    Canonical ordering (recorded_person_id_1 < recorded_person_id_2) is enforced
    here to prevent duplicate measurements from reversed orderings.
    """
    from src.dal.recorded_relationship_repo import insert_recorded_relationship
    for rp_id_l, rp_id_r, score in pairs:
        lo, hi = min(rp_id_l, rp_id_r), max(rp_id_l, rp_id_r)
        insert_recorded_relationship(
            conn,
            recorded_person_id_1=lo,
            recorded_person_id_2=hi,
            rel_type="similarity",
            score=score,
            score_version=score_version,
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_person_similarity(
    conn: psycopg2.extensions.connection,
) -> PersonSimilarityResult:
    """
    Run Splink person similarity across all census source pairs present
    in the database and write results to recorded_relationship with type='similarity'.

    Requires at least two census sources with RecordedPersons. Skips gracefully
    if only one source is present.

    Transaction boundary: one transaction per source-pair. Within each
    source-pair, BATCH_SIZE_PERSON_SIMILARITY controls commit granularity
    (None = all pairs in one transaction).

    Only pairs with match_probability >= PROPOSE_FLOOR are written.
    Canonical ordering (recorded_person_id_1 < recorded_person_id_2) is enforced on insert.

    Returns a PersonSimilarityResult with counts per source-pair.
    """
    from src.constants import (
        BATCH_SIZE_PERSON_SIMILARITY,
        SCORE_VERSION_PERSON_SIMILARITY,
    )
    from src.pipeline.features.census_person import build_census_person_features

    result = PersonSimilarityResult()

    # Build person feature DataFrames from evidence layer
    person_dfs = build_census_person_features(conn)

    if len(person_dfs) < 2:
        result.skipped = (
            f"Only {len(person_dfs)} census source(s) have RecordedPersons; "
            "person similarity requires at least 2."
        )
        return result

    # Index DataFrames by source_id for pair iteration
    df_by_source: dict[int, pd.DataFrame] = {}
    for df in person_dfs:
        source_id = int(df["source_id"].iloc[0])
        df_by_source[source_id] = df

    active_sources = sorted(df_by_source.keys())

    # Iterate over all unordered source pairs
    for source_id_l, source_id_r in itertools.combinations(active_sources, 2):
        df_l = df_by_source[source_id_l]
        df_r = df_by_source[source_id_r]
        label = _pair_label(source_id_l, source_id_r)

        # Run Splink for this source pair only
        db_api   = DuckDBAPI()
        settings = _build_person_settings()
        linker   = Linker([df_l, df_r], settings, db_api=db_api)

        linker.training.estimate_u_using_random_sampling(max_pairs=1e5)

        linker.training.estimate_parameters_using_expectation_maximisation(
            block_on("substr(surname_norm, 1, 4)")
        )
        linker.training.estimate_parameters_using_expectation_maximisation(
            block_on("place_id")
        )

        predictions = linker.inference.predict(
            threshold_match_probability=PROPOSE_FLOOR
        )
        pred_df: pd.DataFrame = predictions.as_pandas_dataframe()

        if pred_df.empty:
            result.source_pair_counts[label] = 0
            result.source_pairs_run += 1
            continue

        pred_df = pred_df.sort_values("match_probability", ascending=False)

        # Collect pairs above floor; track pairs below for reporting
        pairs_to_write: list[tuple[int, int, float]] = []
        for _, row in pred_df.iterrows():
            rp_id_l = int(row["unique_id_l"])
            rp_id_r = int(row["unique_id_r"])
            score = float(row["match_probability"])
            if rp_id_l == rp_id_r:
                continue
            if score >= PROPOSE_FLOOR:
                pairs_to_write.append((rp_id_l, rp_id_r, score))
            else:
                result.pairs_below_floor += 1

        # Commit within one transaction per source-pair, optionally batched
        pair_count = 0
        if BATCH_SIZE_PERSON_SIMILARITY is None:
            # Single transaction for all pairs in this source-pair
            with conn:
                _commit_person_pairs(conn, pairs_to_write, SCORE_VERSION_PERSON_SIMILARITY)
            pair_count = len(pairs_to_write)
        else:
            # Batched commits within this source-pair
            batch_size = BATCH_SIZE_PERSON_SIMILARITY
            for i in range(0, len(pairs_to_write), batch_size):
                batch = pairs_to_write[i : i + batch_size]
                with conn:
                    _commit_person_pairs(conn, batch, SCORE_VERSION_PERSON_SIMILARITY)
                pair_count += len(batch)

        result.pairs_written += pair_count
        result.source_pair_counts[label] = pair_count
        result.source_pairs_run += 1

    return result


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

def print_person_similarity_report(result: PersonSimilarityResult) -> None:
    print("\n  PERSON SIMILARITY (evidence-layer Splink)")
    if result.skipped:
        print(f"    Skipped: {result.skipped}")
        return
    print(f"    Source pairs run:    {result.source_pairs_run:>6}")
    print(f"    Pairs written:       {result.pairs_written:>6}")
    print(f"    Pairs below floor:   {result.pairs_below_floor:>6}")
    if result.source_pair_counts:
        print("    Per source pair:")
        for label, count in sorted(result.source_pair_counts.items()):
            print(f"      {label}:  {count:>6}")
