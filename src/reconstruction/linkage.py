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

import jellyfish
import pandas as pd
import splink.comparison_library as cl
import splink.comparison_level_library as cll
from splink import DuckDBAPI, Linker, SettingsCreator, block_on

from src.reconstruction.features.census import (
    build_census_features,
    build_census_household_features,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# SQLite source_ids for the three census years.  Defined once here so that
# all queries reference the same constant rather than scattered literals.
CENSUS_SOURCE_IDS: tuple[int, ...] = (3, 4, 5)

# ---------------------------------------------------------------------------
# Threshold bands (reconstruction_algorithms.md §1.3)
# ---------------------------------------------------------------------------

AUTO_COMMIT_THRESHOLD = 0.85
PROPOSE_FLOOR         = 0.30
SCORE_VERSION_PERSON  = "census_linkage_v1.0"
SCORE_VERSION_HH      = "household_linkage_v1.0"

_CENSUS_NAMES = {3: "Census 1901", 4: "Census 1911", 5: "Census 1926"}
_CENSUS_SOURCE_PLACEHOLDERS = ",".join("?" * len(CENSUS_SOURCE_IDS))

# Minimum forename similarity to accept a role match in Pass 2.
_MIN_FORENAME_SIM = 0.80

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
# Debug log accumulators
# ---------------------------------------------------------------------------


@dataclass
class _PairRecord:
    """Everything about a single Splink prediction pair, for the detail section."""
    pid_l:            int
    pid_r:            int
    label_l:          str
    label_r:          str
    source_l:         int
    source_r:         int
    score:            float
    surname_sim:      float | None
    forename_sim:     float | None
    birth_year_l:     int | None
    birth_year_r:     int | None
    birth_year_delta: int | None
    place_match:      bool | None
    place_id_l:       int | None
    place_id_r:       int | None
    band:             str   # "merged" | "proposed" | "suppressed" | "skipped"
    skip_reason:      str   # e.g. "already-merged", "vanished", "self-match"


@dataclass
class _HouseholdDebugLog:
    """Accumulates data during the household linkage pipeline."""
    run_ts:                      str = ""
    score_version:               str = SCORE_VERSION_HH
    active_sources:              list[int] = field(default_factory=list)
    records_per_source:          dict[int, int] = field(default_factory=dict)
    total_hh_rows:               int = 0
    null_household_surname_count: int = 0
    null_adult_forenames_count:  int = 0
    null_child_forenames_count:  int = 0
    null_place_count:            int = 0
    pairs_above_floor:           int = 0
    training_notes:              list[str] = field(default_factory=list)
    pairs:                       list[_PairRecord] = field(default_factory=list)
    skipped_reason:              str = ""
    household_surname_freq:      list[tuple[str, int]] = field(default_factory=list)
    persons_merged:              int = 0
    # Timing mirrors HouseholdLinkageResult — populated from result at log-write time.
    elapsed_total:               float = 0.0
    elapsed_feature_extract:     float = 0.0
    elapsed_training:            float = 0.0
    elapsed_prediction:          float = 0.0
    elapsed_merge:               float = 0.0

    def record_pair(self, pr: _PairRecord) -> None:
        self.pairs.append(pr)


@dataclass
class _PersonDebugLog:
    """Accumulates data during the person-level linkage pipeline."""
    run_ts:               str = ""
    score_version:        str = SCORE_VERSION_PERSON
    active_sources:       list[int] = field(default_factory=list)
    persons_per_source:   dict[int, int] = field(default_factory=dict)
    total_feature_rows:   int = 0
    null_surname_count:   int = 0
    null_forename_count:  int = 0
    null_birthyear_count: int = 0
    null_place_count:     int = 0
    pairs_above_floor:    int = 0
    training_notes:       list[str] = field(default_factory=list)
    pairs:                list[_PairRecord] = field(default_factory=list)
    skipped_reason:       str = ""
    surname_freq:         list[tuple[str, int]] = field(default_factory=list)
    # Timing mirrors CensusLinkageResult — populated from result at log-write time.
    elapsed_total:            float = 0.0
    elapsed_feature_extract:  float = 0.0
    elapsed_training:         float = 0.0
    elapsed_prediction:       float = 0.0
    elapsed_merge:            float = 0.0

    def record_pair(self, pr: _PairRecord) -> None:
        self.pairs.append(pr)


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

    # 7. Delete the duplicate Person.
    conn.execute("DELETE FROM person WHERE person_id = ?", (duplicate_id,))

    uf.union(canonical_id, duplicate_id)
    merge_log.append(
        f"Merged person_id={duplicate_id} → canonical person_id={canonical_id} "
        f"(score={score:.3f}, version={score_version})"
    )


# ---------------------------------------------------------------------------
# Household linkage — Splink settings (Pass 1)
# ---------------------------------------------------------------------------

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
            f"nullif(min(len({a}), len({b})), 0)"
        )

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
        return jellyfish.jaro_winkler_similarity(a, b)
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
                        "(len(list_intersect(string_split(\"child_names_l\", '|'), string_split(\"child_names_r\", '|'))) * 1.0) / nullif(min(len(string_split(\"child_names_l\", '|')), len(string_split(\"child_names_r\", '|'))), 0) >= 1.0",
                        label_for_charts="child_ss = 1.0 (full containment)",
                    ),
                    cll.CustomLevel(
                        "(len(list_intersect(string_split(\"child_names_l\", '|'), string_split(\"child_names_r\", '|'))) * 1.0) / nullif(min(len(string_split(\"child_names_l\", '|')), len(string_split(\"child_names_r\", '|'))), 0) >= 0.5",
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
                        "(len(list_intersect(string_split(\"sibling_names_l\", '|'), string_split(\"sibling_names_r\", '|'))) * 1.0) / nullif(min(len(string_split(\"sibling_names_l\", '|')), len(string_split(\"sibling_names_r\", '|'))), 0) >= 1.0",
                        label_for_charts="sibling_ss = 1.0 (full containment)",
                    ),
                    cll.CustomLevel(
                        "(len(list_intersect(string_split(\"sibling_names_l\", '|'), string_split(\"sibling_names_r\", '|'))) * 1.0) / nullif(min(len(string_split(\"sibling_names_l\", '|')), len(string_split(\"sibling_names_r\", '|'))), 0) >= 0.5",
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
            # Each merge commits independently so a failure mid-run does not
            # roll back preceding merges.
            with conn:
                _merge_persons(
                    conn, canonical_id, duplicate_id,
                    score, SCORE_VERSION_PERSON,
                    result.merge_log, uf,
                )
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
# Debug log helpers — shared utilities
# ---------------------------------------------------------------------------

_W = 78  # page width for section headers


def _hr(char: str = "─") -> str:
    return char * _W


def _wrap(text: str, indent: str = "    ", width: int = 74) -> list[str]:
    """Word-wrap text to width, indenting every line with indent."""
    words = text.split()
    lines: list[str] = []
    current = indent
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current.rstrip())
            current = indent + word + " "
        else:
            current += word + " "
    if current.strip():
        lines.append(current.rstrip())
    return lines


