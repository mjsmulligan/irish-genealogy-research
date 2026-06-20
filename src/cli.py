"""
GRA — Genealogy Research Assistant
Command-line interface: sole entry point for all operations.

Usage:
    python -m src.cli <command> [options]

Commands:
    init                Initialise a new Supabase database (schema + seed data)
    clear-evidence      Wipe evidence + conclusions, preserving place_authority
    clear-conclusions   Wipe conclusion layer only (person, relationship, event)
    add-evidence        Run full evidence pipeline (5 steps): ingest CSV + role relationships + place resolution + record similarity + person similarity
    ingest              Ingest a census CSV into the evidence layer (legacy; prefer add-evidence)
    seed-places         Seed place_authority from a logainm CSV
    fetch-places        Fetch place authority from logainm.ie API
    summary             Print knowledge base summary
    place-resolve       Stage 2: resolve place strings across all sources
    household           Stage 3: household inference across all sources
    link                Stage 4: cross-census Splink person linkage
    score-evidence      Stage 5: rebuild event consensus after linkage
    reconstruct         Full pipeline: place-resolve → household → link → score-evidence
    validate            Run genealogical constraint rules (R40–R46)

DATABASE_URL must be set in the environment or .env file before running any command.
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

import psycopg2.extensions

from src.db.db import open_db, init_db, check_version
from src.constants import CENSUS_SOURCE_IDS


# ---------------------------------------------------------------------------
# Summary display helper
# ---------------------------------------------------------------------------


def _q(conn: psycopg2.extensions.connection, sql: str, params: tuple = ()) -> int:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        # COUNT(*) returns 'count'; COALESCE returns 'coalesce'
        return list(row.values())[0]


def print_summary(conn: psycopg2.extensions.connection) -> None:
    """Print a knowledge base summary to stdout."""
    check_version(conn)

    print()
    print("=" * 60)
    print("  GRA — Knowledge Base Summary")
    print("=" * 60)

    print("\n  FOUNDATIONAL LAYER")
    print(f"    Repositories:              {_q(conn, 'SELECT COUNT(*) FROM repository'):>6}")
    print(f"    Sources:                   {_q(conn, 'SELECT COUNT(*) FROM source'):>6}")

    pa_total = _q(conn, "SELECT COUNT(*) FROM place_authority")
    print(f"    Place authorities:         {pa_total:>6}")
    if pa_total:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT place_type, COUNT(*) AS n FROM place_authority "
                "GROUP BY place_type ORDER BY n DESC"
            )
            for tc in cur.fetchall():
                print(f"      {tc['place_type']:<20}   {tc['n']:>4}")

    print("\n  EVIDENCE LAYER")
    print(f"    Records:                   {_q(conn, 'SELECT COUNT(*) FROM record'):>6}")
    print(f"    Recorded Persons:          {_q(conn, 'SELECT COUNT(*) FROM recorded_person'):>6}")
    print(f"    Recorded Relationships:    {_q(conn, 'SELECT COUNT(*) FROM recorded_relationship'):>6}")
    print(f"    Record Similarities:       {_q(conn, 'SELECT COUNT(*) FROM record_similarity'):>6}")

    total_records  = _q(conn, "SELECT COUNT(*) FROM record")
    linked_records = _q(conn, "SELECT COUNT(DISTINCT record_id) FROM place_record")
    if total_records:
        unlinked = total_records - linked_records
        print(f"    Records with place linked: {linked_records:>6}  ({unlinked} unresolved)")

    print("\n  CONCLUSION LAYER")
    couple_count  = _q(conn, "SELECT COUNT(*) FROM relationship WHERE type='couple'")
    parent_count  = _q(conn, "SELECT COUNT(*) FROM relationship WHERE type='parent_child'")
    sibling_count = _q(conn, "SELECT COUNT(*) FROM relationship WHERE type='sibling'")

    print(f"    Persons:                   {_q(conn, 'SELECT COUNT(*) FROM person'):>6}")
    print(f"    Relationships:             {_q(conn, 'SELECT COUNT(*) FROM relationship'):>6}")
    print(f"      Couples:                 {couple_count:>6}")
    print(f"      Parent-child:            {parent_count:>6}")
    print(f"      Siblings:                {sibling_count:>6}")
    print(f"    Events:                    {_q(conn, 'SELECT COUNT(*) FROM event'):>6}")

    print("\n  LINKAGE")
    total_links    = _q(conn, "SELECT COUNT(*) FROM person_recorded_person")
    verified       = _q(conn, "SELECT COUNT(*) FROM person_recorded_person WHERE verified=1")
    place_links    = _q(conn, "SELECT COUNT(*) FROM place_record")
    place_verified = _q(conn, "SELECT COUNT(*) FROM place_record WHERE verified=1")
    print(f"    Person-RecordedPerson:     {total_links:>6}  ({verified} verified)")
    print(f"    Place-Record links:        {place_links:>6}  ({place_verified} verified)")

    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.title, COUNT(DISTINCT r.record_id) AS records,
                   COUNT(rp.recorded_person_id) AS persons
            FROM source s
            JOIN record r ON r.source_id = s.source_id
            JOIN recorded_person rp ON rp.record_id = r.record_id
            GROUP BY s.source_id, s.title
            ORDER BY records DESC
        """)
        source_counts = cur.fetchall()

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


