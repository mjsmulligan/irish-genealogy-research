"""
GRA — Linkage Debug Log
Dataclasses, helper functions, and file writers for the cross-census linkage
debug log.  Imported by linkage.py when --debug-log PATH is passed.

Defining shared threshold constants here breaks the circular dependency
that would arise if debug.py imported from linkage.py.  linkage.py imports
AUTO_COMMIT_THRESHOLD, PROPOSE_FLOOR, SCORE_VERSION_*, and _CENSUS_NAMES
from this module.

Public API
----------
Constants (re-exported to linkage.py):
    AUTO_COMMIT_THRESHOLD, PROPOSE_FLOOR
    SCORE_VERSION_PERSON, SCORE_VERSION_HH
    _CENSUS_NAMES

Dataclasses:
    PairRecord            — one scored pair from a Splink prediction
    HouseholdDebugLog     — accumulator for the household linkage pass
    PersonDebugLog        — accumulator for the person-level linkage pass

Feature stats helpers (mutate the debug accumulator in-place):
    populate_hh_feature_stats(debug, dfs)
    populate_person_feature_stats(debug, dfs)

Label / source map builders:
    build_hh_label_map(conn, dfs) -> dict[int, str]
    build_person_label_and_source_maps(conn, dfs) -> (label_map, source_map)

PairRecord builders:
    build_hh_pair_record(row, band, skip_reason, label_map) -> PairRecord
    build_person_pair_record(row, band, skip_reason, label_map, source_map) -> PairRecord

Log writers:
    write_household_debug_log(path, debug, result)
    write_person_debug_log(path, debug, result)
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    # Only needed for type annotations — avoids the circular import at runtime.
    from src.pipeline.linkage import HouseholdLinkageResult, CensusLinkageResult

# ---------------------------------------------------------------------------
# Shared constants — imported by linkage.py
# ---------------------------------------------------------------------------

# Threshold bands (reconstruction_algorithms.md §1.3)
AUTO_COMMIT_THRESHOLD = 0.85
PROPOSE_FLOOR         = 0.30
SCORE_VERSION_PERSON  = "census_linkage_v1.0"
SCORE_VERSION_HH      = "household_linkage_v1.0"

# Human-readable census names keyed by source_id
_CENSUS_NAMES: dict[int, str] = {3: "Census 1901", 4: "Census 1911", 5: "Census 1926"}

# ---------------------------------------------------------------------------
# Debug log accumulators
# ---------------------------------------------------------------------------


@dataclass
class PairRecord:
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
class HouseholdDebugLog:
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
    pairs:                       list[PairRecord] = field(default_factory=list)
    skipped_reason:              str = ""
    household_surname_freq:      list[tuple[str, int]] = field(default_factory=list)
    persons_merged:              int = 0
    # Timing mirrors HouseholdLinkageResult — populated from result at log-write time.
    elapsed_total:               float = 0.0
    elapsed_feature_extract:     float = 0.0
    elapsed_training:            float = 0.0
    elapsed_prediction:          float = 0.0
    elapsed_merge:               float = 0.0

    def record_pair(self, pr: PairRecord) -> None:
        self.pairs.append(pr)


@dataclass
class PersonDebugLog:
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
    pairs:                list[PairRecord] = field(default_factory=list)
    skipped_reason:       str = ""
    surname_freq:         list[tuple[str, int]] = field(default_factory=list)
    # Timing mirrors CensusLinkageResult — populated from result at log-write time.
    elapsed_total:            float = 0.0
    elapsed_feature_extract:  float = 0.0
    elapsed_training:         float = 0.0
    elapsed_prediction:       float = 0.0
    elapsed_merge:            float = 0.0

    def record_pair(self, pr: PairRecord) -> None:
        self.pairs.append(pr)


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

def populate_hh_feature_stats(
    debug: HouseholdDebugLog,
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


def build_hh_label_map(
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


def build_hh_pair_record(
    row: "pd.Series",
    band: str,
    skip_reason: str,
    label_map: dict[int, str],
) -> PairRecord:
    """Extract a PairRecord from a household Splink prediction row."""
    rid_l = int(row["unique_id_l"])
    rid_r = int(row["unique_id_r"])
    score = float(row["match_probability"])

    by_l = None   # household feature rows carry no birth year
    by_r = None
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

    return PairRecord(
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

def populate_person_feature_stats(
    debug: PersonDebugLog,
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


def build_person_label_and_source_maps(
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


def build_person_pair_record(
    row: "pd.Series",
    band: str,
    skip_reason: str,
    label_map: dict[int, str],
    source_map: dict[int, int],
) -> PairRecord:
    """Extract a PairRecord from a person-level Splink prediction row."""
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

    return PairRecord(
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

def write_household_debug_log(
    path: str,
    debug: HouseholdDebugLog,
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


def write_person_debug_log(
    path: str,
    debug: PersonDebugLog,
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
        # TF adjustment is already enabled in _build_settings() for both
        # surname_norm and forename_norm. This section checks whether the
        # adjustment is sufficient — i.e. whether high-frequency surnames
        # still appear in suspicious merges despite TF downweighting.
        high_freq = [(s, c) for s, c in debug.surname_freq if c >= 10]
        if high_freq:
            names_str = ", ".join(f"'{s}' ({c})" for s, c in high_freq[:5])
            positives.append(
                f"High-frequency surnames detected ({names_str}) — "
                f"term-frequency adjustment is active for surname_norm and forename_norm "
                f"(reconstruction_algorithms.md §4.4). TF downweighting is applied automatically "
                f"by Splink during EM training from the feature DataFrame."
            )
            # Only flag as an issue if there are suspicious cross-place merges —
            # those are the signature of TF adjustment failing to suppress false positives.
            cross_place_merges = [
                p for p in debug.pairs
                if p.band == "merged" and p.place_match is False
            ]
            if cross_place_merges:
                issues.append(
                    f"{len(cross_place_merges)} merged pair(s) do not share a resolved place_id. "
                    f"With high-frequency surnames ({names_str}), cross-place merges are the "
                    f"primary false-positive risk. TF adjustment is active but may not fully "
                    f"suppress ambiguous same-surname pairs at this community scale "
                    f"(reconstruction_algorithms.md §4.4)."
                )
                actions.append(
                    "Inspect cross-place merged pairs in Section 2 (place=miss, band=merged). "
                    "If they involve high-frequency surnames, consider raising "
                    "AUTO_COMMIT_THRESHOLD to 0.90 or deferring TF adjustment until 3–4 DEDs "
                    "are ingested for a representative frequency distribution (ROADMAP.md §4)."
                )
        elif debug.surname_freq:
            positives.append(
                "Surname frequency distribution looks reasonable — no surname exceeds 10 persons. "
                "Term-frequency adjustment is active and not urgently needed at this scale."
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
