-- Migration 004: Add 'conclusion' stage to pipeline_run
-- Purpose: Allow tracking of conclusion pipeline steps in metrics

-- Schema v4.2 (from v4.1)
-- Adds 'conclusion' as valid stage for pipeline_run metrics

ALTER TABLE pipeline_run
DROP CONSTRAINT pipeline_run_stage_check;

ALTER TABLE pipeline_run
ADD CONSTRAINT pipeline_run_stage_check CHECK (stage IN (
    'ingest', 'place', 'similarity', 'person',
    'relationship', 'event', 'validation', 'fetch', 'conclusion'
));

-- Update schema version
UPDATE gra_meta SET value = '42' WHERE key = 'schema_version';
