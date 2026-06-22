# Irish Genealogy Research — Database Schema

*Version 3.2 — 19 June 2026*
*Audience: Developers and data engineers. This document is the authoritative specification for the SQLite database schema. It translates the data model defined in `data_dictionary.md` into concrete DDL. Read `conceptual_model.md` and `data_dictionary.md` first.*

______________________________________________________________________

## 1. Design Decisions

### Implementation status of this document

This rebuild pass brings the document's DDL in line with the actual `schema.sql` (previously out of sync) **and** carries forward the v2.6/v2.7 conceptual-model and data-dictionary changes that have not yet been implemented in code. Both states are marked explicitly throughout §3 so this document is never mistaken for a literal dump of the running database.

**Implemented** (`schema.sql`, `PRAGMA user_version = 30`): `repository`, `source`, `place_authority`, `record`, `recorded_person`, `name_variant`, `person`, `person_name`, `relationship`, `event` (including `is_primary`), `person_record`, `relationship_record`, `event_record`, `place_record`, `person_event`, `training_labels`.

**Target, not yet implemented** — sequenced for the implementation phase of the architecture rebuild (ROADMAP §4, items 10–11):

- `recorded_relationship` and `record_similarity` — new evidence-layer tables (conceptual_model.md §4.7–4.8).
- Rename `person_record` → `person_recorded_person` and `relationship_record` → `relationship_recorded_relationship`. This is not a cosmetic rename: the foreign key target changes from `record_id` to `recorded_person_id` / `recorded_relationship_id` respectively, per the Rule 2 evidence-correspondence principle (Person points to RecordedPerson, Relationship points to RecordedRelationship — not to the whole Record).
- Removal of `training_labels`, `training_repo.py`, and its callers in `linkage.py`. The table is conceptually retired (conceptual_model.md §3) but the code is deliberately untouched until this is sequenced as real implementation work — see the dedicated subsection below.

### SQLite

The database engine is **SQLite**. Rationale:

- The project is a two-collaborator model (Python + Claude). No concurrent write access, no server process required, no configuration overhead.
- The dataset is bounded — Irish townland-scale research, not a national index. SQLite handles tens of millions of rows without difficulty.
- A single `.db` file is portable, trivially backed up with `cp`, and opens directly in DB Browser for SQLite for ad-hoc inspection.
- Python's `sqlite3` module is in the standard library. No additional database dependency.

**SQLite version requirement:** 3.35.0 or later (released 2021-03-12). This version introduced `RETURNING` clauses and fixes for `CHECK` constraint reporting. macOS ships 3.43+; Ubuntu 22.04 ships 3.37+; the dev container (Python 3.12 image) ships a compatible version.

### Array fields → junction tables

The data dictionary defines several `array[integer]` fields representing many-to-many relationships (e.g. `Person.recorded_person_ids`, `Event.person_ids`, `Relationship.recorded_relationship_ids`). SQLite has no native array type. These fields are implemented as **junction tables** — one row per relationship, with a compound primary key.

Junction tables follow a consistent naming convention: `{owner}_{target}` in singular form, e.g. `person_recorded_person` for `Person.recorded_person_ids`.

### Person names → junction table

`Person.names` is an array of `{value, type}` objects. This is implemented as a dedicated `person_name` table rather than a JSON column. Rationale:

- Name search is a primary use case: finding all Persons with a given name or name variant requires an indexed column, not JSON parsing.
- A junction table gives a standard index on `value`, consistent vocabulary enforcement via `CHECK`, and `NOT NULL` constraints on both fields — none of which are available on a JSON TEXT column.
- The join cost on person fetch is negligible for the dataset sizes involved.

### Name variants → dedicated table

The reconstruction algorithm is designed to produce normalised name variants (Anglicised, Irish-language, and phonetic forms) for each name recorded in the evidence layer, stored in a dedicated `name_variant` table rather than appended to `recorded_person` or held in memory. Rationale:

- Variants are computed once and reused across multiple scoring passes; persisting them avoids redundant computation on large batches.
- The variant table is indexed on `variant_value`, enabling fast candidate retrieval during Jaro-Winkler batch loading.
- Variants are derived data, not source evidence. Separating them from `recorded_person` preserves the evidence-layer invariant that `recorded_person` contains only verbatim source content.

**Current status:** the table exists in `schema.sql` and is included in `reset_pipeline.py`'s reset scope, but no code path currently writes to it — `linkage.py` and `scoring.py` compute name comparisons in-memory rather than persisting through `name_variant`. It is not wrong, just unused; worth a flag for whoever picks up the scoring pipeline next, rather than something this rebuild pass resolves.

### Evidence-to-evidence comparisons: RecordedRelationship and RecordSimilarity *(target — not yet implemented)*

Two new evidence-layer tables, per conceptual_model.md §4.7–4.8:

- **`recorded_relationship`** — a relationship between two `recorded_person` rows, either stated directly by a source (a census household role pairing) or computed algorithmically (a cross-census candidate person-match). Uses the same type vocabulary as `relationship`, plus a `similarity` type carrying a Splink-style score.
- **`record_similarity`** — an algorithmic comparison between two `record` rows (e.g. a household-match score across census years). Has no conclusion-layer counterpart by design: it records a measurement, not an assertion.