def _safe_col(row: "pd.Series", *names: str) -> Any:
    """Return the value of the first column name that exists in the row, else None."""
    for name in names:
        if name in row.index and pd.notna(row[name]):
            return row[name]
    return None


# ---------------------------------------------------------------------------
# Debug log helpers — household pipeline
# ---------------------------------------------------------------------------

def _populate_hh_feature_stats(
    debug: _HouseholdDebugLog,
    dfs: list[pd.DataFrame],
) -> None:
    """Collect feature-level nullity and household surname frequency from HH DataFrames."""
    if not dfs:
        return
    combined = pd.concat(dfs, ignore_index=True)
    debug.total_hh_rows                  = len(combined)
    debug.null_household_surname_count   = int(combined["household_surname_norm"].isna().sum())
    debug.null_adult_forenames_count     = int(combined["adult_forenames_sorted"].isna().sum())
    debug.null_child_forenames_count     = int(combined["child_forenames_young"].isna().sum())
    debug.null_place_count               = int(combined["place_id"].isna().sum())

    freq = (
        combined["household_surname_norm"]
        .dropna()
        .value_counts()
        .head(20)
    )
    debug.household_surname_freq = [(str(k), int(v)) for k, v in freq.items()]


def _build_hh_label_map(
    conn: sqlite3.Connection,
    dfs: list[pd.DataFrame],
) -> dict[int, str]:
    """Map record_id → a human-readable household label (head surname + source year)."""
    label_map: dict[int, str] = {}
    if not dfs:
        return label_map

    all_rids: list[int] = []
    for df in dfs:
        all_rids.extend(int(x) for x in df["unique_id"].tolist())

    chunk_size = 200
    for i in range(0, len(all_rids), chunk_size):
        chunk = all_rids[i:i + chunk_size]
        placeholders = ",".join("?" * len(chunk))
        rows = conn.execute(
            f"""
            SELECT r.record_id, r.date,
                   rp.name_as_recorded
            FROM record r
            JOIN recorded_person rp ON rp.record_id = r.record_id
                AND rp.role = 'head'
                AND rp.recorded_person_id = (
                    SELECT MIN(rp2.recorded_person_id)
                    FROM recorded_person rp2
                    WHERE rp2.record_id = r.record_id AND rp2.role = 'head'
                )
            WHERE r.record_id IN ({placeholders})
            """,
            chunk,
        ).fetchall()
        for r in rows:
            year = r["date"][:4] if r["date"] else "????"
            label_map[r["record_id"]] = f"{r['name_as_recorded']} ({year})"

    return label_map


def _build_hh_pair_record(
    row: "pd.Series",
    band: str,
    skip_reason: str,
    label_map: dict[int, str],
) -> _PairRecord:
    """Extract a _PairRecord from a household Splink prediction row."""
    rid_l = int(row["unique_id_l"])
    rid_r = int(row["unique_id_r"])
    score = float(row["match_probability"])

    by_l = _safe_col(row, "adult_forenames_sorted_l")   # no birth year on HH rows
    by_r = _safe_col(row, "adult_forenames_sorted_r")
    pl_l = _safe_col(row, "place_id_l")
    pl_r = _safe_col(row, "place_id_r")

    jw_surname  = _safe_col(row,
        "gamma_household_surname_norm",
        "jaro_winkler_similarity_household_surname_norm",
    )
    jw_forename = _safe_col(row,
        "gamma_adult_forenames_sorted",
        "szymkiewicz_simpson_adult_forenames_sorted",
    )

    by_delta: int | None = None
    if by_l is not None and by_r is not None:
        try:
            by_delta = abs(int(by_l) - int(by_r))
        except (TypeError, ValueError):
            pass

    place_match: bool | None = None
    if pl_l is not None and pl_r is not None:
        try:
            place_match = (int(pl_l) == int(pl_r))
        except (TypeError, ValueError):
            pass

    # source_id not directly on HH rows — derive from label year string
    def _year_to_source(label: str) -> int:
        for src, name in _CENSUS_NAMES.items():
            if name.split()[-1] in label:
                return src
        return 0

    lbl_l = label_map.get(rid_l, str(rid_l))
    lbl_r = label_map.get(rid_r, str(rid_r))

    return _PairRecord(
        pid_l=rid_l,
        pid_r=rid_r,
        label_l=lbl_l,
        label_r=lbl_r,
        source_l=_year_to_source(lbl_l),
        source_r=_year_to_source(lbl_r),
        score=score,
        surname_sim=float(jw_surname)  if jw_surname  is not None else None,
        forename_sim=float(jw_forename) if jw_forename is not None else None,
        birth_year_l=int(by_l) if by_l is not None else None,
        birth_year_r=int(by_r) if by_r is not None else None,
        birth_year_delta=by_delta,
        place_match=place_match,
        place_id_l=int(pl_l) if pl_l is not None else None,
        place_id_r=int(pl_r) if pl_r is not None else None,
        band=band,
        skip_reason=skip_reason,
    )


