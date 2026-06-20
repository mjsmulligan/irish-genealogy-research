-- GRA Migration: schema v2.5 → v2.6
-- Change: score and score_version on all four linkage junction tables
--         made nullable to support manually-asserted linkages (OD-01 resolved).
--
-- SQLite does not support ALTER COLUMN. Each affected table is rebuilt
-- using the standard SQLite table-rename-recreate-reinsert pattern.
-- Foreign key enforcement is disabled during the migration and re-enabled after.
--
-- IMPORTANT: Verify you are on schema v2.5 before running:
--   PRAGMA user_version;  -- must return 25
--
-- Run via Python:
--   python -m src.db migrate --from 25 --to 26
-- Or directly (after verifying version):
--   python3 -c "
--     import sqlite3; conn = sqlite3.connect('genealogy.db')
--     conn.executescript(open('src/db/migrations/migrate_25_to_26.sql').read())
--   "
--
-- Data transformation: existing rows where score=0.0 AND score_version=''
-- (the old NOT NULL defaults used for manually-asserted linkages) are
-- converted to score=NULL, score_version=NULL. Rows with a genuine
-- algorithm score are preserved unchanged.

PRAGMA foreign_keys = OFF;
BEGIN;

-- ── person_record ──────────────────────────────────────────────────────────
CREATE TABLE person_record_new (
    person_id       INTEGER NOT NULL REFERENCES person (person_id),
    record_id       INTEGER NOT NULL REFERENCES record (record_id),
    score           REAL    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    score_version   TEXT,
    verified        INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    PRIMARY KEY (person_id, record_id)
);
INSERT INTO person_record_new
    SELECT person_id, record_id,
           CASE WHEN score = 0.0 AND score_version = '' THEN NULL ELSE score END,
           CASE WHEN score_version = '' THEN NULL ELSE score_version END,
           verified
    FROM person_record;
DROP TABLE person_record;
ALTER TABLE person_record_new RENAME TO person_record;

-- ── relationship_record ────────────────────────────────────────────────────
CREATE TABLE relationship_record_new (
    relationship_id INTEGER NOT NULL REFERENCES relationship (relationship_id),
    record_id       INTEGER NOT NULL REFERENCES record (record_id),
    score           REAL    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    score_version   TEXT,
    verified        INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    PRIMARY KEY (relationship_id, record_id)
);
INSERT INTO relationship_record_new
    SELECT relationship_id, record_id,
           CASE WHEN score = 0.0 AND score_version = '' THEN NULL ELSE score END,
           CASE WHEN score_version = '' THEN NULL ELSE score_version END,
           verified
    FROM relationship_record;
DROP TABLE relationship_record;
ALTER TABLE relationship_record_new RENAME TO relationship_record;

-- ── event_record ───────────────────────────────────────────────────────────
CREATE TABLE event_record_new (
    event_id        INTEGER NOT NULL REFERENCES event (event_id),
    record_id       INTEGER NOT NULL REFERENCES record (record_id),
    score           REAL    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    score_version   TEXT,
    verified        INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    PRIMARY KEY (event_id, record_id)
);
INSERT INTO event_record_new
    SELECT event_id, record_id,
           CASE WHEN score = 0.0 AND score_version = '' THEN NULL ELSE score END,
           CASE WHEN score_version = '' THEN NULL ELSE score_version END,
           verified
    FROM event_record;
DROP TABLE event_record;
ALTER TABLE event_record_new RENAME TO event_record;

-- ── place_record ───────────────────────────────────────────────────────────
CREATE TABLE place_record_new (
    place_id        INTEGER NOT NULL REFERENCES place (place_id),
    record_id       INTEGER NOT NULL REFERENCES record (record_id),
    score           REAL    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    score_version   TEXT,
    verified        INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    PRIMARY KEY (place_id, record_id)
);
INSERT INTO place_record_new
    SELECT place_id, record_id,
           CASE WHEN score = 0.0 AND score_version = '' THEN NULL ELSE score END,
           CASE WHEN score_version = '' THEN NULL ELSE score_version END,
           verified
    FROM place_record;
DROP TABLE place_record;
ALTER TABLE place_record_new RENAME TO place_record;

-- ── Recreate partial indexes ────────────────────────────────────────────────
-- Null-score rows are manually-asserted and excluded from re-scoring passes.
DROP INDEX IF EXISTS idx_person_record_score;
DROP INDEX IF EXISTS idx_event_record_score;
DROP INDEX IF EXISTS idx_relationship_record_score;
DROP INDEX IF EXISTS idx_place_record_score;

CREATE INDEX idx_person_record_score       ON person_record (score)       WHERE verified = 0 AND score IS NOT NULL;
CREATE INDEX idx_event_record_score        ON event_record (score)        WHERE verified = 0 AND score IS NOT NULL;
CREATE INDEX idx_relationship_record_score ON relationship_record (score)  WHERE verified = 0 AND score IS NOT NULL;
CREATE INDEX idx_place_record_score        ON place_record (score)         WHERE verified = 0 AND score IS NOT NULL;

-- ── Bump schema version ────────────────────────────────────────────────────
PRAGMA user_version = 26;

COMMIT;
PRAGMA foreign_keys = ON;
