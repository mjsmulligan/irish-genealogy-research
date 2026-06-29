-- GRA — Genealogy Research Assistant
-- Schema version 4.3 — 29 June 2026
-- PostgreSQL 15+ required
--
-- Changes from v4.2 → v4.3 (migration 005):
--   - check_no_same_census_link() trigger function added
--   - prevent_same_census_link trigger on person_recorded_person
--     (DB-level enforcement: one Person cannot link to two RecordedPersons
--      from the same census source)
--
-- Changes from v4.1 → v4.2 (migration 004):
--   - pipeline_run.stage CHECK constraint extended to include 'conclusion'
--
-- Changes from v4.0 → v4.1 (migration 003):
--   - pipeline_run table added (pipeline timing instrumentation)
--
-- Changes from v3.2 → v4.0 (migration 002 / Review Layer):
--   - reviewer table added (first-class entity: pipeline / human / ai)
--   - conclusion_log table added (append-only audit trail for all conclusion mutations)
--   - person, relationship, event: status + pending_delete_at columns added
--     (lifecycle: active → pending_delete → physical deletion)
--   - Two system reviewers seeded: pipeline:system (id=1), human:unknown (id=2)
--
-- Changes from v3.0 (SQLite) → v3.1 (PostgreSQL):
--   - Migrated from SQLite to PostgreSQL (Supabase)
--   - INTEGER PRIMARY KEY → INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY
--   - PRAGMA statements removed; foreign_keys enforced by Postgres natively
--   - strftime() default → NOW()
--   - Version tracking via gra_meta table (replaces PRAGMA user_version)
--   - recorded_relationship added (Evidence layer — intra-household role pairs)
--   - record_similarity added (Evidence layer — cross-census algorithmic comparison)
--   - person_record renamed → person_recorded_person; FK target record_id → recorded_person_id
--   - relationship_record renamed → relationship_recorded_relationship; FK target record_id → recorded_relationship_id
--   - training_labels retained in schema (conceptually retired; removal is a
--     separate implementation task — ROADMAP item 11)
--
-- Bootstrap via: python -m src.cli init
-- Do not execute directly against a populated database.

-- ---------------------------------------------------------------------------
-- VERSION TRACKING
-- ---------------------------------------------------------------------------
-- Replaces SQLite's PRAGMA user_version.
-- Exactly one row; inserted by init_db() after schema creation.