# ---------------------------------------------------------------------------
# Debug log helpers — person-level pipeline
# ---------------------------------------------------------------------------

def _populate_person_feature_stats(
    debug: _PersonDebugLog,
    dfs: list[pd.DataFrame],
) -> None:
    """Collect feature-level nullity and surname frequency from person DataFrames."""
    if not dfs:
        return
    combined = pd.concat(dfs, ignore_index=True)
    debug.total_feature_rows   = len(combined)
    debug.null_surname_count   = int(combined["surname_norm"].isna().sum())
    debug.null_forename_count  = int(combined["forename_norm"].isna().sum())
    debug.null_birthyear_count = int(combined["birth_year_est"].isna().sum())
    debug.null_place_count     = int(combined["place_id"].isna().sum())

    freq = (
        combined["surname_norm"]
        .dropna()
        .value_counts()
        .head(20)
    )
    debug.surname_freq = [(str(k), int(v)) for k, v in freq.items()]


def _build_person_label_and_source_maps(
    conn: sqlite3.Connection,
    dfs: list[pd.DataFrame],
) -> tuple[dict[int, str], dict[int, int]]:
    """Map person_id → label and person_id → source_id for the debug log."""
    label_map: dict[int, str] = {}
    source_map: dict[int, int] = {}
    if not dfs:
        return label_map, source_map

    all_pids: list[int] = []
    for df in dfs:
        source_id = int(df["source_id"].iloc[0])
        for pid in df["unique_id"].tolist():
            all_pids.append(int(pid))
            source_map[int(pid)] = source_id

    chunk_size = 200
    for i in range(0, len(all_pids), chunk_size):
        chunk = all_pids[i:i + chunk_size]
        placeholders = ",".join("?" * len(chunk))
        rows = conn.execute(
            f"SELECT person_id, label FROM person WHERE person_id IN ({placeholders})",
            chunk,
        ).fetchall()
        for r in rows:
            label_map[r["person_id"]] = r["label"]

    return label_map, source_map


def _build_person_pair_record(
    row: "pd.Series",
    band: str,
    skip_reason: str,
    label_map: dict[int, str],
    source_map: dict[int, int],
) -> _PairRecord:
    """Extract a _PairRecord from a person-level Splink prediction row."""
    pid_l = int(row["unique_id_l"])
    pid_r = int(row["unique_id_r"])
    score = float(row["match_probability"])

    by_l = _safe_col(row, "birth_year_est_l")
    by_r = _safe_col(row, "birth_year_est_r")
    pl_l = _safe_col(row, "place_id_l")
    pl_r = _safe_col(row, "place_id_r")

    jw_surname  = _safe_col(row,
        "gamma_surname_norm",
        "jaro_winkler_similarity_surname_norm",
        "tf_adjusted_match_prob_surname_norm",
    )
    jw_forename = _safe_col(row,
        "gamma_forename_norm",
        "jaro_winkler_similarity_forename_norm",
        "tf_adjusted_match_prob_forename_norm",
    )

    by_delta: int | None = None
    if by_l is not None and by_r is not None:
        try:
            by_delta = abs(int(by_l) - int(by_r))
        except (TypeError, ValueError):
            pass

    place_match: bool | None = None
    if pl_l is not None and pl_r is not None:
        try:
            place_match = (int(pl_l) == int(pl_r))
        except (TypeError, ValueError):
            pass

    return _PairRecord(
        pid_l=pid_l,
        pid_r=pid_r,
        label_l=label_map.get(pid_l, str(pid_l)),
        label_r=label_map.get(pid_r, str(pid_r)),
        source_l=source_map.get(pid_l, 0),
        source_r=source_map.get(pid_r, 0),
        score=score,
        surname_sim=float(jw_surname)  if jw_surname  is not None else None,
        forename_sim=float(jw_forename) if jw_forename is not None else None,
        birth_year_l=int(by_l) if by_l is not None else None,
        birth_year_r=int(by_r) if by_r is not None else None,
        birth_year_delta=by_delta,
        place_match=place_match,
        place_id_l=int(pl_l) if pl_l is not None else None,
        place_id_r=int(pl_r) if pl_r is not None else None,
        band=band,
        skip_reason=skip_reason,
    )


# ---------------------------------------------------------------------------
# Debug log writers
# ---------------------------------------------------------------------------