These are deliberately distinct from the **linkage junction** pattern below. A linkage junction's `score` measures confidence in a conclusion-to-evidence link (e.g. "how sure are we this Person is documented by this Record"). `recorded_relationship.score` and `record_similarity.score` measure something upstream of any conclusion — similarity between two pieces of evidence, full stop. Neither table carries a `verified` column, because there is no conclusion-layer decision to verify; the comparison either stands as recorded or is superseded by a new algorithm run.

### Scoring columns on linkage junction tables

The four linkage junction tables — `person_recorded_person` *(target)*, `event_record`, `relationship_recorded_relationship` *(target)*, `place_record` — carry three additional columns beyond their foreign keys:

- `score REAL` — the floating-point similarity score produced by the reconstruction algorithm when this linkage was asserted. Nullable: null for manually-asserted linkages (no algorithm score); non-null in [0.0, 1.0] for algorithm-scored linkages.
- `score_version TEXT` — the algorithm version string that produced the score. Null when `score` is null.
- `verified INTEGER` — researcher override flag (0 = algorithm assertion or unreviewed manual assertion, 1 = researcher-verified). A verified linkage is never automatically overwritten by a re-scoring pass.

These columns live on the junction tables rather than on the conclusion objects because the score is a property of the specific evidence-to-conclusion linkage, not of the conclusion itself. A Person linked to three RecordedPersons may have three different scores for those three linkages.

`confidence` on `relationship` and `event` was removed in an earlier pass (v2.4). It was a static scalar that could not capture the per-linkage granularity the reconstruction algorithm requires. Aggregate confidence, if needed for display, is derived at query time from the scores across all linked evidence rows.

### URL parameter fields → JSON TEXT columns

`Source.source_parameters` and `Record.record_parameters` are both stored as JSON TEXT columns. Rationale:

- Parameter keys and values are heterogeneous across sources — there is no fixed schema to normalise into typed columns.
- These fields are read as a unit by the deep link builder, not queried individually. There is no use case requiring an index on a specific parameter key.
- JSON TEXT is consistent with `Source.column_schema`, which uses the same approach.

The Python layer is responsible for serialising these fields to JSON on write and deserialising on read. The DB layer applies no structural constraint beyond `TEXT` — validation that parameter keys match `record_parameter_names` is enforced by Python.

### Enforcing evidence-layer isolation at the DB level

Rule R27 (evidence-layer objects must not contain conclusion-layer foreign keys) is enforced architecturally: none of `record`, `recorded_person`, `recorded_relationship` *(target)*, or `record_similarity` *(target)* carry columns for `person_id`, `event_id`, `relationship_id`, or `place_id`. The schema makes the violation structurally impossible.

### Foreign key enforcement

SQLite does not enable foreign key enforcement by default. Every connection must execute `PRAGMA foreign_keys = ON` before performing any write operation. This is the responsibility of the Python layer — see §8.

### Integer primary keys and ROWID

All primary keys are declared `INTEGER PRIMARY KEY`. In SQLite this is an alias for the internal ROWID, making inserts and lookups by primary key O(log n) without a secondary index. IDs are assigned by the Python layer before insert (not auto-incremented by SQLite) to maintain determinism across sessions.

### `training_labels`: conceptually retired, retained in schema

`training_labels` holds cross-census person-linkage proposals written by `linkage.py` and reviewed by a researcher workflow (`decision`: `proposed` → `accepted` / `rejected` / `flagged`). It is fully implemented and in active use today.

conceptual_model.md §3 documents it as a path that was "considered, built, and rejected" — the gap it was meant to fill (recording a candidate match before committing to it) is now reached for differently, as the `similarity` type on `recorded_relationship`, evidence-side rather than conclusion-side. The code and schema are left in place deliberately: removing `training_labels`, `src/dal/training_repo.py`, and its callers is real engineering work, not a documentation change, and is sequenced for the implementation phase (ROADMAP §4, item 11) rather than bundled into this rebuild. The DDL below reflects what is actually running; the retirement note is here so it isn't mistaken for part of the target design going forward.

______________________________________________________________________

## 2. Schema Overview

```
FOUNDATIONAL
  repository
  source
  place_authority              — authoritative place identities seeded from logainm.ie

EVIDENCE
  record                       — includes inline event fields (event_type, date, date_qualifier,
                                  date_as_recorded, place_as_recorded); always one event per record
  recorded_person               — N:1 with record
  recorded_relationship  [target] — relationship between two recorded_person rows; semantic types
                                  plus an algorithmic 'similarity' type
  record_similarity      [target] — algorithmic comparison between two record rows; no conclusion
                                  counterpart by design
  name_variant                 — derived normalised name variants; defined, currently unwritten

CONCLUSION
  person
  person_name                  — one row per name; indexed for search
  relationship
  event                         — carries is_primary (Rule 9 consensus arbitration)

JUNCTION TABLES
  person_recorded_person          [target, renamed from person_record]       — Person.recorded_person_ids
                                   [linkage: score, score_version, verified]
  relationship_recorded_relationship [target, renamed from relationship_record] — Relationship.recorded_relationship_ids
                                   [linkage: score, score_version, verified]
  event_record                  — Event.record_ids        [linkage: score, score_version, verified]
  place_record                  — place_authority.record_ids [linkage: score, score_version, verified]
  person_event                  — Person.event_ids / Event.person_ids [structural; query either direction]

REVIEW / TRAINING LAYER
  training_labels                — conceptually retired (see §1); code/schema retained; removal
                                  sequenced for the implementation phase, not this rebuild

Removed in earlier passes (v2.7–v2.8):
  place                  — superseded by place_authority (flat schema seeded from logainm.ie)
  recorded_event          — merged into record (1:1; no information lost)
  event_recorded_event    — redundant once recorded_event is merged
  person_relationship     — superseded by indexed queries on relationship.person_id_1/2
  relationship_event      — superseded by event.relationship_id column
  event_person             — superseded by person_event (single table, both directions)
```

