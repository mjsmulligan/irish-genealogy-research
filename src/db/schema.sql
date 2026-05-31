-- GRA — Genealogy Research Assistant
-- Schema version 2.7 — May 2026
-- SQLite 3.35.0+ required
--
-- Run via: src/db.py init_db()
-- Do not execute directly against a database that contains data.
-- Use migration scripts in src/db/migrations/ for schema upgrades.
--
-- Changes from v2.6:
--   - place_authority table added to foundational layer (flat schema)
--   - place table (conclusion layer) retired
--   - place_record FK retargeted to place_authority
--   - event.place_id FK retargeted to place_authority
--   - source type 'place_authority' added

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- FOUNDATIONAL LAYER
-- ---------------------------------------------------------------------------

CREATE TABLE repository (
    repository_id   INTEGER PRIMARY KEY,
    name            TEXT    NOT NULL CHECK (trim(name) != ''),
    url             TEXT    NOT NULL CHECK (trim(url) != ''),
    notes           TEXT
);

CREATE TABLE source (
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

-- ---------------------------------------------------------------------------
-- PLACE AUTHORITY (Foundational)
-- Authoritative place identities seeded from logainm.ie or added manually.
-- Flat schema: hierarchy expressed as denormalised columns rather than a
-- separate junction table. This mirrors the logainm API response structure
-- and makes hierarchy queries simple WHERE clauses.
-- ---------------------------------------------------------------------------

CREATE TABLE place_authority (
    place_id          INTEGER PRIMARY KEY,
    logainm_id        INTEGER UNIQUE,        -- logainm.ie numeric ID; null for manually-added entities
    name_en           TEXT    NOT NULL CHECK (trim(name_en) != ''),
    place_type        TEXT    NOT NULL,
    -- Immediate parent (the entity under which this place was fetched)
    parent_name       TEXT,
    parent_id         INTEGER,               -- logainm_id of immediate parent
    parent_type       TEXT,
    -- Hierarchy columns (null where not applicable or not in logainm)
    ded_name          TEXT,
    ded_id            INTEGER,
    county_name       TEXT,
    county_id         INTEGER,
    barony_name       TEXT,
    barony_id         INTEGER,
    civil_parish_name TEXT,
    civil_parish_id   INTEGER,
    -- Geography
    latitude          REAL,
    longitude         REAL,
    -- Reference
    logainm_url       TEXT,
    notes             TEXT,

    CHECK (place_type IN (
        'province', 'county', 'barony', 'civil_parish',
        'ded', 'townland', 'church_parish', 'town'
    ))
);

-- ---------------------------------------------------------------------------
-- EVIDENCE LAYER
-- ---------------------------------------------------------------------------

CREATE TABLE record (
    record_id           INTEGER PRIMARY KEY,
    source_id           INTEGER NOT NULL REFERENCES source (source_id),
    record_parameters   TEXT,
    raw_text            TEXT    NOT NULL CHECK (trim(raw_text) != ''),
    notes               TEXT
);

CREATE TABLE recorded_event (
    recorded_event_id   INTEGER PRIMARY KEY,
    record_id           INTEGER NOT NULL UNIQUE REFERENCES record (record_id),
    type                TEXT    NOT NULL,
    date_as_recorded    TEXT,
    date                TEXT,
    date_qualifier      TEXT,
    place_as_recorded   TEXT,
    notes               TEXT,

    CHECK (type IN (
        'birth', 'baptism', 'marriage', 'death', 'burial',
        'census', 'residence', 'emigration',
        'valuation', 'tithe', 'military_service', 'pension', 'folklore'
    )),
    CHECK (date_qualifier IS NULL OR date_qualifier IN (
        'exact', 'about', 'before', 'after', 'between', 'estimated', 'calculated'
    ))
);

CREATE TABLE recorded_person (
    recorded_person_id      INTEGER PRIMARY KEY,
    record_id               INTEGER NOT NULL REFERENCES record (record_id),
    name_as_recorded        TEXT    NOT NULL CHECK (trim(name_as_recorded) != ''),
    role                    TEXT    NOT NULL,
    age_as_recorded         TEXT,
    age                     INTEGER,
    sex_as_recorded         TEXT,
    occupation_as_recorded  TEXT,
    place_as_recorded       TEXT,
    notes                   TEXT,

    CHECK (role IN (
        'head', 'spouse', 'son', 'daughter',
        'sibling', 'grandchild', 'in_law',
        'niece_nephew', 'aunt_uncle', 'cousin',
        'mother', 'father',
        'servant', 'visitor', 'boarder',
        'principal', 'groom', 'bride',
        'father_of_groom', 'father_of_bride',
        'godfather', 'godmother',
        'witness', 'informant', 'officiator',
        'occupier', 'lessor', 'deceased'
    ))
);

CREATE TABLE name_variant (
    name_variant_id     INTEGER PRIMARY KEY,
    recorded_person_id  INTEGER NOT NULL REFERENCES recorded_person (recorded_person_id),
    variant_value       TEXT    NOT NULL CHECK (trim(variant_value) != ''),
    variant_type        TEXT    NOT NULL,
    algorithm_version   TEXT    NOT NULL,
    notes               TEXT,

    CHECK (variant_type IN ('anglicised', 'irish', 'phonetic', 'normalised'))
);

-- ---------------------------------------------------------------------------
-- CONCLUSION LAYER
-- ---------------------------------------------------------------------------

CREATE TABLE person (
    person_id   INTEGER PRIMARY KEY,
    label       TEXT    NOT NULL CHECK (trim(label) != ''),
    gender      TEXT,
    private     INTEGER NOT NULL DEFAULT 0 CHECK (private IN (0, 1)),
    notes       TEXT,

    CHECK (gender IS NULL OR gender IN ('male', 'female', 'unknown'))
);

CREATE TABLE person_name (
    person_name_id  INTEGER PRIMARY KEY,
    person_id       INTEGER NOT NULL REFERENCES person (person_id),
    value           TEXT    NOT NULL CHECK (trim(value) != ''),
    type            TEXT    NOT NULL,

    CHECK (type IN ('birth_name', 'married_name', 'also_known_as', 'nickname'))
);

CREATE TABLE relationship (
    relationship_id INTEGER PRIMARY KEY,
    type            TEXT    NOT NULL,
    person_id_1     INTEGER NOT NULL REFERENCES person (person_id),
    person_id_2     INTEGER NOT NULL REFERENCES person (person_id),
    notes           TEXT,

    CHECK (person_id_1 != person_id_2),
    CHECK (type IN ('couple', 'parent_child', 'sibling'))
);

CREATE TABLE event (
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

-- ---------------------------------------------------------------------------
-- JUNCTION TABLES
-- ---------------------------------------------------------------------------

CREATE TABLE person_record (
    person_id       INTEGER NOT NULL REFERENCES person (person_id),
    record_id       INTEGER NOT NULL REFERENCES record (record_id),
    score           REAL    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    score_version   TEXT,
    verified        INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    PRIMARY KEY (person_id, record_id)
);

CREATE TABLE person_event (
    person_id   INTEGER NOT NULL REFERENCES person (person_id),
    event_id    INTEGER NOT NULL REFERENCES event (event_id),
    PRIMARY KEY (person_id, event_id)
);

CREATE TABLE person_relationship (
    person_id       INTEGER NOT NULL REFERENCES person (person_id),
    relationship_id INTEGER NOT NULL REFERENCES relationship (relationship_id),
    PRIMARY KEY (person_id, relationship_id)
);

CREATE TABLE relationship_record (
    relationship_id INTEGER NOT NULL REFERENCES relationship (relationship_id),
    record_id       INTEGER NOT NULL REFERENCES record (record_id),
    score           REAL    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    score_version   TEXT,
    verified        INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    PRIMARY KEY (relationship_id, record_id)
);

CREATE TABLE relationship_event (
    relationship_id INTEGER NOT NULL REFERENCES relationship (relationship_id),
    event_id        INTEGER NOT NULL REFERENCES event (event_id),
    PRIMARY KEY (relationship_id, event_id)
);

CREATE TABLE event_record (
    event_id        INTEGER NOT NULL REFERENCES event (event_id),
    record_id       INTEGER NOT NULL REFERENCES record (record_id),
    score           REAL    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    score_version   TEXT,
    verified        INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    PRIMARY KEY (event_id, record_id)
);

CREATE TABLE event_recorded_event (
    event_id            INTEGER NOT NULL REFERENCES event (event_id),
    recorded_event_id   INTEGER NOT NULL REFERENCES recorded_event (recorded_event_id),
    PRIMARY KEY (event_id, recorded_event_id)
);

CREATE TABLE event_person (
    event_id    INTEGER NOT NULL REFERENCES event (event_id),
    person_id   INTEGER NOT NULL REFERENCES person (person_id),
    PRIMARY KEY (event_id, person_id)
);

-- Place linkage: evidence Record → place_authority [linkage junction]
CREATE TABLE place_record (
    place_id        INTEGER NOT NULL REFERENCES place_authority (place_id),
    record_id       INTEGER NOT NULL REFERENCES record (record_id),
    score           REAL    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    score_version   TEXT,
    verified        INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    PRIMARY KEY (place_id, record_id)
);

-- ---------------------------------------------------------------------------
-- INDEXES
-- ---------------------------------------------------------------------------

CREATE INDEX idx_record_source              ON record (source_id);
CREATE INDEX idx_recorded_person_record     ON recorded_person (record_id);
CREATE INDEX idx_recorded_person_name       ON recorded_person (name_as_recorded);
CREATE INDEX idx_person_name_value          ON person_name (value);
CREATE INDEX idx_person_name_person         ON person_name (person_id);
CREATE INDEX idx_person_record_record       ON person_record (record_id);
CREATE INDEX idx_relationship_person1       ON relationship (person_id_1);
CREATE INDEX idx_relationship_person2       ON relationship (person_id_2);
CREATE INDEX idx_event_place                ON event (place_id);
CREATE INDEX idx_event_relationship         ON event (relationship_id);
CREATE INDEX idx_name_variant_value         ON name_variant (variant_value);
CREATE INDEX idx_name_variant_recorded_person ON name_variant (recorded_person_id);

-- Place authority lookups
CREATE INDEX idx_place_authority_logainm    ON place_authority (logainm_id);
CREATE INDEX idx_place_authority_type       ON place_authority (place_type);
-- Hierarchy queries (WHERE civil_parish_id = ? etc.)
CREATE INDEX idx_place_authority_ded        ON place_authority (ded_id);
CREATE INDEX idx_place_authority_civil_parish ON place_authority (civil_parish_id);
CREATE INDEX idx_place_authority_barony     ON place_authority (barony_id);
CREATE INDEX idx_place_authority_county     ON place_authority (county_id);

-- Place record linkage
CREATE INDEX idx_place_record_record        ON place_record (record_id);

-- Unverified linkage re-scoring passes (partial indexes)
CREATE INDEX idx_person_record_score        ON person_record (score)        WHERE verified = 0 AND score IS NOT NULL;
CREATE INDEX idx_event_record_score         ON event_record (score)         WHERE verified = 0 AND score IS NOT NULL;
CREATE INDEX idx_relationship_record_score  ON relationship_record (score)  WHERE verified = 0 AND score IS NOT NULL;
CREATE INDEX idx_place_record_score         ON place_record (score)         WHERE verified = 0 AND score IS NOT NULL;

-- ---------------------------------------------------------------------------
-- SCHEMA VERSION
-- ---------------------------------------------------------------------------

PRAGMA user_version = 27;
