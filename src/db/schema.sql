
-- GRA — Genealogy Research Assistant
-- Schema version 3.0 — 17 June 2026
-- SQLite 3.35.0+ required
--
-- Changes from v2.9:
--   - recorded_person.role made nullable (NULL = blank in source data)
--   - 'unknown' added to role CHECK (value present in source but not mappable)
--   - NOT NULL constraint removed from recorded_person.role
--
-- Changes from v2.8:
--   - training_labels added (linkage proposals + researcher review workflow)
--   - event.is_primary added (consensus arbitration; set by rebuild-consensus stage)
--
-- Changes from v2.7:
--   - recorded_event merged into record (1:1 relationship formalised)
--   - event_recorded_event dropped (absorbed into event_record)
--   - person_relationship dropped (queries go direct to relationship.person_id_1/2)
--   - relationship_event dropped (expressed by event.relationship_id)
--   - event_person dropped (person_event retained; query from either direction)
--
-- Run via: src/db.py init_db()
-- Do not execute directly against a database that contains data.
-- Use migration scripts in src/db/migrations/ for schema upgrades.

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
    source_parameters       TEXT,   -- JSON object; null when all parameters are Record-level
    record_parameter_names  TEXT,   -- JSON array of parameter name strings
    column_schema           TEXT,   -- JSON array of column name strings
    citation                TEXT,
    notes                   TEXT,

    CHECK (type IN (
        'valuation', 'tithe', 'census',
        'birth_registration', 'marriage_registration', 'death_registration',
        'parish_register', 'military', 'folklore', 'place_authority'
    ))
);