CREATE TABLE gra_meta (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- FOUNDATIONAL LAYER
-- ---------------------------------------------------------------------------

CREATE TABLE repository (
    repository_id   INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name            TEXT    NOT NULL CHECK (trim(name) != ''),
    url             TEXT    NOT NULL CHECK (trim(url) != ''),
    notes           TEXT
);

CREATE TABLE source (
    source_id               INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
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
    place_id            INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
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
    record_id           INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
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
    recorded_person_id      INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
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

-- Relationship between two RecordedPersons (Evidence layer).
-- type vocabulary:
--   couple / parent_child / sibling — stated relationships derived from census roles (prior scores 0.75-0.90)
--   similarity                       — algorithmic cross-census candidate match (Splink scores 0.0-1.0)
--
-- score / score_version:
--   All types carry scores per reconstruction_algorithms.md §6.1.
--   Role-pair types use prior scores from the rule table; similarity uses Splink scores.
CREATE TABLE recorded_relationship (
    recorded_relationship_id  INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    recorded_person_id_1      INTEGER NOT NULL REFERENCES recorded_person (recorded_person_id),
    recorded_person_id_2      INTEGER NOT NULL REFERENCES recorded_person (recorded_person_id),
    type                      TEXT    NOT NULL,
    score                     REAL,
    score_version             TEXT,
    notes                     TEXT,

    CHECK (recorded_person_id_1 != recorded_person_id_2),
    CHECK (type IN ('couple', 'parent_child', 'sibling', 'similarity')),
    -- All types should have scores, but allow NULL for backward compatibility during migration
    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    CHECK ((score IS NULL) = (score_version IS NULL))
);

-- Algorithmic comparison between two Records (Evidence layer).
-- No conclusion-layer counterpart by design: records a measurement, not an assertion.
-- Neither table carries a verified column — there is no conclusion-layer decision to verify.
CREATE TABLE record_similarity (
    record_similarity_id  INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    record_id_1           INTEGER NOT NULL REFERENCES record (record_id),
    record_id_2           INTEGER NOT NULL REFERENCES record (record_id),
    score                 REAL    NOT NULL CHECK (score >= 0.0 AND score <= 1.0),
    score_version         TEXT    NOT NULL,
    notes                 TEXT,

    CHECK (record_id_1 != record_id_2)
);

CREATE TABLE name_variant (
    name_variant_id     INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
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
    person_id           INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    label               TEXT        NOT NULL CHECK (trim(label) != ''),
    gender              TEXT,
    private             INTEGER     NOT NULL DEFAULT 0 CHECK (private IN (0, 1)),
    status              TEXT        NOT NULL DEFAULT 'active',
    pending_delete_at   TIMESTAMPTZ,
    notes               TEXT,

    CHECK (gender IS NULL OR gender IN ('male', 'female', 'unknown')),
    CHECK (status IN ('active', 'pending_delete')),
    CHECK (status = 'active' OR pending_delete_at IS NOT NULL)
);

CREATE TABLE person_name (
    person_name_id  INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    person_id       INTEGER NOT NULL REFERENCES person (person_id),
    value           TEXT    NOT NULL CHECK (trim(value) != ''),
    type            TEXT    NOT NULL,

    CHECK (type IN ('birth_name', 'married_name', 'also_known_as', 'nickname'))
);

CREATE TABLE relationship (
    relationship_id     INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    type                TEXT        NOT NULL,
    person_id_1         INTEGER     NOT NULL REFERENCES person (person_id),
    person_id_2         INTEGER     NOT NULL REFERENCES person (person_id),
    status              TEXT        NOT NULL DEFAULT 'active',
    pending_delete_at   TIMESTAMPTZ,
    notes               TEXT,

    CHECK (person_id_1 != person_id_2),
    CHECK (type IN ('couple', 'parent_child', 'sibling')),
    CHECK (status IN ('active', 'pending_delete')),
    CHECK (status = 'active' OR pending_delete_at IS NOT NULL)
);

CREATE TABLE event (
    event_id            INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    type                TEXT        NOT NULL,
    date                TEXT,       -- normalised ISO 8601; validated by Python (R36)
    date_qualifier      TEXT,
    place_id            INTEGER     REFERENCES place_authority (place_id),
    relationship_id     INTEGER     REFERENCES relationship (relationship_id),
    is_primary          INTEGER     NOT NULL DEFAULT 1 CHECK (is_primary IN (0, 1)),
    status              TEXT        NOT NULL DEFAULT 'active',
    pending_delete_at   TIMESTAMPTZ,
    notes               TEXT,

    CHECK (type IN (
        'birth', 'baptism', 'marriage', 'death', 'burial',
        'census', 'residence', 'emigration',
        'valuation', 'tithe', 'military_service', 'pension', 'folklore'
    )),
    CHECK (date_qualifier IS NULL OR date_qualifier IN (
        'exact', 'about', 'before', 'after', 'between', 'estimated', 'calculated'
    )),
    CHECK (status IN ('active', 'pending_delete')),
    CHECK (status = 'active' OR pending_delete_at IS NOT NULL)
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

-- Person.recorded_person_ids  [linkage junction]
-- Rule 2 (evidence correspondence): Person → RecordedPerson (not raw Record).
-- FK target is recorded_person_id, not record_id.
CREATE TABLE person_recorded_person (
    person_id           INTEGER NOT NULL REFERENCES person (person_id),
    recorded_person_id  INTEGER NOT NULL REFERENCES recorded_person (recorded_person_id),
    score               REAL    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    score_version       TEXT,
    verified            INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    PRIMARY KEY (person_id, recorded_person_id)
);

-- Relationship.recorded_relationship_ids  [linkage junction]
-- Rule 2 (evidence correspondence): Relationship → RecordedRelationship (not raw Record).
-- FK target is recorded_relationship_id, not record_id.
CREATE TABLE relationship_recorded_relationship (
    relationship_id          INTEGER NOT NULL REFERENCES relationship (relationship_id),
    recorded_relationship_id INTEGER NOT NULL REFERENCES recorded_relationship (recorded_relationship_id),
    score                    REAL    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    score_version            TEXT,
    verified                 INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    PRIMARY KEY (relationship_id, recorded_relationship_id)
);

-- Event.record_ids  [linkage junction]
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
CREATE TABLE person_event (
    person_id   INTEGER NOT NULL REFERENCES person (person_id),
    event_id    INTEGER NOT NULL REFERENCES event (event_id),
    PRIMARY KEY (person_id, event_id)
);

-- ---------------------------------------------------------------------------
-- REVIEW / TRAINING LAYER
-- ---------------------------------------------------------------------------
-- Conceptually retired (see conceptual_model.md §4.9 and ROADMAP item 11).
-- Retained in schema pending implementation-phase removal.
--
-- decision lifecycle:
--   'proposed'  — written by linkage.py at PROPOSE_FLOOR <= score < AUTO_COMMIT_THRESHOLD
--   'accepted'  — researcher confirms the two persons are the same individual
--   'rejected'  — researcher confirms they are different individuals
--   'flagged'   — ambiguous; needs further evidence before a decision

CREATE TABLE training_labels (
    label_id      INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    person_id_1   INTEGER NOT NULL REFERENCES person (person_id),
    person_id_2   INTEGER NOT NULL REFERENCES person (person_id),
    score         REAL    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    score_version TEXT,
    decision      TEXT NOT NULL DEFAULT 'proposed'
                  CHECK (decision IN ('proposed', 'accepted', 'rejected', 'flagged')),
    note          TEXT,
    created_at    TEXT NOT NULL DEFAULT (NOW()::TEXT),
    reviewed_at   TEXT,
    UNIQUE (person_id_1, person_id_2),
    CHECK (person_id_1 < person_id_2)
);

-- ---------------------------------------------------------------------------
-- REVIEW LAYER
-- ---------------------------------------------------------------------------
-- Reviewer: any agent that creates or modifies conclusion-layer objects.
-- ConclusionLog: append-only audit trail. Entries are never updated or deleted.

CREATE TABLE reviewer (
    reviewer_id  INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name         TEXT        NOT NULL CHECK (trim(name) != ''),
    type         TEXT        NOT NULL,
    notes        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CHECK (type IN ('pipeline', 'human', 'ai'))
);

-- Append-only. All conclusion-layer creates, updates, deletes, verifications,
-- and flags are recorded here. change_group_id (UUID) groups the entries
-- belonging to a single logical researcher action.
CREATE TABLE conclusion_log (
    log_id           INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    reviewer_id      INTEGER     NOT NULL REFERENCES reviewer (reviewer_id),
    action           TEXT        NOT NULL,
    entity_type      TEXT        NOT NULL,
    entity_id        INTEGER     NOT NULL,
    field_name       TEXT,               -- NULL for create/delete; column name for update
    old_value        TEXT,               -- NULL on create
    new_value        TEXT,               -- NULL on delete
    reason           TEXT,
    change_group_id  TEXT,               -- UUID; groups related entries for one logical action
    session_ref      TEXT,               -- pipeline commit hash, Claude session ID, etc.
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CHECK (action IN ('create', 'update', 'delete', 'verify', 'flag')),
    CHECK (entity_type IN (
        'person', 'relationship', 'event',
        'person_recorded_person',
        'relationship_recorded_relationship',
        'event_record',
        'place_record'
    )),
    CHECK (action != 'update' OR field_name IS NOT NULL)
);

-- ---------------------------------------------------------------------------
-- METRICS LAYER
-- ---------------------------------------------------------------------------
-- pipeline_run: one row per pipeline step execution.
-- stage 'conclusion' added in v4.2; all other stages present since v4.1.

CREATE TABLE pipeline_run (
    run_id               INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    stage                TEXT        NOT NULL,
    step_name            TEXT        NOT NULL,   -- e.g. 'ingest_census', 'run_person_resolution'
    records_processed    INTEGER,                -- count of items processed by this step
    duration_ms          INTEGER     NOT NULL,   -- elapsed time in milliseconds
    source_id            INTEGER,                -- optional: which census source (3=1901, 4=1911, 5=1926)
    notes                TEXT,                   -- optional: parse notes, errors, warnings
    session_ref          TEXT,                   -- optional: commit hash, Claude session ID, batch ID
    start_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    end_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CHECK (stage IN (
        'ingest', 'place', 'similarity', 'person',
        'relationship', 'event', 'validation', 'fetch', 'conclusion'
    ))
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
CREATE INDEX idx_person_recorded_person_recorded_person
    ON person_recorded_person (recorded_person_id);
CREATE INDEX idx_relationship_person1    ON relationship (person_id_1);
CREATE INDEX idx_relationship_person2    ON relationship (person_id_2);
CREATE INDEX idx_event_place             ON event (place_id);
CREATE INDEX idx_event_relationship      ON event (relationship_id);

-- Reverse lookup: all events for a person
CREATE INDEX idx_person_event_event      ON person_event (event_id);

-- Name variant scoring
CREATE INDEX idx_name_variant_value           ON name_variant (variant_value);
CREATE INDEX idx_name_variant_recorded_person ON name_variant (recorded_person_id);

-- Place authority lookups
CREATE INDEX idx_place_authority_logainm  ON place_authority (logainm_id);
CREATE INDEX idx_place_authority_type     ON place_authority (place_type);

-- Unverified linkage re-scoring passes (partial indexes)
CREATE INDEX idx_person_recorded_person_score
    ON person_recorded_person (score)
    WHERE verified = 0 AND score IS NOT NULL;

CREATE INDEX idx_relationship_recorded_relationship_score
    ON relationship_recorded_relationship (score)
    WHERE verified = 0 AND score IS NOT NULL;

CREATE INDEX idx_event_record_score
    ON event_record (score)
    WHERE verified = 0 AND score IS NOT NULL;

CREATE INDEX idx_place_record_score
    ON place_record (score)
    WHERE verified = 0 AND score IS NOT NULL;

-- Reverse lookup: relationship_recorded_relationship
CREATE INDEX idx_relationship_recorded_relationship_recorded_relationship
    ON relationship_recorded_relationship (recorded_relationship_id);

-- RecordedRelationship lookups
CREATE INDEX idx_recorded_relationship_person1 ON recorded_relationship (recorded_person_id_1);
CREATE INDEX idx_recorded_relationship_person2 ON recorded_relationship (recorded_person_id_2);

-- RecordSimilarity lookups
CREATE INDEX idx_record_similarity_record1 ON record_similarity (record_id_1);
CREATE INDEX idx_record_similarity_record2 ON record_similarity (record_id_2);

-- training_labels review workflow
CREATE INDEX idx_training_labels_decision    ON training_labels (decision);
CREATE INDEX idx_training_labels_person_id_1 ON training_labels (person_id_1);
CREATE INDEX idx_training_labels_person_id_2 ON training_labels (person_id_2);

-- Reviewer
CREATE INDEX idx_reviewer_type ON reviewer (type);

-- Conclusion log — primary access patterns
CREATE INDEX idx_conclusion_log_reviewer     ON conclusion_log (reviewer_id);
CREATE INDEX idx_conclusion_log_entity       ON conclusion_log (entity_type, entity_id);
CREATE INDEX idx_conclusion_log_created_at   ON conclusion_log (created_at);
CREATE INDEX idx_conclusion_log_change_group ON conclusion_log (change_group_id)
    WHERE change_group_id IS NOT NULL;

-- Bin view — pending_delete rows only
CREATE INDEX idx_person_pending_delete        ON person (pending_delete_at)
    WHERE status = 'pending_delete';
CREATE INDEX idx_relationship_pending_delete  ON relationship (pending_delete_at)
    WHERE status = 'pending_delete';
CREATE INDEX idx_event_pending_delete         ON event (pending_delete_at)
    WHERE status = 'pending_delete';

-- pipeline_run access patterns
CREATE INDEX idx_pipeline_run_start_at    ON pipeline_run (start_at DESC);
CREATE INDEX idx_pipeline_run_stage_step  ON pipeline_run (stage, step_name);
CREATE INDEX idx_pipeline_run_source_id   ON pipeline_run (source_id)
    WHERE source_id IS NOT NULL;
CREATE INDEX idx_pipeline_run_session_ref ON pipeline_run (session_ref)
    WHERE session_ref IS NOT NULL;

-- ---------------------------------------------------------------------------
-- TRIGGERS
-- ---------------------------------------------------------------------------
-- prevent_same_census_link: DB-level enforcement that a single Person conclusion
-- cannot be linked to two RecordedPersons from the same census source.
-- Mirrors the link_type=link_only constraint enforced at the Splink layer.

CREATE OR REPLACE FUNCTION check_no_same_census_link()
RETURNS TRIGGER AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM person_recorded_person prp
        JOIN recorded_person rp ON prp.recorded_person_id = rp.recorded_person_id
        JOIN record r            ON rp.record_id = r.record_id
        WHERE prp.person_id = NEW.person_id
          AND r.source_id = (
              SELECT r2.source_id FROM recorded_person rp2
              JOIN record r2 ON rp2.record_id = r2.record_id
              WHERE rp2.recorded_person_id = NEW.recorded_person_id
          )
          AND prp.recorded_person_id != NEW.recorded_person_id
    ) THEN
        RAISE EXCEPTION
            'Cannot link person % to recorded_person % from same census source',
            NEW.person_id, NEW.recorded_person_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER prevent_same_census_link
BEFORE INSERT ON person_recorded_person
FOR EACH ROW
EXECUTE FUNCTION check_no_same_census_link();
