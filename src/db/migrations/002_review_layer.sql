-- GRA Migration 002 — Review Layer (schema v3.2 → v4.0)
-- 23 June 2026
--
-- Adds:
--   reviewer          — first-class entity for any agent creating/modifying conclusions
--   conclusion_log    — append-only audit trail for all conclusion-layer mutations
--   person.status / person.pending_delete_at
--   relationship.status / relationship.pending_delete_at
--   event.status / event.pending_delete_at
--
-- Apply via: python -m src.cli migrate (or psql manually)
-- Safe to run on a populated database — all new columns have defaults.

-- ---------------------------------------------------------------------------
-- 1. reviewer
-- ---------------------------------------------------------------------------

CREATE TABLE reviewer (
    reviewer_id  INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name         TEXT    NOT NULL CHECK (trim(name) != ''),
    type         TEXT    NOT NULL,
    notes        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CHECK (type IN ('pipeline', 'human', 'ai'))
);

-- Seed the two system reviewers
INSERT INTO reviewer (name, type, notes) VALUES
    ('pipeline:system',  'pipeline', 'Automated pipeline — initial conclusion creation'),
    ('human:unknown',    'human',    'Manual edits with no identified reviewer');

CREATE INDEX idx_reviewer_type ON reviewer (type);

-- ---------------------------------------------------------------------------
-- 2. conclusion_log
-- ---------------------------------------------------------------------------

CREATE TABLE conclusion_log (
    log_id           INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    reviewer_id      INTEGER NOT NULL REFERENCES reviewer (reviewer_id),
    action           TEXT    NOT NULL,
    entity_type      TEXT    NOT NULL,
    entity_id        INTEGER NOT NULL,
    field_name       TEXT,
    old_value        TEXT,
    new_value        TEXT,
    reason           TEXT,
    change_group_id  TEXT,
    session_ref      TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CHECK (action IN ('create', 'update', 'delete', 'verify', 'flag')),
    CHECK (entity_type IN (
        'person', 'relationship', 'event',
        'person_recorded_person',
        'relationship_recorded_relationship',
        'event_record',
        'place_record'
    )),
    -- field_name is required for update actions
    CHECK (action != 'update' OR field_name IS NOT NULL)
);

CREATE INDEX idx_conclusion_log_reviewer    ON conclusion_log (reviewer_id);
CREATE INDEX idx_conclusion_log_entity      ON conclusion_log (entity_type, entity_id);
CREATE INDEX idx_conclusion_log_change_group ON conclusion_log (change_group_id)
    WHERE change_group_id IS NOT NULL;
CREATE INDEX idx_conclusion_log_created_at  ON conclusion_log (created_at);

-- ---------------------------------------------------------------------------
-- 3. Lifecycle columns on conclusion tables
-- ---------------------------------------------------------------------------

ALTER TABLE person
    ADD COLUMN status             TEXT        NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'pending_delete')),
    ADD COLUMN pending_delete_at  TIMESTAMPTZ;

ALTER TABLE relationship
    ADD COLUMN status             TEXT        NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'pending_delete')),
    ADD COLUMN pending_delete_at  TIMESTAMPTZ;

ALTER TABLE event
    ADD COLUMN status             TEXT        NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'pending_delete')),
    ADD COLUMN pending_delete_at  TIMESTAMPTZ;

-- Partial indexes for the bin view (pending_delete rows only)
CREATE INDEX idx_person_pending_delete       ON person (pending_delete_at)
    WHERE status = 'pending_delete';
CREATE INDEX idx_relationship_pending_delete ON relationship (pending_delete_at)
    WHERE status = 'pending_delete';
CREATE INDEX idx_event_pending_delete        ON event (pending_delete_at)
    WHERE status = 'pending_delete';

-- ---------------------------------------------------------------------------
-- 4. Backfill: log existing conclusions as pipeline:system creates
-- ---------------------------------------------------------------------------
-- Inserts one log entry per existing person, relationship, and event row,
-- attributed to reviewer_id=1 (pipeline:system) with action='create'.
-- session_ref records the migration that created these entries.
-- change_group_id is null — these were individual pipeline operations,
-- not grouped researcher actions.

INSERT INTO conclusion_log
    (reviewer_id, action, entity_type, entity_id, reason, session_ref)
SELECT 1, 'create', 'person', person_id,
       'Backfilled by migration 002 — pre-review-layer pipeline conclusion',
       'migration:002_review_layer'
FROM person;

INSERT INTO conclusion_log
    (reviewer_id, action, entity_type, entity_id, reason, session_ref)
SELECT 1, 'create', 'relationship', relationship_id,
       'Backfilled by migration 002 — pre-review-layer pipeline conclusion',
       'migration:002_review_layer'
FROM relationship;

INSERT INTO conclusion_log
    (reviewer_id, action, entity_type, entity_id, reason, session_ref)
SELECT 1, 'create', 'event', event_id,
       'Backfilled by migration 002 — pre-review-layer pipeline conclusion',
       'migration:002_review_layer'
FROM event;

-- ---------------------------------------------------------------------------
-- 5. Version bump
-- ---------------------------------------------------------------------------

UPDATE gra_meta SET value = '40' WHERE key = 'schema_version';