def _make_debug_dir() -> Path:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    d  = Path("debug") / ts
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def _cmd_init(args: argparse.Namespace) -> None:
    conn = init_db()
    print("Database initialised. Run 'python -m src.cli seed-places' to load place authority.")
    conn.close()


def _cmd_clear_evidence(args: argparse.Namespace) -> None:
    """
    Wipe evidence + conclusion layers. place_authority is preserved.
    Useful for re-ingesting from scratch without re-fetching places.
    """
    conn = open_db()
    check_version(conn)

    tables = [
        "training_labels",
        "relationship_recorded_relationship",
        "person_recorded_person",
        "place_record",
        "event_record",
        "person_event",
        "record_similarity",
        "recorded_relationship",
        "event",
        "relationship",
        "person",
        "person_name",
        "recorded_person",
        "record",
    ]

    print("Clearing evidence + conclusion layers (place_authority preserved)...")
    with conn:
        with conn.cursor() as cur:
            for table in tables:
                cur.execute(f"DELETE FROM {table}")
                print(f"  cleared: {table}")

    print("\nReady for re-ingest.\n")
    conn.close()


def _cmd_clear_conclusions(args: argparse.Namespace) -> None:
    """
    Wipe conclusion layer only. Evidence layer (record, recorded_person, etc.)
    and place_authority are preserved. Allows re-running pipeline stages
    without re-ingesting.
    """
    conn = open_db()
    check_version(conn)

    tables = [
        "training_labels",
        "relationship_recorded_relationship",
        "person_recorded_person",
        "event_record",
        "person_event",
        "event",
        "relationship",
        "person",
        "person_name",
    ]

    print("Clearing conclusion layer (evidence and place_authority preserved)...")
    with conn:
        with conn.cursor() as cur:
            for table in tables:
                cur.execute(f"DELETE FROM {table}")
                print(f"  cleared: {table}")

    print("\nReady to re-run pipeline from household stage.\n")
    conn.close()



