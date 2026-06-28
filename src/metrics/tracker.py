"""Performance metrics tracking for the GRA pipeline.

Provides timing instrumentation and persistence for tracking pipeline step
execution time, throughput, and performance trends over time.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import psycopg2.extensions


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
    conn: psycopg2.extensions.connection,
    run: PipelineRun,
) -> None:
    """Write pipeline run metrics to the database.

    Args:
        conn: Database connection
        run: PipelineRun with stage, step_name, duration_ms, etc.
    """
    with conn.cursor() as cur:
        cur.execute(
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
    conn: psycopg2.extensions.connection,
    stage: str | None = None,
    step_name: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Query recent pipeline runs.

    Args:
        conn: Database connection
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

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT run_id, stage, step_name, records_processed, duration_ms,
                   source_id, notes, start_at
            FROM pipeline_run
            {where_sql}
            ORDER BY start_at DESC
            LIMIT %s
            """,
            params,
        )
        return cur.fetchall()
