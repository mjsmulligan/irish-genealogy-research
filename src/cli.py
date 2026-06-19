"""
GRA — Genealogy Research Assistant
Command-line interface: sole entry point for all operations.

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
    score-evidence      Stage 5: rebuild event consensus after linkage
    reconstruct         Full pipeline: place-resolve → household → link → score-evidence
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
# Summary display helper
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
            "SELECT place_type, COUNT(*) AS n FROM place_authority "
            "GROUP BY place_type ORDER BY n DESC"
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
    total_links    = q("SELECT COUNT(*) FROM person_record")
    verified       = q("SELECT COUNT(*) FROM person_record WHERE verified=1")
    place_links    = q("SELECT COUNT(*) FROM place_record")
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
            print(
                f"    {row['title']:<34} "
                f"{row['records']:>4} records  {row['persons']:>5} persons"
            )

    print()
    print("=" * 60)
    print()


# ---------------------------------------------------------------------------
# Debug dir helper
# ---------------------------------------------------------------------------


def _make_debug_dir(db_path: str) -> Path:
    stem = Path(db_path).stem
    ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    d    = Path(db_path).parent / f"{stem}_debug_{ts}"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Command handlers — dispatch only, no pipeline logic
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
    tables_to_wipe = evidence_tables + (["place_authority"] if wipe_all else [])

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

    scope = (
        "all tables including place_authority"
        if wipe_all
        else "evidence + conclusions (place_authority preserved)"
    )
    print(f"  Reset complete — {scope}.")
    print(f"  Database is ready for re-ingest.\n")


def _cmd_ingest(args: argparse.Namespace) -> None:
    from src.ingest.census import ingest_census
    conn = open_db(args.db)
    source_id = int(args.source)

    if source_id not in (3, 4, 5):
        print(f"No ingest handler implemented for source {source_id}.", file=sys.stderr)
        sys.exit(1)

    result = ingest_census(conn, args.file, source_id=source_id)

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
            print(f"    [{n['image_group']}] {n.get('name', '')}: {n['note']}")
    else:
        print("\n  No parse notes — clean ingest.")


def _cmd_seed_places(args: argparse.Namespace) -> None:
    from src.db.seed_places import seed_places, print_seed_places_report
    conn = open_db(args.db)
    check_version(conn)
    result = seed_places(conn, args.file)
    print_seed_places_report(result)
    if not result["ok"]:
        sys.exit(1)


def _cmd_fetch_places(args: argparse.Namespace) -> None:
    from src.db.fetch_places import main as fetch_places_main
    fetch_places_main()


def _cmd_summary(args: argparse.Namespace) -> None:
    conn = open_db(args.db)
    print_summary(conn)


def _cmd_place_resolve(args: argparse.Namespace) -> None:
    from src.pipeline.pipeline import run_place_resolve
    from src.pipeline.place_resolution import print_place_resolution_report
    conn = open_db(args.db)
    check_version(conn)
    print("\nRunning place resolution across all sources...")
    result = run_place_resolve(conn)
    print_place_resolution_report(result.place_resolution)


def _cmd_household(args: argparse.Namespace) -> None:
    from src.pipeline.pipeline import run_household
    from src.pipeline.household_inference import print_household_inference_report
    conn = open_db(args.db)
    check_version(conn)
    print("\nRunning household inference across all sources...")
    result = run_household(conn)
    print_household_inference_report(result.household)


def _cmd_link(args: argparse.Namespace) -> None:
    from src.pipeline.pipeline import run_link
    from src.pipeline.linkage import (
        print_household_linkage_report,
        print_census_linkage_report,
    )
    conn = open_db(args.db)
    check_version(conn)

    force     = getattr(args, "force", False)
    debug     = getattr(args, "debug", False)
    debug_dir = _make_debug_dir(args.db) if debug else None

    if debug_dir:
        print(f"\nDebug mode active — logs will be written to: {debug_dir}/")

    print("\n[1/2] Household linkage...")
    print("\n[2/2] Cross-census person linkage...")
    result = run_link(conn, force=force, debug_dir=debug_dir)

    print_household_linkage_report(result.household_linkage)
    print_census_linkage_report(result.person_linkage)

    for warning in result.warnings:
        print(f"\n  {warning}")

    print("\nLinkage complete. Running summary...\n")
    print_summary(conn)

    if debug_dir:
        print(f"\nDebug logs: {debug_dir}/")
        for log in sorted(debug_dir.glob("*.log")):
            print(f"  {log.name}")


def _cmd_score_evidence(args: argparse.Namespace) -> None:
    from src.pipeline.pipeline import run_rebuild_consensus
    from src.pipeline.scoring import print_rebuild_consensus_report
    conn = open_db(args.db)
    check_version(conn)

    debug     = getattr(args, "debug", False)
    debug_dir = _make_debug_dir(args.db) if debug else None

    if debug_dir:
        print(f"\nDebug mode active — logs will be written to: {debug_dir}/")

    print("\nRebuilding event consensus (post-linkage)...")
    result = run_rebuild_consensus(conn, debug_dir=debug_dir)
    print_rebuild_consensus_report(result.consensus)

    if debug_dir:
        print(f"\nDebug logs: {debug_dir}/")
        for log in sorted(debug_dir.glob("*.log")):
            print(f"  {log.name}")


def _cmd_reconstruct(args: argparse.Namespace) -> None:
    from src.pipeline.pipeline import run_reconstruct
    from src.pipeline.place_resolution import print_place_resolution_report
    from src.pipeline.household_inference import print_household_inference_report
    from src.pipeline.linkage import (
        print_household_linkage_report,
        print_census_linkage_report,
    )
    from src.pipeline.scoring import print_rebuild_consensus_report

    conn = open_db(args.db)
    check_version(conn)

    force     = getattr(args, "force", False)
    debug     = getattr(args, "debug", False)
    debug_dir = _make_debug_dir(args.db) if debug else None

    if debug_dir:
        print(f"\nDebug mode active — logs will be written to: {debug_dir}/")

    print("\nRunning reconstruction pipeline (all sources)...")

    result = run_reconstruct(conn, force=force, debug_dir=debug_dir)

    print("\n[1/4] Place resolution")
    print_place_resolution_report(result.place_resolution)

    print("\n[2/4] Household structure inference")
    print_household_inference_report(result.household)

    print("\n[3/4] Cross-census linkage")
    print_household_linkage_report(result.household_linkage)
    print_census_linkage_report(result.person_linkage)

    print("\n[4/4] Event consensus")
    print_rebuild_consensus_report(result.consensus)

    for warning in result.warnings:
        print(f"\n  {warning}")

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
        help="Wipe evidence + conclusions (use --all to also wipe place_authority)",
    )
    p_reset.add_argument(
        "--all", action="store_true", default=False,
        help="Full wipe including place_authority",
    )

    p_ingest = sub.add_parser("ingest", help="Ingest a source CSV into the evidence layer")
    p_ingest.add_argument("--source", required=True, help="Source ID (3=1901, 4=1911, 5=1926)")
    p_ingest.add_argument("--file", required=True, help="Path to the CSV file")

    p_seed = sub.add_parser("seed-places", help="Seed place_authority from a logainm CSV")
    p_seed.add_argument("--file", required=True, help="Path to place_authority CSV")

    p_fetch = sub.add_parser("fetch-places", help="Fetch place authority from logainm.ie API")
    p_fetch.add_argument("--logainm-id", type=int, default=None, help="Logainm numeric ID")
    p_fetch.add_argument("--csv", default=None, help="Export CSV path")
    p_fetch.add_argument("--from-csv", default=None, help="Load from existing CSV instead of API")
    p_fetch.add_argument("--api-key", default=None, help="Logainm API key")
    p_fetch.add_argument("--rate-delay", type=float, default=0.05, help="Delay between requests (s)")

    sub.add_parser("summary", help="Print knowledge base summary")

    sub.add_parser("place-resolve", help="Stage 2: resolve place strings across all sources")

    sub.add_parser("household", help="Stage 3: household inference across all sources")

    p_link = sub.add_parser("link", help="Stage 4: cross-census Splink person linkage")
    p_link.add_argument("--debug", action="store_true", default=False,
                        help="Write debug logs to a timestamped directory")
    p_link.add_argument("--force", action="store_true", default=False,
                        help="Run even if place_id null rate exceeds threshold")

    p_score = sub.add_parser("score-evidence",
                              help="Stage 5: rebuild event consensus after linkage")
    p_score.add_argument("--debug", action="store_true", default=False,
                         help="Write consensus debug log")

    p_reconstruct = sub.add_parser(
        "reconstruct",
        help="Full pipeline: place-resolve → household → link → score-evidence",
    )
    p_reconstruct.add_argument("--debug", action="store_true", default=False,
                               help="Write per-stage debug logs")
    p_reconstruct.add_argument("--force", action="store_true", default=False,
                               help="Run linkage even if place_id null rate exceeds threshold")

    p_validate = sub.add_parser("validate",
                                 help="Run genealogical constraint rules (R40–R46)")
    p_validate.add_argument("--person", type=int, default=None,
                            help="Validate a single Person by ID (omit for all)")

    dispatch = {
        "init":           _cmd_init,
        "reset":          _cmd_reset,
        "ingest":         _cmd_ingest,
        "seed-places":    _cmd_seed_places,
        "fetch-places":   _cmd_fetch_places,
        "summary":        _cmd_summary,
        "place-resolve":  _cmd_place_resolve,
        "household":      _cmd_household,
        "link":           _cmd_link,
        "score-evidence": _cmd_score_evidence,
        "reconstruct":    _cmd_reconstruct,
        "validate":       _cmd_validate,
    }

    args = parser.parse_args()
    dispatch[args.command](args)


if __name__ == "__main__":
    main()