def _write_household_debug_log(
    path: str,
    debug: _HouseholdDebugLog,
    result: HouseholdLinkageResult,
) -> None:
    """Write the three-section household debug log to disk."""
    out: list[str] = []

    def emit(*args: str) -> None:
        out.extend(args)

    def section(title: str) -> None:
        emit("", "═" * _W, f"  {title}", "═" * _W)

    def sub(title: str) -> None:
        emit("", f"  ── {title}", f"  {'─' * (_W - 5)}")

    def kv(label: str, value: Any, width: int = 38) -> None:
        emit(f"  {label:<{width}} {value}")

    # ── Header ──────────────────────────────────────────────────────────────
    emit(
        "GRA Linkage Pipeline — Household Debug Log",
        f"Generated : {debug.run_ts}",
        f"Score ver : {debug.score_version}",
        f"Thresholds: auto-commit >= {AUTO_COMMIT_THRESHOLD}  |  "
        f"propose floor >= {PROPOSE_FLOOR}",
    )

    # =======================================================================
    # SECTION 1 — PIPELINE SUMMARY
    # =======================================================================
    section("SECTION 1 — PIPELINE SUMMARY")

    if debug.skipped_reason:
        emit("", f"  PIPELINE SKIPPED: {debug.skipped_reason}")
    else:
        sub("Active census sources (records)")
        for src_id in sorted(debug.active_sources):
            n = debug.records_per_source.get(src_id, 0)
            emit(f"    Source {src_id} ({_CENSUS_NAMES.get(src_id, '?')}):  {n} records")

        sub("Household feature matrix quality")
        total = debug.total_hh_rows
        kv("Total household rows:", total)
        kv("Null household_surname_norm:",
           f"{debug.null_household_surname_count}  ({100*debug.null_household_surname_count/max(total,1):.1f}%)")
        kv("Null adult_forenames_sorted:",
           f"{debug.null_adult_forenames_count}  ({100*debug.null_adult_forenames_count/max(total,1):.1f}%)")
        kv("Null child_forenames_young:",
           f"{debug.null_child_forenames_count}  ({100*debug.null_child_forenames_count/max(total,1):.1f}%)")
        kv("Null place_id:",
           f"{debug.null_place_count}  ({100*debug.null_place_count/max(total,1):.1f}%)")

        sub("Candidate household pairs")
        kv("Pairs above propose floor:", debug.pairs_above_floor)
        confirmed = [p for p in debug.pairs if p.band == "merged"]
        proposed  = [p for p in debug.pairs if p.band == "proposed"]
        kv("  → confirmed (auto-commit):", len(confirmed))
        kv("  → proposed (for review):",  len(proposed))
        kv("Persons merged (Pass 2):",    debug.persons_merged)

        sub("Score distribution (household pairs above floor)")
        all_scored = [p for p in debug.pairs if p.band != "skipped"]
        bands_display = [
            ("[0.85–1.00]  auto-commit",  0.85, 1.01),
            ("[0.70–0.85)  propose-high", 0.70, 0.85),
            ("[0.50–0.70)  propose-mid",  0.50, 0.70),
            ("[0.30–0.50)  propose-low",  0.30, 0.50),
        ]
        for band_label, lo, hi in bands_display:
            count = sum(1 for p in all_scored if lo <= p.score < hi)
            bar   = "█" * min(count, 40)
            emit(f"    {band_label:<28}  {count:>5}  {bar}")

        sub("Splink training notes")
        for note in debug.training_notes:
            emit(f"    {note}")
        if not debug.training_notes:
            emit("    (none recorded)")

    # =======================================================================
    # SECTION 2 — SCORING DETAIL
    # =======================================================================
    section("SECTION 2 — SCORING DETAIL")

    if debug.skipped_reason:
        emit("", "  (pipeline did not run — no pairs to display)")
    else:
        sub("Household surname frequency (top 20) — high count = TF inflation risk (now adjusted)")
        for surname, count in debug.household_surname_freq:
            flag = "  ← HIGH FREQUENCY" if count >= 10 else ""
            emit(f"    {surname:<26} {count:>4} households{flag}")

        sub("All scored household pairs — sorted by score descending")
        hdr = (
            f"  {'SCORE':>6}  "
            f"{'LEFT HOUSEHOLD':<32}  "
            f"{'RIGHT HOUSEHOLD':<32}  "
            f"{'SURN':>5}  "
            f"{'FORE':>5}  "
            f"{'BY_Δ':>5}  "
            f"{'PLACE':>5}  "
            f"{'BAND'}"
        )
        emit(hdr, "  " + "─" * (_W - 2))

        for pr in sorted(debug.pairs, key=lambda x: -x.score):
            surn_s  = f"{pr.surname_sim:.2f}"  if pr.surname_sim  is not None else "  —  "
            fore_s  = f"{pr.forename_sim:.2f}" if pr.forename_sim is not None else "  —  "
            delta_s = str(pr.birth_year_delta)  if pr.birth_year_delta is not None else "  —"
            place_s = (
                "match" if pr.place_match is True  else
                "miss"  if pr.place_match is False else
                "  —  "
            )
            band_s  = f"skipped:{pr.skip_reason}" if pr.skip_reason else pr.band
            lbl_l   = pr.label_l[:30] if len(pr.label_l) > 30 else pr.label_l
            lbl_r   = pr.label_r[:30] if len(pr.label_r) > 30 else pr.label_r

            emit(
                f"  {pr.score:>6.3f}  "
                f"{lbl_l:<32}  "
                f"{lbl_r:<32}  "
                f"{surn_s:>5}  "
                f"{fore_s:>5}  "
                f"{delta_s:>5}  "
                f"{place_s:>5}  "
                f"{band_s}"
            )

    # =======================================================================
    # SECTION 3 — CLAUDE ANALYSIS NOTES
    # =======================================================================
    section("SECTION 3 — CLAUDE ANALYSIS NOTES")
    emit(
        "",
        "  This section is written for Claude to read at the start of a research session.",
        "  It summarises what happened, what looks suspicious, and what to try next.",
        "",
    )

    issues:    list[str] = []
    positives: list[str] = []
    actions:   list[str] = []

    if debug.skipped_reason:
        issues.append(f"Household pipeline did not run: {debug.skipped_reason}")
        actions.append(
            "Ingest at least two census sources, run place resolution and "
            "household inference, then retry."
        )
    else:
        n_hh = debug.total_hh_rows
        n_sources = len(debug.active_sources)

        if n_hh < 20:
            issues.append(
                f"Very small household feature matrix ({n_hh} rows across {n_sources} sources). "
                f"Splink EM may produce unreliable weights at this scale. "
                f"Treat auto-committed household pairs with caution."
            )
        else:
            positives.append(
                f"Household feature matrix ({n_hh} rows across {n_sources} sources) "
                f"is sufficient for EM parameter estimation."
            )

        null_sn_pct = 100 * debug.null_household_surname_count / max(n_hh, 1)
        null_af_pct = 100 * debug.null_adult_forenames_count   / max(n_hh, 1)
        null_pl_pct = 100 * debug.null_place_count             / max(n_hh, 1)

        if null_sn_pct > 5:
            issues.append(
                f"{debug.null_household_surname_count} households ({null_sn_pct:.0f}%) have no "
                f"household_surname_norm. These fall back to place_id blocking only."
            )
        if null_af_pct > 30:
            issues.append(
                f"{debug.null_adult_forenames_count} households ({null_af_pct:.0f}%) "
                f"have no adult forenames — household may contain only children or role data is absent."
            )
        if null_pl_pct > 40:
            issues.append(
                f"{debug.null_place_count} households ({null_pl_pct:.0f}%) have no resolved "
                f"place_id. Place is the primary household blocking anchor."
            )
            actions.append(
                "Run place resolution before household linkage and verify place_authority "
                "is seeded for all relevant townlands."
            )

        confirmed = [p for p in debug.pairs if p.band == "merged"]
        if confirmed:
            avg = sum(p.score for p in confirmed) / len(confirmed)
            positives.append(
                f"{len(confirmed)} household pairs confirmed at mean score {avg:.3f}; "
                f"{debug.persons_merged} persons merged in Pass 2."
            )
        else:
            issues.append(
                "No household pairs were auto-committed. Either no genuine matches exist "
                "across census years, or blocking/training failed to generate candidates."
            )
            actions.append(
                "Check null rates above. If place_id null rate is high, "
                "run place resolution first."
            )

        by_deltas = [p.birth_year_delta for p in confirmed if p.birth_year_delta is not None]
        if by_deltas:
            large = [d for d in by_deltas if d > 6]
            if large:
                issues.append(
                    f"{len(large)} confirmed household pair(s) have head birth year delta > 6. "
                    f"These warrant manual verification — informant error or a genuine mismatch."
                )
            else:
                positives.append(
                    f"All confirmed household pairs have head birth year delta ≤ 6 "
                    f"(max: {max(by_deltas)}). Consistent with census age drift tolerances."
                )

    sub("Issues detected")
    if issues:
        for i, issue in enumerate(issues, 1):
            emit(f"  ISSUE {i}:")
            emit(*_wrap(issue))
            emit("")
    else:
        emit("  None detected.")

    sub("What looks good")
    if positives:
        for pos in positives:
            emit(*_wrap("✓ " + pos, indent="  "))
    else:
        emit("  Nothing to highlight.")

    sub("Recommended actions")
    if actions:
        for i, action in enumerate(actions, 1):
            emit(f"  ACTION {i}:")
            emit(*_wrap(action))
            emit("")
    else:
        emit("  No actions recommended — household pipeline looks healthy.")

    emit("", "═" * _W, "  End of GRA Household Linkage Debug Log", "═" * _W, "")
    Path(path).write_text("\n".join(out), encoding="utf-8")