CREATE TABLE place_authority (
    place_id            INTEGER PRIMARY KEY,
    logainm_id          INTEGER UNIQUE,     -- null for manually-added entities
    name_en             TEXT    NOT NULL CHECK (trim(name_en) != ''),
    place_type          TEXT    NOT NULL,
    parent_name         TEXT,
    parent_id           INTEGER,
    parent_type         TEXT,
    ded_name            TEXT,
    ded_id              INTEGER,
    county_name         TEXT,
    county_id           INTEGER,
    barony_name         TEXT,
    barony_id           INTEGER,
    civil_parish_name   TEXT,
    civil_parish_id     INTEGER,
    latitude            REAL,
    longitude           REAL,
    logainm_url         TEXT,
    notes               TEXT,

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
    record_parameters   TEXT,   -- JSON object; keys must match source.record_parameter_names
    raw_text            TEXT    NOT NULL CHECK (trim(raw_text) != ''),

    -- RecordedEvent fields (merged from recorded_event; always 1:1 with record)
    event_type          TEXT    NOT NULL,
    date_as_recorded    TEXT,   -- verbatim; exempt from date format validation
    date                TEXT,   -- normalised ISO 8601; validated by Python (R36)
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

CREATE TABLE recorded_person (
    recorded_person_id      INTEGER PRIMARY KEY,
    record_id               INTEGER NOT NULL REFERENCES record (record_id),
    name_as_recorded        TEXT    NOT NULL CHECK (trim(name_as_recorded) != ''),
    role                    TEXT,   -- NULL = blank in source; 'unknown' = value present but not mappable
    age_as_recorded         TEXT,
    age                     INTEGER,
    sex_as_recorded         TEXT,
    occupation_as_recorded  TEXT,
    place_as_recorded       TEXT,
    notes                   TEXT,

    CHECK (role IS NULL OR role IN (
        -- Census roles (NAI download mapping)
        'head', 'spouse', 'son', 'daughter',
        'sibling', 'grandchild', 'in_law',
        'niece_nephew', 'aunt_uncle', 'cousin',
        'mother', 'father',
        'servant', 'visitor', 'boarder',
        -- Unmapped / missing source data
        'unknown',
        -- Event roles (civil registration, parish register, other)
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
    date            TEXT,   -- normalised ISO 8601; validated by Python (R36)
    date_qualifier  TEXT,
    place_id        INTEGER REFERENCES place_authority (place_id),
    relationship_id INTEGER REFERENCES relationship (relationship_id),
    is_primary      INTEGER NOT NULL DEFAULT 1 CHECK (is_primary IN (0, 1)),
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
-- Naming convention: {owner}_{target} in singular form.
--
-- Linkage junctions (evidence-to-conclusion) carry scoring columns:
--   score:         null for manually-asserted linkages; [0.0, 1.0] for algorithm-scored
--   score_version: null when score is null; algorithm version string otherwise
--   verified:      0 = algorithm assertion or unreviewed manual; 1 = researcher-verified
--                  Verified rows are never overwritten by re-scoring passes.

-- Person.record_ids  [linkage junction]
CREATE TABLE person_record (
    person_id       INTEGER NOT NULL REFERENCES person (person_id),
    record_id       INTEGER NOT NULL REFERENCES record (record_id),
    score           REAL    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    score_version   TEXT,
    verified        INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    PRIMARY KEY (person_id, record_id)
);

-- Relationship.record_ids  [linkage junction]
CREATE TABLE relationship_record (
    relationship_id INTEGER NOT NULL REFERENCES relationship (relationship_id),
    record_id       INTEGER NOT NULL REFERENCES record (record_id),
    score           REAL    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    score_version   TEXT,
    verified        INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    PRIMARY KEY (relationship_id, record_id)
);

-- Event.record_ids  [linkage junction]
-- Replaces both the old event_record and event_recorded_event tables.
-- A record has exactly one event (enforced by schema design); linking a record
-- to an event conclusion implicitly links the record's event data also.
CREATE TABLE event_record (
    event_id        INTEGER NOT NULL REFERENCES event (event_id),
    record_id       INTEGER NOT NULL REFERENCES record (record_id),
    score           REAL    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    score_version   TEXT,
    verified        INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    PRIMARY KEY (event_id, record_id)
);

-- Place.record_ids  [linkage junction]
CREATE TABLE place_record (
    place_id        INTEGER NOT NULL REFERENCES place_authority (place_id),
    record_id       INTEGER NOT NULL REFERENCES record (record_id),
    score           REAL    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    score_version   TEXT,
    verified        INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    PRIMARY KEY (place_id, record_id)
);

-- Person.event_ids  [structural junction — no scoring]
-- Single table; query from either direction by filtering on person_id or event_id.
CREATE TABLE person_event (
    person_id   INTEGER NOT NULL REFERENCES person (person_id),
    event_id    INTEGER NOT NULL REFERENCES event (event_id),
    PRIMARY KEY (person_id, event_id)
);

-- ---------------------------------------------------------------------------
-- REVIEW / TRAINING LAYER
-- ---------------------------------------------------------------------------
-- training_labels holds cross-census person linkage proposals generated by
-- linkage.py and researcher decisions made via review.py.
--
-- decision lifecycle:
--   'proposed'  — written by linkage.py at PROPOSE_FLOOR <= score < AUTO_COMMIT_THRESHOLD
--   'accepted'  — researcher confirms the two persons are the same individual
--   'rejected'  — researcher confirms they are different individuals
--   'flagged'   — ambiguous; needs further evidence before a decision
--
-- score is nullable: algorithmic proposals carry a Splink match probability;
-- manual researcher assertions (score=NULL) are distinguished by the absence
-- of a score value. score_version identifies the algorithm run that generated
-- the score.
--
-- UNIQUE (person_id_1, person_id_2) with CHECK (person_id_1 < person_id_2)
-- enforces the merge contract (lower person_id = canonical) and makes
-- INSERT OR IGNORE idempotent across linkage re-runs.

CREATE TABLE training_labels (
    label_id      INTEGER PRIMARY KEY,
    person_id_1   INTEGER NOT NULL REFERENCES person (person_id),
    person_id_2   INTEGER NOT NULL REFERENCES person (person_id),
    score         REAL    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    score_version TEXT,
    decision      TEXT NOT NULL DEFAULT 'proposed'
                  CHECK (decision IN ('proposed', 'accepted', 'rejected', 'flagged')),
    note          TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    reviewed_at   TEXT,
    UNIQUE (person_id_1, person_id_2),
    CHECK (person_id_1 < person_id_2)
);

-- ---------------------------------------------------------------------------
-- INDEXES
-- ---------------------------------------------------------------------------

-- Ingest traversal
CREATE INDEX idx_record_source           ON record (source_id);
CREATE INDEX idx_recorded_person_record  ON recorded_person (record_id);

-- Linkage scoring: name candidate lookup
CREATE INDEX idx_recorded_person_name    ON recorded_person (name_as_recorded);
CREATE INDEX idx_person_name_value       ON person_name (value);
CREATE INDEX idx_person_name_person      ON person_name (person_id);

-- Reconstruction
CREATE INDEX idx_person_record_record    ON person_record (record_id);
CREATE INDEX idx_relationship_person1    ON relationship (person_id_1);
CREATE INDEX idx_relationship_person2    ON relationship (person_id_2);
CREATE INDEX idx_event_place             ON event (place_id);
CREATE INDEX idx_event_relationship      ON event (relationship_id);

-- Reverse lookup: all events for a person (replaces event_person index)
CREATE INDEX idx_person_event_event      ON person_event (event_id);

-- Name variant scoring
CREATE INDEX idx_name_variant_value           ON name_variant (variant_value);
CREATE INDEX idx_name_variant_recorded_person ON name_variant (recorded_person_id);

-- Place authority lookups
CREATE INDEX idx_place_authority_logainm  ON place_authority (logainm_id);
CREATE INDEX idx_place_authority_type     ON place_authority (place_type);

-- Unverified linkage re-scoring passes (partial indexes; null-score rows excluded)
CREATE INDEX idx_person_record_score       ON person_record (score)       WHERE verified = 0 AND score IS NOT NULL;
CREATE INDEX idx_event_record_score        ON event_record (score)        WHERE verified = 0 AND score IS NOT NULL;
CREATE INDEX idx_relationship_record_score ON relationship_record (score)  WHERE verified = 0 AND score IS NOT NULL;
CREATE INDEX idx_place_record_score        ON place_record (score)         WHERE verified = 0 AND score IS NOT NULL;

-- training_labels review workflow
CREATE INDEX idx_training_labels_decision   ON training_labels (decision);
CREATE INDEX idx_training_labels_person_id_1 ON training_labels (person_id_1);
CREATE INDEX idx_training_labels_person_id_2 ON training_labels (person_id_2);

-- ---------------------------------------------------------------------------
-- SCHEMA VERSION
-- ---------------------------------------------------------------------------

PRAGMA user_version = 30;
