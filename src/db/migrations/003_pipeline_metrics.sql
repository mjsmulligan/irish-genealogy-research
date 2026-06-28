-- Migration 003: Add pipeline_run table for performance metrics tracking
-- Purpose: Track execution time, throughput, and performance trends for each pipeline step

-- Schema v4.1 (from v4.0)
-- Adds infrastructure for monitoring pipeline performance as data grows

CREATE TABLE IF NOT EXISTS pipeline_run (
    run_id               INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    stage                TEXT NOT NULL CHECK (stage IN (
        'ingest', 'place', 'similarity', 'person',
        'relationship', 'event', 'validation', 'fetch'
    )),
    step_name            TEXT NOT NULL,  -- e.g., 'ingest_census', 'run_person_resolution'
    records_processed    INTEGER,         -- count of items processed by this step
    duration_ms          INTEGER NOT NULL,  -- elapsed time in milliseconds
    source_id            INTEGER,         -- optional: which census source (3=1901, 4=1911, 5=1926)
    notes                TEXT,            -- optional: parse notes, errors, warnings
    session_ref          TEXT,            -- optional: commit hash, Claude session ID, batch ID
    start_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    end_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_pipeline_run_start_at
    ON pipeline_run (start_at DESC);

CREATE INDEX IF NOT EXISTS idx_pipeline_run_stage_step
    ON pipeline_run (stage, step_name);

CREATE INDEX IF NOT EXISTS idx_pipeline_run_source_id
    ON pipeline_run (source_id)
    WHERE source_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_pipeline_run_session_ref
    ON pipeline_run (session_ref)
    WHERE session_ref IS NOT NULL;

-- Update schema version
UPDATE gra_meta SET value = '41' WHERE key = 'schema_version';
