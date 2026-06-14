# Irish Genealogy Research — Database Schema

*Version 2.10 — June 2026*
*Audience: Developers and data engineers. This document is the authoritative specification for the SQLite database schema. It translates the data model defined in `data_dictionary.md` into concrete DDL. Read `conceptual_model.md` and `data_dictionary.md` first.*

---

## 1. Design Decisions

### SQLite

The database engine is **SQLite**. Rationale:

- The project is a two-collaborator model (Python + Claude). No concurrent write access, no server process required, no configuration overhead.
- The dataset is bounded — Irish townland-scale research, not a national index. SQLite handles tens of millions of rows without difficulty.
- A single `.db` file is portable, trivially backed up with `cp`, and opens directly in DB Browser for SQLite for ad-hoc inspection.
- Python's `sqlite3` module is in the standard library. No additional database dependency.

**SQLite version requirement:** 3.35.0 or later (released 2021-03-12). This version introduced `RETURNING` clauses and fixes for `CHECK` constraint reporting. macOS ships 3.43+; Ubuntu 22.04 ships 3.37+; the dev container (Python 3.12 image) ships a compatible version.

### Array fields → junction tables

The data dictionary defines several `array[integer]` fields representing many-to-many relationships (e.g. `Person.record_ids`, `Event.person_ids`, `Relationship.record_ids`). SQLite has no native array type. These fields are implemented as **junction tables** — one row per relationship, with a compound primary key.

Junction tables follow a consistent naming convention: `{owner}_{target}` in singular form, e.g. `person_record` for `Person.record_ids`.

### Person names → junction table

`Person.names` is an array of `{value, type}` objects. This is implemented as a dedicated `person_name` table rather than a JSON column. Rationale:

- Name search is a primary use case: finding all Persons with a given name or name variant requires an indexed column, not JSON parsing.
- A junction table gives a standard index on `value`, consistent vocabulary enforcement via `CHECK`, and `NOT NULL` constraints on both fields — none of which are available on a JSON TEXT column.
- The join cost on person fetch is negligible for the dataset sizes involved.

### Name variants → dedicated table

The reconstruction algorithm produces normalised name variants (Anglicised, Irish-language, and phonetic forms) for each name recorded in the evidence layer. These are stored in a dedicated `name_variant` table rather than appended to `recorded_person` or held in memory. Rationale:

- Variants are computed once and reused across multiple scoring passes; persisting them avoids redundant computation on large batches.
- The variant table is indexed on `variant_value`, enabling fast candidate retrieval during Jaro-Winkler batch loading — the same pattern as `idx_recorded_person_name`.
- Variants are derived data, not source evidence. Separating them from `recorded_person` preserves the evidence-layer invariant that `recorded_person` contains only verbatim source content.

### Scoring columns on linkage junction tables

The four linkage junction tables (`person_record`, `event_record`, `relationship_record`, `place_record`) carry three additional columns beyond their foreign keys:

- `score REAL` — the floating-point similarity score produced by the reconstruction algorithm when this linkage was asserted. Nullable: null for manually-asserted linkages (no algorithm score); non-null in [0.0, 1.0] for algorithm-scored linkages.
- `score_version TEXT` — the algorithm version string that produced the score. Null when `score` is null.
- `verified INTEGER`  — researcher override flag (0 = algorithm assertion or unreviewed manual assertion, 1 = researcher-verified). A verified linkage is never automatically overwritten by a re-scoring pass.

These columns live on the junction tables rather than on the conclusion objects because the score is a property of the specific record-to-conclusion linkage, not of the conclusion itself. A Person linked to three Records may have three different scores for those three linkages.

`confidence` on `relationship` and `event` has been removed. It was a static scalar that could not capture the per-linkage granularity the reconstruction algorithm requires. Aggregate confidence, if needed for display, is derived at query time from the scores across all linked Records.

Null score is the correct representation for a manually-asserted linkage (`assert_linkage()` in the service layer). The previous schema used `NOT NULL DEFAULT 0.0` with an empty score_version, which was a misleading sentinel. Migration script `migrate_25_to_26.sql` converts existing sentinel rows to null.

### URL parameter fields → JSON TEXT columns

`Source.source_parameters` and `Record.record_parameters` are both stored as JSON TEXT columns. Rationale:

- Parameter keys and values are heterogeneous across sources — there is no fixed schema to normalise into typed columns.
- These fields are read as a unit by the deep link builder, not queried individually. There is no use case requiring an index on a specific parameter key.
- JSON TEXT is consistent with `Source.column_schema`, which uses the same approach.

