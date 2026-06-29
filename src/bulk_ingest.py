"""
Bulk ingest and add evidence for all CSV files in the /data folder.

Usage:
    python -m src.bulk_ingest

Processes each CSV file found in data/ directory:
  1. Ingest the CSV into the record layer
  2. Assign role relationships
  3. Run place resolution
  4. Run record similarity (household-level, cross-census)
  5. Run person similarity (person-level, cross-census)

Runs all 5 evidence pipeline steps across all ingested censuses.
"""

from __future__ import annotations

import sys
from pathlib import Path

from src.db.db import open_db, check_version
from src.constants import CENSUS_SOURCE_IDS
from src.evidence.census import ingest_census
from src.evidence.role_relationships import assign_role_relationships
from src.evidence.place_resolution import run_place_resolution
from src.evidence.similarity import (
    run_record_similarity,
    run_person_similarity,
)
from src.metrics import Timer, PipelineRun, log_run


def bulk_ingest_and_add_evidence() -> None:
    """Process all CSV files in /data folder through full evidence pipeline."""
    repo = open_db()
    check_version(repo)

    # Collect all CSV files
    data_dir = Path(__file__).parent.parent / "data"
    csv_files = sorted(data_dir.glob("*.csv"))

    if not csv_files:
        print(f"No CSV files found in {data_dir}")
        return

    print(f"\nFound {len(csv_files)} CSV files to ingest")
    print("=" * 80)

    # --- STEP 1-3: Ingest each CSV + assign relationships + place resolution ---
    total_records = 0
    total_relationships = 0

    for csv_file in csv_files:
        filename = csv_file.name
        print(f"\n[CSV] {filename}")

        # Infer source_id from filename (e.g., "Donegal_1901.csv" → 3)
        if "_1901" in filename:
            source_id = 3
        elif "_1911" in filename:
            source_id = 4
        elif "_1926" in filename:
            source_id = 5
        else:
            print(f"  ✗ Could not infer census year from filename (expected *_1901, *_1911, or *_1926)")
            continue

        if source_id not in CENSUS_SOURCE_IDS:
            print(f"  ✗ Unknown source_id {source_id}")
            continue

        # [1/5] Ingest CSV
        print(f"  [1/5] Ingesting (source {source_id})...")
        try:
            with Timer('ingest', 'ingest_census', source_id=source_id) as timer:
                ingest_result = ingest_census(repo, str(csv_file), source_id=source_id)
            log_run(repo, PipelineRun(
                stage='ingest',
                step_name='ingest_census',
                records_processed=ingest_result['records_committed'],
                duration_ms=timer.duration_ms,
                source_id=source_id,
            ))
            records_committed = ingest_result['records_committed']
            total_records += records_committed
            print(f"    ✓ {records_committed} households ingested ({timer.duration_ms/1000:.2f}s)")
        except Exception as e:
            print(f"    ✗ Ingest failed: {e}")
            repo.rollback()
            continue

        # [2/5] Assign role relationships for this source
        print(f"  [2/5] Assigning role relationships...")
        try:
            with Timer('evidence', 'assign_role_relationships', source_id=source_id) as timer:
                rr_totals = {"created": 0, "skipped_null": 0, "skipped_no_rule": 0}
                record_ids = repo.fetch_all(
                    "SELECT record_id FROM record WHERE source_id = %s "
                    "ORDER BY record_id DESC LIMIT %s",
                    (source_id, records_committed),
                )

                for rid_row in record_ids:
                    rr = assign_role_relationships(repo, rid_row["record_id"])
                    rr_totals["created"] += rr.relationships_created
                    rr_totals["skipped_null"] += rr.skipped_null_role_pairs
                    rr_totals["skipped_no_rule"] += rr.skipped_no_rule

            log_run(repo, PipelineRun(
                stage='ingest',
                step_name='assign_role_relationships',
                records_processed=len(record_ids),
                duration_ms=timer.duration_ms,
                source_id=source_id,
            ))
            total_relationships += rr_totals['created']
            print(f"    ✓ {rr_totals['created']} relationships created ({timer.duration_ms/1000:.2f}s)")
        except Exception as e:
            print(f"    ✗ Role relationships failed: {e}")
            repo.rollback()

        # [3/5] Place resolution (run once globally after each ingest, but it's cumulative)
        print(f"  [3/5] Running place resolution...")
        try:
            with Timer('evidence', 'run_place_resolution', source_id=source_id) as timer:
                place_result = run_place_resolution(repo)
            log_run(repo, PipelineRun(
                stage='place',
                step_name='run_place_resolution',
                records_processed=place_result.records_linked,
                duration_ms=timer.duration_ms,
                source_id=source_id,
            ))
            print(f"    ✓ {place_result.records_linked} records linked ({timer.duration_ms/1000:.2f}s)")
        except Exception as e:
            print(f"    ✗ Place resolution failed: {e}")
            repo.rollback()

    # --- STEP 4-5: Similarity analysis (cross-census, run once after all ingests) ---
    print()
    print("=" * 80)
    print("\nFinal cross-census steps:")

    print("\n[4/5] Running record similarity (Splink household-level, cross-census)...")
    try:
        with Timer('similarity', 'run_record_similarity') as timer:
            record_similarity_result = run_record_similarity(repo)
        log_run(repo, PipelineRun(
            stage='similarity',
            step_name='run_record_similarity',
            records_processed=None,
            duration_ms=timer.duration_ms,
        ))
        print(f"  ✓ Record similarity complete ({timer.duration_ms/1000:.2f}s)")
    except Exception as e:
        print(f"  ✗ Record similarity failed: {e}")
        repo.rollback()

    print("\n[5/5] Running person similarity (Splink person-level, cross-census)...")
    try:
        with Timer('similarity', 'run_person_similarity') as timer:
            person_similarity_result = run_person_similarity(repo)
        log_run(repo, PipelineRun(
            stage='similarity',
            step_name='run_person_similarity',
            records_processed=None,
            duration_ms=timer.duration_ms,
        ))
        print(f"  ✓ Person similarity complete ({timer.duration_ms/1000:.2f}s)")
    except Exception as e:
        print(f"  ✗ Person similarity failed: {e}")
        repo.rollback()

    # --- Summary ---
    print()
    print("=" * 80)
    print(f"\n✓ Bulk ingest and evidence pipeline complete")
    print(f"  {total_records} total records ingested")
    print(f"  {total_relationships} total relationships created")


if __name__ == "__main__":
    bulk_ingest_and_add_evidence()
