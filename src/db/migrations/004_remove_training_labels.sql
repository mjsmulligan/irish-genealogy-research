-- Migration 004: Remove training_labels table (conceptually retired)
--
-- Context: training_labels was designed for a training/review workflow that was
-- superseded by the review layer (src/review/) in June 2026. The table has never
-- been populated by any active pipeline step; it only appears in reset/clear
-- commands in cli.py.
--
-- This migration removes the unused table and its indexes.

DROP INDEX IF EXISTS idx_training_labels_decision;
DROP INDEX IF EXISTS idx_training_labels_person_id_1;
DROP INDEX IF EXISTS idx_training_labels_person_id_2;
DROP TABLE IF EXISTS training_labels;

-- Update schema version
UPDATE gra_meta SET value = '44' WHERE key = 'schema_version';
