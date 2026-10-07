-- Migration 007: Partial index on recorded_relationship for similarity queries
--
-- person_resolution queries recorded_relationship heavily with a WHERE type = 'similarity'
-- filter. Without an index, each query is a full table scan. At full census scale
-- (~100k pairs) this becomes the dominant cost of the evidence pipeline.
--
-- The partial index covers the type filter and orders by score DESC so that
-- high-confidence pair retrieval is a pure index scan.

CREATE INDEX IF NOT EXISTS idx_recorded_relationship_type_score
    ON recorded_relationship (type, score DESC)
    WHERE type = 'similarity';

-- Update schema version
UPDATE gra_meta SET value = '45' WHERE key = 'schema_version';
