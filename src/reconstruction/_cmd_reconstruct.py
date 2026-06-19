"""
GRA CLI — _cmd_reconstruct (updated extract)

Changes from previous version
------------------------------
1.  --debug-log <path>  →  --debug  (boolean flag)
    Debug is now on/off.  Each pipeline stage that supports debug output
    writes to a hardcoded filename within a single run output directory.
    The caller no longer manages filenames.

2.  Run output directory
    Derived automatically from the database path:
        <db_stem>_debug_<YYYYMMDD_HHMMSS>/
    Created only when --debug is set.  All stage debug logs land here.

3.  Per-stage filenames (hardcoded in each debug module):
        household_debug.log     ← debug.py          (stage 3a)
        person_debug.log        ← debug.py          (stage 3b)
        consensus_debug.log     ← consensus_debug.py (stage 4/5)

4.  ConsensusDebugLog is created here and passed into rebuild_consensus()
    so the accumulator is populated inline during the run.  The writer is
    called immediately after rebuild_consensus() returns, before the
    summary, so all logs are present together.
"""

from __future__ import annotations

import argparse
import datetime
from pathlib import Path


def _make_debug_dir(db_path: str) -> Path:
    """
    Create and return a timestamped debug output directory next to the database.

    Example: gra.db  →  gra_debug_20250611_143022/
    """
    stem = Path(db_path).stem
    ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    d    = Path(db_path).parent / f"{stem}_debug_{ts}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cmd_reconstruct(args: argparse.Namespace) -> None:
    from src.reconstruction import (
        run_place_resolution, print_place_resolution_report,
        run_household_inference, print_household_inference_report,
    )
    from src.reconstruction.linkage import (
        run_census_household_linkage, print_household_linkage_report,
        run_census_linkage, print_census_linkage_report,
    )
    from src.reconstruction.scoring import rebuild_consensus, print_rebuild_consensus_report
    conn = open_db(args.db)
    check_version(conn)

    force     = getattr(args, "force", False)
    debug     = getattr(args, "debug", False)
    debug_dir = _make_debug_dir(args.db) if debug else None

    if debug_dir:
        print(f"\nDebug mode active — logs will be written to: {debug_dir}/")

    print("\nRunning reconstruction pipeline (all sources)...")

    print("\n[1/4] Place resolution")
    place_result = run_place_resolution(conn)
    print_place_resolution_report(place_result)

    print("\n[2/4] Household structure inference")
    inference_result = run_household_inference(conn)
    print_household_inference_report(inference_result)

    print("\n[3/4] Cross-census linkage")
    _check_place_id_null_rate(conn, force=force)

    # Stages 3a and 3b pass debug_dir as a string; the existing debug.py
    # writer appends its own hardcoded filenames (household_debug.log,
    # person_debug.log) to this directory.  No change needed to their
    # signatures beyond switching from a file path to a directory path —
    # that refactor is tracked separately.
    hh_log     = str(debug_dir) if debug_dir else None
    person_log = str(debug_dir) if debug_dir else None

    print("\n  [3a] Household linkage (Pass 1: Splink; Pass 2: person resolution)...")
    hh_result = run_census_household_linkage(conn, debug_log=hh_log)
    print_household_linkage_report(hh_result)

    print("\n  [3b] Cross-census person linkage...")
    person_result = run_census_linkage(
        conn,
        already_merged=hh_result.merged_person_ids,
        debug_log=person_log,
    )
    print_census_linkage_report(person_result)

    print("\n[4/4] Rebuild event consensus")

    # Build the debug accumulator for stage 4 when debug mode is active.
    # It is populated inline by rebuild_consensus() and written immediately
    # after the run completes.
    consensus_debug = None
    if debug_dir:
        from src.reconstruction.consensus_debug import (
            ConsensusDebugLog,
            write_consensus_debug_log,
        )
        import datetime as _dt
        consensus_debug = ConsensusDebugLog(
            run_ts=_dt.datetime.now().isoformat(timespec="seconds"),
            score_version="consensus_v1.0",
        )

    consensus_result = rebuild_consensus(conn, debug=consensus_debug)
    print_rebuild_consensus_report(consensus_result)

    if debug_dir and consensus_debug is not None:
        write_consensus_debug_log(str(debug_dir), consensus_debug, consensus_result)
        print(f"  → consensus_debug.log written to {debug_dir}/")

    print("\nReconstruction complete. Running summary...\n")
    print_summary(conn)

    if debug_dir:
        print(f"\nDebug logs: {debug_dir}/")
        for log in sorted(debug_dir.glob("*.log")):
            print(f"  {log.name}")