The Python layer is responsible for serialising these fields to JSON on write and deserialising on read. The DB layer applies no structural constraint beyond `TEXT` — validation that parameter keys match `record_parameter_names` is enforced by Python.

### Enforcing evidence-layer isolation at the DB level

Rule R27 (evidence-layer objects must not contain conclusion-layer foreign keys) is enforced architecturally: neither `record` nor `recorded_person` carry columns for `person_id`, `event_id`, `relationship_id`, or `place_id`. The schema makes the violation structurally impossible.

### Foreign key enforcement

SQLite does not enable foreign key enforcement by default. Every connection must execute `PRAGMA foreign_keys = ON` before performing any write operation. This is the responsibility of the Python layer — see §8.

### Integer primary keys and ROWID

All primary keys are declared `INTEGER PRIMARY KEY`. In SQLite this is an alias for the internal ROWID, making inserts and lookups by primary key O(log n) without a secondary index. IDs are assigned by the Python layer before insert (not auto-incremented by SQLite) to maintain determinism across sessions.

---

## 2. Schema Overview

```
FOUNDATIONAL
  repository
  source
  place_authority         — authoritative place identities seeded from logainm.ie

EVIDENCE
  record                  — includes inline event fields (event_type, date, date_qualifier,
                            date_as_recorded, place_as_recorded); always one event per record
  recorded_person         — N:1 with record
  name_variant            — derived normalised variants of recorded names; indexed for scoring

CONCLUSION
  person
  person_name             — one row per name; indexed for search
  relationship
  event

JUNCTION TABLES
  person_record           — Person.record_ids          [linkage: score, score_version, verified]
  person_event            — Person.event_ids / Event.person_ids  [structural; query either direction]
  relationship_record     — Relationship.record_ids    [linkage: score, score_version, verified]
  event_record            — Event.record_ids           [linkage: score, score_version, verified]
  place_record            — place_authority → record   [linkage: score, score_version, verified]

Removed in v2.8:
  recorded_event          — merged into record (1:1; no information lost)
  event_recorded_event    — redundant once recorded_event is merged
  person_relationship     — superseded by indexed queries on relationship.person_id_1/2
  relationship_event      — superseded by event.relationship_id column
  event_person            — superseded by person_event (single table, both directions)
```

---

## 3. DDL

### Foundational Layer

```sql
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
    record_url_template     TEXT,   -- URL template with {placeholder} tokens; null for sources without direct linking
    source_parameters       TEXT,   -- JSON object of Source-level URL parameter constants; null when all parameters are Record-level
    record_parameter_names  TEXT,   -- JSON array of parameter name strings expected from Record.record_parameters; null when source has no direct linking
    column_schema           TEXT,   -- JSON array of column name strings; null for narrative sources
    citation                TEXT,
    notes                   TEXT,

    CHECK (type IN (
        'valuation', 'tithe', 'census',
        'birth_registration', 'marriage_registration', 'death_registration',
        'parish_register', 'military', 'folklore'
    ))
);
```

---

### Evidence Layer

```sql
CREATE TABLE record (
    record_id           INTEGER PRIMARY KEY,
    source_id           INTEGER NOT NULL REFERENCES source (source_id),
    record_parameters   TEXT,   -- JSON object of Record-level URL parameter values; keys must match Source.record_parameter_names
    raw_text            TEXT    NOT NULL CHECK (trim(raw_text) != ''),

    -- Event fields (formerly on recorded_event; always 1:1 with record)
    event_type          TEXT    NOT NULL,
    date_as_recorded    TEXT,   -- verbatim; exempt from date format validation (Rule R36)
    date                TEXT,   -- normalised ISO 8601; validated by Python (Rule R36)
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
    age_as_recorded         TEXT,   -- verbatim; may be "about 30", "inf", etc.
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
```

---

### Conclusion Layer

```sql
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
    -- Rule R22: self-reference prohibition enforced at DB level.

    CHECK (type IN ('couple', 'parent_child', 'sibling'))
);

CREATE TABLE event (
    event_id        INTEGER PRIMARY KEY,
    type            TEXT    NOT NULL,
    date            TEXT,   -- normalised ISO 8601; validated by Python (Rule R36)
    date_qualifier  TEXT,
    place_id        INTEGER REFERENCES place (place_id),
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

CREATE TABLE place (
    place_id        INTEGER PRIMARY KEY,
    name            TEXT    NOT NULL CHECK (trim(name) != ''),
    townland_ie_url TEXT,
    logainm_id      INTEGER,
    logainm_url     TEXT,
    notes           TEXT
);
```

