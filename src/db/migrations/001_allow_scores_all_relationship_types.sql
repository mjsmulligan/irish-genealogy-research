-- Migration: Allow scores for all recorded_relationship types
-- Schema version: 3.1 → 3.2
-- Date: 2026-06-22
-- Fixes: test_evidence_role_relationship_scores_not_null
--
-- Background:
-- The original schema enforced that scores could ONLY exist for type='similarity'.
-- However, reconstruction_algorithms.md §6.1 specifies that role-pair types
-- (couple, parent_child, sibling) should also have prior scores (0.75-0.90).
--
-- This migration drops the restrictive CHECK constraint and replaces it with
-- a version that allows (but doesn't require) scores for all types.

BEGIN;

-- Drop the old constraint that restricted scores to similarity only
ALTER TABLE recorded_relationship
    DROP CONSTRAINT IF EXISTS recorded_relationship_check1;

-- Add a new constraint that allows scores for all types
-- (The specific constraint name recorded_relationship_check1 comes from Postgres auto-naming)
ALTER TABLE recorded_relationship
    ADD CONSTRAINT recorded_relationship_check1
    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0));

-- Update version (stored as integer: 32 represents v3.2)
UPDATE gra_meta SET value = '32' WHERE key = 'schema_version';

COMMIT;
