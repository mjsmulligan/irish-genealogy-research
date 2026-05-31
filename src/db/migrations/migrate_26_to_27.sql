-- GRA Migration: schema v2.6 → v2.7
-- Changes:
--   - place_authority added to foundational layer (flat schema with hierarchy columns)
--   - place conclusion table retired
--   - place_record FK retargeted to place_authority
--   - event.place_id FK retargeted to place_authority
--   - source type 'place_authority' added to CHECK constraint
--
-- Data transformation:
--   Existing place rows are migrated into place_authority with:
--     place_id preserved, logainm_id from existing column,
--     name_en from name column, place_type = 'townland' (all old conclusions
--     were townland-level), all hierarchy columns NULL.
--   place_record rows preserved (place_id values carry over).
--   event.place_id values preserved (same synthetic IDs).
--
-- IMPORTANT: Verify schema v2.6 before running:
--   PRAGMA user_version;  -- must return 26
--
-- Run via: python -m src.db migrate --from 26 --to 27

PRAGMA foreign_keys = OFF;
BEGIN;

-- ── 1. Create place_authority from existing place rows ─────────────────────
CREATE TABLE place_authority (
    place_id          INTEGER PRIMARY KEY,
    logainm_id        INTEGER UNIQUE,
    name_en           TEXT    NOT NULL CHECK (trim(name_en) != ''),
    place_type        TEXT    NOT NULL,
    parent_name       TEXT,
    parent_id         INTEGER,
    parent_type       TEXT,
    ded_name          TEXT,
    ded_id            INTEGER,
    county_name       TEXT,
    county_id         INTEGER,
    barony_name       TEXT,
    barony_id         INTEGER,
    civil_parish_name TEXT,
    civil_parish_id   INTEGER,
    latitude          REAL,
    longitude         REAL,
    logainm_url       TEXT,
    notes             TEXT,

    CHECK (place_type IN (
        'province', 'county', 'barony', 'civil_parish',
        'ded', 'townland', 'church_parish', 'town'
    ))
);

INSERT INTO place_authority
    (place_id, logainm_id, name_en, place_type, logainm_url, notes)
    SELECT place_id, logainm_id, name, 'townland', logainm_url, notes
    FROM place;

-- ── 2. Rebuild place_record targeting place_authority ──────────────────────
CREATE TABLE place_record_new (
    place_id        INTEGER NOT NULL REFERENCES place_authority (place_id),
    record_id       INTEGER NOT NULL REFERENCES record (record_id),
    score           REAL    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    score_version   TEXT,
    verified        INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    PRIMARY KEY (place_id, record_id)
);
INSERT INTO place_record_new SELECT * FROM place_record;
DROP TABLE place_record;
ALTER TABLE place_record_new RENAME TO place_record;

-- ── 3. Rebuild event with place_id → place_authority ──────────────────────
CREATE TABLE event_new (
    event_id        INTEGER PRIMARY KEY,
    type            TEXT    NOT NULL,
    date            TEXT,
    date_qualifier  TEXT,
    place_id        INTEGER REFERENCES place_authority (place_id),
    relationship_id INTEGER REFERENCES relationship (relationship_id),
    notes           TEXT,

    CHECK (type IN (
        'birth', 'baptism', 'marriage', 'death', 'burial',
        'census', 'residence', 'emigration',
        'valuation', 'tithe', 'military_service', 'pension', 'folklore'
    )),
    CHECK (date_qualifier IS NULL OR date_qualifier IN (
        'exact', 'about', 'before', 'after', 'between', 'estimated', 'calculated'
    ))
);
INSERT INTO event_new SELECT * FROM event;
DROP TABLE event;
ALTER TABLE event_new RENAME TO event;

-- ── 4. Add place_authority to source CHECK constraint ─────────────────────
CREATE TABLE source_new (
    source_id               INTEGER PRIMARY KEY,
    repository_id           INTEGER NOT NULL REFERENCES repository (repository_id),
    title                   TEXT    NOT NULL CHECK (trim(title) != ''),
    type                    TEXT    NOT NULL,
    coverage_from           INTEGER,
    coverage_to             INTEGER,
    source_url              TEXT,
    record_url_template     TEXT,
    source_parameters       TEXT,
    record_parameter_names  TEXT,
    column_schema           TEXT,
    citation                TEXT,
    notes                   TEXT,

    CHECK (type IN (
        'valuation', 'tithe', 'census',
        'birth_registration', 'marriage_registration', 'death_registration',
        'parish_register', 'military', 'folklore', 'place_authority'
    ))
);
INSERT INTO source_new SELECT * FROM source;
DROP TABLE source;
ALTER TABLE source_new RENAME TO source;

-- ── 5. Drop retired place table ────────────────────────────────────────────
DROP TABLE place;

-- ── 6. Recreate indexes ────────────────────────────────────────────────────
DROP INDEX IF EXISTS idx_place_record_score;
DROP INDEX IF EXISTS idx_event_place;

CREATE INDEX idx_place_authority_logainm      ON place_authority (logainm_id);
CREATE INDEX idx_place_authority_type         ON place_authority (place_type);
CREATE INDEX idx_place_authority_ded          ON place_authority (ded_id);
CREATE INDEX idx_place_authority_civil_parish ON place_authority (civil_parish_id);
CREATE INDEX idx_place_authority_barony       ON place_authority (barony_id);
CREATE INDEX idx_place_authority_county       ON place_authority (county_id);
CREATE INDEX idx_place_record_record          ON place_record (record_id);
CREATE INDEX idx_place_record_score           ON place_record (score) WHERE verified = 0 AND score IS NOT NULL;
CREATE INDEX idx_event_place                  ON event (place_id);

-- ── 7. Bump schema version ─────────────────────────────────────────────────
PRAGMA user_version = 27;

COMMIT;
PRAGMA foreign_keys = ON;