### Evidence Layer (continued) — Name Variants

```sql
CREATE TABLE name_variant (
    name_variant_id     INTEGER PRIMARY KEY,
    recorded_person_id  INTEGER NOT NULL REFERENCES recorded_person (recorded_person_id),
    variant_value       TEXT    NOT NULL CHECK (trim(variant_value) != ''),
    variant_type        TEXT    NOT NULL,
    -- variant_type values: 'anglicised', 'irish', 'phonetic', 'normalised'
    algorithm_version   TEXT    NOT NULL,
    notes               TEXT,

    CHECK (variant_type IN ('anglicised', 'irish', 'phonetic', 'normalised'))
);
```

---

### Junction Tables

All junction tables use a compound primary key on both columns. The ordering convention is `(owner_id, target_id)`.

The four **linkage junction tables** (`person_record`, `event_record`, `relationship_record`, `place_record`) carry additional scoring columns:

- `score REAL` — similarity score in [0.0, 1.0] assigned by the reconstruction algorithm.
  Null for manually-asserted linkages (no algorithm score).
- `score_version TEXT` — algorithm version string. Null when score is null.
- `verified INTEGER` — researcher override: 0 = algorithm assertion or unreviewed manual, 1 = researcher-verified.
  Verified rows are never overwritten by re-scoring passes.

```sql
-- Person.record_ids  (linkage junction — carries scoring columns)
CREATE TABLE person_record (
    person_id       INTEGER NOT NULL REFERENCES person (person_id),
    record_id       INTEGER NOT NULL REFERENCES record (record_id),
    score           REAL    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    score_version   TEXT,
    verified        INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    PRIMARY KEY (person_id, record_id)
);

-- Person.event_ids
CREATE TABLE person_event (
    person_id   INTEGER NOT NULL REFERENCES person (person_id),
    event_id    INTEGER NOT NULL REFERENCES event (event_id),
    PRIMARY KEY (person_id, event_id)
);

-- Relationship.record_ids  (linkage junction — carries scoring columns)
-- Note: person_relationship removed in v2.8; Person.relationship_ids is
-- queried directly via relationship.person_id_1 / person_id_2.
CREATE TABLE relationship_record (
    relationship_id INTEGER NOT NULL REFERENCES relationship (relationship_id),
    record_id       INTEGER NOT NULL REFERENCES record (record_id),
    score           REAL    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    score_version   TEXT,
    verified        INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    PRIMARY KEY (relationship_id, record_id)
);

-- Event.record_ids  (linkage junction — carries scoring columns)
-- Note: relationship_event removed in v2.8; event.relationship_id expresses this directly.
CREATE TABLE event_record (
    event_id        INTEGER NOT NULL REFERENCES event (event_id),
    record_id       INTEGER NOT NULL REFERENCES record (record_id),
    score           REAL    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    score_version   TEXT,
    verified        INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    PRIMARY KEY (event_id, record_id)
);

-- Place.record_ids  (linkage junction — carries scoring columns)
-- Note: event_recorded_event and event_person removed in v2.8.
-- person_event handles both person→event and event→person directions.
CREATE TABLE place_record (
    place_id        INTEGER NOT NULL REFERENCES place (place_id),
    record_id       INTEGER NOT NULL REFERENCES record (record_id),
    score           REAL    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    score_version   TEXT,
    verified        INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    PRIMARY KEY (place_id, record_id)
);
```

---

## 4. Indexes

The primary key indexes (via `INTEGER PRIMARY KEY`) cover all single-object lookups. The following secondary indexes cover the most frequent query patterns: ingest traversal (all children of a parent), linkage scoring (all RecordedPersons for a source batch), and conclusion reconstruction (all Records for a Person).