def _write_person_debug_log(
    path: str,
    debug: _PersonDebugLog,
    result: CensusLinkageResult,
) -> None:
    """Write the three-section person-level linkage debug log to disk."""
    out: list[str] = []

    def emit(*args: str) -> None:
        out.extend(args)

    def section(title: str) -> None:
        emit("", "═" * _W, f"  {title}", "═" * _W)

    def sub(title: str) -> None:
        emit("", f"  ── {title}", f"  {'─' * (_W - 5)}")

    def kv(label: str, value: Any, width: int = 38) -> None:
        emit(f"  {label:<{width}} {value}")

    # ── Header ──────────────────────────────────────────────────────────────
    emit(
        "GRA Linkage Pipeline — Person-Level Debug Log",
        f"Generated : {debug.run_ts}",
        f"Score ver : {debug.score_version}",
        f"Thresholds: auto-commit >= {AUTO_COMMIT_THRESHOLD}  |  "
        f"propose floor >= {PROPOSE_FLOOR}",
    )

    # =======================================================================
    # SECTION 1 — PIPELINE SUMMARY
    # =======================================================================
    section("SECTION 1 — PIPELINE SUMMARY")

    if debug.skipped_reason:
        emit("", f"  PIPELINE SKIPPED: {debug.skipped_reason}")
    else:
        sub("Active census sources")
        for src_id in sorted(debug.active_sources):
            n = debug.persons_per_source.get(src_id, 0)
            emit(f"    Source {src_id} ({_CENSUS_NAMES.get(src_id, '?')}):  {n} persons")

        sub("Feature matrix quality")
        total = debug.total_feature_rows
        kv("Total person rows:", total)
        kv("Null surname_norm:",
           f"{debug.null_surname_count}  ({100*debug.null_surname_count/max(total,1):.1f}%)")
        kv("Null forename_norm:",
           f"{debug.null_forename_count}  ({100*debug.null_forename_count/max(total,1):.1f}%)")
        kv("Null birth_year_est:",
           f"{debug.null_birthyear_count}  ({100*debug.null_birthyear_count/max(total,1):.1f}%)")
        kv("Null place_id:",
           f"{debug.null_place_count}  ({100*debug.null_place_count/max(total,1):.1f}%)")

        sub("Candidate pairs")
        kv("Pairs above propose floor:", debug.pairs_above_floor)

        merged_pairs   = [p for p in debug.pairs if p.band == "merged"]
        proposed_pairs = [p for p in debug.pairs if p.band == "proposed"]
        skipped_pairs  = [p for p in debug.pairs if p.band == "skipped"]

        kv("  → merged (auto-commit):",     len(merged_pairs))
        kv("  → proposed (for review):",    len(proposed_pairs))
        kv("  → skipped (stale/vanished):", len(skipped_pairs))

        sub("Score distribution (all pairs above floor)")
        all_scored = [p for p in debug.pairs if p.band != "skipped"]
        bands_display = [
            ("[0.85–1.00]  auto-commit",  0.85, 1.01),
            ("[0.70–0.85)  propose-high", 0.70, 0.85),
            ("[0.50–0.70)  propose-mid",  0.50, 0.70),
            ("[0.30–0.50)  propose-low",  0.30, 0.50),
        ]
        for band_label, lo, hi in bands_display:
            count = sum(1 for p in all_scored if lo <= p.score < hi)
            bar   = "█" * min(count, 40)
            emit(f"    {band_label:<28}  {count:>5}  {bar}")

        sub("Splink training notes")
        for note in debug.training_notes:
            emit(f"    {note}")
        if not debug.training_notes:
            emit("    (none recorded)")

    # =======================================================================
    # SECTION 2 — SCORING DETAIL
    # =======================================================================
    section("SECTION 2 — SCORING DETAIL")

    if debug.skipped_reason:
        emit("", "  (pipeline did not run — no pairs to display)")
    else:
        sub("Surname frequency (top 20) — high count = term-frequency inflation risk")
        for surname, count in debug.surname_freq:
            flag = "  ← HIGH FREQUENCY" if count >= 10 else ""
            emit(f"    {surname:<26} {count:>4} persons{flag}")

        sub("All scored pairs — sorted by score descending")
        hdr = (
            f"  {'SCORE':>6}  "
            f"{'LEFT PERSON':<30}  "
            f"{'RIGHT PERSON':<30}  "
            f"{'SRC_L':>5}  "
            f"{'SRC_R':>5}  "
            f"{'SURN':>5}  "
            f"{'FORE':>5}  "
            f"{'BY_Δ':>5}  "
            f"{'PLACE':>5}  "
            f"{'BAND'}"
        )
        emit(hdr, "  " + "─" * (_W - 2))

        for pr in sorted(debug.pairs, key=lambda x: -x.score):
            surn_s  = f"{pr.surname_sim:.2f}"  if pr.surname_sim  is not None else "  —  "
            fore_s  = f"{pr.forename_sim:.2f}" if pr.forename_sim is not None else "  —  "
            delta_s = str(pr.birth_year_delta)  if pr.birth_year_delta is not None else "  —"
            place_s = (
                "match" if pr.place_match is True  else
                "miss"  if pr.place_match is False else
                "  —  "
            )
            src_l_s = _CENSUS_NAMES.get(pr.source_l, str(pr.source_l)).replace("Census ", "")
            src_r_s = _CENSUS_NAMES.get(pr.source_r, str(pr.source_r)).replace("Census ", "")
            band_s  = f"skipped:{pr.skip_reason}" if pr.skip_reason else pr.band
            lbl_l   = pr.label_l[:28] if len(pr.label_l) > 28 else pr.label_l
            lbl_r   = pr.label_r[:28] if len(pr.label_r) > 28 else pr.label_r

            emit(
                f"  {pr.score:>6.3f}  "
                f"{lbl_l:<30}  "
                f"{lbl_r:<30}  "
                f"{src_l_s:>5}  "
                f"{src_r_s:>5}  "
                f"{surn_s:>5}  "
                f"{fore_s:>5}  "
                f"{delta_s:>5}  "
                f"{place_s:>5}  "
                f"{band_s}"
            )
            if pr.birth_year_l is not None or pr.birth_year_r is not None:
                emit(
                    f"           birth years: "
                    f"{pr.birth_year_l or '?'} ←→ {pr.birth_year_r or '?'}"
                )

        sub("Proposed pairs — queued for researcher review")
        proposed_pairs_local = [p for p in debug.pairs if p.band == "proposed"]
        if proposed_pairs_local:
            emit(
                "  These pairs scored in the propose band and were written to person_record.",
                "  Require researcher accept/reject in an update-knowledge session.",
                "",
            )
            for pr in sorted(proposed_pairs_local, key=lambda x: -x.score):
                emit(
                    f"    [{pr.score:.3f}]  "
                    f"pid={pr.pid_l} ({pr.label_l})  ←→  "
                    f"pid={pr.pid_r} ({pr.label_r})"
                )
        else:
            emit("  No proposed pairs.")

    # =======================================================================
    # SECTION 3 — CLAUDE ANALYSIS NOTES
    # =======================================================================
    section("SECTION 3 — CLAUDE ANALYSIS NOTES")
    emit(
        "",
        "  This section is written for Claude to read at the start of a research session.",
        "  It summarises what happened, what looks suspicious, and what to try next.",
        "  All recommendations reference the GRA document set (reconstruction_algorithms.md,",
        "  genealogical_constraints.md) where relevant.",
        "",
    )

    issues:    list[str] = []
    positives: list[str] = []
    actions:   list[str] = []

    if debug.skipped_reason:
        issues.append(f"Pipeline did not run: {debug.skipped_reason}")
        actions.append(
            "Ingest at least two census sources and run household inference "
            "before attempting cross-census linkage."
        )
    else:
        n_persons = debug.total_feature_rows
        n_sources = len(debug.active_sources)

        # ── Training data adequacy ──────────────────────────────────────────
        if n_persons < 50:
            issues.append(
                f"Very small feature matrix ({n_persons} persons across {n_sources} sources). "
                f"Splink's EM algorithm needs sufficient pair-space to estimate reliable "
                f"m/u probabilities. Below 50 persons, parameter estimates may be noisy "
                f"and individual match probabilities unreliable. "
                f"Auto-commit decisions from this run should be treated with caution."
            )
            actions.append(
                "Consider expanding the geographic scope or ingesting a third census year "
                "before relying on auto-commit decisions. Use debug Section 2 to manually "
                "inspect each merged pair before accepting."
            )
        elif n_persons < 200:
            issues.append(
                f"Small feature matrix ({n_persons} persons). EM estimates are usable but "
                f"carry higher variance than a larger dataset, especially for rare name forms. "
                f"Check merged pairs with birth year delta > 3 carefully (GC03 tolerance)."
            )
        else:
            positives.append(
                f"Feature matrix ({n_persons} persons across {n_sources} census sources) "
                f"is adequate for Splink EM parameter estimation."
            )

        # ── Null feature rates ──────────────────────────────────────────────
        null_sn_pct = 100 * debug.null_surname_count   / max(n_persons, 1)
        null_by_pct = 100 * debug.null_birthyear_count / max(n_persons, 1)
        null_pl_pct = 100 * debug.null_place_count     / max(n_persons, 1)

        if null_sn_pct > 5:
            issues.append(
                f"{debug.null_surname_count} persons ({null_sn_pct:.0f}%) have no "
                f"surname_norm. These persons cannot be blocked or scored on surname "
                f"and will only generate candidates via the place_id blocking rule. "
                f"'Unknown' names written by the census normaliser are the most common cause."
            )
            actions.append(
                "Inspect ingest parse notes for records where name_as_recorded resolved to "
                "'Unknown'. Investigate whether the original CSV has blank firstname/surname "
                "columns for these persons."
            )

        if null_by_pct > 30:
            issues.append(
                f"{debug.null_birthyear_count} persons ({null_by_pct:.0f}%) have no "
                f"birth_year_est. Birth year is the primary disambiguation feature for "
                f"same-name persons in the same townland (reconstruction_algorithms.md §5.2). "
                f"High null rate means the pipeline falls back to name+place matching only, "
                f"increasing false-positive risk for common surnames."
            )
            actions.append(
                "Check ingest parse notes for age parsing failures. The census normaliser "
                "stores a null integer age when the raw age field cannot be parsed as a "
                "number. Blank or non-numeric age values in the NAI CSV are the usual cause."
            )
        elif null_by_pct > 10:
            issues.append(
                f"{null_by_pct:.0f}% of persons have no birth_year_est. "
                f"Moderate null rate — scores for these persons rely on name and place only. "
                f"Watch for false positives among common surnames with no birth year signal."
            )
        else:
            positives.append(
                f"Birth year null rate: {null_by_pct:.0f}% — good feature coverage."
            )

        if null_pl_pct > 40:
            issues.append(
                f"{debug.null_place_count} persons ({null_pl_pct:.0f}%) have no resolved "
                f"place_id. Place is the primary blocking anchor "
                f"(reconstruction_algorithms.md §5.1). Without it, these persons fall back "
                f"to surname-prefix blocking only, generating more spurious pairs and "
                f"potentially missing genuine cross-townland matches."
            )
            actions.append(
                "Run place resolution before linkage, and verify that place_authority is "
                "seeded for all townlands in the census data. Check the place resolution "
                "report for unresolved tokens. Missing logainm entries can be fetched with "
                "'python -m src.fetch_places --logainm-id <ID> --db genealogy.db'."
            )
        elif null_pl_pct > 20:
            issues.append(
                f"{null_pl_pct:.0f}% of persons have an unresolved place_id. "
                f"These persons use surname-prefix blocking only, which is less discriminating "
                f"and generates more false-positive candidates."
            )
        else:
            positives.append(
                f"Place null rate: {null_pl_pct:.0f}% — most persons have a resolved townland."
            )

        # ── Surname frequency risk ──────────────────────────────────────────
        high_freq = [(s, c) for s, c in debug.surname_freq if c >= 10]
        if high_freq:
            names_str = ", ".join(f"'{s}' ({c})" for s, c in high_freq[:5])
            issues.append(
                f"High-frequency surnames detected: {names_str}. "
                f"In a small townland community, dominant surnames create many same-surname "
                f"candidate pairs. Without Splink term-frequency (TF) adjustment, a surname "
                f"match carries the same discriminating weight regardless of frequency, "
                f"inflating match probabilities for ambiguous pairs "
                f"(reconstruction_algorithms.md §4.4)."
            )
            actions.append(
                "Enable Splink term-frequency adjustment for surname_norm. In _build_settings(), "
                "configure the JaroWinklerAtThresholds comparison for surname_norm with "
                "term_frequency_adjustments=True. The frequency table is computed automatically "
                "from the feature DataFrame by Splink's EM training."
            )
        elif debug.surname_freq:
            positives.append(
                "Surname frequency distribution looks reasonable — no surname exceeds 10 persons. "
                "Term-frequency adjustment is not urgently needed at this scale."
            )

        # ── Score clustering near thresholds ───────────────────────────────
        all_scored = [p for p in debug.pairs if p.band != "skipped"]
        near_commit = [p for p in all_scored if 0.80 <= p.score < 0.85]
        near_floor  = [p for p in all_scored if 0.30 <= p.score < 0.35]

        if len(near_commit) >= 3:
            issues.append(
                f"{len(near_commit)} pairs scored in [0.80–0.85), just below the auto-commit "
                f"threshold of {AUTO_COMMIT_THRESHOLD}. These were queued as proposals rather "
                f"than committed. If manual review of these proposals shows they are mostly "
                f"correct linkages, the threshold may be conservatively high for this dataset. "
                f"If they are mostly incorrect, the model needs more training data."
            )
            actions.append(
                f"In the update-knowledge session, review the {len(near_commit)} near-commit "
                f"proposals first. If ≥80% are correct, consider lowering AUTO_COMMIT_THRESHOLD "
                f"to 0.82 on a trial basis. Document the decision in ROADMAP.md."
            )
        if len(near_floor) >= 5:
            issues.append(
                f"{len(near_floor)} pairs scored in [0.30–0.35), just above the suppression "
                f"floor. These low-confidence proposals may represent transcription-damaged "
                f"records or extended-family members with similar names. They warrant "
                f"careful review and are likely flag candidates rather than accepts."
            )

        # ── Outcome quality ─────────────────────────────────────────────────
        merged_pairs   = [p for p in debug.pairs if p.band == "merged"]
        proposed_pairs = [p for p in debug.pairs if p.band == "proposed"]

        if not merged_pairs and not proposed_pairs:
            issues.append(
                "No pairs were merged or proposed. The pipeline ran Splink but found nothing "
                "above the propose floor. Possible causes: (1) genuine mortality attrition "
                "between census years means few of the same persons appear across sources — "
                "possible but unlikely to eliminate all matches in a stable rural community; "
                "(2) blocking rules failed to generate candidates — check null place_id and "
                "surname rates above; (3) EM training failed to converge and all match "
                "probabilities landed near the null prior (typically ~0.001–0.01)."
            )
            actions.append(
                "Add diagnostic calls before predict() to inspect EM convergence: "
                "'linker.visualisations.match_weights_chart()' and "
                "'linker.training.estimate_probability_two_random_records_match()'. "
                "If match weights are all near zero, EM did not converge — increase "
                "max_pairs in estimate_u_using_random_sampling or add a third EM pass."
            )
        else:
            if merged_pairs:
                avg = sum(p.score for p in merged_pairs) / len(merged_pairs)
                positives.append(
                    f"{len(merged_pairs)} persons auto-committed at mean score {avg:.3f}."
                )
            if proposed_pairs:
                positives.append(
                    f"{len(proposed_pairs)} pairs proposed for researcher review."
                )

        # ── Place-match rate among merged pairs ─────────────────────────────
        merged_with_place = [p for p in merged_pairs if p.place_match is not None]
        if merged_with_place:
            match_rate = sum(1 for p in merged_with_place if p.place_match) / len(merged_with_place)
            if match_rate < 0.70:
                issues.append(
                    f"Only {match_rate:.0%} of merged pairs share the same resolved place_id. "
                    f"Auto-committed merges should almost always share a townland — a person "
                    f"does not move between townlands between census years. "
                    f"Low place-match rate among merges suggests the surname-prefix blocking "
                    f"rule is generating cross-townland false positives that score above the "
                    f"auto-commit threshold."
                )
                actions.append(
                    "Inspect merged pairs where place_match=miss in Section 2. These are the "
                    "highest-risk false merges. Consider raising AUTO_COMMIT_THRESHOLD to 0.90 "
                    "or narrowing the surname-prefix blocking rule from 4 to 5 characters."
                )
            else:
                positives.append(
                    f"Place match rate among merged pairs: {match_rate:.0%} — good spatial "
                    f"coherence. Merges are consistent with GC22 geographical coherence."
                )

        # ── Birth year delta distribution among merged pairs ─────────────────
        by_deltas = [p.birth_year_delta for p in merged_pairs if p.birth_year_delta is not None]
        if by_deltas:
            large = [d for d in by_deltas if d > 5]
            if large:
                issues.append(
                    f"{len(large)} merged pair(s) have birth year delta > 5 years "
                    f"(max: {max(large)} years). The GC03 census age drift tolerance is ±3 years "
                    f"for 1901↔1911 and ±4 for 1901↔1926. Deltas above 5 suggest informant "
                    f"error or a genuine mismatch. These merges should be reviewed and "
                    f"potentially rolled back."
                )
                actions.append(
                    "In the update-knowledge session, flag merged persons with birth year "
                    "delta > 5 for researcher review. Cross-reference with household membership "
                    "(GC16 couple co-residency, GC15 parent-child co-residency) to triangulate "
                    "whether the age discrepancy is likely informant error or a different person."
                )
            else:
                positives.append(
                    f"All merged pairs have birth year delta ≤ 5 years "
                    f"(max: {max(by_deltas) if by_deltas else 'n/a'}). "
                    f"Consistent with GC03 census age drift tolerances."
                )

    # ── Emit findings ───────────────────────────────────────────────────────
    sub("Issues detected")
    if issues:
        for i, issue in enumerate(issues, 1):
            emit(f"  ISSUE {i}:")
            emit(*_wrap(issue))
            emit("")
    else:
        emit("  None detected.")

    sub("What looks good")
    if positives:
        for pos in positives:
            emit(*_wrap("✓ " + pos, indent="  "))
    else:
        emit("  Nothing to highlight.")

    sub("Recommended actions")
    if actions:
        for i, action in enumerate(actions, 1):
            emit(f"  ACTION {i}:")
            emit(*_wrap(action))
            emit("")
    else:
        emit("  No actions recommended — pipeline looks healthy.")

    emit("", "═" * _W, "  End of GRA Person Linkage Debug Log", "═" * _W, "")
    Path(path).write_text("\n".join(out), encoding="utf-8")


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
