"""
GRA — Tullynaught Pipeline Benchmark
tests/benchmark_tullynaught.py

Standalone script (not a pytest test) that runs the full pipeline against the
Tullynaught fixtures, captures linkage quality, data quality, and performance
metrics, and writes a structured JSON file to tests/benchmarks/.

Used to produce before/after comparisons when changing pipeline steps.

Usage:
    python tests/benchmark_tullynaught.py
    python tests/benchmark_tullynaught.py --label post-continuity-linking
    python tests/benchmark_tullynaught.py --no-setup   # skip pipeline, just capture metrics
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")

from src.db.db import open_db, check_version
from src.constants import SOURCE_ID_1901, SOURCE_ID_1911, SOURCE_ID_1926

FIXTURES = {
    SOURCE_ID_1901: REPO_ROOT / "tests" / "tullynaught_1901.csv",
    SOURCE_ID_1911: REPO_ROOT / "tests" / "tullynaught_1911.csv",
    SOURCE_ID_1926: REPO_ROOT / "tests" / "tullynaught_1926.csv",
}

EXACT_PERSONS_TOTAL = 3167
BENCHMARKS_DIR = REPO_ROOT / "tests" / "benchmarks"


# ---------------------------------------------------------------------------
# Pipeline setup (mirrors _setup_data in test_pipeline.py)
# ---------------------------------------------------------------------------

def _run_pipeline(repo) -> dict[str, int]:
    """
    Clear the DB, ingest all three Tullynaught fixtures, run the full pipeline.
    Returns step timing in milliseconds keyed by step name.
    """
    from src.evidence.census import ingest_census
    from src.evidence.role_relationships import assign_role_relationships
    from src.evidence.place_resolution import run_place_resolution
    from src.evidence.similarity import run_record_similarity, run_person_similarity
    from src.conclusion.person_resolution import run_person_resolution
    from src.conclusion.relationship_resolution import run_relationship_resolution
    from src.conclusion.household_resolution import run_household_resolution
    from src.conclusion.event_resolution import run_event_resolution

    clear_tables = [
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
        "conclusion_log",
    ]
    print("Clearing evidence + conclusion layers...")
    with repo:
        for table in clear_tables:
            repo.execute(f"DELETE FROM {table}")

    timing: dict[str, int] = {}

    print("Ingesting sources...")
    for source_id, fixture_path in FIXTURES.items():
        if not fixture_path.exists():
            raise FileNotFoundError(f"Fixture not found: {fixture_path}")
        print(f"  source {source_id} ({fixture_path.name})...", end=" ", flush=True)
        t0 = time.perf_counter()
        ingest_result = ingest_census(repo, str(fixture_path), source_id=source_id)
        rows = repo.fetch_all(
            "SELECT record_id FROM record WHERE source_id = %s ORDER BY record_id DESC LIMIT %s",
            (source_id, ingest_result["records_committed"]),
        )
        record_ids = [r["record_id"] for r in rows]
        with repo:
            for rid in record_ids:
                assign_role_relationships(repo, rid)
        elapsed = time.perf_counter() - t0
        timing[f"ingest_{source_id}"] = int(elapsed * 1000)
        print(f"{ingest_result['records_committed']} records ({elapsed:.2f}s)")

    def _step(label: str, fn):
        print(f"  {label}...", end=" ", flush=True)
        t0 = time.perf_counter()
        fn(repo)
        elapsed = time.perf_counter() - t0
        timing[label] = int(elapsed * 1000)
        print(f"({elapsed:.2f}s)")

    print("Running pipeline steps...")
    _step("place_resolution", run_place_resolution)
    _step("record_similarity", run_record_similarity)
    _step("person_similarity", run_person_similarity)
    _step("person_resolution", run_person_resolution)
    _step("relationship_resolution", run_relationship_resolution)
    _step("household_resolution", run_household_resolution)
    _step("event_resolution", run_event_resolution)

    return timing


# ---------------------------------------------------------------------------
# Metric capture
# ---------------------------------------------------------------------------

def _q(repo, sql: str, params: tuple = ()):
    row = repo.fetch_one(sql, params)
    return list(row.values())[0] if row else 0


def _rows(repo, sql: str, params: tuple = ()) -> list[dict]:
    return repo.fetch_all(sql, params)


def _capture_metrics(repo) -> dict:
    print("Capturing metrics...")

    # --- Linkage quality ---
    total_persons = _q(repo, "SELECT COUNT(*) FROM person")
    linked_rps = _q(repo, "SELECT COUNT(DISTINCT recorded_person_id) FROM person_recorded_person")
    orphan_rps = _q(repo, """
        SELECT COUNT(*) FROM recorded_person rp
        WHERE NOT EXISTS (
            SELECT 1 FROM person_recorded_person prp
            WHERE prp.recorded_person_id = rp.recorded_person_id
        )
    """)

    # Census appearance distribution
    appearance_dist_rows = _rows(repo, """
        SELECT census_count, COUNT(*) as person_count
        FROM (
            SELECT prp.person_id,
                   COUNT(DISTINCT s.source_id) as census_count
            FROM person_recorded_person prp
            JOIN recorded_person rp ON rp.recorded_person_id = prp.recorded_person_id
            JOIN record r ON r.record_id = rp.record_id
            JOIN source s ON s.source_id = r.source_id
            WHERE s.type = 'census'
            GROUP BY prp.person_id
        ) sub
        GROUP BY census_count
        ORDER BY census_count
    """)
    appearance_dist = {str(r["census_count"]): r["person_count"] for r in appearance_dist_rows}
    multi_census_persons = sum(v for k, v in appearance_dist.items() if int(k) >= 2)
    multi_census_pct = round(100.0 * multi_census_persons / total_persons, 1) if total_persons else 0

    # person_recorded_person rows by score version
    score_version_rows = _rows(repo, """
        SELECT score_version, COUNT(*) as cnt
        FROM person_recorded_person
        GROUP BY score_version
        ORDER BY cnt DESC
    """)
    linkages_by_version = {r["score_version"]: r["cnt"] for r in score_version_rows}

    # Relationships by type
    rel_rows = _rows(repo, """
        SELECT type, COUNT(*) as cnt
        FROM relationship
        GROUP BY type
        ORDER BY cnt DESC
    """)
    relationships_by_type = {r["type"]: r["cnt"] for r in rel_rows}
    total_relationships = sum(relationships_by_type.values())

    linkage_pct = round(100.0 * linked_rps / EXACT_PERSONS_TOTAL, 1)

    # Splink candidate pairs (person-level similarity before threshold)
    splink_pairs = _q(repo, "SELECT COUNT(*) FROM recorded_relationship WHERE type = 'similarity'")
    splink_above_threshold = _q(repo, """
        SELECT COUNT(*) FROM recorded_relationship
        WHERE type = 'similarity' AND score >= 0.45
    """)

    # --- Data quality ---
    # parent_age_regression findings — query review report table if it exists,
    # else compute inline from relationships
    age_regression_total = _q(repo, """
        SELECT COUNT(*) FROM relationship rel
        JOIN person_recorded_person prp1 ON prp1.person_id = rel.person_id_1
        JOIN person_recorded_person prp2 ON prp2.person_id = rel.person_id_2
        JOIN recorded_person rp1 ON rp1.recorded_person_id = prp1.recorded_person_id
        JOIN recorded_person rp2 ON rp2.recorded_person_id = prp2.recorded_person_id
        JOIN record r1 ON r1.record_id = rp1.record_id
        JOIN record r2 ON r2.record_id = rp2.record_id
        WHERE rel.type = 'parent_child'
          AND r1.source_id = r2.source_id
          AND rp1.age IS NOT NULL AND rp2.age IS NOT NULL
    """)

    # Age progression anomalies — Persons with 2+ census appearances
    # where recorded age deviates >15 years from expected (first_age + elapsed)
    age_anomaly_rows = _rows(repo, """
        WITH appearances AS (
            SELECT
                prp.person_id,
                CASE s.source_id WHEN 3 THEN 1901 WHEN 4 THEN 1911 WHEN 5 THEN 1926 END as census_year,
                rp.age
            FROM person_recorded_person prp
            JOIN recorded_person rp ON rp.recorded_person_id = prp.recorded_person_id
            JOIN record r ON r.record_id = rp.record_id
            JOIN source s ON s.source_id = r.source_id
            WHERE s.type = 'census' AND rp.age IS NOT NULL
        ),
        min_years AS (
            SELECT person_id, MIN(census_year) as first_year
            FROM appearances
            GROUP BY person_id
        ),
        first_ages AS (
            SELECT a.person_id, a.age as first_age, m.first_year
            FROM appearances a
            JOIN min_years m ON m.person_id = a.person_id AND m.first_year = a.census_year
        ),
        with_expected AS (
            SELECT a.person_id, a.census_year, a.age as recorded_age,
                   fa.first_age + (a.census_year - fa.first_year) as expected_age
            FROM appearances a
            JOIN first_ages fa ON fa.person_id = a.person_id
            WHERE a.census_year > fa.first_year
        )
        SELECT COUNT(DISTINCT person_id) as anomaly_count
        FROM with_expected
        WHERE ABS(recorded_age - expected_age) > 15
    """)
    age_progression_anomalies = age_anomaly_rows[0]["anomaly_count"] if age_anomaly_rows else 0

    return {
        "linkage": {
            "total_persons": total_persons,
            "total_recorded_persons": EXACT_PERSONS_TOTAL,
            "linked_recorded_persons": linked_rps,
            "orphan_recorded_persons": orphan_rps,
            "linkage_pct": linkage_pct,
            "multi_census_persons": multi_census_persons,
            "multi_census_pct": multi_census_pct,
            "census_appearance_distribution": appearance_dist,
            "linkages_by_score_version": linkages_by_version,
            "relationships_by_type": relationships_by_type,
            "total_relationships": total_relationships,
            "splink_pairs_total": splink_pairs,
            "splink_pairs_above_threshold": splink_above_threshold,
        },
        "data_quality": {
            "age_progression_anomaly_persons": age_progression_anomalies,
            "parent_child_relationships_total": age_regression_total,
        },
    }


# ---------------------------------------------------------------------------
# Diff report
# ---------------------------------------------------------------------------

def _diff_benchmarks(before: dict, after: dict) -> None:
    print("\n" + "=" * 70)
    print("BENCHMARK DIFF")
    print("=" * 70)

    def _pct_change(a, b):
        if a == 0:
            return "N/A"
        change = 100.0 * (b - a) / a
        sign = "+" if change >= 0 else ""
        return f"{sign}{change:.1f}%"

    metrics = [
        ("total_persons", "Total Persons"),
        ("linked_recorded_persons", "Linked RecordedPersons"),
        ("orphan_recorded_persons", "Orphan RecordedPersons"),
        ("linkage_pct", "Linkage %"),
        ("multi_census_persons", "Multi-census Persons"),
        ("multi_census_pct", "Multi-census %"),
        ("total_relationships", "Total Relationships"),
        ("splink_pairs_total", "Splink Pairs Total"),
        ("splink_pairs_above_threshold", "Splink Pairs ≥ 0.45"),
    ]

    print(f"\n{'Metric':<35} {'Before':>10} {'After':>10} {'Change':>10}")
    print("-" * 70)
    for key, label in metrics:
        b = before["linkage"].get(key, 0)
        a = after["linkage"].get(key, 0)
        print(f"{label:<35} {str(b):>10} {str(a):>10} {_pct_change(b, a):>10}")

    print(f"\n{'Data Quality':<35} {'Before':>10} {'After':>10} {'Change':>10}")
    print("-" * 70)
    dq_metrics = [
        ("age_progression_anomaly_persons", "Age Progression Anomalies"),
    ]
    for key, label in dq_metrics:
        b = before["data_quality"].get(key, 0)
        a = after["data_quality"].get(key, 0)
        print(f"{label:<35} {str(b):>10} {str(a):>10} {_pct_change(b, a):>10}")

    print(f"\n{'Step Timing (ms)':<35} {'Before':>10} {'After':>10} {'Change':>10}")
    print("-" * 70)
    timing_steps = [
        "person_similarity",
        "person_resolution",
        "relationship_resolution",
        "household_resolution",
        "event_resolution",
    ]
    for step in timing_steps:
        b = before["performance_ms"].get(step, 0)
        a = after["performance_ms"].get(step, 0)
        print(f"{step:<35} {str(b):>10} {str(a):>10} {_pct_change(b, a):>10}")

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Tullynaught pipeline benchmark")
    parser.add_argument("--label", default="pre-continuity-linking",
                        help="Label for this benchmark run (used in output filename)")
    parser.add_argument("--no-setup", action="store_true",
                        help="Skip pipeline setup, just capture metrics from current DB state")
    parser.add_argument("--diff", metavar="BASELINE_FILE",
                        help="Diff current run against a previous baseline JSON file")
    args = parser.parse_args()

    repo = open_db()
    check_version(repo)

    timing: dict[str, int] = {}

    if not args.no_setup:
        timing = _run_pipeline(repo)
    else:
        print("Skipping pipeline setup (--no-setup), capturing metrics from current state.")

    metrics = _capture_metrics(repo)
    repo.close()

    run_at = datetime.now(timezone.utc).isoformat()
    output = {
        "run_at": run_at,
        "label": args.label,
        "linkage": metrics["linkage"],
        "data_quality": metrics["data_quality"],
        "performance_ms": timing,
    }

    BENCHMARKS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = args.label.replace(" ", "_").replace("/", "-")
    outfile = BENCHMARKS_DIR / f"benchmark_{safe_label}_{timestamp}.json"
    outfile.write_text(json.dumps(output, indent=2))
    print(f"\nBenchmark written to: {outfile}")

    # Print summary
    lk = metrics["linkage"]
    print(f"\n{'='*50}")
    print(f"SUMMARY — {args.label}")
    print(f"{'='*50}")
    print(f"  Total Persons:          {lk['total_persons']}")
    print(f"  Linked RecordedPersons: {lk['linked_recorded_persons']} / {EXACT_PERSONS_TOTAL} ({lk['linkage_pct']}%)")
    print(f"  Orphans:                {lk['orphan_recorded_persons']}")
    print(f"  Multi-census Persons:   {lk['multi_census_persons']} ({lk['multi_census_pct']}%)")
    print(f"  Census appearance dist: {lk['census_appearance_distribution']}")
    print(f"  Splink pairs:           {lk['splink_pairs_total']} total, {lk['splink_pairs_above_threshold']} ≥ 0.45")
    print(f"  Total Relationships:    {lk['total_relationships']}")
    print(f"  Age anomaly Persons:    {metrics['data_quality']['age_progression_anomaly_persons']}")
    if timing:
        print(f"\n  Step timing (ms):")
        for step, ms in timing.items():
            print(f"    {step:<35} {ms:>8} ms")

    if args.diff:
        diff_path = Path(args.diff)
        if not diff_path.exists():
            print(f"Diff file not found: {diff_path}")
        else:
            before = json.loads(diff_path.read_text())
            _diff_benchmarks(before, output)

    return outfile


if __name__ == "__main__":
    main()