```sql
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

-- Reverse lookup on person_event (replaces former event_person index)
CREATE INDEX idx_person_event_event      ON person_event (event_id);

-- Name variant scoring
CREATE INDEX idx_name_variant_value           ON name_variant (variant_value);
CREATE INDEX idx_name_variant_recorded_person ON name_variant (recorded_person_id);

-- Place authority lookups
CREATE INDEX idx_place_authority_logainm  ON place_authority (logainm_id);
CREATE INDEX idx_place_authority_type     ON place_authority (place_type);

-- Unverified linkage re-scoring passes (null-score rows excluded)
CREATE INDEX idx_person_record_score       ON person_record (score)       WHERE verified = 0 AND score IS NOT NULL;
CREATE INDEX idx_event_record_score        ON event_record (score)        WHERE verified = 0 AND score IS NOT NULL;
CREATE INDEX idx_relationship_record_score ON relationship_record (score)  WHERE verified = 0 AND score IS NOT NULL;
CREATE INDEX idx_place_record_score        ON place_record (score)         WHERE verified = 0 AND score IS NOT NULL;
```

---

## 5. Validation Rule Mapping

This table documents which validation rules (from `validation_rules.md`) are enforced by the database schema itself versus which must be enforced by the Python layer. Rules enforced by both are noted.

| Rule | Description | DB enforcement | Python enforcement |
|---|---|---|---|
| R01 | Required fields on Repository | `NOT NULL` + `CHECK` on name, url | Yes |
| R02 | Required fields on Source | `NOT NULL` + `CHECK (trim(...) != '')` on title | Yes |
| R03 | raw_text required on Record | `NOT NULL` + `CHECK (trim(raw_text) != '')` | Yes |
| R04 | Required fields on RecordedEvent | **Retired** — event fields now on `record`; R03 covers them | N/A |
| R05 | Required fields on RecordedPerson | `NOT NULL` + `CHECK` on name_as_recorded; role is nullable (NULL = blank in source) | Yes |
| R06 | Required fields on Person | `NOT NULL` + `CHECK` on label | Yes |
| R07 | Required fields on Relationship | `NOT NULL` on type, person_id_1, person_id_2 | Yes |
| R08 | Required fields on Event | `NOT NULL` on type | Yes |
| R09 | Required fields on Place | `NOT NULL` + `CHECK` on name | Yes |
| R10 | Name object completeness | `NOT NULL` + `CHECK` on person_name table | Yes |
| R12 | Source → Repository FK | `REFERENCES repository` | Yes |
| R13 | Record → Source FK | `REFERENCES source` | Yes |
| R14 | RecordedEvent → Record FK | **Retired** — `recorded_event` table removed | N/A |
| R15 | RecordedPerson → Record FK | `REFERENCES record` | Yes |
| R16 | Person FK arrays | Junction table FKs | Yes |
| R17 | Relationship FK arrays | `REFERENCES person`; junction table FKs | Yes |
| R18 | Event FK arrays | `REFERENCES place`, `REFERENCES relationship`; junction table FKs | Yes |
| R19 | Place FK arrays | Junction table FKs | Yes |
| R20 | Exactly one RecordedEvent per Record | **Retired** — event fields are columns on `record`; one-event-per-record is structural | N/A |
| R21 | At least one RecordedPerson per Record | Not enforceable declaratively | **Python only** |
| R22 | Relationship self-reference | `CHECK (person_id_1 != person_id_2)` | No |
| R23 | Person ↔ Relationship bidirectionality | Retired — junction table is single source of truth | N/A |
| R24 | Person ↔ Event bidirectionality | Retired — junction table is single source of truth | N/A |
| R25 | Relationship ↔ Event bidirectionality | Retired — junction table is single source of truth | N/A |
| R26 | RecordedEvent ↔ Event Record consistency | **Retired** — `event_recorded_event` table removed | N/A |
| R27 | Evidence layer isolation | Retired — columns absent from schema | N/A |
| R28 | Source type vocabulary | `CHECK (type IN (...))` | Yes |
| R29 | Event type vocabulary | `CHECK (type IN (...))` on both tables | Yes |
| R30 | Date qualifier vocabulary | `CHECK (date_qualifier IN (...))` | Yes |
| R31 | RecordedPerson role vocabulary | `CHECK (role IN (...))` — see DDL for full list | Yes |
| R32 | Person gender vocabulary | `CHECK (gender IN (...))` | Yes |
| R33 | Name type vocabulary | `CHECK (type IN (...))` on person_name table | Yes |
| R34 | Relationship type vocabulary | `CHECK (type IN (...))` | Yes |
| R35 | Confidence vocabulary | **Retired** — `confidence` removed from `relationship` and `event` | N/A |
| R36 | Date format | Not enforceable declaratively in SQLite | **Python only** |
| R37 | record_parameters keys match record_parameter_names | Not enforceable declaratively | **Python only** |
| R38 | Linkage score range [0.0–1.0] or null | `CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0))` on scoring junction tables | Yes (pre-write) |
| R39 | verified flag values {0, 1} | `CHECK (verified IN (0, 1))` on scoring junction tables | Yes (pre-write) |

