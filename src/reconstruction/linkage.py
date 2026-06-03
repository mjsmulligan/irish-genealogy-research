"""
GRA — Cross-Source Person Linkage
Stage 4 of the reconstruction pipeline.

Loads Person conclusions from the conclusion layer, builds a feature
DataFrame via a source-specific feature extractor, runs Splink
probabilistic linkage using DuckDB in-memory, then writes results
back to genealogy.db:

  - Score >= AUTO_COMMIT  → merge lower person_id wins; person_record committed
  - AUTO_COMMIT > score >= PROPOSE_FLOOR → person_record row written, verified=0
  - Score < PROPOSE_FLOOR → suppressed

Merge contract (lower person_id = canonical):
  - person_record rows       → re-pointed to canonical
  - person_event rows        → re-pointed to canonical
  - person_name rows         → re-pointed to canonical (duplicates dropped)
  - relationship endpoints   → person_id_1 / person_id_2 updated
  - provisional person row   → deleted

Entry point: run_census_linkage(conn) -> CensusLinkageResult
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

import pandas as pd
import splink.comparison_library as cl
import splink.comparison_level_library as cll
from splink import DuckDBAPI, Linker, SettingsCreator, block_on

from src.reconstruction.features.census import build_census_features

# ---------------------------------------------------------------------------
# Threshold bands (reconstruction_algorithms.md §1.3)
# ---------------------------------------------------------------------------

AUTO_COMMIT_THRESHOLD = 0.85
PROPOSE_FLOOR         = 0.30
SCORE_VERSION         = "census_linkage_v1.0"

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class CensusLinkageResult:
    persons_merged:    int = 0
    proposals_written: int = 0
    suppressed:        int = 0
    skipped:           str = ""          # reason if pipeline did not run
    merge_log:         list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Splink configuration
# ---------------------------------------------------------------------------

def _build_settings() -> SettingsCreator:
    """
    Splink settings for cross-census person linkage.

    link_type = "link_and_dedupe": find matches both within and across
    census sources. This handles the case where household inference
    has already created provisional Person conclusions per source and
    we need to collapse them.

    Blocking rules:
      Primary:  same resolved place_id  (strong geographic anchor)
      Fallback: same first 4 chars of surname_norm (phonetic-adjacent)

    Comparisons follow reconstruction_algorithms.md §5.2.
    Birth year comparison uses absolute difference; place uses exact match.
    """
    return SettingsCreator(
        link_type="link_and_dedupe",
        blocking_rules_to_generate_predictions=[
            block_on("place_id"),
            block_on("substr(surname_norm, 1, 4)"),
        ],
        comparisons=[
            cl.JaroWinklerAtThresholds(
                "surname_norm",
                [0.92, 0.80],
            ),
            cl.JaroWinklerAtThresholds(
                "forename_norm",
                [0.92, 0.80],
            ),
            # birth_year_est is an integer — use AbsoluteDifferenceLevel directly.
            # Thresholds match reconstruction_algorithms.md §5.6: ±2, ±5, ±10 years.
            cl.CustomComparison(
                comparison_levels=[
                    cll.NullLevel("birth_year_est"),
                    cll.ExactMatchLevel("birth_year_est"),
                    cll.AbsoluteDifferenceLevel("birth_year_est", 2),
                    cll.AbsoluteDifferenceLevel("birth_year_est", 5),
                    cll.AbsoluteDifferenceLevel("birth_year_est", 10),
                    cll.ElseLevel(),
                ],
                output_column_name="birth_year_est",
                comparison_description="Birth year absolute difference at thresholds 2, 5, 10",
            ),
            # place_id: exact match on resolved townland conclusion.
            # A NullLevel is required first — without it, DuckDB's
            # IS NOT DISTINCT FROM treats NULL=NULL as a positive place
            # match, giving unresolved persons a spurious place score.
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
# Merge logic
# ---------------------------------------------------------------------------

def _merge_persons(
    conn: sqlite3.Connection,
    canonical_id: int,
    duplicate_id: int,
    score: float,
    score_version: str,
    result: CensusLinkageResult,
) -> None:
    """
    Merge duplicate_id into canonical_id.
    Lower person_id is always canonical (enforced by caller).

    All junction rows referencing duplicate_id are re-pointed to
    canonical_id. The duplicate person row is then deleted.
    """
    assert canonical_id < duplicate_id, (
        f"Merge called with canonical_id={canonical_id} > duplicate_id={duplicate_id}; "
        "lower person_id must be canonical."
    )

    # 1. person_record: move records, avoid duplicate PKs
    dup_records = conn.execute(
        "SELECT record_id, score, score_version, verified FROM person_record "
        "WHERE person_id = ?",
        (duplicate_id,),
    ).fetchall()

    existing_record_ids = {
        row[0] for row in conn.execute(
            "SELECT record_id FROM person_record WHERE person_id = ?",
            (canonical_id,),
        ).fetchall()
    }

    for row in dup_records:
        if row["record_id"] not in existing_record_ids:
            conn.execute(
                "INSERT INTO person_record "
                "(person_id, record_id, score, score_version, verified) "
                "VALUES (?, ?, ?, ?, ?)",
                (canonical_id, row["record_id"],
                 row["score"], row["score_version"], row["verified"]),
            )
        # Always delete the duplicate's row (either we just inserted the
        # canonical version, or canonical already has this record)
    conn.execute(
        "DELETE FROM person_record WHERE person_id = ?", (duplicate_id,)
    )

    # 2. person_event: move, drop duplicates
    conn.execute(
        """
        INSERT OR IGNORE INTO person_event (person_id, event_id)
        SELECT ?, event_id FROM person_event WHERE person_id = ?
        """,
        (canonical_id, duplicate_id),
    )
    conn.execute(
        "DELETE FROM person_event WHERE person_id = ?", (duplicate_id,)
    )

    dup_names = conn.execute(
        "SELECT value, type FROM person_name WHERE person_id = ?",
        (duplicate_id,),
    ).fetchall()
    existing_names = {
        (row["value"], row["type"])
        for row in conn.execute(
            "SELECT value, type FROM person_name WHERE person_id = ?",
            (canonical_id,),
        ).fetchall()
    }
    for name_row in dup_names:
        key = (name_row["value"], name_row["type"])
        if key not in existing_names:
            max_pn_id = conn.execute(
                "SELECT COALESCE(MAX(person_name_id), 0) FROM person_name"
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO person_name (person_name_id, person_id, value, type) "
                "VALUES (?, ?, ?, ?)",
                (max_pn_id + 1, canonical_id, name_row["value"], name_row["type"]),
            )
    conn.execute(
        "DELETE FROM person_name WHERE person_id = ?", (duplicate_id,)
    )

    # 5. relationship endpoints: re-point person_id_1 and person_id_2.
    #
    # The CHECK constraint person_id_1 != person_id_2 fires immediately on
    # each row as UPDATE executes — SQLite does not defer constraint checks
    # to end-of-statement. A relationship between canonical_id and
    # duplicate_id will become self-referential the moment one endpoint is
    # updated, causing an IntegrityError before we can clean it up.
    #
    # Solution: identify and delete those relationships BEFORE the UPDATE,
    # cleaning their junction rows first so FK constraints are satisfied.
    #
    # A relationship becomes self-referential after re-pointing if:
    #   - one endpoint is canonical_id and the other is duplicate_id, OR
    #   - both endpoints are duplicate_id (edge case: relationship to self
    #     in source data, shouldn't exist but guard anyway).
    self_ref_ids = [
        row[0] for row in conn.execute(
            """
            SELECT relationship_id FROM relationship
            WHERE (person_id_1 = ? AND person_id_2 = ?)
               OR (person_id_1 = ? AND person_id_2 = ?)
               OR (person_id_1 = ? AND person_id_2 = ?)
            """,
            (canonical_id, duplicate_id,
             duplicate_id, canonical_id,
             duplicate_id, duplicate_id),
        ).fetchall()
    ]

    if self_ref_ids:
        placeholders = ",".join("?" * len(self_ref_ids))
        conn.execute(
            f"DELETE FROM relationship_record WHERE relationship_id IN ({placeholders})",
            self_ref_ids,
        )
        conn.execute(
            f"DELETE FROM relationship WHERE relationship_id IN ({placeholders})",
            self_ref_ids,
        )

    # Now safe to re-point all remaining endpoints.
    conn.execute(
        "UPDATE relationship SET person_id_1 = ? WHERE person_id_1 = ?",
        (canonical_id, duplicate_id),
    )
    conn.execute(
        "UPDATE relationship SET person_id_2 = ? WHERE person_id_2 = ?",
        (canonical_id, duplicate_id),
    )

    # 6. (Safety net) Drop any remaining self-referential relationships.
    # Under correct logic step 6 should have caught all of them; this is
    # a belt-and-suspenders guard for any edge case missed above.
    # Junction rows cleaned first for the same FK reason as above.
    conn.execute(
        """
        DELETE FROM relationship_record
        WHERE relationship_id IN (
            SELECT relationship_id FROM relationship
            WHERE person_id_1 = person_id_2
        )
        """
    )
    conn.execute(
        "DELETE FROM relationship WHERE person_id_1 = person_id_2"
    )

    # 7. Deduplicate relationships: if re-pointing created an exact
    # (type, person_id_1, person_id_2) duplicate, keep the lower relationship_id
    # and delete the higher ones — but clean their junction rows first.
    conn.execute(
        """
        DELETE FROM relationship_record
        WHERE relationship_id NOT IN (
            SELECT MIN(relationship_id)
            FROM relationship
            GROUP BY type, person_id_1, person_id_2
        )
        """
    )
    conn.execute(
        """
        DELETE FROM relationship
        WHERE relationship_id NOT IN (
            SELECT MIN(relationship_id)
            FROM relationship
            GROUP BY type, person_id_1, person_id_2
        )
        """
    )

    # 8. Delete the duplicate Person.
    # All junction rows referencing duplicate_id have been moved or deleted
    # above. The DELETE will now succeed without FK violations.
    conn.execute("DELETE FROM person WHERE person_id = ?", (duplicate_id,))

    result.persons_merged += 1
    result.merge_log.append(
        f"Merged person_id={duplicate_id} → canonical person_id={canonical_id} "
        f"(score={score:.3f})"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_census_linkage(conn: sqlite3.Connection) -> CensusLinkageResult:
    """
    Run cross-census person linkage for all census sources that have
    been ingested and reconstructed.

    Only runs if at least two census sources have Person conclusions.
    Safe to call incrementally — Splink will still score all pairs but
    the merge step only acts on pairs where neither person has already
    been merged (i.e. where both person_ids still exist).

    Returns a CensusLinkageResult summary.
    """
    result = CensusLinkageResult()

    # Check how many census sources have Person conclusions
    source_counts = conn.execute(
        """
        SELECT s.source_id, COUNT(DISTINCT pr.person_id) AS person_count
        FROM person_record pr
        JOIN record r ON r.record_id = pr.record_id
        JOIN source s ON s.source_id = r.source_id
        WHERE s.source_id IN (3, 4, 5)
        GROUP BY s.source_id
        """
    ).fetchall()

    active_sources = [row["source_id"] for row in source_counts]

    if len(active_sources) < 2:
        result.skipped = (
            f"Only {len(active_sources)} census source(s) have Person conclusions; "
            f"cross-census linkage requires at least 2."
        )
        return result

    # Build feature DataFrames — one per census source
    source_dfs = build_census_features(conn)

    if not source_dfs:
        result.skipped = "Feature extraction returned no rows."
        return result

    # Run Splink with DuckDB backend (in-memory).
    # Pass the list of per-source DataFrames; Splink's link_and_dedupe mode
    # assigns source_dataset automatically from list position and uses
    # unique_id (= person_id) as the row key.
    db_api = DuckDBAPI()
    settings = _build_settings()

    linker = Linker(source_dfs, settings, db_api=db_api)

    # Estimate u probabilities via random sampling
    linker.training.estimate_u_using_random_sampling(max_pairs=1e5)

    # Estimate m probabilities via two EM passes with different blocking keys.
    #
    # Pass 1 blocks on surname prefix — this trains birth_year_est, forename_norm,
    # and place_id. Splink explicitly excludes any comparison whose column is used
    # as the blocking key, so surname_norm cannot be estimated in this pass.
    #
    # Pass 2 blocks on place_id — place_id is not a comparison feature, so all
    # four comparisons (including surname_norm) receive m-probability estimates.
    # Without this pass surname_norm carries no trained weight and all match
    # probabilities are depressed below the auto-commit threshold.
    linker.training.estimate_parameters_using_expectation_maximisation(
        block_on("substr(surname_norm, 1, 4)")
    )
    linker.training.estimate_parameters_using_expectation_maximisation(
        block_on("place_id")
    )

    # Generate predictions
    predictions = linker.inference.predict(
        threshold_match_probability=PROPOSE_FLOOR
    )
    pred_df: pd.DataFrame = predictions.as_pandas_dataframe()

    if pred_df.empty:
        result.skipped = "Splink produced no predictions above the propose floor."
        return result

    # Sort by score descending; process highest confidence first
    pred_df = pred_df.sort_values("match_probability", ascending=False)

    # Track which person_ids have already been merged this run
    # to avoid acting on stale pairs (both IDs must still exist)
    merged_this_run: set[int] = set()

    with conn:
        for _, row in pred_df.iterrows():
            # Splink link_and_dedupe outputs unique_id_l / unique_id_r;
            # unique_id == person_id in our feature DataFrames.
            pid_l = int(row["unique_id_l"])
            pid_r = int(row["unique_id_r"])
            score = float(row["match_probability"])

            # Skip self-matches (shouldn't happen but guard anyway)
            if pid_l == pid_r:
                continue

            # Skip if either person was already merged this run
            if pid_l in merged_this_run or pid_r in merged_this_run:
                continue

            # Verify both persons still exist in the DB
            existing = {
                row2[0] for row2 in conn.execute(
                    "SELECT person_id FROM person WHERE person_id IN (?, ?)",
                    (pid_l, pid_r),
                ).fetchall()
            }
            if len(existing) < 2:
                continue

            canonical_id  = min(pid_l, pid_r)
            duplicate_id  = max(pid_l, pid_r)

            if score >= AUTO_COMMIT_THRESHOLD:
                _merge_persons(
                    conn, canonical_id, duplicate_id,
                    score, SCORE_VERSION, result,
                )
                merged_this_run.add(duplicate_id)

            else:
                # Propose: write a person_record link for the duplicate's
                # records against the canonical person for researcher review.
                # The duplicate Person is not deleted — researcher decides.
                dup_records = conn.execute(
                    "SELECT record_id FROM person_record WHERE person_id = ?",
                    (duplicate_id,),
                ).fetchall()
                for rec_row in dup_records:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO person_record
                        (person_id, record_id, score, score_version, verified)
                        VALUES (?, ?, ?, ?, 0)
                        """,
                        (canonical_id, rec_row["record_id"], score, SCORE_VERSION),
                    )
                result.proposals_written += 1

    return result


def print_census_linkage_report(result: CensusLinkageResult) -> None:
    """Print a human-readable summary of census linkage results."""
    print("\n  CROSS-CENSUS LINKAGE")
    if result.skipped:
        print(f"    Skipped: {result.skipped}")
        return
    print(f"    Persons merged:        {result.persons_merged:>6}")
    print(f"    Proposals written:     {result.proposals_written:>6}")
    if result.merge_log:
        print(f"\n  MERGE LOG ({len(result.merge_log)} entries)")
        for entry in result.merge_log[:20]:
            print(f"    {entry}")
        if len(result.merge_log) > 20:
            print(f"    ... and {len(result.merge_log) - 20} more")