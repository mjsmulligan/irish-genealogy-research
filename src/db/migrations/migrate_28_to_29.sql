-- GRA — Schema Migration v2.8 → v2.9
-- Adds training_labels table for linkage proposals and researcher review workflow.
--
-- Referenced by:
--   src/reconstruction/linkage.py  — writes rows with decision='proposed'
--   src/review.py (forthcoming)    — reads WHERE decision='proposed'
--
-- UNIQUE (person_id_1, person_id_2) supports INSERT OR IGNORE idempotency:
-- re-running linkage never duplicates an existing proposal.
-- CHECK (person_id_1 < person_id_2) enforces the merge contract (lower id = canonical).
-- score is nullable to distinguish algorithmic proposals (score set) from
-- manual researcher assertions (score NULL) — see open decision in ROADMAP.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS training_labels (
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

CREATE INDEX IF NOT EXISTS idx_training_labels_decision
    ON training_labels (decision);

CREATE INDEX IF NOT EXISTS idx_training_labels_person_id_1
    ON training_labels (person_id_1);

CREATE INDEX IF NOT EXISTS idx_training_labels_person_id_2
    ON training_labels (person_id_2);

PRAGMA user_version = 29;