**Rules requiring Python-only enforcement:** R20 (lower bound), R21, R26, R36, R37.
**Retired rules:** R23, R24, R25, R27, R33, R35.

---

## 6. Python DataStore Mapping

The Python `DataStore` class maps the ten first-class objects to dictionaries keyed by primary key. This table shows how each DataStore collection maps to the database.

| DataStore attribute | DB table(s) | Notes |
|---|---|---|
| `ds.repositories` | `repository` | Simple 1:1 |
| `ds.sources` | `source` | `column_schema`, `source_parameters`, and `record_parameter_names` stored as JSON strings |
| `ds.records` | `record` | `record_parameters` stored as JSON string |
| `ds.recorded_persons` | `recorded_person` | Simple 1:1 |
| `ds.name_variants` | `name_variant` | Keyed by `recorded_person_id`; assembled as a list of `{variant_value, variant_type, algorithm_version}` dicts |
| `ds.persons` | `person` + `person_name` + junction tables | `names` assembled from `person_name` rows; `record_ids`, `event_ids`, `relationship_ids` from junction tables |
| `ds.relationships` | `relationship` + junction tables | `record_ids`, `event_ids` from junctions; no `confidence` field |
| `ds.events` | `event` + junction tables | `record_ids`, `recorded_event_ids`, `person_ids` from junctions; no `confidence` field |
| `ds.places` | `place` + junction tables | `record_ids` from junction |

On **read**, the Python layer assembles each Person object by joining `person` with `person_name` (for names) and the relevant junction tables (for ID arrays). For linkage junctions, the `score`, `score_version`, and `verified` columns are included in the assembled dict alongside the foreign key. On **write**, it inserts the main `person` row then inserts one `person_name` row per name entry.

The deep link builder is a utility function in `db.py` with the signature `build_record_url(source: dict, record: dict) -> str | None`. It merges `source["source_parameters"]` (deserialised from JSON) with `record["record_parameters"]` (deserialised from JSON) and substitutes each `{placeholder}` in `source["record_url_template"]`. Returns `None` if `record_url_template` is null.

---

## 7. Worked Example — Marriage Record

The following shows how the worked example from `conceptual_model.md` §7 maps to database rows.

**Foundational layer**

```sql
INSERT INTO repository VALUES (1, 'General Register Office, Ireland', 'https://www.irishgenealogy.ie', NULL);

INSERT INTO source VALUES (
    1, 1,
    'Civil Marriage Registrations, Boyle District, 1890',
    'marriage_registration',
    1890, 1890,
    'https://www.irishgenealogy.ie',
    'https://civilrecords.irishgenealogy.ie/churchrecords/images/marriage_returns/marriages_{year}/{folder_id}/{image_id}.pdf',
    NULL,                                                        -- source_parameters: all parameters are Record-level
    '["year", "folder_id", "image_id"]',                         -- record_parameter_names
    '["date","place","groom_name","groom_age","groom_occupation","bride_name","bride_age","father_of_groom","father_of_bride"]',
    'Civil Marriage Registrations, Boyle District, 1890. General Register Office, Ireland. irishgenealogy.ie, accessed May 2026.',
    NULL
);
```

**Evidence layer**

```sql
-- Record now carries event fields inline; no separate recorded_event insert.
INSERT INTO record VALUES (
    1, 1,
    '{"year": 1890, "folder_id": "marriages_1890_001", "image_id": "0042"}',  -- record_parameters
    '1890-01-10,Straness,John Mulligan,28,farmer,Mary Brennan,24,Patrick Mulligan,Thomas Brennan',
    'marriage',          -- event_type
    '10th Jany 1890',    -- date_as_recorded
    '1890-01-10',        -- date
    'exact',             -- date_qualifier
    'Straness',          -- place_as_recorded
    NULL                 -- notes
);
-- Deep link resolves to:
-- https://civilrecords.irishgenealogy.ie/churchrecords/images/marriage_returns/marriages_1890/marriages_1890_001/0042.pdf

INSERT INTO recorded_person VALUES (1, 1, 'John Mulligan',   'groom',           '28', 28, NULL, 'farmer', NULL, NULL);
INSERT INTO recorded_person VALUES (2, 1, 'Mary Brennan',    'bride',           '24', 24, NULL, NULL,     NULL, NULL);
INSERT INTO recorded_person VALUES (3, 1, 'Patrick Mulligan','father_of_groom', NULL, NULL, NULL, NULL,   NULL, NULL);
INSERT INTO recorded_person VALUES (4, 1, 'Thomas Brennan',  'father_of_bride', NULL, NULL, NULL, NULL,   NULL, NULL);
```

