"""Performance metrics tracking for the GRA pipeline.

Provides timing instrumentation and persistence for tracking pipeline step
execution time, throughput, and performance trends over time.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from src.db.repository import Repository


@dataclass
class PipelineRun:
    """Metrics for a single pipeline execution step."""

    stage: str  # ingest, place, similarity, person, relationship, event
    step_name: str  # e.g., ingest_census, run_person_resolution
    records_processed: int | None
    duration_ms: int
    source_id: int | None = None  # 3=1901, 4=1911, 5=1926
    notes: str | None = None
    session_ref: str | None = None


class Timer:
    """Context manager for measuring execution time of pipeline steps.

    Usage:
        with Timer('ingest', 'ingest_census', source_id=3) as timer:
            ingest_result = ingest_census(conn, file_path, source_id=3)

        elapsed_ms = timer.duration_ms
    """

    def __init__(self, stage: str, step_name: str, source_id: int | None = None):
        self.stage = stage
        self.step_name = step_name
        self.source_id = source_id
        self.start_time = None
        self.duration_ms = None

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, *args):
        elapsed_s = time.time() - self.start_time
        self.duration_ms = int(elapsed_s * 1000)


def log_run(
    repo: Repository,
    run: PipelineRun,
) -> None:
    """Write pipeline run metrics to the database.

    Args:
        repo: Database repository
        run: PipelineRun with stage, step_name, duration_ms, etc.
    """
    repo.execute(
        """
        INSERT INTO pipeline_run
        (stage, step_name, records_processed, duration_ms, source_id, notes, session_ref)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            run.stage,
            run.step_name,
            run.records_processed,
            run.duration_ms,
            run.source_id,
            run.notes,
            run.session_ref,
        ),
    )


def get_recent_runs(
    repo: Repository,
    stage: str | None = None,
    step_name: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Query recent pipeline runs.

    Args:
        repo: Database repository
        stage: Filter by stage (optional)
        step_name: Filter by step name (optional)
        limit: Maximum rows to return

    Returns:
        List of dicts with run_id, stage, step_name, duration_ms, etc.
    """
    where_clauses = []
    params = []

    if stage:
        where_clauses.append("stage = %s")
        params.append(stage)

    if step_name:
        where_clauses.append("step_name = %s")
        params.append(step_name)

    params.append(limit)

    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    return repo.fetch_all(
        f"""
        SELECT run_id, stage, step_name, records_processed, duration_ms,
               source_id, notes, start_at
        FROM pipeline_run
        {where_sql}
        ORDER BY start_at DESC
        LIMIT %s
        """,
        tuple(params),
    )


def print_timing_report(
    repo: Repository,
    stage: str | None = None,
    limit: int = 50,
) -> None:
    """Print a formatted timing report of recent pipeline runs.

    Args:
        repo: Database repository
        stage: Filter by stage (optional)
        limit: Maximum runs to display
    """
    where_sql = "WHERE stage = %s" if stage else ""
    params = [stage] if stage else []
    params.append(limit)

    runs = repo.fetch_all(
        f"""
        SELECT stage, step_name, COUNT(*) as count,
               ROUND(AVG(duration_ms)::numeric, 0)::int as avg_ms,
               MIN(duration_ms) as min_ms,
               MAX(duration_ms) as max_ms,
               SUM(duration_ms) as total_ms,
               SUM(records_processed) as total_records
        FROM pipeline_run
        {where_sql}
        GROUP BY stage, step_name
        ORDER BY stage, total_ms DESC
        LIMIT %s
        """,
        tuple(params),
    )

    if not runs:
        print("No timing data available.")
        return

    print()
    print("=" * 120)
    print("  PIPELINE TIMING REPORT")
    print("=" * 120)
    print()
    print(f"{'Stage':<12} {'Step':<35} {'Count':>6} {'Avg (ms)':>10} {'Min (ms)':>10} {'Max (ms)':>10} {'Total (ms)':>12} {'Records':>10}")
    print("-" * 120)

    for run in runs:
        stage = run["stage"] or ""
        step = run["step_name"] or ""
        count = run["count"]
        avg = run["avg_ms"]
        min_ms = run["min_ms"]
        max_ms = run["max_ms"]
        total = run["total_ms"]
        records = run["total_records"] or 0

        print(
            f"{stage:<12} {step:<35} {count:>6} {avg:>10} {min_ms:>10} {max_ms:>10} {total:>12} {records:>10}"
        )

    print()
    print("=" * 120)
    print()