def _cmd_add_evidence(args: argparse.Namespace) -> None:
    """
    Add evidence from a census CSV. This is the evidence-layer entry point,
    replacing the bare 'ingest' command.

    Steps:
      1. Ingest CSV → record + recorded_person rows
      2. Assign RecordedRelationship rows from household role pairs
         (reconstruction_algorithms.md §6.1)
      3. Run place resolution to link records to place_authority
      4. Run Splink household similarity across all census sources present
         and write results to record_similarity
    """
    from src.ingest.census import ingest_census
    from src.evidence.role_relationships import assign_role_relationships
    from src.pipeline.pipeline import run_place_resolve
    from src.evidence.similarity import (
        run_record_similarity,
        print_record_similarity_report,
        run_person_similarity,
        print_person_similarity_report,
    )

    conn = open_db()
    check_version(conn)
    source_id = int(args.source)

    if source_id not in CENSUS_SOURCE_IDS:
        print(f"No ingest handler implemented for source {source_id}.", file=sys.stderr)
        sys.exit(1)

    print(f"\n[1/5] Ingesting CSV (source {source_id})...")
    ingest_result = ingest_census(conn, args.file, source_id=source_id)

    print("\n[2/5] Assigning role-pair RecordedRelationships...")

    # ingest_census commits its own transaction; role-relationship assignment
    # runs in a second transaction over the newly committed records.
    rr_totals = {"created": 0, "skipped_null": 0, "skipped_no_rule": 0}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT record_id FROM record WHERE source_id = %s "
            "ORDER BY record_id DESC LIMIT %s",
            (source_id, ingest_result["records_committed"]),
        )
        record_ids = [row["record_id"] for row in cur.fetchall()]

    with conn:
        for rid in record_ids:
            rr = assign_role_relationships(conn, rid)
            rr_totals["created"] += rr.relationships_created
            rr_totals["skipped_null"] += rr.skipped_null_role_pairs
            rr_totals["skipped_no_rule"] += rr.skipped_no_rule

    print("\n[3/5] Running place resolution...")
    place_result = run_place_resolve(conn)

    print("\n[4/5] Running record similarity (Splink household-level across all census sources)...")
    record_similarity_result = run_record_similarity(conn)

    print("\n[5/5] Running person similarity (Splink person-level across all census sources)...")
    person_similarity_result = run_person_similarity(conn)

    # --- Report ---
    print(f"\nadd-evidence complete — {ingest_result['source_title']}")
    print(f"  CSV rows:                  {ingest_result['rows_in_csv']}")
    print(f"  Households (records):      {ingest_result['records_committed']}")
    print(f"  Recorded Persons:          {ingest_result['persons_committed']}")
    tl_count = ingest_result['townland_count']
    tl_list = ', '.join(ingest_result['townlands'])
    print(f"  Townlands ({tl_count}):            {tl_list}")
    print(f"  RecordedRelationships:     {rr_totals['created']}")
    print(f"    (skipped - null role):   {rr_totals['skipped_null']}")
    print(f"    (skipped - no rule):     {rr_totals['skipped_no_rule']}")

    # Place resolution stats
    pr = place_result.place_resolution
    print(f"\n  PLACE RESOLUTION")
    print(f"    Records linked:          {pr.records_linked}")
    print(f"    Already linked:          {pr.records_already_linked}")
    print(f"    Unresolved places:       {len(pr.unresolved)}")
    print(f"    Blank place strings:     {pr.skipped_blank}")

    print_record_similarity_report(record_similarity_result)
    print_person_similarity_report(person_similarity_result)

    notes = ingest_result["parse_notes"]
    if notes:
        print(f"\n  Parse notes ({len(notes)}):")
        for n in notes:
            print(f"    [{n['image_group']}] {n.get('name', '')}: {n['note']}")
    else:
        print("\n  No parse notes — clean ingest.")

    conn.close()


def _cmd_ingest(args: argparse.Namespace) -> None:
    from src.ingest.census import ingest_census
    conn = open_db()
    source_id = int(args.source)

    if source_id not in CENSUS_SOURCE_IDS:
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

    conn.close()


def _cmd_seed_places(args: argparse.Namespace) -> None:
    from src.db.seed_places import seed_places, print_seed_places_report
    conn = open_db()
    check_version(conn)
    result = seed_places(conn, args.file)
    print_seed_places_report(result)
    conn.close()
    if not result["ok"]:
        sys.exit(1)


def _cmd_fetch_places(args: argparse.Namespace) -> None:
    from src.db.fetch_places import fetch_places, write_to_db, write_to_csv, load_from_csv
    import os
    import sys

    if not args.csv:
        # Default: write to DB directly
        args.csv = None

    if not args.from_csv and args.logainm_id is None:
        print("Error: --logainm-id is required when not using --from-csv.", file=sys.stderr)
        sys.exit(1)

    # Load rows
    if args.from_csv:
        print(f"Loading from CSV: {args.from_csv}")
        rows = load_from_csv(args.from_csv)
        print(f"  Loaded {len(rows)} rows.")
        errors = []
    else:
        api_key = args.api_key or os.environ.get("LOGAINM_API_KEY")
        if not api_key:
            print("Error: No API key provided. Use --api-key or set LOGAINM_API_KEY environment variable.", file=sys.stderr)
            sys.exit(1)

        print(f"Fetching logainm ID {args.logainm_id}...")
        result = fetch_places(args.logainm_id, api_key, args.rate_delay)
        rows = result.rows
        errors = result.errors
        print(f"  Fetched {len(rows)} rows ({len(errors)} errors).")
        if errors:
            for e in errors:
                print(f"  WARNING: {e}")

    # Write CSV if requested
    if args.csv:
        write_to_csv(rows, args.csv)
        print(f"  CSV written to: {args.csv}")

    # Write to DB (always for this CLI flow)
    conn = open_db()
    check_version(conn)
    inserted, skipped = write_to_db(conn, rows)
    print(f"  DB: {inserted} inserted, {skipped} skipped (already present).")
    conn.close()