**Conclusion layer**

```sql
INSERT INTO place VALUES (1, 'Straness', 'https://www.townlands.ie/roscommon/.../straness/', 12345, 'https://www.logainm.ie/en/12345', NULL);

INSERT INTO person VALUES (1, 'John Mulligan (Boyle 1890)', 'male',  0, NULL);
INSERT INTO person VALUES (2, 'Mary Brennan (Boyle 1890)',  'female', 0, NULL);
INSERT INTO person VALUES (3, 'Patrick Mulligan',           'male',  0, NULL);
INSERT INTO person VALUES (4, 'Thomas Brennan',             'male',  0, NULL);

-- Person names
INSERT INTO person_name VALUES (1, 1, 'John Mulligan', 'birth_name');
INSERT INTO person_name VALUES (2, 2, 'Mary Brennan',  'birth_name');

INSERT INTO relationship VALUES (1, 'couple', 1, 2, 'Single civil registration record.');

INSERT INTO event VALUES (1, 'marriage', '1890-01-10', 'exact', 1, 1, NULL);

-- Junction rows: Person.record_ids  (score columns: score, score_version, verified)
INSERT INTO person_record VALUES (1, 1, 0.91, 'v1.0', 0);
INSERT INTO person_record VALUES (2, 1, 0.88, 'v1.0', 0);
INSERT INTO person_record VALUES (3, 1, 0.75, 'v1.0', 0);
INSERT INTO person_record VALUES (4, 1, 0.75, 'v1.0', 0);

-- Junction rows: Person.event_ids  (via person_event; also serves Event.person_ids direction)
INSERT INTO person_event VALUES (1, 1);
INSERT INTO person_event VALUES (2, 1);
INSERT INTO person_event VALUES (3, 1);
INSERT INTO person_event VALUES (4, 1);

-- Junction rows: Relationship.record_ids  (linkage junction)
INSERT INTO relationship_record VALUES (1, 1, 0.91, 'v1.0', 0);

-- Junction rows: Event.record_ids  (linkage junction; replaces both event_record and event_recorded_event)
INSERT INTO event_record VALUES (1, 1, 0.91, 'v1.0', 0);

-- Junction rows: place_authority → record  (linkage junction)
INSERT INTO place_record VALUES (1, 1, 0.85, 'v1.0', 0);
```

---

## 8. Connection Setup

Every Python connection must execute the following PRAGMAs immediately after opening. These are non-negotiable — foreign key enforcement is off by default in SQLite and PRAGMA settings do not persist across connections.

```python
import sqlite3

def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row  # access columns by name
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")   # concurrent reads during writes
    conn.execute("PRAGMA synchronous = NORMAL")  # safe with WAL; faster than FULL
    conn.execute("PRAGMA temp_store = MEMORY")
    return conn
```

`journal_mode = WAL` is strongly recommended. It allows reads while a write transaction is open, which matters during ingestion sessions where validation queries run concurrently with batch inserts.

---

## 9. Schema Initialisation

The complete schema is maintained in a single file `schema.sql`. The Python layer initialises a new database with:

```python
def init_db(path: str) -> sqlite3.Connection:
    conn = open_db(path)
    with open("schema.sql") as f:
        conn.executescript(f.read())
    conn.commit()
    return conn
```

`executescript()` implicitly commits any pending transaction before executing — call it only on a fresh database. For migrations, use explicit `ALTER TABLE` statements with a `schema_version` user-version pragma:

```python
# Record schema version on init
conn.execute("PRAGMA user_version = 30")  # version 2.10

# Check version on open
version = conn.execute("PRAGMA user_version").fetchone()[0]
if version != 30:
    raise RuntimeError(f"Schema version mismatch: expected 30, got {version}")
```

---

## 10. File Locations

