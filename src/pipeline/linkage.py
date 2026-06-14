"""
GRA — Cross-Source Person Linkage
Stage 4 of the reconstruction pipeline.

Two entry points:

run_census_household_linkage(conn, debug_log=None)
    Pass 1: match census household Records across census years using
    household-level Splink (head name, spouse forename, child forenames,
    place, household size). One row per Record.
    Pass 2: resolve individual Person identities within confirmed household
    pairs and merge them using the lower-person-id-wins rule.
    Census sources only (source_ids 3, 4, 5).
    Must run before run_census_linkage().

run_census_linkage(conn, already_merged=None, debug_log=None)
    General cross-census person linkage for persons not already resolved
    by the household pass. Uses person-level features (name, birth year,
    place, spouse/child/sibling names from the conclusion layer).
    Skips persons whose person_id appears in already_merged.

Merge contract (lower person_id = canonical) — applied by _merge_persons():
  - person_record rows       → re-pointed to canonical
  - person_event rows        → re-pointed to canonical
  - person_name rows         → re-pointed to canonical (duplicates dropped)
  - relationship endpoints   → person_id_1 / person_id_2 updated
  - provisional person row   → deleted

Debug log
---------
Both entry points accept an optional debug_log="path/to/file.txt" argument.
When provided, a three-section plain-text log is written after the pipeline
completes (even if it was skipped early):

  SECTION 1 — PIPELINE SUMMARY
    Active sources, feature matrix quality (null rates, size), candidate
    pair counts, score distribution histogram, training notes.
    For the household pass: confirmed/proposed pair counts, persons merged.

  SECTION 2 — SCORING DETAIL
    Surname/head-surname frequency table, one row per Splink pair showing
    score, labels, source years, name similarity, birth year delta, place
    match, and outcome band. Proposed pairs listed separately.

  SECTION 3 — CLAUDE ANALYSIS NOTES
    Opinionated analysis: issues (thin training data, high null rates,
    surname frequency risk, score clustering near thresholds, suspicious
    merges), what looks good, and specific recommended actions.
    Formatted for direct consumption in a GRA research session prompt.
"""

from __future__ import annotations

import datetime
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import rapidfuzz 
import pandas as pd
import splink.comparison_library as cl
import splink.comparison_level_library as cll
from splink import DuckDBAPI, Linker, SettingsCreator, block_on

