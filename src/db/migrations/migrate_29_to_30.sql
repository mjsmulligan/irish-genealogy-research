-- GRA — Migration v2.9 → v2.10
-- June 2026
--
-- Changes:
--   - recorded_person.role made nullable (NULL = blank in source data)
--   - 'unknown' added to role vocabulary (value present but not mappable)
--
-- SQLite does not support ALTER COLUMN or DROP CONSTRAINT, so this migration
-- uses the standard recreate-and-copy pattern.
--
-- Safe to run on a populated database. Existing 'principal' rows written by
-- the ingest layer for blank/unmapped relationships will remain; re-ingest
-- after reset is the recommended path to clean them out.

PRAGMA foreign_keys = OFF;

BEGIN;

-- Step 1: Create replacement table with updated constraints
CREATE TABLE recorded_person_new (
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

-- Step 2: Copy all data
INSERT INTO recorded_person_new SELECT * FROM recorded_person;

-- Step 3: Swap tables
DROP TABLE recorded_person;
ALTER TABLE recorded_person_new RENAME TO recorded_person;

-- Step 4: Recreate indexes
CREATE INDEX idx_recorded_person_record ON recorded_person (record_id);
CREATE INDEX idx_recorded_person_name   ON recorded_person (name_as_recorded);

-- Step 5: Bump schema version
PRAGMA user_version = 30;

COMMIT;

PRAGMA foreign_keys = ON;