```
/
  schema.sql              — complete DDL (CREATE TABLE + CREATE INDEX statements)
  genealogy.db            — SQLite database file (gitignored)
  src/
    db.py                 — open_db(), init_db(), build_record_url(), DataStore read/write methods
```

`genealogy.db` must be added to `.gitignore`. The database is a build artefact derived from `schema.sql` plus ingested data. The source of truth for schema structure is `schema.sql`; the source of truth for data is the raw ingest files plus the session logs.

---

## 11. Changelog

| Version | Date | Change |
|---|---|---|
| 2.1 | May 2026 | Initial SQLite schema document |
| 2.2 | May 2026 | Replaced `person.names` JSON TEXT column with `person_name` table. Added `idx_person_name_value` and `idx_person_name_person` indexes. Updated schema overview, DDL, validation rule mapping, DataStore mapping, and worked example accordingly. R10 and R33 reclassified from Python-only to DB+Python. |
| 2.3 | May 2026 | Replaced `record.source_identifier TEXT` with `record.record_parameters TEXT` (JSON). Added `source.source_parameters TEXT` (JSON) and `source.record_parameter_names TEXT` (JSON array) to the source table. Added §1 design decision explaining JSON TEXT choice for parameter fields. Added R37 (record_parameters key validation, Python-only) to validation rule mapping. Updated DataStore mapping to note JSON serialisation for new fields. Added `build_record_url()` utility to DataStore mapping and file locations. Updated worked example INSERT statements to reflect new column structure and show a resolved deep link URL. Schema user_version bumped to 23. |
| 2.4 | May 2026 | Removed `confidence TEXT` from `relationship` and `event` tables; retired R35. Added `score REAL`, `score_version TEXT`, `verified INTEGER` scoring columns to `person_record`, `event_record`, `relationship_record`, `place_record`; added R38 and R39. Added `name_variant` table with `variant_type` vocabulary `CHECK` and `algorithm_version`. Added `idx_name_variant_value`, `idx_name_variant_recorded_person`, and partial indexes on score for unverified linkage rows. Added §1 design decisions for name variants and scoring junction columns. Updated schema overview, validation rule mapping, DataStore mapping, and worked example. Schema user_version bumped to 24. |
| 2.5 | May 2026 | Expanded `recorded_person.role` CHECK constraint to cover full NAI census download vocabulary. Added census roles: `son`, `daughter`, `sibling`, `grandchild`, `in_law`, `niece_nephew`, `aunt_uncle`, `cousin`, `servant`, `visitor`, `boarder`. Removed `child` (replaced by `son`/`daughter`). Grouped CHECK values into census roles and event roles with inline comments. Updated R31 note in validation rule mapping. Schema user_version bumped to 25. |
| 2.6 | May 2026 | Made `score` and `score_version` nullable on all four linkage junction tables. Null score represents a manually-asserted linkage (OD-01 resolved). Updated partial indexes to exclude null-score rows. Added migration script `src/db/migrations/migrate_25_to_26.sql`. Schema user_version bumped to 26. |
| 2.7 | May 2026 | Added `place_authority` table (flat denormalised schema seeded from logainm.ie). Replaced `place` conclusion table. `event.place_id` now references `place_authority`. |
| 2.8 | June 2026 | Merged `recorded_event` into `record` (inline event fields). Dropped `event_recorded_event`, `person_relationship`, `relationship_event`, `event_person`. Retained `person_event` for both person↔event directions with added `idx_person_event_event` index. Junction table count reduced from 9 to 5. Added `idx_place_authority_logainm` and `idx_place_authority_type`. Schema user_version bumped to 28. Migration script `src/db/migrations/migrate_27_to_28.sql`. |
| 2.9 | June 2026 | Added `training_labels` table (linkage proposals + researcher review workflow). Added `event.is_primary BOOLEAN DEFAULT true` (consensus arbitration; set by rebuild-consensus stage). Schema user_version bumped to 29. Migration script `src/db/migrations/migrate_28_to_29.sql`. |
| 2.10 | June 2026 | Made `recorded_person.role` nullable (NULL = blank in source data). Added `'unknown'` to role CHECK vocabulary (value present in source but not mappable). Removed `NOT NULL` constraint from `recorded_person.role`. Updated R05. Schema user_version bumped to 30. Migration script `src/db/migrations/migrate_29_to_30.sql`. |

---

*Related documents: `conceptual_model.md`, `data_dictionary.md`, `validation_rules.md`, `reconstruction_algorithms.md`*

*Schema version: 2.10 — June 2026*
