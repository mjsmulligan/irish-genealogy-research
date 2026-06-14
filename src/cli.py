"""
GRA — Genealogy Research Assistant
Command-line interface: sole entry point for all pipeline operations.

Usage:
    python -m src.cli <command> [options]

Commands:
    init                Initialise a new database
    reset               Wipe evidence + conclusions (--all to include place_authority)
    ingest              Ingest a census CSV into the evidence layer
    seed-places         Seed place_authority from a logainm CSV
    fetch-places        Fetch place authority from logainm.ie API
    summary             Print knowledge base summary
    place-resolve       Stage 2: resolve place strings across all sources
    household           Stage 3: household inference across all sources
    link                Stage 4: cross-census Splink person linkage
    rebuild-consensus   Stage 5: rebuild event consensus after linkage
    reconstruct         Full pipeline: place-resolve → household → link → rebuild-consensus
    validate            Run genealogical constraint rules (R40–R46)

Default database path: genealogy.db
"""

from __future__ import annotations

import argparse
import datetime
import sqlite3
import sys
from pathlib import Path

from src.db.db import (
    DEFAULT_DB,
    open_db,
    init_db,
    check_version,
)

# ---------------------------------------------------------------------------
# Summary (display helper used by multiple commands)
# ---------------------------------------------------------------------------


def print_summary(conn: sqlite3.Connection) -> None:
    """Print a knowledge base summary to stdout."""
    check_version(conn)

    def q(sql: str) -> int:
        return conn.execute(sql).fetchone()[0]

    print()
    print("=" * 60)
    print("  GRA — Knowledge Base Summary")
    print("=" * 60)

    print("\n  FOUNDATIONAL LAYER")
    print(f"    Repositories:              {q('SELECT COUNT(*) FROM repository'):>6}")
    print(f"    Sources:                   {q('SELECT COUNT(*) FROM source'):>6}")

    pa_total = q("SELECT COUNT(*) FROM place_authority")
    print(f"    Place authorities:         {pa_total:>6}")
    if pa_total:
        type_counts = conn.execute(
            "SELECT place_type, COUNT(*) AS n FROM place_authority GROUP BY place_type ORDER BY n DESC"
        ).fetchall()
        for tc in type_counts:
            print(f"      {tc['place_type']:<20}   {tc['n']:>4}")

    print("\n  EVIDENCE LAYER")
    print(f"    Records:                   {q('SELECT COUNT(*) FROM record'):>6}")
    print(f"    Recorded Persons:          {q('SELECT COUNT(*) FROM recorded_person'):>6}")

    total_records = q("SELECT COUNT(*) FROM record")
    linked_records = q("SELECT COUNT(DISTINCT record_id) FROM place_record")
    if total_records:
        unlinked = total_records - linked_records
        print(f"    Records with place linked: {linked_records:>6}  ({unlinked} unresolved)")

    print("\n  CONCLUSION LAYER")
    couple_count  = q("SELECT COUNT(*) FROM relationship WHERE type='couple'")
    parent_count  = q("SELECT COUNT(*) FROM relationship WHERE type='parent_child'")
    sibling_count = q("SELECT COUNT(*) FROM relationship WHERE type='sibling'")

    print(f"    Persons:                   {q('SELECT COUNT(*) FROM person'):>6}")
    print(f"    Relationships:             {q('SELECT COUNT(*) FROM relationship'):>6}")
    print(f"      Couples:                 {couple_count:>6}")
    print(f"      Parent-child:            {parent_count:>6}")
    print(f"      Siblings:                {sibling_count:>6}")
    print(f"    Events:                    {q('SELECT COUNT(*) FROM event'):>6}")

    print("\n  LINKAGE")
    total_links = q("SELECT COUNT(*) FROM person_record")
    verified    = q("SELECT COUNT(*) FROM person_record WHERE verified=1")
    place_links = q("SELECT COUNT(*) FROM place_record")
    place_verified = q("SELECT COUNT(*) FROM place_record WHERE verified=1")
    print(f"    Person-Record links:       {total_links:>6}  ({verified} verified)")
    print(f"    Place-Record links:        {place_links:>6}  ({place_verified} verified)")

    source_counts = conn.execute("""
        SELECT s.title, COUNT(DISTINCT r.record_id) AS records,
               COUNT(rp.recorded_person_id) AS persons
        FROM source s
        JOIN record r ON r.source_id = s.source_id
        JOIN recorded_person rp ON rp.record_id = r.record_id
        GROUP BY s.source_id
        ORDER BY records DESC
    """).fetchall()

    if source_counts:
        print("\n  RECORDS BY SOURCE")
        for row in source_counts:
            print(f"    {row['title']:<34} {row['records']:>4} records  {row['persons']:>5} persons")

    print()
    print("=" * 60)
    print()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_PLACE_ID_NULL_RATE_LIMIT = 0.15


