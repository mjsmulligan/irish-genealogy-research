-- GRA Migration: schema v2.7 → v2.8
--
-- Changes:
--   1. recorded_event fields merged into record table
--   2. event_recorded_event dropped (absorbed: event_record already links record→event)
--   3. person_relationship dropped (relationship.person_id_1/2 + indexes suffice)
--   4. relationship_event dropped (event.relationship_id already expresses this)
--   5. event_person dropped (person_event retained for both directions)
--
-- SQLite does not support ADD COLUMN with CHECK constraints or DEFAULT expressions
-- beyond literals, but the new event_type column has a CHECK — we must rebuild
-- record via the rename-recreate-reinsert pattern.
--
-- IMPORTANT: Verify you are on schema v2.7 before running:
--   PRAGMA user_version;  -- must return 27
--
-- Run via Python:
--   python -m src.db migrate --from 27 --to 28
-- Or directly (after verifying version):
--   python3 -c "
--     import sqlite3; conn = sqlite3.connect('genealogy.db')
--     conn.executescript(open('src/db/migrations/migrate_27_to_28.sql').read())
--   "

PRAGMA foreign_keys = OFF;
BEGIN;

-- ── 1. Rebuild record with RecordedEvent fields merged in ──────────────────
--
-- Data migration:
--   event_type        ← recorded_event.type
--   date_as_recorded  ← recorded_event.date_as_recorded
--   date              ← recorded_event.date
--   date_qualifier    ← recorded_event.date_qualifier
--   place_as_recorded ← recorded_event.place_as_recorded  (from recorded_event;
--                        recorded_person also has place_as_recorded — different field)
--   notes             ← COALESCE(record.notes, recorded_event.notes)
--                        (preserve both if present, record notes take precedence)

CREATE TABLE record_new (
    record_id           INTEGER PRIMARY KEY,
    source_id           INTEGER NOT NULL REFERENCES source (source_id),
    record_parameters   TEXT,
    raw_text            TEXT    NOT NULL CHECK (trim(raw_text) != ''),

    event_type          TEXT    NOT NULL,
    date_as_recorded    TEXT,
    date                TEXT,
    date_qualifier      TEXT,
    place_as_recorded   TEXT,

    notes               TEXT,

    CHECK (event_type IN (
        'birth', 'baptism', 'marriage', 'death', 'burial',
        'census', 'residence', 'emigration',
        'valuation', 'tithe', 'military_service', 'pension', 'folklore'
    )),
    CHECK (date_qualifier IS NULL OR date_qualifier IN (
        'exact', 'about', 'before', 'after', 'between', 'estimated', 'calculated'
    ))
);

INSERT INTO record_new
SELECT
    r.record_id,
    r.source_id,
    r.record_parameters,
    r.raw_text,
    re.type              AS event_type,
    re.date_as_recorded,
    re.date,
    re.date_qualifier,
    re.place_as_recorded,
    CASE
        WHEN r.notes IS NOT NULL AND re.notes IS NOT NULL
            THEN r.notes || ' | ' || re.notes
        ELSE COALESCE(r.notes, re.notes)
    END                  AS notes
FROM record r
JOIN recorded_event re ON re.record_id = r.record_id;

DROP TABLE record;
ALTER TABLE record_new RENAME TO record;

-- ── 2. Drop recorded_event ─────────────────────────────────────────────────
DROP TABLE recorded_event;

-- ── 3. Drop event_recorded_event ───────────────────────────────────────────
-- event_record already links event → record; this junction is redundant.
DROP TABLE event_recorded_event;

-- ── 4. Drop person_relationship ────────────────────────────────────────────
-- relationship.person_id_1 and person_id_2 with indexed lookups replace this.
DROP TABLE person_relationship;

-- ── 5. Drop relationship_event ─────────────────────────────────────────────
-- event.relationship_id already expresses this association.
DROP TABLE relationship_event;

-- ── 6. Drop event_person ───────────────────────────────────────────────────
-- person_event is retained; query from either direction via idx_person_event_event.
DROP TABLE event_person;

-- ── 7. Recreate indexes on record (lost when table was rebuilt) ────────────
CREATE INDEX idx_record_source ON record (source_id);

-- ── 8. Add new indexes ─────────────────────────────────────────────────────

-- Reverse lookup on person_event (replaces event_person)
CREATE INDEX IF NOT EXISTS idx_person_event_event ON person_event (event_id);

-- Place authority lookups (may already exist in v2.7; IF NOT EXISTS guards)
CREATE INDEX IF NOT EXISTS idx_place_authority_logainm ON place_authority (logainm_id);
CREATE INDEX IF NOT EXISTS idx_place_authority_type    ON place_authority (place_type);

-- ── 9. Bump schema version ─────────────────────────────────────────────────
PRAGMA user_version = 28;

COMMIT;
PRAGMA foreign_keys = ON;