______________________________________________________________________

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
    record_parameter_names  TEXT,   -- JSON array of parameter name strings expected from Record.record_parameters
    column_schema           TEXT,   -- JSON array of column name strings; null for narrative sources
    citation                TEXT,
    notes                   TEXT,

    CHECK (type IN (
        'valuation', 'tithe', 'census',
        'birth_registration', 'marriage_registration', 'death_registration',
        'parish_register', 'military', 'folklore', 'place_authority'
    ))
);

-- Authoritative place identities. Foundational, not concluded — seeded from
-- logainm.ie via fetch-places/seed-places, never written through the normal
-- conclusion pipeline (Rule 8). Flat denormalised hierarchy: county, barony,
-- civil parish, and DED are columns on each row, not a junction table.
CREATE TABLE place_authority (
    place_id            INTEGER PRIMARY KEY,
    logainm_id           INTEGER UNIQUE,    -- null for manually-added entities (e.g. church parishes)
    name_en              TEXT    NOT NULL CHECK (trim(name_en) != ''),
    place_type           TEXT    NOT NULL,
    parent_name          TEXT,
    parent_id            INTEGER,
    parent_type          TEXT,
    ded_name              TEXT,
    ded_id                INTEGER,
    county_name           TEXT,
    county_id             INTEGER,
    barony_name           TEXT,
    barony_id             INTEGER,
    civil_parish_name     TEXT,
    civil_parish_id       INTEGER,
    latitude              REAL,
    longitude             REAL,
    logainm_url           TEXT,
    notes                 TEXT,

    CHECK (place_type IN (
        'province', 'county', 'barony', 'civil_parish',
        'ded', 'townland', 'church_parish', 'town'
    ))
);
```

______________________________________________________________________

### Evidence Layer

```sql
CREATE TABLE record (
    record_id           INTEGER PRIMARY KEY,
    source_id           INTEGER NOT NULL REFERENCES source (source_id),
    record_parameters   TEXT,   -- JSON object of Record-level URL parameter values; keys must match Source.record_parameter_names
    raw_text            TEXT    NOT NULL CHECK (trim(raw_text) != ''),

    -- Event fields (formerly on recorded_event; always 1:1 with record — Rule 3)
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
    role                    TEXT,   -- NULL = blank in source; 'unknown' = value present but not mappable (nullable since v3.0)
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

#### `recorded_relationship` — Evidence *(target, not yet implemented)*

A relationship between two RecordedPersons, asserted by a source or computed algorithmically. Requires no Person to exist on either side (Rule 10). The two RecordedPersons may belong to the same Record (a census household role pairing) or to different Records (a cross-census candidate match).

```sql
CREATE TABLE recorded_relationship (
    recorded_relationship_id  INTEGER PRIMARY KEY,
    recorded_person_id_1      INTEGER NOT NULL REFERENCES recorded_person (recorded_person_id),
    recorded_person_id_2      INTEGER NOT NULL REFERENCES recorded_person (recorded_person_id),
    type                       TEXT    NOT NULL,
    score                      REAL,   -- required when type = 'similarity'; null otherwise
    score_version              TEXT,   -- null when score is null
    notes                      TEXT,

    CHECK (recorded_person_id_1 != recorded_person_id_2),
    CHECK (type IN ('couple', 'parent_child', 'sibling', 'similarity')),
    -- score is required exactly when type is the algorithmic 'similarity' type
    CHECK ((type = 'similarity') = (score IS NOT NULL)),
    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    CHECK ((score IS NULL) = (score_version IS NULL))
);
```

#### `record_similarity` — Evidence *(target, not yet implemented)*

An algorithmic comparison between two Records — e.g. a score suggesting the same household's return appears in two different census years. No conclusion-layer counterpart by design: it records a measurement, not an assertion (Rule 11).

```sql
CREATE TABLE record_similarity (
    record_similarity_id  INTEGER PRIMARY KEY,
    record_id_1            INTEGER NOT NULL REFERENCES record (record_id),
    record_id_2            INTEGER NOT NULL REFERENCES record (record_id),
    score                   REAL    NOT NULL CHECK (score >= 0.0 AND score <= 1.0),
    score_version           TEXT    NOT NULL,
    notes                   TEXT,

    CHECK (record_id_1 != record_id_2)
);
```

#### Name Variants

```sql
-- Defined and indexed, but currently unwritten by any pipeline stage — see §1.
CREATE TABLE name_variant (
    name_variant_id     INTEGER PRIMARY KEY,
    recorded_person_id  INTEGER NOT NULL REFERENCES recorded_person (recorded_person_id),
    variant_value       TEXT    NOT NULL CHECK (trim(variant_value) != ''),
    variant_type        TEXT    NOT NULL,
    algorithm_version   TEXT    NOT NULL,
    notes               TEXT,

    CHECK (variant_type IN ('anglicised', 'irish', 'phonetic', 'normalised'))
);
```

______________________________________________________________________

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
    -- Note: 'similarity' is valid on recorded_relationship.type only — it is
    -- an evidence-layer-only extension, never a valid conclusion-layer value.
);

