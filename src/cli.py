"""
GRA — Genealogy Research Assistant
Command-line interface: sole entry point for all operations.

Usage:
    python -m src.cli <command> [options]

Commands:
    init                Initialise a new Supabase database (schema + seed data)
    clear-evidence      Wipe evidence + conclusions, preserving place_authority
    clear-conclusions   Wipe conclusion layer only (person, relationship, event)
    add-evidence        Run full evidence pipeline (5 steps): ingest CSV + role
                        relationships + place resolution + record similarity +
                        person similarity
    ingest              Ingest a census CSV into the evidence layer
                        (legacy; prefer add-evidence)
    seed-places         Seed place_authority from a logainm CSV
    fetch-places        Fetch place authority from logainm.ie API
    summary             Print knowledge base summary
    conclude            Run conclusion pipeline (3 steps): person resolution +
                        relationship resolution + event resolution
    review              Run the research review — produce a prioritised findings
                        report (JSON + Markdown) in the reports/ directory
    export-validation   Export validation dataset for manual linkage review.
                        Creates a CSV with all persons across all censuses,
                        marked with linkage status for researcher validation.
    validate-linkages   Validate all linkages for age progression, name variants,
                        and household coherence errors. Flags problematic linkages.

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
from src.export_validation_dataset import export_validation_dataset
from src.validation import validate_all_linkages, remove_flagged_linkages


# ---------------------------------------------------------------------------
# Summary display helper
# ---------------------------------------------------------------------------


def _q(conn: psycopg2.extensions.connection, sql: str, params: tuple = ()) -> int:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return list(row.values())[0]


def print_summary(conn: psycopg2.extensions.connection) -> None:
    """Print a knowledge base summary to stdout.

    Optimized for fast metrics checking. Uses simple COUNTs instead of
    complex JOINs. Includes census linkage breakdown by pair.
    """
    check_version(conn)

    print()
    print("=" * 80)
    print("  GRA — Knowledge Base Summary")
    print("=" * 80)

    print("\n  FOUNDATIONAL LAYER")
    print(f"    Repositories:              {_q(conn, 'SELECT COUNT(*) FROM repository'):>6}")
    print(f"    Sources:                   {_q(conn, 'SELECT COUNT(*) FROM source'):>6}")

    pa_total = _q(conn, "SELECT COUNT(*) FROM place_authority")
    print(f"    Place authorities:         {pa_total:>6}")

    print("\n  EVIDENCE LAYER")
    records = _q(conn, "SELECT COUNT(*) FROM record")
    recorded_persons = _q(conn, "SELECT COUNT(*) FROM recorded_person")
    print(f"    Records:                   {records:>6}")
    print(f"    Recorded Persons:          {recorded_persons:>6}")
    print(f"    Recorded Relationships:    {_q(conn, 'SELECT COUNT(*) FROM recorded_relationship'):>6}")
    print(f"    Record Similarities:       {_q(conn, 'SELECT COUNT(*) FROM record_similarity'):>6}")

    print("\n  CENSUS COMPOSITION (3,167 total persons)")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.source_id, s.title,
                   COUNT(DISTINCT rp.recorded_person_id) AS count
            FROM source s
            LEFT JOIN record r ON r.source_id = s.source_id
            LEFT JOIN recorded_person rp ON rp.record_id = r.record_id
            WHERE s.source_id IN (3, 4, 5)
            GROUP BY s.source_id, s.title
            ORDER BY s.source_id
        """)
        census_counts = cur.fetchall()
        for row in census_counts:
            pct = 100.0 * row['count'] / 3167 if row['count'] else 0
            print(f"    {row['title']:<20} {row['count']:>5} persons  ({pct:>5.1f}%)")

    print("\n  CONCLUSION LAYER")
    persons = _q(conn, "SELECT COUNT(*) FROM person")
    relationships = _q(conn, "SELECT COUNT(*) FROM relationship")
    events = _q(conn, "SELECT COUNT(*) FROM event")

    print(f"    Persons (clustered):       {persons:>6}")
    print(f"    Relationships:             {relationships:>6}")
    print(f"    Events:                    {events:>6}")

    print("\n  LINKAGE METRICS")

    # Total linkage: recorded persons with person links
    linked_rp = _q(conn, "SELECT COUNT(DISTINCT recorded_person_id) FROM person_recorded_person")
    linkage_pct = 100.0 * linked_rp / recorded_persons if recorded_persons > 0 else 0

    print(f"    Recorded persons linked:   {linked_rp:>6} / {recorded_persons:<6}  ({linkage_pct:>5.1f}%)")

    # Census link breakdown: how many persons appear in multiple censuses
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                COUNT(CASE WHEN census_count = 1 THEN 1 END) as single_census,
                COUNT(CASE WHEN census_count = 2 THEN 1 END) as two_census,
                COUNT(CASE WHEN census_count = 3 THEN 1 END) as three_census
            FROM (
                SELECT person_id, COUNT(DISTINCT s.source_id) as census_count
                FROM person_recorded_person prp
                JOIN recorded_person rp ON rp.recorded_person_id = prp.recorded_person_id
                JOIN record r ON r.record_id = rp.record_id
                JOIN source s ON s.source_id = r.source_id
                WHERE s.source_id IN (3, 4, 5)
                GROUP BY person_id
            ) census_coverage
        """)
        row = cur.fetchone()

    if persons > 0:
        print(f"    Persons in 1 census:       {row['single_census']:>6}  ({100.0*row['single_census']/persons:>5.1f}%)")
        print(f"    Persons in 2 censuses:     {row['two_census']:>6}  ({100.0*row['two_census']/persons:>5.1f}%)")
        print(f"    Persons in 3 censuses:     {row['three_census']:>6}  ({100.0*row['three_census']/persons:>5.1f}%)")

    # Pairwise census links — count persons with recorded_persons from each pair
    print(f"\n  PAIRWISE CENSUS LINKAGE")
    with conn.cursor() as cur:
        # For each person, check if they have recordings from both censuses in the pair
        cur.execute("""
            WITH person_by_source AS (
                SELECT DISTINCT prp.person_id, s.source_id
                FROM person_recorded_person prp
                JOIN recorded_person rp ON rp.recorded_person_id = prp.recorded_person_id
                JOIN record r ON r.record_id = rp.record_id
                JOIN source s ON s.source_id = r.source_id
                WHERE s.source_id IN (3, 4, 5)
            )
            SELECT
                COUNT(DISTINCT CASE WHEN p1.person_id IS NOT NULL AND p2.person_id IS NOT NULL
                    THEN p1.person_id END) as link_1901_1911,
                COUNT(DISTINCT CASE WHEN p1.person_id IS NOT NULL AND p3.person_id IS NOT NULL
                    THEN p1.person_id END) as link_1901_1926,
                COUNT(DISTINCT CASE WHEN p2.person_id IS NOT NULL AND p3.person_id IS NOT NULL
                    THEN p2.person_id END) as link_1911_1926
            FROM (SELECT DISTINCT person_id FROM person_by_source) all_persons
            LEFT JOIN person_by_source p1 ON p1.person_id = all_persons.person_id AND p1.source_id = 3
            LEFT JOIN person_by_source p2 ON p2.person_id = all_persons.person_id AND p2.source_id = 4
            LEFT JOIN person_by_source p3 ON p3.person_id = all_persons.person_id AND p3.source_id = 5
        """)
        row = cur.fetchone()

    if row:
        if row['link_1901_1911']:
            print(f"    1901 ↔ 1911:               {row['link_1901_1911']:>6} persons linked")
        if row['link_1901_1926']:
            print(f"    1901 ↔ 1926:               {row['link_1901_1926']:>6} persons linked")
        if row['link_1911_1926']:
            print(f"    1911 ↔ 1926:               {row['link_1911_1926']:>6} persons linked")

    print()
    print("=" * 80)
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
    and place_authority are preserved. Allows re-running conclude without
    re-ingesting.
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

    print("\nReady to re-run conclude.\n")
    conn.close()


def _cmd_add_evidence(args: argparse.Namespace) -> None:
    """
    Add evidence from a census CSV: full 5-step evidence pipeline.

    Steps:
      [1/5] Ingest CSV → record + recorded_person rows
      [2/5] Assign RecordedRelationship rows from household role pairs
      [3/5] Place resolution — link records to place_authority
      [4/5] Splink record similarity (household-level, cross-census)
      [5/5] Splink person similarity (person-level, cross-census)
    """
    from src.evidence.census import ingest_census
    from src.evidence.role_relationships import assign_role_relationships
    from src.evidence.place_resolution import run_place_resolution, PlaceResolutionResult
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
    place_result = run_place_resolution(conn)

    print("\n[4/5] Running record similarity (Splink household-level, cross-census)...")
    record_similarity_result = run_record_similarity(conn)

    print("\n[5/5] Running person similarity (Splink person-level, cross-census)...")
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

    pr = place_result
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
    """Legacy single-step ingest. Prefer add-evidence."""
    from src.evidence.census import ingest_census
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

    if not args.from_csv and args.logainm_id is None:
        print("Error: --logainm-id is required when not using --from-csv.", file=sys.stderr)
        sys.exit(1)

    if args.from_csv:
        print(f"Loading from CSV: {args.from_csv}")
        rows = load_from_csv(args.from_csv)
        print(f"  Loaded {len(rows)} rows.")
        errors = []
    else:
        api_key = args.api_key or os.environ.get("LOGAINM_API_KEY")
        if not api_key:
            print("Error: No API key provided. Use --api-key or set LOGAINM_API_KEY.", file=sys.stderr)
            sys.exit(1)

        print(f"Fetching logainm ID {args.logainm_id}...")
        result = fetch_places(args.logainm_id, api_key, args.rate_delay)
        rows = result.rows
        errors = result.errors
        print(f"  Fetched {len(rows)} rows ({len(errors)} errors).")
        if errors:
            for e in errors:
                print(f"  WARNING: {e}")

    if args.csv:
        write_to_csv(rows, args.csv)
        print(f"  CSV written to: {args.csv}")

    conn = open_db()
    check_version(conn)
    inserted, skipped = write_to_db(conn, rows)
    print(f"  DB: {inserted} inserted, {skipped} skipped (already present).")
    conn.close()


def _cmd_fetch_census(args: argparse.Namespace) -> None:
    from src.db.fetch_census import fetch_census, print_fetch_census_report, _logainm_id_exists
    from src.db.fetch_places import fetch_places, write_to_db as write_places_to_db
    from src.evidence.census import ingest_census
    from src.evidence.role_relationships import assign_role_relationships
    from src.evidence.place_resolution import run_place_resolution
    from src.evidence.similarity import (
        run_record_similarity,
        print_record_similarity_report,
        run_person_similarity,
        print_person_similarity_report,
    )
    import os

    # Get API key
    api_key = args.api_key or os.environ.get("LOGAINM_API_KEY")
    if not api_key:
        print("Error: No API key provided. Use --api-key or set LOGAINM_API_KEY.", file=sys.stderr)
        sys.exit(1)

    conn = open_db()
    check_version(conn)

    # Step 1: Seed place authority via fetch-places (skip if already exists)
    if _logainm_id_exists(conn, args.logainm_id):
        print(f"Step 1/2: logainm ID {args.logainm_id} already in place_authority. Skipping fetch-places.")
    else:
        print(f"Step 1/2: Seeding place_authority with logainm ID {args.logainm_id}...")
        try:
            rate_delay = getattr(args, 'rate_delay', 0.05)  # Default to 0.05s if not provided
            result = fetch_places(args.logainm_id, api_key, rate_delay)
            rows = result.rows
            print(f"  Fetched {len(rows)} place rows.")
            inserted, skipped = write_places_to_db(conn, rows)
            print(f"  DB: {inserted} inserted, {skipped} skipped.")
        except Exception as e:
            print(f"Error seeding places: {e}", file=sys.stderr)
            conn.close()
            sys.exit(1)

    # Step 2: Fetch and save census files
    print(f"\nStep 2/2: Downloading census files...")
    years = args.year if args.year else [1901, 1911, 1926]
    census_result = fetch_census(conn, args.logainm_id, years=years)
    print_fetch_census_report(census_result)

    if census_result.errors:
        conn.close()
        sys.exit(1)

    # Optional Step 3: Run add-evidence pipeline on downloaded files
    if args.add_evidence:
        from pathlib import Path
        data_dir = Path(__file__).parent.parent / "data"

        print(f"\nRunning add-evidence pipeline on downloaded census files...")

        # Check for existing records before ingesting
        source_ids_to_process = []
        for source_id, year in [(3, 1901), (4, 1911), (5, 1926)]:
            if year not in census_result.records_per_year:
                continue

            csv_file = data_dir / f"{census_result.ded_name}_{year}.csv"
            if not csv_file.exists():
                print(f"  Skipping {year}: CSV not found at {csv_file}")
                continue

            # Check if records for this source already exist
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) as count FROM record WHERE source_id = %s", (source_id,))
                existing_count = cur.fetchone()["count"]

            if existing_count > 0:
                print(f"\nWARNING: {existing_count} records already exist for source {source_id} ({year} census).")
                print(f"  Halting add-evidence pipeline to prevent duplicate ingestion.")
                print(f"  Run `clear-evidence` first if you want to re-ingest.")
                conn.close()
                sys.exit(1)

            source_ids_to_process.append((source_id, year, csv_file))

        for source_id, year, csv_file in source_ids_to_process:
            print(f"\n[Evidence {year}/3] Running evidence pipeline for {year} census...")

            # [1/3] Ingest CSV
            print(f"  [1/3] Ingesting CSV (source {source_id})...")
            ingest_result = ingest_census(conn, str(csv_file), source_id=source_id)
            print(f"    Households: {ingest_result['records_committed']}, Persons: {ingest_result['persons_committed']}")

            # [2/3] Assign role-pair RecordedRelationships
            print(f"  [2/3] Assigning role-pair RecordedRelationships...")
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
            print(f"    Relationships: {rr_totals['created']}")

            # [3/3] Place resolution
            print(f"  [3/3] Running place resolution...")
            place_result = run_place_resolution(conn)
            print(f"    Records linked: {place_result.records_linked}, Unresolved: {len(place_result.unresolved)}")

        # Run cross-census similarity (once after all years ingested)
        print(f"\nRunning cross-census similarity analysis...")
        print(f"  [4/5] Record similarity (Splink)...")
        record_similarity_result = run_record_similarity(conn)

        print(f"  [5/5] Person similarity (Splink)...")
        person_similarity_result = run_person_similarity(conn)

        print_record_similarity_report(record_similarity_result)
        print_person_similarity_report(person_similarity_result)

        print(f"\nadd-evidence pipeline complete")

    conn.close()


def _cmd_summary(args: argparse.Namespace) -> None:
    conn = open_db()
    print_summary(conn)
    conn.close()


def _cmd_conclude(args: argparse.Namespace) -> None:
    """
    Run the conclusion pipeline (4 steps) against all evidence.

    Steps:
      [1/4] Person resolution      — cluster RecordedPersons into Person conclusions
      [2/4] Relationship resolution — create Relationships from household structure
      [3/4] Event resolution        — create census, birth, and marriage Events
      [4/4] Validation cleanup      — remove linkages failing validation checks
    """
    from src.conclusion.person_resolution import (
        run_person_resolution,
        print_person_resolution_report,
    )
    from src.conclusion.relationship_resolution import (
        run_relationship_resolution,
        print_relationship_resolution_report,
    )
    from src.conclusion.event_resolution import (
        run_event_resolution,
        print_event_resolution_report,
    )
    from src.conclusion.validation_cleanup import (
        run_validation_cleanup,
        print_validation_cleanup_report,
    )

    conn = open_db()
    check_version(conn)

    print("\nRunning conclusion pipeline...")

    print("\n[1/4] Person resolution...")
    person_result = run_person_resolution(conn)
    print_person_resolution_report(person_result)

    print("\n[2/4] Relationship resolution...")
    rel_result = run_relationship_resolution(conn)
    print_relationship_resolution_report(rel_result)

    if rel_result.merge_candidates:
        print(f"\n  NOTE: {len(rel_result.merge_candidates)} merge candidate(s) detected.")
        print("  Review and resolve manually before re-running.")

    print("\n[3/4] Event resolution...")
    event_result = run_event_resolution(conn)
    print_event_resolution_report(event_result)

    print("\n[4/4] Validation cleanup...")
    cleanup_result = run_validation_cleanup(conn)
    print_validation_cleanup_report(cleanup_result)

    print("Conclusion pipeline complete. Running summary...\n")
    print_summary(conn)

    conn.close()


def _cmd_review(args: argparse.Namespace) -> None:
    from src.review.runner import run_and_print
    conn = open_db()
    check_version(conn)
    run_and_print(conn)
    conn.close()


def _cmd_export_validation(args: argparse.Namespace) -> None:
    export_validation_dataset(args.output)


def _cmd_validate_linkages(args: argparse.Namespace) -> None:
    conn = open_db()
    check_version(conn)
    try:
        report = validate_all_linkages(conn)

        print()
        print("=" * 80)
        print("  LINKAGE VALIDATION REPORT")
        print("=" * 80)
        print(f"\n  Total linkages checked: {report.total_linkages_checked:,}")
        print(f"  Total violations found: {report.total_violations} ({report.violation_rate:.1f}%)")
        print(f"\n  Violations by type:")
        print(f"    Age progression errors: {report.age_violations}")
        print(f"    Name mismatch errors:   {report.name_mismatches}")
        print(f"    Household coherence:    {report.household_errors}")

        if report.flagged_pairs:
            print(f"\n  Flagged pairs (details saved to validation_flags.csv if requested):")
            for i, pair in enumerate(report.flagged_pairs[:10], 1):
                print(f"    {i}. Person {pair['person_id']}: {pair['violations']}")
            if len(report.flagged_pairs) > 10:
                print(f"    ... and {len(report.flagged_pairs) - 10} more")

        # Optionally save to CSV
        if args.save_csv:
            import csv
            with open(args.save_csv, 'w', newline='', encoding='utf-8') as f:
                if report.flagged_pairs:
                    writer = csv.DictWriter(f, fieldnames=report.flagged_pairs[0].keys())
                    writer.writeheader()
                    writer.writerows(report.flagged_pairs)
            print(f"\n  Flagged pairs saved to: {args.save_csv}")

        # Optionally remove flagged linkages
        if args.remove:
            if args.dry_run:
                count, msg = remove_flagged_linkages(conn, report, dry_run=True)
                print(f"\n  DRY RUN: {msg}")
            else:
                count, msg = remove_flagged_linkages(conn, report, dry_run=False)
                print(f"\n  {msg}")
                print(f"  Remaining linkages: {report.total_linkages_checked - count}")

        print("\n" + "=" * 80)
    finally:
        conn.close()


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
        help="Wipe conclusion layer only; evidence and place_authority preserved",
    )

    p_add_evidence = sub.add_parser(
        "add-evidence",
        help="Evidence pipeline [1/5–5/5]: ingest CSV + relationships + place + similarity",
    )
    p_add_evidence.add_argument("--source", required=True, help="Source ID (3=1901, 4=1911, 5=1926)")
    p_add_evidence.add_argument("--file", required=True, help="Path to the CSV file")

    p_ingest = sub.add_parser(
        "ingest",
        help="Ingest a census CSV (legacy; prefer add-evidence)",
    )
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

    p_fetch_census = sub.add_parser("fetch-census", help="Download census CSVs from National Archives API")
    p_fetch_census.add_argument("--logainm-id", type=int, required=True, help="DED logainm ID")
    p_fetch_census.add_argument("--api-key", default=None, help="Logainm API key (or use LOGAINM_API_KEY env var)")
    p_fetch_census.add_argument("--year", type=int, nargs="+", default=None, help="Census years to download (default: 1901 1911 1926)")
    p_fetch_census.add_argument("--add-evidence", action="store_true", help="After download, run the 3-step evidence pipeline (ingest, relationships, place resolution)")

    sub.add_parser("summary", help="Print knowledge base summary")

    sub.add_parser(
        "conclude",
        help="Conclusion pipeline [1/3–3/3]: person + relationship + event resolution",
    )

    sub.add_parser(
        "review",
        help="Run research review — produces prioritised findings report (reports/ dir)",
    )

    p_export = sub.add_parser(
        "export-validation",
        help="Export validation dataset for manual linkage review by researchers",
    )
    p_export.add_argument(
        "-o", "--output",
        default="validation_dataset.csv",
        help="Output CSV file path (default: validation_dataset.csv)"
    )

    p_validate = sub.add_parser(
        "validate-linkages",
        help="Validate all linkages for age/name/household errors",
    )
    p_validate.add_argument(
        "--save-csv",
        help="Save flagged pairs to CSV file for review"
    )
    p_validate.add_argument(
        "--remove",
        action="store_true",
        help="Remove flagged linkages from database"
    )
    p_validate.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be removed without actually deleting"
    )

    dispatch = {
        "init":              _cmd_init,
        "clear-evidence":    _cmd_clear_evidence,
        "clear-conclusions": _cmd_clear_conclusions,
        "add-evidence":      _cmd_add_evidence,
        "ingest":            _cmd_ingest,
        "seed-places":       _cmd_seed_places,
        "fetch-places":      _cmd_fetch_places,
        "fetch-census":      _cmd_fetch_census,
        "summary":           _cmd_summary,
        "conclude":          _cmd_conclude,
        "review":            _cmd_review,
        "export-validation": _cmd_export_validation,
        "validate-linkages": _cmd_validate_linkages,
    }

    args = parser.parse_args()
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