from src.pipeline.features.census import (
    build_census_features,
    build_census_household_features,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# SQLite source_ids for the three census years.  Defined once here so that
# all queries reference the same constant rather than scattered literals.
CENSUS_SOURCE_IDS: tuple[int, ...] = (3, 4, 5)

# _CENSUS_SOURCE_PLACEHOLDERS is derived here; threshold constants and
# _CENSUS_NAMES are defined in debug.py and imported above.
_CENSUS_SOURCE_PLACEHOLDERS = ",".join("?" * len(CENSUS_SOURCE_IDS))

# Census year for each source_id — used by the birth-year coherence gate.
_CENSUS_YEAR: dict[int, int] = {3: 1901, 4: 1911, 5: 1926}

# Minimum forename similarity to accept a role match in Pass 2.
_MIN_FORENAME_SIM = 0.80


def _gc03_birth_year_tol(source_id_l: int, source_id_r: int) -> int:
    """
    Return the GC03 birth-year delta tolerance for a given census pair.

    GC03 tolerances:
      1901↔1911 (10-year gap) — ±3 years
      1911↔1926 (15-year gap) — ±3 years
      1901↔1926 (25-year gap) — ±4 years

    Returns 4 (the widest tolerance) when source years are unknown,
    so the gate passes conservatively rather than incorrectly rejecting.
    """
    year_l = _CENSUS_YEAR.get(source_id_l)
    year_r = _CENSUS_YEAR.get(source_id_r)
    if year_l is None or year_r is None:
        return 4
    gap = abs(year_r - year_l)
    return 4 if gap > 15 else 3

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class HouseholdLinkageResult:
    household_pairs_confirmed: int = 0
    household_pairs_proposed:  int = 0
    persons_merged:            int = 0
    merge_log:                 list[str] = field(default_factory=list)
    merged_person_ids:         set[int]  = field(default_factory=set)
    skipped:                   str = ""
    # Timing (seconds). Zero means the stage did not run.
    elapsed_total:             float = 0.0
    elapsed_feature_extract:   float = 0.0
    elapsed_training:          float = 0.0
    elapsed_prediction:        float = 0.0
    elapsed_merge:             float = 0.0


@dataclass
class CensusLinkageResult:
    persons_merged:    int = 0
    proposals_written: int = 0
    suppressed:        int = 0
    skipped:           str = ""
    merge_log:         list[str] = field(default_factory=list)
    # Timing (seconds). Zero means the stage did not run.
    elapsed_total:           float = 0.0
    elapsed_feature_extract: float = 0.0
    elapsed_training:        float = 0.0
    elapsed_prediction:      float = 0.0
    elapsed_merge:           float = 0.0


# ---------------------------------------------------------------------------
# Debug log — accumulators, helpers, and writers
# ---------------------------------------------------------------------------

from src.pipeline.debug import (
    AUTO_COMMIT_THRESHOLD,
    PROPOSE_FLOOR,
    SCORE_VERSION_PERSON,
    SCORE_VERSION_HH,
    _CENSUS_NAMES,
    PairRecord as _PairRecord,
    HouseholdDebugLog as _HouseholdDebugLog,
    PersonDebugLog as _PersonDebugLog,
    populate_hh_feature_stats  as _populate_hh_feature_stats,
    build_hh_label_map          as _build_hh_label_map,
    build_hh_pair_record        as _build_hh_pair_record,
    populate_person_feature_stats      as _populate_person_feature_stats,
    build_person_label_and_source_maps as _build_person_label_and_source_maps,
    build_person_pair_record           as _build_person_pair_record,
    write_household_debug_log   as _write_household_debug_log,
    write_person_debug_log      as _write_person_debug_log,
)


# ---------------------------------------------------------------------------
# Union-Find for transitive identity resolution
# ---------------------------------------------------------------------------


class _UnionFind:
    """
    Path-compressed, union-by-min-id union-find structure for person identity
    clusters.

    Lower person_id is always the canonical (root) node, matching the merge
    contract enforced by _merge_persons().

    This replaces the simple merged_set pattern, which caused non-transitive
    resolution: if A→B merged first and then C→B was evaluated, C→B was
    skipped (B absorbed) without evaluating C→A, leaving C unlinked.

    With union-find:
      - find(id)  returns the current canonical id for any person, following
                  the chain with path compression.
      - union(a, b)  merges the two clusters; lower root wins.
      - absorbed  is the set of all non-canonical ids (formerly merged_set),
                  used to exclude already-resolved persons from Splink input.
      - rewrite(pid_l, pid_r)  translates a raw Splink pair to their current
                  canonical ids before any merge decision is made, enabling
                  transitive closure across sequential pair processing.
    """

    def __init__(self, initial: set[int] | None = None) -> None:
        # parent[id] = canonical id (or self if root)
        self._parent: dict[int, int] = {}
        # _absorbed is maintained incrementally so absorbed is O(1).
        self._absorbed: set[int] = set()
        if initial:
            for pid in initial:
                self._parent[pid] = pid

    def _ensure(self, pid: int) -> None:
        if pid not in self._parent:
            self._parent[pid] = pid

    def find(self, pid: int) -> int:
        """Return canonical id for pid, with path compression."""
        self._ensure(pid)
        root = pid
        while self._parent[root] != root:
            root = self._parent[root]
        # Path compression: point every node on the chain directly to root.
        node = pid
        while self._parent[node] != root:
            nxt = self._parent[node]
            self._parent[node] = root
            node = nxt
        return root

    def union(self, a: int, b: int) -> int:
        """
        Merge clusters containing a and b. Lower canonical id wins.
        Returns the canonical id of the merged cluster.
        """
        ra = self.find(a)
        rb = self.find(b)
        if ra == rb:
            return ra
        canonical  = min(ra, rb)
        absorbed   = max(ra, rb)
        self._parent[absorbed] = canonical
        self._absorbed.add(absorbed)
        return canonical

    def rewrite(self, pid_l: int, pid_r: int) -> tuple[int, int]:
        """
        Translate a raw pair to their current canonical ids.
        Use this before any merge decision so stale pair endpoints resolve
        correctly and transitive links are not missed.
        """
        return self.find(pid_l), self.find(pid_r)

    @property
    def absorbed(self) -> set[int]:
        """
        Set of all non-canonical (absorbed) person_ids.
        Maintained incrementally in union() — O(1) access.
        Equivalent to the old merged_set: use to exclude already-resolved
        persons from Splink feature DataFrames.
        """
        return self._absorbed


# ---------------------------------------------------------------------------
# Shared merge logic
# ---------------------------------------------------------------------------

def _merge_persons(
    conn: sqlite3.Connection,
    canonical_id: int,
    duplicate_id: int,
    score: float,
    score_version: str,
    merge_log: list[str],
    uf: "_UnionFind",
) -> None:
    """
    Merge duplicate_id into canonical_id.
    Lower person_id is always canonical (enforced by caller).

    All junction rows referencing duplicate_id are re-pointed to
    canonical_id. The duplicate person row is then deleted.

    merge_log is mutated in place. uf.union() records the merge in the
    union-find structure so subsequent pairs resolve transitively.
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

    # 3. person_name: move, drop duplicates
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
    # Fetch MAX once before the loop; increment a local counter per insert
    # to avoid re-querying inside the transaction where visibility of
    # just-inserted rows is implementation-defined.
    next_pn_id = conn.execute(
        "SELECT COALESCE(MAX(person_name_id), 0) FROM person_name"
    ).fetchone()[0] + 1
    for name_row in dup_names:
        key = (name_row["value"], name_row["type"])
        if key not in existing_names:
            conn.execute(
                "INSERT INTO person_name (person_name_id, person_id, value, type) "
                "VALUES (?, ?, ?, ?)",
                (next_pn_id, canonical_id, name_row["value"], name_row["type"]),
            )
            existing_names.add(key)
            next_pn_id += 1
    conn.execute(
        "DELETE FROM person_name WHERE person_id = ?", (duplicate_id,)
    )

    # 4. relationship endpoints.
    #
    # The CHECK constraint person_id_1 != person_id_2 fires immediately on
    # each UPDATE row. A relationship between canonical_id and duplicate_id
    # will become self-referential the moment one endpoint is updated.
    # Identify and delete those relationships BEFORE the UPDATE.
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

    conn.execute(
        "UPDATE relationship SET person_id_1 = ? WHERE person_id_1 = ?",
        (canonical_id, duplicate_id),
    )
    conn.execute(
        "UPDATE relationship SET person_id_2 = ? WHERE person_id_2 = ?",
        (canonical_id, duplicate_id),
    )

    # 5. Safety net: drop any remaining self-referential relationships.
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

    # 6. Deduplicate relationships created by re-pointing.
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

    # 7. training_labels: re-point or delete proposals referencing duplicate_id.

    # Delete the direct proposal between this pair — superseded by the merge.
    conn.execute(
        """
        DELETE FROM training_labels
        WHERE (person_id_1 = ? AND person_id_2 = ?)
           OR (person_id_1 = ? AND person_id_2 = ?)
        """,
        (canonical_id, duplicate_id, duplicate_id, canonical_id),
    )

    # Re-point remaining proposals that reference duplicate_id.
    # Fetch them, delete them, reinsert with canonical_id substituted and
    # endpoints re-sorted (min left, max right) to satisfy person_id_1 < person_id_2.
    stale_rows = conn.execute(
        """
        SELECT label_id, person_id_1, person_id_2, score, score_version,
               decision, note, created_at, reviewed_at
        FROM training_labels
        WHERE person_id_1 = ? OR person_id_2 = ?
        """,
        (duplicate_id, duplicate_id),
    ).fetchall()

    if stale_rows:
        stale_ids = [row["label_id"] for row in stale_rows]
        placeholders = ",".join("?" * len(stale_ids))
        conn.execute(
            f"DELETE FROM training_labels WHERE label_id IN ({placeholders})",
            stale_ids,
        )
        for row in stale_rows:
            p1 = canonical_id if row["person_id_1"] == duplicate_id else row["person_id_1"]
            p2 = canonical_id if row["person_id_2"] == duplicate_id else row["person_id_2"]
            lo, hi = min(p1, p2), max(p1, p2)
            if lo == hi:
                continue  # self-referential after substitution — drop it
            conn.execute(
                """
                INSERT OR IGNORE INTO training_labels
                    (person_id_1, person_id_2, score, score_version,
                     decision, note, created_at, reviewed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (lo, hi, row["score"], row["score_version"],
                 row["decision"], row["note"], row["created_at"], row["reviewed_at"]),
            )

    # 8. Delete the duplicate Person.
    conn.execute("DELETE FROM person WHERE person_id = ?", (duplicate_id,))

    uf.union(canonical_id, duplicate_id)
    merge_log.append(
        f"Merged person_id={duplicate_id} → canonical person_id={canonical_id} "
        f"(score={score:.3f}, version={score_version})"
    )


# ---------------------------------------------------------------------------
# Household linkage — Splink settings (Pass 1)
# ---------------------------------------------------------------------------


def _ss_sql(col: str) -> str:
    """
    DuckDB SQL for Szymkiewicz–Simpson on a pipe-joined string column.
    Returns |A∩B| / min(|A|, |B|). The column suffix _l/_r is applied
    by Splink automatically.

    NULLIF prevents division by zero when either side has an empty set
    (though NullLevel fires first for genuine nulls).
    """
    a = f"string_split(\"{col}_l\", '|')"
    b = f"string_split(\"{col}_r\", '|')"
    return (
        f"(len(list_intersect({a}, {b})) * 1.0) / "
        f"nullif(least(len({a}), len({b})), 0)"
    )


def _build_household_settings() -> SettingsCreator:
    """
    Splink settings for household-level cross-census matching.

    link_type = "link_only": matching households across census years only;
    each census year is a separate DataFrame so Splink generates cross-source
    pairs only — never within-source.

    Features are role-independent to handle head changes across the 25-year
    span (death → spouse becomes head → son becomes head). Anchoring on the
    head's forename or birth year would produce column mismatches for valid
    household continuations where the head has changed.

    Blocking:
      Primary:  same resolved place_id (strongest anchor)
      Fallback: first 4 chars of household_surname_norm

    Comparisons follow reconstruction_algorithms.md §5.7.

    Name-set comparisons use Szymkiewicz–Simpson (|A∩B| / min(|A|,|B|))
    rather than Jaccard. Over a 25-year span, children leave and adults die;
    the expanding union penalises valid continuations under Jaccard.
    S–S measures whether the smaller set is contained in the larger, which
    is the right question for household continuity.

    Child forenames are split by departure prior (age <= 20 vs age > 20):
      child_forenames_young — primary signal; children certainly still
        present as dependents. S–S on this set is the main child feature.
      child_forenames_older — spinster/bachelor pattern; present at this
        census but expected to have departed by the next. Softer signal;
        NullLevel fires frequently and absence does not penalise.
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
            # Adult forename set — role-independent; includes head, spouse, and
            # any other non-child co-resident. Szymkiewicz–Simpson tolerates
            # adults who have died or left between census years.
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
            # Young child forename set (age <= 20) — primary continuity signal.
            # These children are definitively present at the time of census and
            # not yet of departure age. S–S measures containment of the smaller
            # census set in the larger; departed children reduce the later set
            # without penalising the match.
            # NullLevel fires when either household has no young children.
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
                comparison_description="Young child forename set (age<=20) Szymkiewicz–Simpson",
            ),
            # Older resident child forename set (age > 20) — spinster/bachelor
            # pattern. Present in this census but likely departed by the next.
            # Treated as a softer secondary signal: absence is expected and does
            # not penalise a valid continuation. NullLevel fires when neither
            # household has any older resident children.
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
                comparison_description="Older resident child forename set (age>20) Szymkiewicz–Simpson",
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
# Household linkage — Pass 2: intra-household person resolution
# ---------------------------------------------------------------------------

def _jaro_winkler(a: str | None, b: str | None) -> float:
    """Jaro-Winkler similarity between two strings. Returns 0.0 if either is None."""
    if not a or not b:
        return 0.0
    try:
        return rapidfuzz.jaro_winkler_similarity(a, b)
    except Exception:
        return 0.0


def _persons_for_record(
    conn: sqlite3.Connection,
    record_id: int,
) -> list[dict]:
    """
    Return all Person conclusions linked to a census Record, with their
    role (from recorded_person) and normalised forename.

    Each dict: { person_id, role, forename_norm, birth_year_est, age }

    Join strategy: fetch person_record rows and recorded_person rows for
    this record separately, then pair them positionally by insertion order
    (person_name_id ASC for persons, recorded_person_id ASC for evidence).

    This avoids two historical problems:
      1. Brittle name-string equality join (rp.name_as_recorded = pn.value)
         that caused silent exclusions on transcription/case variance.
      2. Role-collision: when two persons share the same role (e.g. two
         boarders), a MIN(recorded_person_id) subquery assigned the same
         evidence row to both conclusion-layer persons.

    Positional pairing is valid because household inference creates Person
    conclusions in the same order as recorded_person rows for the record.
    Where the counts differ (inference skipped some rows), we truncate to
    the shorter list — unmatched persons are excluded rather than mis-paired.
    """
    # Fetch persons for this record in creation order.
    person_rows = conn.execute(
        """
        SELECT
            pr.person_id,
            pn.value        AS full_name
        FROM person_record pr
        JOIN person_name pn ON pn.person_id = pr.person_id
            AND pn.type = 'birth_name'
            AND pn.person_name_id = (
                SELECT MIN(pn2.person_name_id)
                FROM person_name pn2
                WHERE pn2.person_id = pr.person_id
                  AND pn2.type = 'birth_name'
            )
        WHERE pr.record_id = ?
        ORDER BY pr.person_id   -- creation order proxy; person_id is auto-increment
        """,
        (record_id,),
    ).fetchall()

    # Fetch evidence rows for this record in recorded order.
    evidence_rows = conn.execute(
        """
        SELECT
            rp.role,
            rp.age,
            r.date AS census_date
        FROM recorded_person rp
        JOIN record r ON r.record_id = rp.record_id
        WHERE rp.record_id = ?
        ORDER BY rp.recorded_person_id
        """,
        (record_id,),
    ).fetchall()

    result = []
    for pr, er in zip(person_rows, evidence_rows):
        full = pr["full_name"] or ""
        parts = full.strip().split()
        forename_raw = parts[0] if parts else None
        forename_norm = forename_raw.lower() if forename_raw else None

        birth_year = None
        if er["age"] is not None and er["census_date"]:
            m = re.match(r"^(\d{4})", er["census_date"])
            if m:
                raw = int(m.group(1)) - int(er["age"])
                birth_year = raw if 1750 <= raw <= 1926 else None

        result.append({
            "person_id":      pr["person_id"],
            "role":           er["role"],
            "forename_norm":  forename_norm,
            "birth_year_est": birth_year,
            "age":            er["age"],
        })
    return result


def _resolve_household_persons(
    conn: sqlite3.Connection,
    record_id_l: int,
    record_id_r: int,
    hh_score: float,
    result: HouseholdLinkageResult,
    uf: "_UnionFind",
) -> None:
    """
    Pass 2: resolve Person identities within a confirmed household pair
    (record_id_l from year Y1, record_id_r from year Y2) and merge them.

    Resolution order per §5.7: head → spouse → children → other roles.

    For head and spouse: merge when forename similarity >= _MIN_FORENAME_SIM
    and birth year delta is within census tolerance (§5.6).

    For children: bipartite matching — each child in L is scored against
    each child in R; highest-scoring valid assignment is selected greedily.
    A child forename similarity threshold of _MIN_FORENAME_SIM applies.

    Other roles (mother, father, grandchild, sibling, in_law, etc.) are
    matched by forename similarity where unambiguous; otherwise skipped
    and noted for researcher attention (deferred to leads system in R2).

    Birth year delta tolerances from GC03/§5.6:
      1901↔1911: ±3    1911↔1926: ±3    1901↔1926: ±4
    """

    def _census_year(record_id: int) -> int | None:
        row = conn.execute(
            "SELECT date FROM record WHERE record_id = ?", (record_id,)
        ).fetchone()
        if row and row["date"]:
            m = re.match(r"^(\d{4})", row["date"])
            return int(m.group(1)) if m else None
        return None

    year_l = _census_year(record_id_l)
    year_r = _census_year(record_id_r)

    # Census gaps are exact (1901↔1911=10, 1911↔1926=15, 1901↔1926=25).
    # Age coherence: the observed age delta between two persons proposed as
    # the same individual should equal the known census gap, within tolerance.
    # This is stronger than comparing birth year estimates because it encodes
    # what we know exactly (the gap) rather than what we estimate (birth year).
    #
    # GC03 tolerances: ±3 years for 10/15-year gaps, ±4 years for 25-year gap.
    # These account for transcription error and age rounding in census records.
    _expected_gap: int | None = abs(year_r - year_l) if (year_l and year_r) else None

    def _age_coherence_tol() -> int:
        if _expected_gap is None:
            return 3
        return 4 if _expected_gap > 15 else 3

    _tol = _age_coherence_tol()

    def _age_coherent(age_l: int | None, age_r: int | None) -> bool:
        """
        True if the observed age delta is within tolerance of the expected
        census gap. Passes when either age is missing (can't disqualify on
        absent data). Also passes when census years are unknown.

        Example: child aged 4 in 1901 should be aged 14 in 1911.
        observed_delta = |14 - 4| = 10, expected_gap = 10, deviation = 0 ✓
        A child aged 16 in 1911 would give deviation = 2 — within ±3 ✓
        A child aged 20 in 1911 would give deviation = 6 — rejected ✗
        """
        if age_l is None or age_r is None or _expected_gap is None:
            return True
        observed_delta = abs(int(age_r) - int(age_l))
        return abs(observed_delta - _expected_gap) <= _tol

    persons_l = _persons_for_record(conn, record_id_l)
    persons_r = _persons_for_record(conn, record_id_r)

    def _by_role(persons: list[dict], role: str) -> list[dict]:
        return [p for p in persons if p["role"] == role]

    def _try_merge(pl: dict, pr: dict, score: float) -> bool:
        """Attempt to merge two persons. Returns True if merged."""
        pid_l = pl["person_id"]
        pid_r = pr["person_id"]
        # Rewrite through union-find so stale ids resolve to their current
        # canonical before the merge decision.
        can_l, can_r = uf.rewrite(pid_l, pid_r)
        if can_l == can_r:
            return False
        canonical  = min(can_l, can_r)
        duplicate  = max(can_l, can_r)
        _merge_persons(
            conn, canonical, duplicate, score, SCORE_VERSION_HH,
            result.merge_log, uf,
        )
        result.persons_merged += 1
        return True

    # --- Head ---
    heads_l = _by_role(persons_l, "head")
    heads_r = _by_role(persons_r, "head")
    if heads_l and heads_r:
        hl, hr = heads_l[0], heads_r[0]
        sim = _jaro_winkler(hl["forename_norm"], hr["forename_norm"])
        if sim >= _MIN_FORENAME_SIM and _age_coherent(hl["age"], hr["age"]):
            _try_merge(hl, hr, hh_score)

    # --- Spouse ---
    spouses_l = _by_role(persons_l, "spouse")
    spouses_r = _by_role(persons_r, "spouse")
    if spouses_l and spouses_r:
        sl, sr = spouses_l[0], spouses_r[0]
        sim = _jaro_winkler(sl["forename_norm"], sr["forename_norm"])
        if sim >= _MIN_FORENAME_SIM and _age_coherent(sl["age"], sr["age"]):
            _try_merge(sl, sr, hh_score)

    # --- Children: greedy bipartite matching on forename similarity ---
    children_l = [p for p in persons_l if p["role"] in ("son", "daughter")]
    children_r = [p for p in persons_r if p["role"] in ("son", "daughter")]

    if children_l and children_r:
        pairs = []
        for cl_p in children_l:
            for cr_p in children_r:
                sim = _jaro_winkler(cl_p["forename_norm"], cr_p["forename_norm"])
                if sim >= _MIN_FORENAME_SIM and _age_coherent(cl_p["age"], cr_p["age"]):
                    pairs.append((sim, cl_p, cr_p))
        pairs.sort(key=lambda x: x[0], reverse=True)

        matched_l: set[int] = set()
        matched_r: set[int] = set()
        for sim, cl_p, cr_p in pairs:
            pid_l = cl_p["person_id"]
            pid_r = cr_p["person_id"]
            if pid_l in matched_l or pid_r in matched_r:
                continue
            if _try_merge(cl_p, cr_p, hh_score):
                matched_l.add(pid_l)
                matched_r.add(pid_r)

    # Other roles (mother, father, grandchild, sibling, in_law, etc.) are
    # not resolved automatically. Interval signal generation for these is
    # deferred to the leads system in Release 2 (§5.7).


# ---------------------------------------------------------------------------
# Household linkage — entry point (Pass 1 + Pass 2)
# ---------------------------------------------------------------------------

def run_census_household_linkage(
    conn: sqlite3.Connection,
    debug_log: str | None = None,
) -> HouseholdLinkageResult:
    """
    Run the two-pass household linkage pipeline for census sources.

    Pass 1: Splink household matching across census years.
    Pass 2: Person resolution and merge within confirmed pairs.

    Returns a HouseholdLinkageResult. The set of merged person_ids is
    stored on the result object so run_census_linkage() can skip them.

    Parameters
    ----------
    conn :
        Open SQLite connection from open_db().
    debug_log :
        Optional path to a plain-text debug log file. When provided, a
        three-section log is written after the pipeline completes.

    Requires:
      - Place resolution completed (place_record populated)
      - Household inference completed (person_record populated)
      - At least 2 census sources with Records
    """
    result = HouseholdLinkageResult()
    debug  = _HouseholdDebugLog(
        run_ts=datetime.datetime.now().isoformat(timespec="seconds")
    )
    _t_total = time.perf_counter()

    # Guard: need at least 2 census sources with Records.
    source_counts = conn.execute(
        f"""
        SELECT source_id, COUNT(*) AS n
        FROM record
        WHERE source_id IN ({_CENSUS_SOURCE_PLACEHOLDERS})
        GROUP BY source_id
        """,
        CENSUS_SOURCE_IDS,
    ).fetchall()

    active_sources = [row["source_id"] for row in source_counts]
    debug.active_sources    = active_sources
    debug.records_per_source = {row["source_id"]: row["n"] for row in source_counts}

    if len(active_sources) < 2:
        reason = (
            f"Only {len(active_sources)} census source(s) have Records; "
            "household linkage requires at least 2."
        )
        result.skipped       = reason
        debug.skipped_reason = reason
        if debug_log:
            _write_household_debug_log(debug_log, debug, result)
        return result

    # Build household feature DataFrames — one per census source.
    _t0 = time.perf_counter()
    hh_dfs = build_census_household_features(conn)
    result.elapsed_feature_extract = time.perf_counter() - _t0
    if not hh_dfs:
        reason = "Household feature extraction returned no rows."
        result.skipped       = reason
        debug.skipped_reason = reason
        if debug_log:
            _write_household_debug_log(debug_log, debug, result)
        return result

    _populate_hh_feature_stats(debug, hh_dfs)

    # --- Pass 1: Splink household matching ---
    db_api   = DuckDBAPI()
    settings = _build_household_settings()
    linker   = Linker(hh_dfs, settings, db_api=db_api)

    _t0 = time.perf_counter()
    linker.training.estimate_u_using_random_sampling(max_pairs=1e5)
    debug.training_notes.append("u-probabilities: random sampling (max_pairs=1e5)")

    linker.training.estimate_parameters_using_expectation_maximisation(
        block_on("substr(household_surname_norm, 1, 4)")
    )
    debug.training_notes.append(
        "EM pass 1: block_on('substr(household_surname_norm, 1, 4)') — "
        "trains adult_forenames_sorted, child_forenames_young, child_forenames_older, place_id"
    )

    linker.training.estimate_parameters_using_expectation_maximisation(
        block_on("place_id")
    )
    debug.training_notes.append(
        "EM pass 2: block_on('place_id') — trains household_surname_norm weight"
    )
    result.elapsed_training = time.perf_counter() - _t0

    _t0 = time.perf_counter()
    predictions = linker.inference.predict(
        threshold_match_probability=PROPOSE_FLOOR
    )
    pred_df: pd.DataFrame = predictions.as_pandas_dataframe()
    result.elapsed_prediction = time.perf_counter() - _t0

    if pred_df.empty:
        reason = "Splink produced no household predictions above the propose floor."
        result.skipped       = reason
        debug.skipped_reason = reason
        if debug_log:
            _write_household_debug_log(debug_log, debug, result)
        return result

    pred_df = pred_df.sort_values("match_probability", ascending=False)
    debug.pairs_above_floor = len(pred_df)

    # Build a label map for the debug log: record_id → head name string
    label_map = _build_hh_label_map(conn, hh_dfs)

    # uf is shared across Pass 1 and Pass 2 — tracks all identity clusters
    # so _try_merge can resolve stale pair endpoints transitively and
    # _resolve_household_persons can skip already-canonical pairs.
    uf: _UnionFind = _UnionFind()

    # processed_records prevents acting on the same household pair twice
    # (Splink may produce (A,B) and (B,A) as separate rows).
    processed_records: set[frozenset] = set()

    _t0 = time.perf_counter()
    for _, row in pred_df.iterrows():
        rid_l = int(row["unique_id_l"])   # unique_id == record_id
        rid_r = int(row["unique_id_r"])
        score = float(row["match_probability"])

        if rid_l == rid_r:
            continue

        pair_key = frozenset((rid_l, rid_r))
        if pair_key in processed_records:
            continue
        processed_records.add(pair_key)

        if score >= AUTO_COMMIT_THRESHOLD:
            result.household_pairs_confirmed += 1
            # Pass 2: resolve persons within this confirmed household pair.
            # Each household pair commits independently so a failure mid-run
            # does not roll back all preceding merges.
            with conn:
                _resolve_household_persons(
                    conn, rid_l, rid_r, score, result, uf,
                )
            if debug_log:
                debug.record_pair(_build_hh_pair_record(
                    row, "merged", "", label_map,
                ))
                debug.persons_merged = result.persons_merged
        else:
            # Below auto-commit but above floor — queue for researcher review.
            # No person merges; the pair is noted for leads generation (R2).
            result.household_pairs_proposed += 1
            if debug_log:
                debug.record_pair(_build_hh_pair_record(
                    row, "proposed", "", label_map,
                ))
    result.elapsed_merge = time.perf_counter() - _t0

    result.merged_person_ids = uf.absorbed
    debug.persons_merged     = result.persons_merged
    result.elapsed_total     = time.perf_counter() - _t_total

    if debug_log:
        _write_household_debug_log(debug_log, debug, result)

    return result


# ---------------------------------------------------------------------------
# Person-level linkage — Splink settings
# ---------------------------------------------------------------------------

def _build_settings() -> SettingsCreator:
    """
    Splink settings for cross-census person linkage.

    link_type = "link_only": generate candidate pairs across census sources
    only — never within the same source. Each census year is a separate
    DataFrame; Splink generates cross-DataFrame pairs only, so two persons
    from the same census year can never be proposed or merged.

    This matches the household linker's link_type and is the correct mode
    for cross-census identity resolution. "link_and_dedupe" was previously
    used here but caused intra-census pairs (husband/wife, siblings, same-
    name neighbours) to be generated and committed as spurious merges.

    Term-frequency adjustment is enabled for surname_norm and forename_norm.
    In a small townland community, dominant surnames (Graham, Cassidy, Wray,
    Gallagher, McCadden) and common forenames (Mary, John, James) create many
    candidate pairs where a name match is weak evidence. TF adjustment scales
    match weight by log(1/frequency) in log-odds space: a Graham↔Graham match
    contributes far less than a Stevenson↔Stevenson match. Splink computes the
    frequency distribution automatically from the feature DataFrames at
    training time.

    Blocking rules:
      Primary:  same resolved place_id  (strong geographic anchor)
      Fallback: same first 4 chars of surname_norm (phonetic-adjacent)

    Comparisons follow reconstruction_algorithms.md §5.2.
    Birth year comparison uses absolute difference; place uses exact match.
    """
    return SettingsCreator(
        link_type="link_only",
        blocking_rules_to_generate_predictions=[
            block_on("place_id"),
            block_on("substr(surname_norm, 1, 4)"),
        ],
        comparisons=[
            # TF adjustment on surname_norm downweights matches on high-frequency
            # surnames (Graham, Cassidy, Wray, Gallagher, McCadden) that would
            # otherwise carry the same m-weight as rare surnames. Splink computes
            # the frequency distribution from the feature DataFrames at training
            # time. In Splink 4, TF is set via .configure(), not the constructor.
            cl.JaroWinklerAtThresholds(
                "surname_norm",
                [0.92, 0.80],
            ).configure(term_frequency_adjustments=True),
            # TF adjustment on forename_norm for the same reason: Mary, John,
            # James are so common that a forename match alone is weak evidence.
            cl.JaroWinklerAtThresholds(
                "forename_norm",
                [0.92, 0.80],
            ).configure(term_frequency_adjustments=True),
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
            # Spouse name: JaroWinkler on the normalised concluded spouse name.
            cl.CustomComparison(
                comparison_levels=[
                    cll.NullLevel("spouse_name_norm"),
                    cll.JaroWinklerLevel("spouse_name_norm", 0.92),
                    cll.JaroWinklerLevel("spouse_name_norm", 0.80),
                    cll.ElseLevel(),
                ],
                output_column_name="spouse_name_norm",
                comparison_description="Spouse name JaroWinkler (nulls = no spouse concluded)",
            ),
            # Child name overlap: Szymkiewicz–Simpson via DuckDB array functions.
            # S–S = |A∩B| / min(|A|,|B|) — measures containment of smaller set
            # in larger. Correct for cross-census comparison where children leave
            # over time; Jaccard would penalise valid continuations.
            cl.CustomComparison(
                comparison_levels=[
                    cll.NullLevel("child_names"),
                    cll.CustomLevel(
                        f"({_ss_sql('child_names')}) >= 1.0",
                        label_for_charts="child_ss = 1.0 (full containment)",
                    ),
                    cll.CustomLevel(
                        f"({_ss_sql('child_names')}) >= 0.5",
                        label_for_charts="child_ss >= 0.5 (partial overlap)",
                    ),
                    cll.ElseLevel(),
                ],
                output_column_name="child_names",
                comparison_description="Child name set Szymkiewicz–Simpson overlap",
            ),
            # Sibling name overlap: Szymkiewicz–Simpson. Siblings leave to form
            # their own households between census years.
            cl.CustomComparison(
                comparison_levels=[
                    cll.NullLevel("sibling_names"),
                    cll.CustomLevel(
                        f"({_ss_sql('sibling_names')}) >= 1.0",
                        label_for_charts="sibling_ss = 1.0 (full containment)",
                    ),
                    cll.CustomLevel(
                        f"({_ss_sql('sibling_names')}) >= 0.5",
                        label_for_charts="sibling_ss >= 0.5 (partial overlap)",
                    ),
                    cll.ElseLevel(),
                ],
                output_column_name="sibling_names",
                comparison_description="Sibling name set Szymkiewicz–Simpson overlap",
            ),
        ],
        retain_matching_columns=True,
        retain_intermediate_calculation_columns=False,
    )


# ---------------------------------------------------------------------------
# Person-level linkage — entry point
# ---------------------------------------------------------------------------

def run_census_linkage(
    conn: sqlite3.Connection,
    already_merged: set[int] | None = None,
    debug_log: str | None = None,
) -> CensusLinkageResult:
    """
    Run cross-census person linkage for all census sources that have
    been ingested and reconstructed.

    Parameters
    ----------
    conn :
        Open SQLite connection from open_db().
    already_merged :
        Set of person_ids merged by run_census_household_linkage().
        These persons are excluded from Splink candidate generation.
        If None, no filtering is applied (standalone usage).
    debug_log :
        Optional path to a plain-text debug log file. When provided, a
        three-section log is written after the pipeline completes:
          Section 1 — Pipeline Summary  (counts, null rates, score histogram)
          Section 2 — Scoring Detail    (one row per Splink pair)
          Section 3 — Claude Analysis   (issues, positives, recommended actions)
        The log is always written even if the pipeline is skipped early.

    Returns
    -------
    CensusLinkageResult
    """
    result = CensusLinkageResult()
    debug  = _PersonDebugLog(
        run_ts=datetime.datetime.now().isoformat(timespec="seconds")
    )
    _t_total = time.perf_counter()
    # Seed the union-find with already-merged ids from the household pass so
    # pair endpoint rewriting works correctly across both passes.
    uf: _UnionFind = _UnionFind(initial=set(already_merged or []))

    source_counts = conn.execute(
        f"""
        SELECT s.source_id, COUNT(DISTINCT pr.person_id) AS person_count
        FROM person_record pr
        JOIN record r ON r.record_id = pr.record_id
        JOIN source s ON s.source_id = r.source_id
        WHERE s.source_id IN ({_CENSUS_SOURCE_PLACEHOLDERS})
        GROUP BY s.source_id
        """,
        CENSUS_SOURCE_IDS,
    ).fetchall()

    active_sources = [row["source_id"] for row in source_counts]
    debug.active_sources     = active_sources
    debug.persons_per_source = {row["source_id"]: row["person_count"] for row in source_counts}

    if len(active_sources) < 2:
        reason = (
            f"Only {len(active_sources)} census source(s) have Person conclusions; "
            "cross-census linkage requires at least 2."
        )
        result.skipped       = reason
        debug.skipped_reason = reason
        if debug_log:
            _write_person_debug_log(debug_log, debug, result)
        return result

    _t0 = time.perf_counter()
    source_dfs = build_census_features(conn)
    result.elapsed_feature_extract = time.perf_counter() - _t0
    if not source_dfs:
        reason = "Feature extraction returned no rows."
        result.skipped       = reason
        debug.skipped_reason = reason
        if debug_log:
            _write_person_debug_log(debug_log, debug, result)
        return result

    # Exclude persons already resolved by the household pass.
    if uf.absorbed:
        source_dfs = [
            df[~df["unique_id"].isin(uf.absorbed)].reset_index(drop=True)
            for df in source_dfs
        ]
        source_dfs = [df for df in source_dfs if not df.empty]

    if not source_dfs:
        reason = "No unmerged persons remain after household linkage pass."
        result.skipped       = reason
        debug.skipped_reason = reason
        if debug_log:
            _write_person_debug_log(debug_log, debug, result)
        return result

    _populate_person_feature_stats(debug, source_dfs)
    label_map, source_map = _build_person_label_and_source_maps(conn, source_dfs)

    db_api   = DuckDBAPI()
    settings = _build_settings()
    linker   = Linker(source_dfs, settings, db_api=db_api)

    _t0 = time.perf_counter()
    linker.training.estimate_u_using_random_sampling(max_pairs=1e5)
    debug.training_notes.append("u-probabilities: random sampling (max_pairs=1e5)")

    # EM pass 1 — trains birth_year_est, forename_norm, place_id
    # (surname_norm excluded because it is the blocking key)
    linker.training.estimate_parameters_using_expectation_maximisation(
        block_on("substr(surname_norm, 1, 4)")
    )
    debug.training_notes.append(
        "EM pass 1: block_on('substr(surname_norm, 1, 4)') — "
        "trains birth_year_est, forename_norm, place_id"
    )

    # EM pass 2 — trains surname_norm (place_id is not a comparison feature)
    linker.training.estimate_parameters_using_expectation_maximisation(
        block_on("place_id")
    )
    debug.training_notes.append(
        "EM pass 2: block_on('place_id') — trains surname_norm weight"
    )
    result.elapsed_training = time.perf_counter() - _t0

    _t0 = time.perf_counter()
    predictions = linker.inference.predict(
        threshold_match_probability=PROPOSE_FLOOR
    )
    pred_df: pd.DataFrame = predictions.as_pandas_dataframe()
    result.elapsed_prediction = time.perf_counter() - _t0

    if pred_df.empty:
        reason = "Splink produced no predictions above the propose floor."
        result.skipped       = reason
        debug.skipped_reason = reason
        if debug_log:
            _write_person_debug_log(debug_log, debug, result)
        return result

    pred_df = pred_df.sort_values("match_probability", ascending=False)
    debug.pairs_above_floor = len(pred_df)

    processed_pairs: set[frozenset] = set()
    # 1:1 bipartite guard — each canonical person_id may be party to at most
    # one auto-commit merge per run.  Without this, person A (canonical after
    # merging with B) can immediately satisfy a second high-score pair A↔C,
    # because _UnionFind only blocks pairs where one side is *absorbed*; A
    # remains canonical and visible as a merge target.  The result is a person
    # from one census appearing in two merged clusters — impossible by definition.
    # Pairs demoted by this gate are written as proposals for researcher review.
    committed_this_run: set[int] = set()

    for _, row in pred_df.iterrows():
        pid_l = int(row["unique_id_l"])
        pid_r = int(row["unique_id_r"])
        score = float(row["match_probability"])

        if pid_l == pid_r:
            if debug_log:
                debug.record_pair(_build_person_pair_record(
                    row, "skipped", "self-match", label_map, source_map))
            continue

        # Rewrite through union-find: if either id was previously absorbed,
        # resolve to its current canonical before making any merge decision.
        # This enables transitive closure — A→B then C→B becomes C→A.
        can_l, can_r = uf.rewrite(pid_l, pid_r)
        if can_l == can_r:
            if debug_log:
                debug.record_pair(_build_person_pair_record(
                    row, "skipped", "already-merged", label_map, source_map))
            continue

        pair_key = frozenset((can_l, can_r))
        if pair_key in processed_pairs:
            if debug_log:
                debug.record_pair(_build_person_pair_record(
                    row, "skipped", "duplicate-pair", label_map, source_map))
            continue
        processed_pairs.add(pair_key)

        # Forename gate: reject auto-commit when forenames are entirely
        # different (gamma_forename_norm == 0 means the ElseLevel fired —
        # no Jaro-Winkler similarity above the lowest threshold).
        # Surname + place alone is not sufficient evidence for an identity
        # merge. Demote to proposal so the researcher sees the pair.
        gamma_forename = row.get("gamma_forename_norm")
        if (
            score >= AUTO_COMMIT_THRESHOLD
            and gamma_forename is not None
            and float(gamma_forename) == 0.0
        ):
            with conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO training_labels
                        (person_id_1, person_id_2, score, score_version, decision)
                    VALUES (?, ?, ?, ?, 'proposed')
                    """,
                    (min(can_l, can_r), max(can_l, can_r),
                     score, SCORE_VERSION_PERSON),
                )
            result.proposals_written += 1
            if debug_log:
                debug.record_pair(_build_person_pair_record(
                    row, "proposed", "forename-gate", label_map, source_map))
            continue