-- Unlike Person and Relationship, Event permits multiple competing conclusions
-- of the same type for the same Person. Exactly one per (person, type) pair
-- is marked is_primary — the current best estimate, re-derived idempotently
-- by rebuild-consensus from event_record vote counts (Rule 9).
CREATE TABLE event (
    event_id        INTEGER PRIMARY KEY,
    type            TEXT    NOT NULL,
    date            TEXT,   -- normalised ISO 8601; validated by Python (Rule R36)
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
```

______________________________________________________________________

### Junction Tables

All junction tables use a compound primary key on both columns. The ordering convention is `(owner_id, target_id)`.

The four **linkage junction tables** carry additional scoring columns:

- `score REAL` — similarity score in [0.0, 1.0] assigned by the reconstruction algorithm. Null for manually-asserted linkages (no algorithm score).
- `score_version TEXT` — algorithm version string. Null when score is null.
- `verified INTEGER` — researcher override: 0 = algorithm assertion or unreviewed manual, 1 = researcher-verified. Verified rows are never overwritten by re-scoring passes.

```sql
-- Person.recorded_person_ids  [target, renamed from person_record]
-- The FK target changes from record_id to recorded_person_id here, not just
-- the table name: a Person now links to the specific RecordedPerson row that
-- evidences it, not to the whole Record it appears within (Rule 2).
CREATE TABLE person_recorded_person (
    person_id            INTEGER NOT NULL REFERENCES person (person_id),
    recorded_person_id   INTEGER NOT NULL REFERENCES recorded_person (recorded_person_id),
    score                 REAL    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    score_version         TEXT,
    verified               INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    PRIMARY KEY (person_id, recorded_person_id)
);

-- Relationship.recorded_relationship_ids  [target, renamed from relationship_record]
-- Same Rule 2 shift: FK target moves from record_id to recorded_relationship_id.
CREATE TABLE relationship_recorded_relationship (
    relationship_id            INTEGER NOT NULL REFERENCES relationship (relationship_id),
    recorded_relationship_id   INTEGER NOT NULL REFERENCES recorded_relationship (recorded_relationship_id),
    score                       REAL    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    score_version                TEXT,
    verified                      INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    PRIMARY KEY (relationship_id, recorded_relationship_id)
);

-- Event.record_ids  — unchanged. Event continues to point to Record directly
-- (Rule 2's explicit carve-out): event fields are inline on Record itself,
-- so there is no more specific evidence object for Event to point to.
CREATE TABLE event_record (
    event_id        INTEGER NOT NULL REFERENCES event (event_id),
    record_id       INTEGER NOT NULL REFERENCES record (record_id),
    score           REAL    CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
    score_version   TEXT,
    verified        INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    PRIMARY KEY (event_id, record_id)
);

-- place_authority.record_ids  — unchanged (Rule 8 mechanism, distinct from
-- Rule 2's conclusion-evidence correspondence).
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
```

______________________________________________________________________

### Review / Training Layer

`training_labels` holds cross-census person-linkage proposals generated by `linkage.py` and researcher decisions made via the review workflow. Conceptually retired (see §1) but fully implemented and in active use — this DDL matches `schema.sql` exactly.

```sql
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
    -- Lower person_id canonical; makes INSERT OR IGNORE idempotent across
    -- linkage re-runs and matches the _UnionFind merge convention.
);
```

______________________________________________________________________

## 4. Indexes

The primary key indexes (via `INTEGER PRIMARY KEY`) cover all single-object lookups. The following secondary indexes cover the most frequent query patterns: ingest traversal, linkage scoring, and conclusion reconstruction.

```sql
-- Ingest traversal
CREATE INDEX idx_record_source           ON record (source_id);
CREATE INDEX idx_recorded_person_record  ON recorded_person (record_id);

-- Linkage scoring: name candidate lookup
CREATE INDEX idx_recorded_person_name    ON recorded_person (name_as_recorded);
CREATE INDEX idx_person_name_value       ON person_name (value);
CREATE INDEX idx_person_name_person      ON person_name (person_id);

-- Reconstruction
CREATE INDEX idx_relationship_person1    ON relationship (person_id_1);
CREATE INDEX idx_relationship_person2    ON relationship (person_id_2);
CREATE INDEX idx_event_place             ON event (place_id);
CREATE INDEX idx_event_relationship      ON event (relationship_id);

-- Reverse lookup on person_event
CREATE INDEX idx_person_event_event      ON person_event (event_id);

-- Name variant scoring
CREATE INDEX idx_name_variant_value           ON name_variant (variant_value);
CREATE INDEX idx_name_variant_recorded_person ON name_variant (recorded_person_id);

-- Place authority lookups
CREATE INDEX idx_place_authority_logainm  ON place_authority (logainm_id);
CREATE INDEX idx_place_authority_type     ON place_authority (place_type);

-- Unverified linkage re-scoring passes (partial indexes; null-score rows excluded)
CREATE INDEX idx_event_record_score        ON event_record (score)        WHERE verified = 0 AND score IS NOT NULL;
CREATE INDEX idx_place_record_score        ON place_record (score)        WHERE verified = 0 AND score IS NOT NULL;

-- training_labels review workflow
CREATE INDEX idx_training_labels_decision    ON training_labels (decision);
CREATE INDEX idx_training_labels_person_id_1 ON training_labels (person_id_1);
CREATE INDEX idx_training_labels_person_id_2 ON training_labels (person_id_2);

-- ---- target indexes, accompanying the renamed/new tables above ----

-- Person.recorded_person_ids reverse lookup [renamed from idx_person_record_record]
CREATE INDEX idx_person_recorded_person_recorded_person
    ON person_recorded_person (recorded_person_id);

-- Relationship.recorded_relationship_ids reverse lookup [new]
CREATE INDEX idx_relationship_recorded_relationship_recorded_relationship
    ON relationship_recorded_relationship (recorded_relationship_id);

-- Renamed score indexes [from idx_person_record_score / idx_relationship_record_score]
CREATE INDEX idx_person_recorded_person_score
    ON person_recorded_person (score) WHERE verified = 0 AND score IS NOT NULL;
CREATE INDEX idx_relationship_recorded_relationship_score
    ON relationship_recorded_relationship (score) WHERE verified = 0 AND score IS NOT NULL;

-- RecordedRelationship traversal [new]
CREATE INDEX idx_recorded_relationship_person1 ON recorded_relationship (recorded_person_id_1);
CREATE INDEX idx_recorded_relationship_person2 ON recorded_relationship (recorded_person_id_2);

-- RecordSimilarity traversal [new]
CREATE INDEX idx_record_similarity_record1 ON record_similarity (record_id_1);
CREATE INDEX idx_record_similarity_record2 ON record_similarity (record_id_2);
```

______________________________________________________________________

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
| R09 | Required fields on PlaceAuthority | `NOT NULL` + `CHECK` on name_en, place_type | Yes |
| R10 | Name object completeness | `NOT NULL` + `CHECK` on person_name table | Yes |
| R12 | Source → Repository FK | `REFERENCES repository` | Yes |
| R13 | Record → Source FK | `REFERENCES source` | Yes |
| R14 | RecordedEvent → Record FK | **Retired** — `recorded_event` table removed | N/A |
| R15 | RecordedPerson → Record FK | `REFERENCES record` | Yes |
| R16 | Person FK arrays | Junction table FKs | Yes |
| R17 | Relationship FK arrays | `REFERENCES person`; junction table FKs | Yes |
| R18 | Event FK arrays | `REFERENCES place_authority`, `REFERENCES relationship`; junction table FKs | Yes |
| R19 | PlaceAuthority FK arrays | Junction table FKs | Yes |
| R20 | Exactly one RecordedEvent per Record | **Retired** — event fields are columns on `record`; one-event-per-record is structural | N/A |
| R21 | At least one RecordedPerson per Record | Not enforceable declaratively | **Python only** |
| R22 | Relationship self-reference | `CHECK (person_id_1 != person_id_2)` | No |
| R23–R26 | Bidirectionality / RecordedEvent consistency | **Retired** — junction tables are single source of truth; `event_recorded_event` removed | N/A |
| R27 | Evidence layer isolation | Retired — columns absent from schema | N/A |
| R28 | Source type vocabulary | `CHECK (type IN (...))` (now includes `place_authority`) | Yes |
| R29 | Event type vocabulary | `CHECK (type IN (...))` on both tables | Yes |
| R30 | Date qualifier vocabulary | `CHECK (date_qualifier IN (...))` | Yes |
| R31 | RecordedPerson role vocabulary | `CHECK (role IN (...))`, nullable — see DDL for full list | Yes |
| R32 | Person gender vocabulary | `CHECK (gender IN (...))` | Yes |
| R33 | Name type vocabulary | `CHECK (type IN (...))` on person_name table | Yes |
| R34 | Relationship type vocabulary | `CHECK (type IN (...))` | Yes |
| R35 | Confidence vocabulary | **Retired** — `confidence` removed from `relationship` and `event` | N/A |
| R36 | Date format | Not enforceable declaratively in SQLite | **Python only** |
| R37 | record_parameters keys match record_parameter_names | Not enforceable declaratively | **Python only** |
| R38 | Linkage score range [0.0–1.0] or null | `CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0))` on scoring tables | Yes (pre-write) |
| R39 | verified flag values {0, 1} | `CHECK (verified IN (0, 1))` on linkage junction tables | Yes (pre-write) |

**Rules requiring Python-only enforcement:** R20 (lower bound), R21, R26, R36, R37.
**Retired rules:** R23, R24, R25, R27, R33, R35.

**Pending rules (R47–R50)** — the following DDL-level constraints exist on tables added after the main rule set was written. They have been assigned R-numbers in `validation_rules.md` §7 (as of v2.7 rules) and are included in the table above. No Python enforcement exists yet — DB `CHECK` clauses are the sole gate until the implementation phase:

| Rule | Description | DB enforcement | Python enforcement |
|---|---|---|---|
| R47 | Required fields on RecordedRelationship; `type` vocabulary (couple, parent_child, sibling, similarity) | `NOT NULL`; `CHECK (type IN (...))` on `recorded_relationship` *(target)* | **Pending** |
| R48 | RecordedRelationship FK integrity; self-reference prohibition | `REFERENCES recorded_person`; `CHECK (recorded_person_id_1 != recorded_person_id_2)` on `recorded_relationship` *(target)* | **Pending** |
| R48 (score) | `score`/`score_version` conditional-on-type: required when `type = 'similarity'`, null otherwise; score range [0.0–1.0] | `CHECK ((type = 'similarity') = (score IS NOT NULL))`; `CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0))`; `CHECK ((score IS NULL) = (score_version IS NULL))` on `recorded_relationship` *(target)* | **Pending** |
| R49 | Required fields on RecordSimilarity; score range [0.0–1.0]; self-reference prohibition | `NOT NULL` on score, score_version; `CHECK (score >= 0.0 AND score <= 1.0)`; `CHECK (record_id_1 != record_id_2)` on `record_similarity` *(target)* | **Pending** |
| R50 | `training_labels` write guard (table is conceptually retired; no new rows should be written) | None — no DB-level barrier prevents inserts | **Pending** |

______________________________________________________________________

## 6. Python DAL Mapping

There is no `DataStore` class — that description in earlier versions of this document was stale (`src/service.py` was removed; see `future_ideas.md`). Data access is a **repository-per-table** pattern: `src/dal/*.py` holds the only raw SQL in the codebase, one file per primary table domain, called directly by `src/ingest/` and `src/pipeline/` modules. `src/cli.py` is the sole entry point that wires these together.

| DAL module | Tables touched | Notes |
|---|---|---|
| `source_repo.py` | `source` | Read-only; `source` rows are seeded once via `seed.sql` |
| `record_repo.py` | `record`, `recorded_person` | Read functions for pipeline stages; insert functions called only from `src/ingest/census.py` — the evidence layer is never written after ingest |
| `person_repo.py` | `person`, `person_name`, `person_record` | `next_ids()` also allocates `relationship_id`/`event_id`/`person_name_id` for household_inference in one call |
| `relationship_repo.py` | `relationship`, `relationship_record` | Smallest DAL file — two insert functions, no reads yet |
| `event_repo.py` | `event`, `event_record`, `person_event` | Includes the `is_primary` consensus machinery: `get_vote_counts()` and `set_is_primary()` back the `rebuild-consensus` CLI command |
| `place_repo.py` | `place_authority`, `place_record` | No insert function for `place_authority` itself — rows arrive via `fetch_places.py`/`seed_places.py`, not through this DAL file |
| `training_repo.py` | `training_labels` | Conceptually retired (§1) but actively called by `linkage.py`; includes the merge-repointing logic (`get_stale_rows`, `reinsert_repointed`) that keeps proposals consistent across `_UnionFind` merges |

**Gaps, as of this rebuild:**

- `repository` has no dedicated DAL file — it is seeded once via `seed.sql` and never written by application code, so there has been nothing to put one.
- `name_variant` has no DAL file — consistent with §1's note that nothing currently writes to this table.
- `recorded_relationship` and `record_similarity` have no DAL file yet — they don't exist in `schema.sql`. A `recorded_relationship_repo.py` (or folding into `record_repo.py`, which already owns the evidence layer) is implementation-phase work once the target tables land.

On read, callers assemble a Person by joining `person` with `person_name` and the relevant junction tables. For linkage junctions, `score`, `score_version`, and `verified` come along with the foreign key. On write, `person_repo.insert_person()` and `insert_person_name()` are called separately — there's no single "save a Person" call that bundles names.

The deep link builder is `build_record_url(source: dict, record: dict) -> str | None` in `src/db/db.py`. It merges `source["source_parameters"]` (deserialised from JSON) with `record["record_parameters"]` (deserialised from JSON) and substitutes each `{placeholder}` in `source["record_url_template"]`. Returns `None` if `record_url_template` is null; raises `ValueError` if a placeholder remains unresolved after the merge.

______________________________________________________________________

## 7. Worked Example — Marriage Record

The following shows how the worked example from `conceptual_model.md` maps to database rows, updated for the target schema (place_authority, recorded_relationship, and the renamed junction tables).

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

-- Straness townland, Tullynaught DED, Donegal (matches conceptual_model.md §4.3)
INSERT INTO place_authority VALUES (
    1,                                      -- place_id
    12345,                                  -- logainm_id
    'Straness',                             -- name_en
    'townland',                             -- place_type
    'Tullynaught', 111482, 'ded',           -- parent_name, parent_id, parent_type
    'Tullynaught', 111482,                  -- ded_name, ded_id
    'Donegal', 100013,                      -- county_name, county_id
    'Tirhugh', 52,                          -- barony_name, barony_id
    'Drumhome', 785,                        -- civil_parish_name, civil_parish_id
    NULL, NULL,                             -- latitude, longitude
    'https://www.logainm.ie/en/12345',      -- logainm_url
    NULL                                    -- notes
);
```

**Evidence layer**

```sql
INSERT INTO record VALUES (
    1, 1,
    '{"year": 1890, "folder_id": "marriages_1890_001", "image_id": "0042"}',  -- record_parameters
    '1890-01-10,Straness,John Mulligan,28,farmer,Mary Brennan,24,Patrick Mulligan,Thomas Brennan',
    'marriage',          -- event_type
    '10th Jany 1890',    -- date_as_recorded
    '1890-01-10',        -- date
    'exact',              -- date_qualifier
    'Straness',           -- place_as_recorded
    NULL                  -- notes
);
-- Deep link resolves to:
-- https://civilrecords.irishgenealogy.ie/churchrecords/images/marriage_returns/marriages_1890/marriages_1890_001/0042.pdf

INSERT INTO recorded_person VALUES (1, 1, 'John Mulligan',   'groom',           '28', 28, NULL, 'farmer', NULL, NULL);
INSERT INTO recorded_person VALUES (2, 1, 'Mary Brennan',    'bride',           '24', 24, NULL, NULL,     NULL, NULL);
INSERT INTO recorded_person VALUES (3, 1, 'Patrick Mulligan','father_of_groom', NULL, NULL, NULL, NULL,   NULL, NULL);
INSERT INTO recorded_person VALUES (4, 1, 'Thomas Brennan',  'father_of_bride', NULL, NULL, NULL, NULL,   NULL, NULL);

-- target: the groom/bride role pairing is itself evidence of a relationship,
-- independent of whether John or Mary is yet concluded to be a real Person (Rule 10)
INSERT INTO recorded_relationship VALUES (
    1, 1, 2, 'couple', NULL, NULL,
    'Stated by groom/bride roles on the marriage record.'
);
```

**Conclusion layer**

```sql
INSERT INTO person VALUES (1, 'John Mulligan (Boyle 1890)', 'male',  0, NULL);
INSERT INTO person VALUES (2, 'Mary Brennan (Boyle 1890)',  'female', 0, NULL);
INSERT INTO person VALUES (3, 'Patrick Mulligan',           'male',  0, NULL);
INSERT INTO person VALUES (4, 'Thomas Brennan',             'male',  0, NULL);

-- Person names
INSERT INTO person_name VALUES (1, 1, 'John Mulligan', 'birth_name');
INSERT INTO person_name VALUES (2, 2, 'Mary Brennan',  'birth_name');

INSERT INTO relationship VALUES (1, 'couple', 1, 2, 'Single civil registration record.');

-- is_primary defaults to 1 — no competing birth-year Event exists for this marriage
INSERT INTO event VALUES (1, 'marriage', '1890-01-10', 'exact', 1, 1, 1, NULL);

-- target: Person → RecordedPerson directly, not Person → Record (Rule 2)
INSERT INTO person_recorded_person VALUES (1, 1, 0.91, 'v1.0', 0);
INSERT INTO person_recorded_person VALUES (2, 2, 0.88, 'v1.0', 0);
INSERT INTO person_recorded_person VALUES (3, 3, 0.75, 'v1.0', 0);
INSERT INTO person_recorded_person VALUES (4, 4, 0.75, 'v1.0', 0);

-- Junction rows: Person.event_ids  (via person_event; also serves Event.person_ids direction)
INSERT INTO person_event VALUES (1, 1);
INSERT INTO person_event VALUES (2, 1);
INSERT INTO person_event VALUES (3, 1);
INSERT INTO person_event VALUES (4, 1);

-- target: Relationship → RecordedRelationship directly, not Relationship → Record (Rule 2)
INSERT INTO relationship_recorded_relationship VALUES (1, 1, 0.91, 'v1.0', 0);

-- Junction rows: Event.record_ids  (unchanged — Event still points to Record)
INSERT INTO event_record VALUES (1, 1, 0.91, 'v1.0', 0);

-- Junction rows: place_authority → record  (unchanged)
INSERT INTO place_record VALUES (1, 1, 0.85, 'v1.0', 0);
```

A single civil-registration record like this one has nothing to populate `record_similarity` with — that table only gets rows when two separate Records are being compared (e.g. a cross-census household match). It would appear in a worked example built from a pair of Tullynaught census returns instead.

______________________________________________________________________

## 8. Connection Setup

Every Python connection must execute the following PRAGMAs immediately after opening. These are non-negotiable — foreign key enforcement is off by default in SQLite and PRAGMA settings do not persist across connections. This matches `src/db/db.py` exactly.

```python
import sqlite3

DEFAULT_DB = "genealogy.db"

def open_db(path: str = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row  # access columns by name
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")   # concurrent reads during writes
    conn.execute("PRAGMA synchronous = NORMAL")  # safe with WAL; faster than FULL
    conn.execute("PRAGMA temp_store = MEMORY")
    return conn
```

`journal_mode = WAL` is strongly recommended. It allows reads while a write transaction is open, which matters during ingestion sessions where validation queries run concurrently with batch inserts.

______________________________________________________________________

## 9. Schema Initialisation

The complete schema is maintained in `src/db/schema.sql`; seed data (repositories, sources, the place_authority bootstrap row set) lives separately in `src/db/seed.sql`. `init_db()` runs both and refuses to touch an existing database file:

```python
from pathlib import Path

SCHEMA_VERSION = 30
SCHEMA_SQL = Path(__file__).parent / "schema.sql"
SEED_SQL = Path(__file__).parent / "seed.sql"

def init_db(path: str = DEFAULT_DB) -> sqlite3.Connection:
    if Path(path).exists():
        raise FileExistsError(
            f"Database already exists at '{path}'. Delete it manually before reinitialising."
        )
    conn = open_db(path)
    conn.executescript(SCHEMA_SQL.read_text())
    conn.executescript(SEED_SQL.read_text())
    conn.commit()
    return conn

def check_version(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version != SCHEMA_VERSION:
        raise RuntimeError(
            f"Schema version mismatch: expected {SCHEMA_VERSION}, got {version}. "
            "Run migrations before using this database."
        )
```

**Note on versioning:** `PRAGMA user_version` is currently `30` (schema v3.0), matching what's actually deployed. The target additions described throughout §3 (`recorded_relationship`, `record_similarity`, the two junction renames, `training_labels` removal) are not yet reflected in `schema.sql` and will not bump `SCHEMA_VERSION` until they're built as a real migration (`migrate_30_to_31.sql` or similar) — that's implementation-phase work, sequenced after this documentation rebuild, per ROADMAP §4 items 10–11.

______________________________________________________________________

## 10. File Locations

```
src/
  db/
    schema.sql            — complete DDL (CREATE TABLE + CREATE INDEX statements)
    seed.sql               — repository/source/place_authority seed rows
    db.py                   — open_db(), init_db(), check_version(), build_record_url()
    fetch_places.py         — logainm.ie API client
    seed_places.py           — CSV → place_authority loader
    reset_pipeline.py        — selective table-wipe utility (preserves place_authority by default)
    migrations/              — migrate_25_to_26.sql … migrate_29_to_30.sql
  dal/
    repository: no dedicated file — seeded once via seed.sql
    source_repo.py, record_repo.py, person_repo.py, relationship_repo.py,
    event_repo.py, place_repo.py, training_repo.py
  cli.py                    — sole entry point (python -m src.cli)
genealogy.db                — SQLite database file (gitignored)
```

`genealogy.db` must be (and is) in `.gitignore`. The database is a build artefact derived from `schema.sql` plus `seed.sql` plus ingested data. The source of truth for schema structure is `schema.sql`; the source of truth for data is the raw NAI CSV ingest files plus the session logs.

______________________________________________________________________

## 11. Changelog

| Version | Date | Change |
|---|---|---|
| 2.1 | May 2026 | Initial SQLite schema document |
| 2.2 | May 2026 | Replaced `person.names` JSON TEXT column with `person_name` table. Added `idx_person_name_value` and `idx_person_name_person` indexes. R10 and R33 reclassified from Python-only to DB+Python. |
| 2.3 | May 2026 | Replaced `record.source_identifier TEXT` with `record.record_parameters TEXT` (JSON). Added `source.source_parameters TEXT` (JSON) and `source.record_parameter_names TEXT` (JSON array). Added R37. Added `build_record_url()` utility. Schema user_version bumped to 23. |
| 2.4 | May 2026 | Removed `confidence TEXT` from `relationship` and `event`; retired R35. Added `score`, `score_version`, `verified` scoring columns to `person_record`, `event_record`, `relationship_record`, `place_record`; added R38 and R39. Added `name_variant` table. Schema user_version bumped to 24. |
| 2.5 | May 2026 | Expanded `recorded_person.role` CHECK to cover full NAI census download vocabulary. Schema user_version bumped to 25. |
| 2.6 | May 2026 | Made `score` and `score_version` nullable on all four linkage junction tables (OD-01 resolved). Migration `migrate_25_to_26.sql`. Schema user_version bumped to 26. |
| 2.7 | May 2026 | Added `place_authority` table (flat denormalised schema seeded from logainm.ie). Replaced `place` conclusion table. `event.place_id` now references `place_authority`. |
| 2.8 | June 2026 | Merged `recorded_event` into `record` (inline event fields). Dropped `event_recorded_event`, `person_relationship`, `relationship_event`, `event_person`. Junction table count reduced from 9 to 5. Migration `migrate_27_to_28.sql`. Schema user_version bumped to 28. |
| 2.9 | June 2026 | Added `training_labels` table (linkage proposals + researcher review workflow). Added `event.is_primary BOOLEAN DEFAULT true`. Migration `migrate_28_to_29.sql`. Schema user_version bumped to 29. |
| 3.0 | 17 June 2026 | Made `recorded_person.role` nullable. Added `'unknown'` to role CHECK vocabulary. Migration `migrate_29_to_30.sql`. Schema user_version bumped to 30. |
| 3.2 | 19 June 2026 | **Item 13 resolved.** §5 Validation Rule Mapping: replaced the "pending rule assignment" bullet list with a proper R-number table. The constraints on `recorded_relationship` (type vocabulary, score conditional, self-reference) are now mapped to R47/R48; `record_similarity` constraints mapped to R49; `training_labels` write guard mapped to R50. All four were already assigned in `validation_rules.md` §7 (v2.7 rules); this entry backfills the cross-reference in the schema doc. |
| 3.1 | 18 June 2026 | **Documentation rebuild — DDL pass.** Brought this document's DDL in line with the actual `schema.sql` for the first time since v2.7 drift was introduced: added the `place_authority` CREATE TABLE that had gone missing from this doc, removed the obsolete `place` table it had been left alongside, added the `event.is_primary` column and `training_labels` table + indexes that the v2.9/v3.0 changelog entries claimed but the DDL never carried. Rewrote §6 (renamed from "Python DataStore Mapping" to "Python DAL Mapping") to describe the actual `src/dal/` repository-per-table pattern, including the gaps found while grounding this against the live code (`repository` and `name_variant` have no DAL writer; `name_variant` is unused by any pipeline stage). Fixed the worked example to match. Carried forward the v2.6/v2.7 conceptual-model and data-dictionary target design not yet in code, marked `[target]` throughout: added `recorded_relationship` and `record_similarity` DDL (conceptual_model.md §4.7–4.8); renamed `person_record`→`person_recorded_person` and `relationship_record`→`relationship_recorded_relationship`, with the underlying FK changing from `record_id` to `recorded_person_id`/`recorded_relationship_id` per the Rule 2 evidence-correspondence resolution; documented `training_labels`'s conceptual retirement without removing it from the DDL, since removal is real engineering work sequenced separately. Data layer phase of the architecture rebuild (conceptual model → data dictionary → database schema) now complete; implementation phase is next. |

______________________________________________________________________

*Related documents: `conceptual_model.md`, `data_dictionary.md`, `validation_rules.md`, `reconstruction_algorithms.md`*

*Document version: 3.2 — 19 June 2026. Implemented schema version (`PRAGMA user_version`): 30 (v3.0) — see §1 and §9 for what's target vs. implemented.*
