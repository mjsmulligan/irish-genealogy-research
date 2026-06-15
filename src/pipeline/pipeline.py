"""
GRA — Pipeline orchestrator.

Owns sequence knowledge only: which stages run, in what order, with what
arguments. No argparse. No SQL. No display logic.

Entry points
------------
run_reconstruct(conn, *, force, debug_dir)
    Full post-ingest pipeline for all sources:
    place-resolve → household → link → rebuild-consensus

run_place_resolve(conn)
    Stage 2 only.

run_household(conn)
    Stage 3 only.

run_link(conn, *, force, debug_dir)
    Stage 4 only (household linkage pass + person linkage pass).

run_rebuild_consensus(conn, *, debug_dir)
    Stage 5 only.

All functions return a PipelineResult containing per-stage results.
Callers (cli.py) are responsible for printing reports.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.pipeline.place_resolution import (
    run_place_resolution,
    PlaceResolutionResult,
)
from src.pipeline.household_inference import (
    run_household_inference,
    HouseholdInferenceResult,
)
from src.pipeline.linkage import (
    run_census_household_linkage,
    run_census_linkage,
    HouseholdLinkageResult,
    CensusLinkageResult,
)
from src.pipeline.scoring import (
    rebuild_consensus,
    RebuildConsensusResult,
)

# ---------------------------------------------------------------------------
# Place_id null rate gate
# ---------------------------------------------------------------------------

_PLACE_ID_NULL_RATE_LIMIT = 0.15


def _check_place_id_null_rate(conn: sqlite3.Connection, force: bool) -> str | None:
    """
    Return a warning string if the null rate exceeds the threshold, else None.
    Raises SystemExit if not forced and rate is too high.
    """
    import sys

    row = conn.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN rp.recorded_person_id NOT IN (
                SELECT recorded_person_id FROM place_record
            ) THEN 1 ELSE 0 END) AS unresolved
        FROM recorded_person rp
    """).fetchone()
    total = row["total"] or 0
    unresolved = row["unresolved"] or 0
    if total == 0:
        return None
    null_rate = unresolved / total
    pct = null_rate * 100
    if null_rate > _PLACE_ID_NULL_RATE_LIMIT:
        msg = (
            f"place_id null rate is {pct:.1f}% ({unresolved}/{total}) — "
            f"above the {_PLACE_ID_NULL_RATE_LIMIT * 100:.0f}% threshold. "
            f"Seed place authority for missing DEDs and re-run place resolution, "
            f"or pass --force to override."
        )
        if not force:
            print(f"\n  ABORTED: {msg}", file=sys.stderr)
            sys.exit(1)
        return f"WARNING: {msg}"
    return None


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class PipelineResult:
    place_resolution:   PlaceResolutionResult | None = None
    household:          HouseholdInferenceResult | None = None
    household_linkage:  HouseholdLinkageResult | None = None
    person_linkage:     CensusLinkageResult | None = None
    consensus:          RebuildConsensusResult | None = None
    warnings:           list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage entry points
# ---------------------------------------------------------------------------


def run_place_resolve(conn: sqlite3.Connection) -> PipelineResult:
    """Stage 2: resolve place strings across all sources."""
    result = PipelineResult()
    result.place_resolution = run_place_resolution(conn)
    return result


def run_household(conn: sqlite3.Connection) -> PipelineResult:
    """Stage 3: household inference across all sources."""
    result = PipelineResult()
    result.household = run_household_inference(conn)
    return result


def run_link(
    conn: sqlite3.Connection,
    *,
    force: bool = False,
    debug_dir: Path | None = None,
) -> PipelineResult:
    """Stage 4: cross-census linkage (household pass then person pass)."""
    result = PipelineResult()

    warning = _check_place_id_null_rate(conn, force=force)
    if warning:
        result.warnings.append(warning)

    debug_log = str(debug_dir) if debug_dir else None

    result.household_linkage = run_census_household_linkage(
        conn, debug_log=debug_log
    )
    result.person_linkage = run_census_linkage(
        conn,
        already_merged=result.household_linkage.merged_person_ids,
        debug_log=debug_log,
    )
    return result


def run_rebuild_consensus(
    conn: sqlite3.Connection,
    *,
    debug_dir: Path | None = None,
) -> PipelineResult:
    """Stage 5: rebuild event consensus after linkage."""
    result = PipelineResult()

    consensus_debug = None
    if debug_dir:
        import datetime
        from src.pipeline.debug import (
            ConsensusDebugLog,
            write_consensus_debug_log,
        )
        consensus_debug = ConsensusDebugLog(
            run_ts=datetime.datetime.now().isoformat(timespec="seconds"),
            score_version="consensus_v1.0",
        )

    result.consensus = rebuild_consensus(conn, debug=consensus_debug)

    if debug_dir and consensus_debug is not None:
        from src.pipeline.debug import write_consensus_debug_log
        write_consensus_debug_log(str(debug_dir), consensus_debug, result.consensus)

    return result


def run_reconstruct(
    conn: sqlite3.Connection,
    *,
    force: bool = False,
    debug_dir: Path | None = None,
) -> PipelineResult:
    """
    Full post-ingest pipeline across all sources:
        Stage 2 — place resolution
        Stage 3 — household inference
        Stage 4 — cross-census linkage
        Stage 5 — rebuild consensus
    """
    result = PipelineResult()

    r2 = run_place_resolve(conn)
    result.place_resolution = r2.place_resolution

    r3 = run_household(conn)
    result.household = r3.household

    r4 = run_link(conn, force=force, debug_dir=debug_dir)
    result.household_linkage = r4.household_linkage
    result.person_linkage    = r4.person_linkage
    result.warnings.extend(r4.warnings)

    r5 = run_rebuild_consensus(conn, debug_dir=debug_dir)
    result.consensus = r5.consensus

    return result