def _cmd_summary(args: argparse.Namespace) -> None:
    conn = open_db()
    print_summary(conn)
    conn.close()


def _cmd_place_resolve(args: argparse.Namespace) -> None:
    from src.pipeline.pipeline import run_place_resolve
    from src.pipeline.place_resolution import print_place_resolution_report
    conn = open_db()
    check_version(conn)
    print("\nRunning place resolution across all sources...")
    result = run_place_resolve(conn)
    print_place_resolution_report(result.place_resolution)
    conn.close()


def _cmd_household(args: argparse.Namespace) -> None:
    from src.pipeline.pipeline import run_household
    from src.pipeline.household_inference import print_household_inference_report
    conn = open_db()
    check_version(conn)
    print("\nRunning household inference across all sources...")
    result = run_household(conn)
    print_household_inference_report(result.household)
    conn.close()


def _cmd_link(args: argparse.Namespace) -> None:
    from src.pipeline.pipeline import run_link
    from src.pipeline.linkage import (
        print_household_linkage_report,
        print_census_linkage_report,
    )
    conn = open_db()
    check_version(conn)

    force     = getattr(args, "force", False)
    debug     = getattr(args, "debug", False)
    debug_dir = _make_debug_dir() if debug else None

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

    conn.close()


def _cmd_score_evidence(args: argparse.Namespace) -> None:
    from src.pipeline.pipeline import run_rebuild_consensus
    from src.pipeline.scoring import print_rebuild_consensus_report
    conn = open_db()
    check_version(conn)

    debug     = getattr(args, "debug", False)
    debug_dir = _make_debug_dir() if debug else None

    if debug_dir:
        print(f"\nDebug mode active — logs will be written to: {debug_dir}/")

    print("\nRebuilding event consensus (post-linkage)...")
    result = run_rebuild_consensus(conn, debug_dir=debug_dir)
    print_rebuild_consensus_report(result.consensus)

    if debug_dir:
        print(f"\nDebug logs: {debug_dir}/")
        for log in sorted(debug_dir.glob("*.log")):
            print(f"  {log.name}")

    conn.close()


def _cmd_reconstruct(args: argparse.Namespace) -> None:
    from src.pipeline.pipeline import run_reconstruct
    from src.pipeline.place_resolution import print_place_resolution_report
    from src.pipeline.household_inference import print_household_inference_report
    from src.pipeline.linkage import (
        print_household_linkage_report,
        print_census_linkage_report,
    )
    from src.pipeline.scoring import print_rebuild_consensus_report

    conn = open_db()
    check_version(conn)

    force     = getattr(args, "force", False)
    debug     = getattr(args, "debug", False)
    debug_dir = _make_debug_dir() if debug else None

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

    conn.close()


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
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Initialise a new Supabase database (schema + seed data)")

    sub.add_parser(
        "clear-evidence",
        help="Wipe evidence + conclusions, preserving place_authority",
    )

    sub.add_parser(
        "clear-conclusions",
        help="Wipe conclusion layer only (person, relationship, event); evidence preserved",
    )

    p_add_evidence = sub.add_parser(
        "add-evidence",
        help="Add evidence: ingest CSV + assign role-pair RecordedRelationships (replaces ingest)",
    )
    p_add_evidence.add_argument("--source", required=True, help="Source ID (3=1901, 4=1911, 5=1926)")
    p_add_evidence.add_argument("--file", required=True, help="Path to the CSV file")

    p_ingest = sub.add_parser("ingest", help="Ingest a source CSV into the evidence layer (legacy; prefer add-evidence)")
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
        "init":               _cmd_init,
        "clear-evidence":     _cmd_clear_evidence,
        "clear-conclusions":  _cmd_clear_conclusions,
        "add-evidence":       _cmd_add_evidence,
        "ingest":             _cmd_ingest,
        "seed-places":        _cmd_seed_places,
        "fetch-places":       _cmd_fetch_places,
        "summary":            _cmd_summary,
        "place-resolve":      _cmd_place_resolve,
        "household":          _cmd_household,
        "link":               _cmd_link,
        "score-evidence":     _cmd_score_evidence,
        "reconstruct":        _cmd_reconstruct,
        "validate":           _cmd_validate,
    }

    args = parser.parse_args()
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