# Birth year coherence gate: reject auto-commit when the birth year
        # delta exceeds the GC03 tolerance for this specific census pair.
        # Uses estimated birth years rather than raw ages; tolerance is
        # derived from the actual census gap between the two sources
        # (±3 years for 10/15-year gaps, ±4 years for the 25-year gap).
        by_l = row.get("birth_year_est_l")
        by_r = row.get("birth_year_est_r")
        if (
            score >= AUTO_COMMIT_THRESHOLD
            and by_l is not None
            and by_r is not None
        ):
            try:
                by_l_int = int(by_l)
                by_r_int = int(by_r)
                delta = abs(by_l_int - by_r_int)
                # Look up the source_id for each side from the feature DataFrame
                # map built before the loop. Fall back to the widest tolerance
                # (4) when source is not found rather than over-rejecting.
                tol = _gc03_birth_year_tol(
                    source_map.get(pid_l, 0),
                    source_map.get(pid_r, 0),
                )
                if delta > tol:
                    with conn:
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO training_labels
                                (person_id_1, person_id_2, score, score_version, decision)
                            VALUES (?, ?, ?, ?, 'proposed')
                            """,
                            (min(can_l, can_r), max(can_l, can_r),
                             score, SCORE_VERSION_PERSON),
                        )
                    result.proposals_written += 1
                    if debug_log:
                        debug.record_pair(_build_person_pair_record(
                            row, "proposed", "birthyear-gate", label_map, source_map))
                    continue
            except (TypeError, ValueError):
                pass  # can't compute delta — let Splink score decide

        existing = {
            r2[0] for r2 in conn.execute(
                "SELECT person_id FROM person WHERE person_id IN (?, ?)",
                (can_l, can_r),
            ).fetchall()
        }
        if len(existing) < 2:
            if debug_log:
                debug.record_pair(_build_person_pair_record(
                    row, "skipped", "vanished", label_map, source_map))
            continue

        canonical_id = min(can_l, can_r)
        duplicate_id = max(can_l, can_r)

        if score >= AUTO_COMMIT_THRESHOLD:
            # 1:1 bipartite gate: if either canonical id was already committed
            # in this run, demote to proposal.  A person can appear in only one
            # census record, so merging them twice is a logical impossibility.
            if canonical_id in committed_this_run or duplicate_id in committed_this_run:
                with conn:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO training_labels
                            (person_id_1, person_id_2, score, score_version, decision)
                        VALUES (?, ?, ?, ?, 'proposed')
                        """,
                        (canonical_id, duplicate_id, score, SCORE_VERSION_PERSON),
                    )
                result.proposals_written += 1
                if debug_log:
                    debug.record_pair(_build_person_pair_record(
                        row, "proposed", "1:1-gate", label_map, source_map))
                continue
            # Each merge commits independently so a failure mid-run does not
            # roll back preceding merges.
            with conn:
                _merge_persons(
                    conn, canonical_id, duplicate_id,
                    score, SCORE_VERSION_PERSON,
                    result.merge_log, uf,
                )
            committed_this_run.add(canonical_id)
            committed_this_run.add(duplicate_id)
            result.persons_merged += 1
            if debug_log:
                debug.record_pair(_build_person_pair_record(
                    row, "merged", "", label_map, source_map))

        else:
            # Score is in the propose band — queue for researcher review.
            # Do NOT write person_record rows here: doing so would attach
            # the duplicate's records to the canonical person before any
            # researcher decision, effectively performing a partial merge
            # without consent.  Instead write a pending proposal to
            # training_labels with decision='proposed' so the review
            # workflow can present it for accept/reject.
            with conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO training_labels
                        (person_id_1, person_id_2, score, score_version, decision)
                    VALUES (?, ?, ?, ?, 'proposed')
                    """,
                    (canonical_id, duplicate_id, score, SCORE_VERSION_PERSON),
                )
            result.proposals_written += 1
            if debug_log:
                debug.record_pair(_build_person_pair_record(
                    row, "proposed", "", label_map, source_map))

    if debug_log:
        _write_person_debug_log(debug_log, debug, result)

    return result




# ---------------------------------------------------------------------------
# Report printers
# ---------------------------------------------------------------------------

def print_household_linkage_report(result: HouseholdLinkageResult) -> None:
    print("\n  HOUSEHOLD LINKAGE (Pass 1 + Pass 2)")
    if result.skipped:
        print(f"    Skipped: {result.skipped}")
        return
    print(f"    Household pairs confirmed: {result.household_pairs_confirmed:>6}")
    print(f"    Household pairs proposed:  {result.household_pairs_proposed:>6}")
    print(f"    Persons merged (Pass 2):   {result.persons_merged:>6}")
    if result.merge_log:
        print(f"\n  MERGE LOG ({len(result.merge_log)} entries)")
        for entry in result.merge_log[:20]:
            print(f"    {entry}")
        if len(result.merge_log) > 20:
            print(f"    ... and {len(result.merge_log) - 20} more")


def print_census_linkage_report(result: CensusLinkageResult) -> None:
    print("\n  CROSS-CENSUS PERSON LINKAGE")
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
