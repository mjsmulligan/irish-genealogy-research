"""
GRA — Genealogy Research Assistant
Database layer: connection management, schema initialisation, ingest, summary.

CLI usage:
    python -m src.db init [--db PATH]
    python -m src.db ingest --source SOURCE_ID --file CSV_PATH [--db PATH]
    python -m src.db seed-places --file CSV_PATH [--db PATH]
    python -m src.db summary [--db PATH]
    python -m src.db reconstruct [--db PATH]

Default database path: genealogy.db

Connection management, schema helpers, and URL builder now live in
src/db/connection.py — imported here for backward compatibility.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
import sqlite3

from src.db.connection import (
    SCHEMA_VERSION,
    DEFAULT_DB,
    SCHEMA_SQL,
    SEED_SQL,
    open_db,
    init_db,
    check_version,
    build_record_url,
)


# ---------------------------------------------------------------------------
# Census ingest (Sources 3, 4, 5)
# ---------------------------------------------------------------------------

from src.ingest.census import ingest_census  # noqa: E402  (after stdlib imports)


# ---------------------------------------------------------------------------
# Summary
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
# CLI
# ---------------------------------------------------------------------------


def _cmd_init(args: argparse.Namespace) -> None:
    init_db(args.db)


def _cmd_ingest(args: argparse.Namespace) -> None:
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
    from src.seed_places import seed_places, print_seed_places_report
    conn = open_db(args.db)
    check_version(conn)
    result = seed_places(conn, args.file)
    print_seed_places_report(result)
    if not result["ok"]:
        sys.exit(1)


def _cmd_summary(args: argparse.Namespace) -> None:
    conn = open_db(args.db)
    print_summary(conn)


def _cmd_place_resolve(args: argparse.Namespace) -> None:
    from src.reconstruction import run_place_resolution, print_place_resolution_report
    conn = open_db(args.db)
    check_version(conn)
    print("\nRunning place resolution across all sources...")
    result = run_place_resolution(conn)
    print_place_resolution_report(result)


def _cmd_household(args: argparse.Namespace) -> None:
    from src.reconstruction import run_household_inference, print_household_inference_report
    conn = open_db(args.db)
    check_version(conn)
    print("\nRunning household inference across all sources...")
    result = run_household_inference(conn)
    print_household_inference_report(result)


_PLACE_ID_NULL_RATE_LIMIT = 0.15  # refuse linkage above this threshold unless --force


def _check_place_id_null_rate(conn: sqlite3.Connection, force: bool) -> None:
    """
    Check the place_id null rate across all recorded_person rows.
    Abort (or warn) if the rate exceeds _PLACE_ID_NULL_RATE_LIMIT.
    """
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
    """
    Create and return a timestamped debug output directory next to the database.

    Example: genealogy.db  →  genealogy_debug_20250611_143022/

    All pipeline stage debug logs are written here.  Filenames are hardcoded
    within each debug module — the caller passes only this directory path.
    """
    stem = Path(db_path).stem
    ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    d    = Path(db_path).parent / f"{stem}_debug_{ts}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cmd_link(args: argparse.Namespace) -> None:
    from src.reconstruction.linkage import (
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


def _cmd_reset(args: argparse.Namespace) -> None:
    """
    Wipe the database back to a clean state ready for re-ingest.

    Default (no flag): preserves place_authority; wipes all evidence and
    conclusions (record, recorded_person, person, relationship, event,
    person_record, place_record, training_labels, and all junction tables).

    --all: full wipe including place_authority. Use only when reseeding
    places from scratch.
    """
    conn = open_db(args.db)
    check_version(conn)

    wipe_all = getattr(args, "all", False)

    # Tables to always wipe (evidence + conclusions + linkage artefacts).
    # Ordered to respect FK constraints: children before parents.
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
        warning = (
            "\n  WARNING: --all will wipe place_authority. "
            "You will need to re-seed places before running the pipeline.\n"
        )
        print(warning)

    print("Resetting database...")
    with conn:
        for table in tables_to_wipe:
            try:
                conn.execute(f"DELETE FROM {table}")
            except sqlite3.OperationalError:
                # Table may not exist in all schema versions — skip silently
                pass

    scope = "all tables including place_authority" if wipe_all else "evidence + conclusions (place_authority preserved)"
    print(f"  Reset complete — {scope}.")
    print(f"  Database is ready for re-ingest.\n")


def _cmd_rebuild_consensus(args: argparse.Namespace) -> None:
    from src.reconstruction.scoring import rebuild_consensus, print_rebuild_consensus_report
    conn = open_db(args.db)
    check_version(conn)

    debug     = getattr(args, "debug", False)
    debug_dir = _make_debug_dir(args.db) if debug else None

    if debug_dir:
        print(f"\nDebug mode active — logs will be written to: {debug_dir}/")

    print("\nRebuilding event consensus (post-linkage)...")

    consensus_debug = None
    if debug_dir:
        from src.reconstruction.consensus_debug import (
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
        from src.reconstruction.consensus_debug import (
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


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m src.db",
        description="GRA database management",
    )
    parser.add_argument("--db", default=DEFAULT_DB, help=f"Database path (default: {DEFAULT_DB})")
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

    p_seed = sub.add_parser("seed-places", help="Seed place_authority from a CSV file")
    p_seed.add_argument("--file", required=True, help="Path to place_authority CSV (logainm format)")

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

    args = parser.parse_args()

    dispatch = {
        "init":               _cmd_init,
        "reset":              _cmd_reset,
        "ingest":             _cmd_ingest,
        "seed-places":        _cmd_seed_places,
        "summary":            _cmd_summary,
        "place-resolve":      _cmd_place_resolve,
        "household":          _cmd_household,
        "link":               _cmd_link,
        "rebuild-consensus":  _cmd_rebuild_consensus,
        "reconstruct":        _cmd_reconstruct,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