def _check_place_id_null_rate(conn: sqlite3.Connection, force: bool) -> None:
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
        return
    null_rate = unresolved / total
    pct = null_rate * 100
    if null_rate > _PLACE_ID_NULL_RATE_LIMIT:
        msg = (
            f"  place_id null rate is {pct:.1f}% ({unresolved}/{total} persons unresolved) — "
            f"above the {_PLACE_ID_NULL_RATE_LIMIT * 100:.0f}% threshold.\n"
            f"  Seed place authority for any missing DEDs and re-run place resolution,\n"
            f"  or pass --force to run linkage anyway."
        )
        if force:
            print(f"\n  WARNING: {msg}\n  Proceeding because --force was passed.")
        else:
            print(f"\n  ABORTED: {msg}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"  place_id null rate: {pct:.1f}% ({unresolved}/{total}) — within threshold.")


def _make_debug_dir(db_path: str) -> Path:
    stem = Path(db_path).stem
    ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    d    = Path(db_path).parent / f"{stem}_debug_{ts}"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def _cmd_init(args: argparse.Namespace) -> None:
    init_db(args.db)


def _cmd_reset(args: argparse.Namespace) -> None:
    conn = open_db(args.db)
    check_version(conn)

    wipe_all = getattr(args, "all", False)

    evidence_tables = [
        "training_labels",
        "person_record",
        "place_record",
        "relationship_event",
        "person_event",
        "event",
        "relationship",
        "person",
        "recorded_person",
        "record",
    ]
    place_tables = ["place_authority"]
    tables_to_wipe = evidence_tables + (place_tables if wipe_all else [])

    if wipe_all:
        print(
            "\n  WARNING: --all will wipe place_authority. "
            "You will need to re-seed places before running the pipeline.\n"
        )

    print("Resetting database...")
    with conn:
        for table in tables_to_wipe:
            try:
                conn.execute(f"DELETE FROM {table}")
            except sqlite3.OperationalError:
                pass

    scope = "all tables including place_authority" if wipe_all else "evidence + conclusions (place_authority preserved)"
    print(f"  Reset complete — {scope}.")
    print(f"  Database is ready for re-ingest.\n")


def _cmd_ingest(args: argparse.Namespace) -> None:
    from src.ingest.census import ingest_census
    conn = open_db(args.db)
    source_id = int(args.source)

    if source_id in (3, 4, 5):
        result = ingest_census(conn, args.file, source_id=source_id)
    else:
        print(f"No ingest handler implemented for source {source_id}.", file=sys.stderr)
        sys.exit(1)

    print(f"\nIngest complete — {result['source_title']}")
    print(f"  CSV rows:        {result['rows_in_csv']}")
    print(f"  Households:      {result['households']}")
    print(f"  Records:         {result['records_committed']}")
    print(f"  Persons:         {result['persons_committed']}")
    print(f"  Townlands ({result['townland_count']}): {', '.join(result['townlands'])}")

    notes = result["parse_notes"]
    if notes:
        print(f"\n  Parse notes ({len(notes)}):")
        for n in notes:
            name = n.get("name", "")
            print(f"    [{n['image_group']}] {name}: {n['note']}")
    else:
        print("\n  No parse notes — clean ingest.")


def _cmd_seed_places(args: argparse.Namespace) -> None:
    from src.pipeline.seed_places import seed_places, print_seed_places_report
    conn = open_db(args.db)
    check_version(conn)
    result = seed_places(conn, args.file)
    print_seed_places_report(result)
    if not result["ok"]:
        sys.exit(1)


def _cmd_fetch_places(args: argparse.Namespace) -> None:
    from src.pipeline.fetch_places import main as fetch_places_main
    fetch_places_main()


def _cmd_summary(args: argparse.Namespace) -> None:
    conn = open_db(args.db)
    print_summary(conn)


def _cmd_place_resolve(args: argparse.Namespace) -> None:
    from src.pipeline import run_place_resolution, print_place_resolution_report
    conn = open_db(args.db)
    check_version(conn)
    print("\nRunning place resolution across all sources...")
    result = run_place_resolution(conn)
    print_place_resolution_report(result)


def _cmd_household(args: argparse.Namespace) -> None:
    from src.pipeline import run_household_inference, print_household_inference_report
    conn = open_db(args.db)
    check_version(conn)
    print("\nRunning household inference across all sources...")
    result = run_household_inference(conn)
    print_household_inference_report(result)


def _cmd_link(args: argparse.Namespace) -> None:
    from src.pipeline.linkage import (
        run_census_household_linkage, print_household_linkage_report,
        run_census_linkage, print_census_linkage_report,
    )
    conn = open_db(args.db)
    check_version(conn)

    force     = getattr(args, "force", False)
    debug     = getattr(args, "debug", False)
    debug_dir = _make_debug_dir(args.db) if debug else None

    if debug_dir:
        print(f"\nDebug mode active — logs will be written to: {debug_dir}/")

    _check_place_id_null_rate(conn, force=force)

    debug_log = str(debug_dir) if debug_dir else None

    print("\n[1/2] Household linkage (Pass 1: Splink; Pass 2: person resolution)...")
    hh_result = run_census_household_linkage(conn, debug_log=debug_log)
    print_household_linkage_report(hh_result)

    print("\n[2/2] Cross-census person linkage...")
    person_result = run_census_linkage(
        conn,
        already_merged=hh_result.merged_person_ids,
        debug_log=debug_log,
    )
    print_census_linkage_report(person_result)

    print("\nLinkage complete. Running summary...\n")
    print_summary(conn)

    if debug_dir:
        print(f"\nDebug logs: {debug_dir}/")
        for log in sorted(debug_dir.glob("*.log")):
            print(f"  {log.name}")


def _cmd_rebuild_consensus(args: argparse.Namespace) -> None:
    from src.pipeline.scoring import rebuild_consensus, print_rebuild_consensus_report
    conn = open_db(args.db)
    check_version(conn)

    debug     = getattr(args, "debug", False)
    debug_dir = _make_debug_dir(args.db) if debug else None

    if debug_dir:
        print(f"\nDebug mode active — logs will be written to: {debug_dir}/")

    print("\nRebuilding event consensus (post-linkage)...")

    consensus_debug = None
    if debug_dir:
        from src.pipeline.consensus_debug import (
            ConsensusDebugLog, write_consensus_debug_log,
        )
        consensus_debug = ConsensusDebugLog(
            run_ts=datetime.datetime.now().isoformat(timespec="seconds"),
            score_version="consensus_v1.0",
        )

    result = rebuild_consensus(conn, debug=consensus_debug)
    print_rebuild_consensus_report(result)

    if debug_dir and consensus_debug is not None:
        write_consensus_debug_log(str(debug_dir), consensus_debug, result)
        print(f"\nDebug logs: {debug_dir}/")
        for log in sorted(debug_dir.glob("*.log")):
            print(f"  {log.name}")


def _cmd_reconstruct(args: argparse.Namespace) -> None:
    from src.pipeline import (
        run_place_resolution, print_place_resolution_report,
        run_household_inference, print_household_inference_report,
    )
    from src.pipeline.linkage import (
        run_census_household_linkage, print_household_linkage_report,
        run_census_linkage, print_census_linkage_report,
    )
    from src.pipeline.scoring import rebuild_consensus, print_rebuild_consensus_report
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

    debug_log = str(debug_dir) if debug_dir else None

    print("\n  [3a] Household linkage (Pass 1: Splink; Pass 2: person resolution)...")
    hh_result = run_census_household_linkage(conn, debug_log=debug_log)
    print_household_linkage_report(hh_result)

    print("\n  [3b] Cross-census person linkage...")
    person_result = run_census_linkage(
        conn,
        already_merged=hh_result.merged_person_ids,
        debug_log=debug_log,
    )
    print_census_linkage_report(person_result)

    print("\n[4/4] Rebuild event consensus")

    consensus_debug = None
    if debug_dir:
        from src.pipeline.consensus_debug import (
            ConsensusDebugLog, write_consensus_debug_log,
        )
        consensus_debug = ConsensusDebugLog(
            run_ts=datetime.datetime.now().isoformat(timespec="seconds"),
            score_version="consensus_v1.0",
        )

    consensus_result = rebuild_consensus(conn, debug=consensus_debug)
    print_rebuild_consensus_report(consensus_result)

    if debug_dir and consensus_debug is not None:
        write_consensus_debug_log(str(debug_dir), consensus_debug, consensus_result)

    print("\nReconstruction complete. Running summary...\n")
    print_summary(conn)

    if debug_dir:
        print(f"\nDebug logs: {debug_dir}/")
        for log in sorted(debug_dir.glob("*.log")):
            print(f"  {log.name}")


def _cmd_validate(args: argparse.Namespace) -> None:
    from src.pipeline.validator import main as validator_main
    validator_main()


# ---------------------------------------------------------------------------
# Argparse + dispatch
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m src.cli",
        description="GRA — Genealogy Research Assistant",
    )
    parser.add_argument(
        "--db", default=DEFAULT_DB,
        help=f"Database path (default: {DEFAULT_DB})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Initialise a new database")

    p_reset = sub.add_parser(
        "reset",
        help="Wipe evidence + conclusions; preserve place_authority (use --all to wipe everything)",
    )
    p_reset.add_argument(
        "--all", action="store_true", default=False,
        help="Full wipe including place_authority (use only when reseeding places from scratch)",
    )

    p_ingest = sub.add_parser("ingest", help="Ingest a source CSV into the evidence layer")
    p_ingest.add_argument("--source", required=True, help="Source ID (e.g. 4 for Census 1911)")
    p_ingest.add_argument("--file", required=True, help="Path to the CSV file")

    p_seed = sub.add_parser("seed-places", help="Seed place_authority from a logainm CSV file")
    p_seed.add_argument("--file", required=True, help="Path to place_authority CSV (logainm format)")

    p_fetch = sub.add_parser(
        "fetch-places",
        help="Fetch place authority from logainm.ie API and load into DB",
    )
    p_fetch.add_argument("--logainm-id", type=int, default=None, help="Logainm numeric ID")
    p_fetch.add_argument("--csv", default=None, help="Export CSV path")
    p_fetch.add_argument("--from-csv", default=None, help="Load from existing CSV instead of API")
    p_fetch.add_argument("--api-key", default=None, help="Logainm API key (or LOGAINM_API_KEY env var)")
    p_fetch.add_argument("--rate-delay", type=float, default=0.05, help="Delay between API requests (s)")

    sub.add_parser("summary", help="Print knowledge base summary")

    sub.add_parser("place-resolve", help="Stage 2: resolve place strings across all sources")

    sub.add_parser("household", help="Stage 3: household inference across all sources")

    p_link = sub.add_parser("link", help="Stage 4: cross-census Splink person linkage")
    p_link.add_argument(
        "--debug", action="store_true", default=False,
        help="Write per-stage debug logs to a timestamped directory next to the database",
    )
    p_link.add_argument(
        "--force", action="store_true", default=False,
        help="Run linkage even if place_id null rate exceeds the 15%% threshold",
    )

    p_rebuild = sub.add_parser(
        "rebuild-consensus",
        help="Stage 5: rebuild event consensus after linkage (marks is_primary on Event)",
    )
    p_rebuild.add_argument(
        "--debug", action="store_true", default=False,
        help="Write consensus debug log to a timestamped directory next to the database",
    )

    p_reconstruct = sub.add_parser(
        "reconstruct",
        help="Full post-ingest pipeline: place-resolve → household → link → rebuild-consensus",
    )
    p_reconstruct.add_argument(
        "--debug", action="store_true", default=False,
        help="Write per-stage debug logs to a timestamped directory next to the database",
    )
    p_reconstruct.add_argument(
        "--force", action="store_true", default=False,
        help="Run linkage even if place_id null rate exceeds the 15%% threshold",
    )

    p_validate = sub.add_parser(
        "validate",
        help="Run genealogical constraint rules (R40–R46) across the database",
    )
    p_validate.add_argument(
        "--person", type=int, default=None,
        help="Validate a single Person by ID (omit to validate all)",
    )

    args = parser.parse_args()

    dispatch = {
        "init":               _cmd_init,
        "reset":              _cmd_reset,
        "ingest":             _cmd_ingest,
        "seed-places":        _cmd_seed_places,
        "fetch-places":       _cmd_fetch_places,
        "summary":            _cmd_summary,
        "place-resolve":      _cmd_place_resolve,
        "household":          _cmd_household,
        "link":               _cmd_link,
        "rebuild-consensus":  _cmd_rebuild_consensus,
        "reconstruct":        _cmd_reconstruct,
        "validate":           _cmd_validate,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
