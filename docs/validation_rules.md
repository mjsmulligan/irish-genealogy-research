# Irish Genealogy Research — Validation Rules

*Version 2.9 — 24 June 2026*
*Audience: Developers and data engineers. This document is the authoritative specification for all validation rules enforced by the Python validation layer. It is the companion to `data_dictionary.md`, `conceptual_model.md`, `database_schema.md`, and `genealogical_constraints.md`.*

> **Status notice — 24 June 2026:** The genealogical constraint rules in §6 (R40–R46) and their implementation in `src/review/validator.py` are **superseded**. The `validator.py` module is retired in full. Researcher-facing findings derived from these constraints are now the responsibility of the new review layer (`src/review/`), specified in `docs/review_layer.md`. Pre-write structural validation (formerly `validate_object`) is not replaced in the new design — structural constraints are enforced at the DB layer and repo level. This document is retained as a historical record of the rule vocabulary and thresholds; the implementation it describes no longer exists.

______________________________________________________________________

## 1. Overview

### Validation in a relational database

The move from JSON files to SQLite changes the distribution of enforcement responsibility. The database now enforces a significant subset of the rules that previously required Python code. This document reflects that shift.

Rules are annotated with their enforcement locus:

- **[DB]** — enforced by a SQLite constraint (`NOT NULL`, `CHECK`, `UNIQUE`, `REFERENCES`). A violation raises a constraint error on insert or update and cannot reach the Python layer.
- **[Python]** — enforced exclusively by the Python validator. The database schema cannot express this invariant declaratively.
- **[DB + Python]** — the database enforces what it can; Python enforces the remainder or validates before write.
- **[Retired]** — the rule is no longer meaningful in the relational model and has been removed.

The Python validator's role has shifted from *checking a loaded dataset for consistency* to *validating objects before they are written to the database*. The two entry points reflect this: `validate(conn)` for full dataset checks, and pre-write structural checks on individual objects before insert.

### Rule categories

Rules are grouped into five categories, executed in order:

1. **Structural rules** — well-formedness of individual objects
1. **Referential integrity rules** — foreign keys resolve to existing objects
1. **Consistency rules** — cross-object invariants
1. **Vocabulary and format rules** — controlled values and date formats
1. **Genealogical constraint rules** — domain knowledge checks derived from `genealogical_constraints.md`; near-zero probability violations flagged as merge error candidates

Each rule carries a code in the form `[Rnn]`. Error messages always include the rule code and the primary key of the offending object. The validator returns a flat list of error strings. A dataset is considered valid when the list is empty.

______________________________________________________________________

## 2. Structural Rules

Structural rules check that required fields are present, non-null, and non-empty on every object, independent of any other object.

### R01 — Required fields present on Repository `[DB + Python]`

Every Repository must have `repository_id`, `name`, and `url`. Both `name` and `url` must be non-null and non-empty.

DB enforcement: `NOT NULL` and `CHECK (trim(name) != '')`, `CHECK (trim(url) != '')` on the `repository` table.
Python enforcement: pre-write validation via `validate_object()`.

```
[R01] Repository {id}: required field '{field}' is absent or empty
```

______________________________________________________________________

### R02 — Required fields present on Source `[DB + Python]`

Every Source must have `source_id`, `title`, `type`, and `repository_id`. All must be non-null and, for string fields, non-empty.

DB enforcement: `NOT NULL` and `CHECK` constraints on the `source` table.
Python enforcement: pre-write validation via `validate_object()`.

```
[R02] Source {id}: required field '{field}' is absent or empty
```

______________________________________________________________________

### R03 — Required fields present on Record `[DB + Python]`

Every Record must have `record_id`, `source_id`, and `raw_text`. `raw_text` must be non-null and non-empty after stripping whitespace. A whitespace-only `raw_text` is treated as absent.

DB enforcement: `NOT NULL` and `CHECK (trim(raw_text) != '')` on the `record` table.
Python enforcement: pre-write validation via `validate_object()`.

```
[R03] Record {id}: raw_text is absent or empty
[R03] Record {id}: required field '{field}' is absent or null
```

______________________________________________________________________

### R04 — Required fields present on Record event fields `[DB + Python]`

**Updated in v2.8.** The `recorded_event` table has been merged into `record`. Event fields (`event_type`, `date_as_recorded`, `date`, `date_qualifier`, `place_as_recorded`) are now columns on the `record` table. `event_type` must be non-null and non-empty. This rule is now subsumed by R03 — the record `CHECK` constraint on `event_type` enforces the vocabulary, and R36 covers the date format. No separate R04 validation step is required.

DB enforcement: `NOT NULL` and `CHECK (event_type IN (...))` on the `record` table.
Python enforcement: covered by R03 pre-write validation and R36 date format check.

```
[R03] Record {id}: required field 'event_type' is absent or empty
```

______________________________________________________________________

### R05 — Required fields present on RecordedPerson `[DB + Python]`

**Updated in v3.0.** `role` is now nullable on the `recorded_person` table. A blank role field in the source CSV is ingested as `NULL` (genuinely absent); a field that is present in the source but does not map to any recognised role vocabulary value is ingested as `'unknown'`. Neither `NULL` nor `'unknown'` constitutes a structural violation.

Every RecordedPerson must have `recorded_person_id`, `record_id`, and `name_as_recorded`. `name_as_recorded` must be non-null and non-empty after stripping whitespace. `role`, when non-null, is subject to vocabulary validation under R31.

DB enforcement: `NOT NULL` on `recorded_person_id`, `record_id`, `name_as_recorded`; `role` column is nullable with no `NOT NULL` constraint.
Python enforcement: pre-write structural check on required non-nullable fields only.

**Known code bug:** The existing `validate_object()` implementation in `validator.py` still treats `role` as required and raises `[R05] RecordedPerson {id}: role is absent or empty` for null roles. This is incorrect as of v3.0 schema. The error message should be suppressed for null roles pending a fix to the validator code. The correct behaviour is documented here; the code has not yet been updated.

```
[R05] RecordedPerson {id}: name_as_recorded is absent or empty
[R05] RecordedPerson {id}: required field '{field}' is absent or null
```

______________________________________________________________________

### R06 — Required fields present on Person `[DB + Python]`

Every Person must have `person_id` and `label`. `label` must be non-null and non-empty.

DB enforcement: `NOT NULL` and `CHECK (trim(label) != '')` on the `person` table.
Python enforcement: pre-write validation via `validate_object()`.

```
[R06] Person {id}: required field '{field}' is absent or empty
```

______________________________________________________________________

### R07 — Required fields present on Relationship `[DB + Python]`

Every Relationship must have `relationship_id`, `type`, `person_id_1`, and `person_id_2`. All must be non-null.

DB enforcement: `NOT NULL` constraints on the `relationship` table.
Python enforcement: pre-write validation via `validate_object()`.

```
[R07] Relationship {id}: required field '{field}' is absent or null
```

______________________________________________________________________

### R08 — Required fields present on Event `[DB + Python]`

Every Event must have `event_id` and `type`. Both must be non-null and non-empty.

DB enforcement: `NOT NULL` constraints on the `event` table.
Python enforcement: pre-write validation via `validate_object()`.

```
[R08] Event {id}: required field '{field}' is absent or empty
```

______________________________________________________________________

### R09 — Required fields present on PlaceAuthority `[DB + Python]`

**Updated in v2.7 (schema).** The conclusion-layer `Place` object has been retired. `place_authority` is the structural place table, seeded from logainm.ie. Every PlaceAuthority entry must have `place_authority_id`, `logainm_id`, and `name_en` or `name_ga` (at least one non-null name field). `logainm_id` must be non-null.

DB enforcement: `NOT NULL` on `place_authority_id` and `logainm_id`; at minimum one name column constrained non-null by schema convention.
Python enforcement: pre-write validation via structural check before insert.

```
[R09] PlaceAuthority {id}: required field '{field}' is absent or empty
```

______________________________________________________________________

### R10 — Name object completeness `[Retired]`

**Retired.** `Person.names` was previously stored as a JSON array in a TEXT column, making structural validation of individual name entries Python-only. Names are now stored in the `person_name` table, where `NOT NULL` and `CHECK (trim(value) != '')` enforce field presence, and `CHECK (type IN (...))` enforces vocabulary. Both R10 and R33 are superseded by the table structure.

______________________________________________________________________

## 3. Referential Integrity Rules

In the relational schema, all single-column foreign keys are enforced by `REFERENCES` constraints with `PRAGMA foreign_keys = ON`. A violation raises a SQLite constraint error on insert or update and cannot reach the Python layer.

All junction table foreign keys are likewise enforced at the DB level — an attempt to insert a row referencing a non-existent primary key is rejected immediately.

Python's residual responsibility in this section is **pre-write validation**: before constructing INSERT statements, the repo layer should confirm that referenced IDs exist in the database. This catches errors earlier and produces friendlier error messages than raw SQLite constraint errors.

### R11 — Repository → (no upstream FK) `[N/A]`

Repository is a root object with no foreign keys. No referential integrity rule applies.

______________________________________________________________________

### R12 — Source → Repository `[DB + Python]`

`Source.repository_id` must resolve to an existing Repository.

DB enforcement: `REFERENCES repository (repository_id)` on the `source` table.

```
[R12] Source {id}: repository_id={val} does not resolve to a Repository
```

______________________________________________________________________

### R13 — Record → Source `[DB + Python]`

`Record.source_id` must resolve to an existing Source.

DB enforcement: `REFERENCES source (source_id)` on the `record` table.

```
[R13] Record {id}: source_id={val} does not resolve to a Source
```

______________________________________________________________________

### R14 — RecordedEvent → Record `[Retired]`

**Retired in v2.8.** The `recorded_event` table has been removed. Event data is now inline on `record`. This rule no longer applies.

______________________________________________________________________

### R15 — RecordedPerson → Record `[DB + Python]`

`RecordedPerson.record_id` must resolve to an existing Record.

DB enforcement: `REFERENCES record (record_id)` on the `recorded_person` table.

```
[R15] RecordedPerson {id}: record_id={val} does not resolve to a Record
```

______________________________________________________________________

### R16 — Person foreign keys `[DB + Python]`

Each entry in `Person.record_ids` must resolve to an existing Record. Each entry in `Person.event_ids` must resolve to an existing Event. Each entry in `Person.relationship_ids` must resolve to an existing Relationship.

DB enforcement: `REFERENCES` constraints on `person_record` and `person_event`. A junction row referencing a non-existent ID is rejected. Note: `Person.relationship_ids` is no longer backed by a `person_relationship` junction table — relationships are queried directly via `relationship.person_id_1` / `person_id_2`.

```
[R16] Person {id}: record_id={val} does not resolve to a Record
[R16] Person {id}: event_id={val} does not resolve to an Event
[R16] Person {id}: relationship_id={val} does not resolve to a Relationship
```

______________________________________________________________________

### R17 — Relationship foreign keys `[DB + Python]`

`Relationship.person_id_1` and `Relationship.person_id_2` must each resolve to an existing Person. Each entry in `Relationship.record_ids` must resolve to an existing Record. Each entry in `Relationship.event_ids` must resolve to an existing Event.

DB enforcement: `REFERENCES person` on both FK columns; `REFERENCES` constraint on `relationship_record`. Note: `relationship_event` has been removed — the `event.relationship_id` column expresses this association directly.

```
[R17] Relationship {id}: person_id_1={val} does not resolve to a Person
[R17] Relationship {id}: person_id_2={val} does not resolve to a Person
[R17] Relationship {id}: record_id={val} does not resolve to a Record
[R17] Relationship {id}: event_id={val} does not resolve to an Event
```

______________________________________________________________________

### R18 — Event foreign keys `[DB + Python]`

`Event.place_id`, when present, must resolve to an existing PlaceAuthority entry. Each entry in `Event.person_ids` must resolve to an existing Person via `person_event`. `Event.relationship_id`, when present, must resolve to an existing Relationship. Each entry in `Event.record_ids` must resolve to an existing Record via `event_record`.

DB enforcement: `REFERENCES place_authority` and `REFERENCES relationship` on the `event` table; `REFERENCES` constraints on `person_event` and `event_record`.

```
[R18] Event {id}: place_id={val} does not resolve to a PlaceAuthority entry
[R18] Event {id}: person_id={val} does not resolve to a Person
[R18] Event {id}: relationship_id={val} does not resolve to a Relationship
[R18] Event {id}: record_id={val} does not resolve to a Record
```

______________________________________________________________________

### R19 — PlaceAuthority foreign keys `[DB + Python]`

**Updated in v2.7 (schema).** The conclusion-layer `Place` object has been retired; `place_authority` is now the canonical place table. The `place_record` junction table remains: each `place_authority_id` in `place_record` must resolve to an existing `place_authority` entry. Each `record_id` in `place_record` must resolve to an existing Record.

DB enforcement: `REFERENCES place_authority` and `REFERENCES record` on junction table `place_record`.

```
[R19] place_record (place_authority_id={pid}, record_id={rid}): place_authority_id does not resolve to a PlaceAuthority entry
[R19] place_record (place_authority_id={pid}, record_id={rid}): record_id does not resolve to a Record
```

______________________________________________________________________

## 4. Consistency Rules

### R20 — One event per Record `[DB]`

**Updated in v2.8.** The `recorded_event` table has been merged into `record`. Each Record carries exactly one set of event fields (`event_type`, `date`, etc.) as columns. The one-event-per-record invariant is now structural — it is impossible to create a second event for the same record. No Python enforcement is required.

DB enforcement: event fields are columns on `record`; the constraint is structural.

______________________________________________________________________

### R21 — At least one RecordedPerson per Record `[Python]`

Every Record must have at least one RecordedPerson whose `record_id` points to it. SQLite cannot enforce a minimum child-row count declaratively.

```
[R21] Record {id}: has no RecordedPersons — at least 1 required
```

______________________________________________________________________

### R22 — Relationship self-reference prohibition `[DB]`

`Relationship.person_id_1` and `Relationship.person_id_2` must not be equal. Enforced by `CHECK (person_id_1 != person_id_2)` on the `relationship` table. A violating insert is rejected by the DB; this rule requires no Python enforcement and generates no Python error message.

*Documented here for completeness. No Python action required.*

______________________________________________________________________

### R23 — Bidirectional consistency: Person ↔ Relationship `[Retired]`

**Retired.** In the JSON model, `Person.relationship_ids` was a list maintained independently of the `Relationship` object. In the relational schema, `relationship.person_id_1` and `person_id_2` are the source of truth — no `person_relationship` junction table exists. Querying a person's relationships is a direct filter on the `relationship` table. The invariant is structurally enforced.

______________________________________________________________________

### R24 — Bidirectional consistency: Person ↔ Event `[Retired]`

**Retired.** Same reasoning as R23. The `person_event` junction table is the single source of truth. `Person.event_ids` and `Event.person_ids` are both derived by querying the same junction table rows; they cannot diverge.

______________________________________________________________________

### R25 — Bidirectional consistency: Relationship ↔ Event `[Retired]`

**Retired.** The `relationship_event` junction table has been removed. `event.relationship_id` is the sole expression of this association — a nullable FK on the `event` table. No bidirectionality inconsistency is possible.

______________________________________________________________________

### R26 — RecordedEvent ↔ Event Record consistency `[Retired]`

**Retired in v2.8.** Both `recorded_event` and `event_recorded_event` have been removed. `event_record` links an Event directly to a Record. Since a Record carries its event fields inline, linking the Record to an Event is equivalent to linking the event data — the split that R26 was protecting against no longer exists.

______________________________________________________________________

### R27 — Evidence-layer objects contain no conclusion-layer foreign keys `[Retired]`

**Retired.** In the JSON model, this rule detected cases where a conclusion-layer foreign key had been written into a RecordedEvent or RecordedPerson object. In the relational schema, neither `record` nor `recorded_person` carry foreign keys to conclusion-layer objects. The violation is architecturally impossible. No rule text is needed.

______________________________________________________________________

## 5. Vocabulary and Format Rules

### R28 — Source type controlled vocabulary `[DB + Python]`

`Source.type` must be one of the values defined in §6.1 of the data dictionary.

Valid values: `valuation`, `tithe`, `census`, `birth_registration`, `marriage_registration`, `death_registration`, `parish_register`, `military`, `folklore`.

DB enforcement: `CHECK (type IN (...))` on the `source` table.

```
[R28] Source {id}: type='{val}' is not a valid source type
```

______________________________________________________________________

### R29 — Event type controlled vocabulary `[DB + Python]`

`Record.event_type` and `Event.type` must each be one of the values defined in §6.2 of the data dictionary.

Valid values: `birth`, `baptism`, `marriage`, `death`, `burial`, `census`, `residence`, `emigration`, `valuation`, `tithe`, `military_service`, `pension`, `folklore`.

DB enforcement: `CHECK (event_type IN (...))` on the `record` table; `CHECK (type IN (...))` on the `event` table.

```
[R29] Record {id}: event_type='{val}' is not a valid event type
[R29] Event {id}: type='{val}' is not a valid event type
```

______________________________________________________________________

### R30 — Date qualifier controlled vocabulary `[DB + Python]`

`Record.date_qualifier` and `Event.date_qualifier`, when present, must each be one of the values defined in §6.3 of the data dictionary.

Valid values: `exact`, `about`, `before`, `after`, `between`, `estimated`, `calculated`.

DB enforcement: `CHECK (date_qualifier IS NULL OR date_qualifier IN (...))` on both `record` and `event` tables.

```
[R30] Record {id}: date_qualifier='{val}' is not a valid date qualifier
[R30] Event {id}: date_qualifier='{val}' is not a valid date qualifier
```

______________________________________________________________________

### R31 — RecordedPerson role controlled vocabulary `[DB + Python]`

**Updated in v3.0.** `role` is nullable (see R05). When non-null, `role` must be one of the values defined in §6.4 of the data dictionary.

Valid values: `principal`, `head`, `spouse`, `child`, `groom`, `bride`, `father`, `mother`, `father_of_groom`, `father_of_bride`, `godfather`, `godmother`, `witness`, `informant`, `officiator`, `occupier`, `lessor`, `deceased`, `unknown`.

The value `'unknown'` is used during census ingest when the source field is non-blank but does not map to any other vocabulary term (e.g. an unrecognised `relation_to_head_updated` value). It is not an error — it is a signal that the source value was present but unclassified.

A null `role` is not a vocabulary violation and is not checked by this rule.

DB enforcement: `CHECK (role IS NULL OR role IN (...))` on the `recorded_person` table.

```
[R31] RecordedPerson {id}: role='{val}' is not a valid role
```

______________________________________________________________________

### R32 — Person gender controlled vocabulary `[DB + Python]`

`Person.gender`, when present, must be one of the values defined in §6.5 of the data dictionary.

Valid values: `male`, `female`, `unknown`.

DB enforcement: `CHECK (gender IS NULL OR gender IN (...))` on the `person` table.

```
[R32] Person {id}: gender='{val}' is not a valid gender value
```

______________________________________________________________________

### R33 — Name type controlled vocabulary `[Retired]`

**Retired.** Name type vocabulary was previously Python-only because names were stored as a JSON array in a TEXT column. Names are now stored in the `person_name` table with a `CHECK (type IN (...))` constraint. Vocabulary enforcement is now DB-level, consistent with all other vocabulary rules.

______________________________________________________________________

### R34 — Relationship type controlled vocabulary `[DB + Python]`

`Relationship.type` must be one of the values defined in §6.7 of the data dictionary.

Valid values: `couple`, `parent_child`, `sibling`.

DB enforcement: `CHECK (type IN (...))` on the `relationship` table.

```
[R34] Relationship {id}: type='{val}' is not a valid relationship type
```

______________________________________________________________________

### R35 — Confidence controlled vocabulary `[Retired]`

**Retired.** `Relationship.confidence` and `Event.confidence` have been removed from the schema. Confidence was a static scalar that could not capture the per-linkage granularity required by the reconstruction algorithm. Aggregate confidence, where needed for display, is derived at query time from the `score` values across all linked Records in the relevant junction table. The `CHECK` constraints on both tables have been dropped.

______________________________________________________________________

### R36 — Date format `[Python]`

All fields typed as `date` — `Record.date` and `Event.date` — must conform to one of three valid ISO 8601 partial date forms when non-null. SQLite has no native date type and stores these fields as TEXT; format validation is Python-only.

| Form | Pattern | Constraints |
|---|---|---|
| `YYYY` | Four-digit year | Year must be a plausible genealogical year (1500–2100) |
| `YYYY-MM` | Year and month | Month must be 01–12 |
| `YYYY-MM-DD` | Full date | Month 01–12; day 01–28/29/30/31 valid for the given month |

Note: `Record.date_as_recorded` is a free-text verbatim field and is explicitly exempt from this rule.

Text dates, circa prefixes, non-ISO separators, two-digit years, and day or month values of zero are all invalid.

```
[R36] Record {id}: date='{val}' is not a valid ISO 8601 partial date
[R36] Event {id}: date='{val}' is not a valid ISO 8601 partial date
```

______________________________________________________________________

### R38 — Linkage score range `[DB + Python]`

The `score` column on all four linkage junction tables must be either null or a real number in the closed interval [0.0, 1.0].
Null score represents a manually-asserted linkage — one created via `assert_linkage()` where no algorithm score was computed. Null is semantically distinct from a score of 0.0 (which would represent a near-certain non-match). A null-score row should always have `verified = 1`.
Non-null score must fall within [0.0, 1.0].
DB enforcement: `CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0))` on all four tables.
Python enforcement: pre-write validation via `validate_object()`.

```

---

### R39 — Verified flag values `[DB + Python]`

The `verified` column on all four linkage junction tables must be either 0 (algorithm assertion) or 1 (researcher-verified). A verified row is never automatically overwritten by a re-scoring pass.

DB enforcement: `CHECK (verified IN (0, 1))` on all four tables.
Python enforcement: pre-write validation via `validate_object()`.

```

[R39] person_record (person_id={pid}, record_id={rid}): verified={val} must be 0 or 1
[R39] event_record (event_id={eid}, record_id={rid}): verified={val} must be 0 or 1
[R39] relationship_record (relationship_id={rid}, record_id={rec}): verified={val} must be 0 or 1
[R39] place_record (place_id={pid}, record_id={rid}): verified={val} must be 0 or 1

```

---

---

## 6. Genealogical Constraint Rules

These rules formalise the hardest constraints from `genealogical_constraints.md` — those flagged as near-zero probability violations — as Python validation rules. They are the counterpart to the probabilistic scoring constraints: where the constraint engine adjusts scores and queues recommendations, these rules generate explicit error-level flags for violations that are strong enough to be treated as merge error candidates regardless of Splink scores.

All rules in this section are **[Python]** only. They require cross-object lookups against the existing conclusion layer and cannot be expressed as SQLite constraints. They run as part of `validate(conn)` and are also callable individually for targeted post-linkage checks.

**Relationship to `genealogical_constraints.md`:** Each rule cites the GC code of the constraint it formalises. The GC document is the authoritative source for the genealogical rationale; this document is the authoritative source for the validation implementation.

**Error severity:** Rules in this section produce warnings rather than hard errors by default. A warning is a flag surfaced to the researcher for review — it does not prevent a linkage from being committed. The researcher's `verified = 1` on the relevant junction row is the mechanism for acknowledging and overriding a warning. This is consistent with the probabilistic framing of the overall system.

---

### R40 — Birth Event `is_primary` cardinality `[Python]` *(GC04)*

**Updated in v2.8 (rules).** The conceptual model (v2.5) permits multiple birth Events per Person as competing conclusions — for example, a civil birth registration and a baptism record may each generate a birth Event before they are synthesised. Exactly one of these must be marked `is_primary = True` by the `rebuild-consensus` step. R40 therefore enforces `is_primary` cardinality, not raw Event count.

This rule queries `person_event` joined to `event` to count Events of type `birth` where `is_primary = True`, per Person. The valid count is exactly 1. Deviations in either direction are flagged as merge error candidates:

- **Zero primaries** — no birth Event is marked primary. This indicates `rebuild-consensus` has not run, or no birth Records are linked to this Person. Flagged as a data completeness warning.
- **Multiple primaries** — more than one birth Event is marked primary. This is a data integrity error: the `is_primary` mechanism is broken or two conflicting consensus passes have fired for the same Person.

The total count of birth Events (primary + non-primary) is not itself a violation — non-primary birth Events represent legitimate alternative conclusions pending researcher review.

**Scope note:** An analogous rule for Relationship-scoped Event cardinality is not defined. The `event` table's `is_primary` column is scoped to Person conclusions; Relationship objects carry no primary/alternate mechanism.

```

[R40] Person {id}: has 0 birth Events marked is_primary — exactly 1 required; rebuild-consensus may not have run
[R40] Person {id}: has {n} birth Events marked is_primary — exactly 1 permitted; probable data integrity error

```

---

### R41 — Death Event `is_primary` cardinality `[Python]` *(GC05)*

**Updated in v2.8 (rules).** Same reasoning as R40. Multiple death Events per Person are permitted as competing conclusions; exactly one must be marked `is_primary = True`. A burial Event linked to the same Person is permitted and expected — this rule checks only Events of type `death`.

This rule queries `person_event` joined to `event` to count Events of type `death` where `is_primary = True`, per Person. A Person with no linked death Records produces a count of zero — this is not a violation (death Records are not available for all Persons). The rule fires only when at least one death Event exists for the Person and the `is_primary` count deviates from 1.

- **Zero primaries, at least one death Event linked** — primary not yet determined; rebuild-consensus has not run or has not propagated to this Person.
- **Multiple primaries** — data integrity error.

```

[R41] Person {id}: has {n} death Events but none marked is_primary — exactly 1 required when death Events exist; rebuild-consensus may not have run
[R41] Person {id}: has {n} death Events marked is_primary — exactly 1 permitted; probable data integrity error

```

---

### R42 — Census Record singularity per source `[Python]` *(GC07)*

A concluded `Person` may not be linked to more than one `Record` from the same census source (source_ids 3, 4, or 5) via `person_record` where `verified = 0`. Multiple unverified census linkages for the same source and Person indicate a high probability of a merge error.

Linkages where `verified = 1` are excluded from this check — the researcher has explicitly confirmed the double enumeration exception.

This rule queries `person_record` joined to `record` and `source` to count unverified Records per census source per Person. A count greater than one triggers the warning.

```

[R42] Person {id}: has {n} unverified Records from census source {source_id} ('{source_title}') — maximum 1 expected; probable merge error or double enumeration

```

---

### R43 — Life event sequence `[Python]` *(GC02)*

**Updated in v2.8 (rules).** Redesigned to specify the full qualifier-aware comparison that GC02 requires, and to document the gap between this specification and the current placeholder implementation in `validator.py`.

For any concluded `Person`, the dates of their concluded life Events must follow chronological order where those dates are non-null and their uncertainty intervals do not overlap. Confirmed sequence violations indicate a merge error.

**Checks performed:**

| Check | Condition flagged |
|---|---|
| Birth before baptism | Baptism date interval ends before birth date interval begins (excluding adult baptism — see below) |
| Birth before all other Events | Any non-birth, non-baptism Event date interval ends before the birth date interval begins |
| Marriage before death | Marriage date interval begins after death date interval ends |
| Death before burial | Burial date interval begins before death date interval ends |
| Events after death | Any census, residence, valuation, tithe, or military Event date interval begins after death date interval ends |

**Date interval construction:** Each date is converted to an interval based on its qualifier before comparison. A violation is confirmed only when the two intervals do not overlap — i.e. one ends strictly before the other begins.

| Qualifier | Interval construction |
|---|---|
| `exact` or null | Point interval: `[date, date]` |
| `about` | `[date − 2yr, date + 2yr]` |
| `estimated` | `[date − 2yr, date + 2yr]` |
| `calculated` | `[date − 2yr, date + 2yr]` |
| `before` | `(−∞, date − 1yr]` — treat as right-bounded; comparison only fires for checks where the `before` date is the *later* event |
| `after` | `[date + 1yr, +∞)` — treat as left-bounded; comparison only fires for checks where the `after` date is the *earlier* event |
| `between` | Not directly representable as a point; treat as `[date − 2yr, date + 2yr]` pending a structured `between` representation |

When a date has a `before` or `after` qualifier and the comparison is in the direction where the bound is unbounded (e.g. checking whether a `before`-qualified death date follows a marriage date — if death is "before 1900," the comparison cannot confirm whether the marriage precedes death), the check is **skipped** and noted rather than flagged as a violation.

**Adult baptism exception:** The birth-before-baptism check is suppressed for a given baptism Event if the RecordedPerson linked to the baptism Record — i.e. the RecordedPerson whose `record_id` points to the Record linked via `event_record` to that baptism Event — has a non-null `age_as_recorded` value greater than 1. This targets adult converts and immigrants baptised late, where the source evidence itself establishes the sequence anomaly is genuine.

**Implementation gap:** The current `validator.py` implementation does not yet apply qualifier-aware interval logic. It performs a simplified point-date comparison with a flat ±2-year tolerance, does not implement the `before`/`after`/`between` qualifier handling, and does not implement the adult baptism exception correctly. This specification is the authoritative design; the code is a placeholder. The gap should be resolved before genealogical validation is relied upon in research outputs.

```

[R43] Person {id}: sequence violation — {event_type_1} date {date_1} ({qualifier_1}) precedes {event_type_2} date {date_2} ({qualifier_2}); intervals do not overlap; probable merge error
[R43] Person {id}: sequence check {check_name} skipped — qualifier '{qualifier}' on Event {eid} does not bound the comparison in the required direction

```

---

### R44 — Parent age range `[Python]` *(GC12)*

**Updated in v2.8 (rules).** Title changed from "Minimum parent age" to "Parent age range" to reflect that both a minimum and a maximum apply, and that the maximum varies by parent gender.

For any `parent_child` Relationship, the gap between the parent's birth year and the child's birth year must fall within the biologically and historically plausible range. Violations are flagged as merge error candidates.

**Birth year sourcing:** Each Person's birth year is taken from their `is_primary = True` birth Event where one exists. Where no primary birth Event is available, the birth year is estimated from the Person's linked Records (the earliest age-as-recorded field, adjusted to the record year). Where no birth year can be established for either Person in the Relationship, the rule is skipped and noted as unevaluated.

**Gap calculation:** `gap = child_birth_year − parent_birth_year`. Tolerance of ±2 years is applied to both estimates before computing the gap — i.e. the gap check fires only when it holds outside the combined ±4-year uncertainty window.

**Minimum gap (all parents):** Gap below 15 years is a near-zero probability biological violation.

**Maximum gap (female parent):** For `Person.gender = 'female'`, a gap greater than 50 years is flagged. A woman giving birth at age 50+ is a near-zero probability event in historical Irish records.

**Maximum gap (male parent):** For `Person.gender = 'male'`, a gap greater than 65 years is flagged. A man fathering a child at age 65+ is a near-zero probability event in historical Irish records. This cap is softer than the maternal cap — late paternity is documented in the historical record more often — but gaps above 65 years are sufficiently unusual to warrant researcher review as probable merge error candidates.

**Gender unknown:** Where `Person.gender` is null or `'unknown'` for the parent, only the minimum gap check is applied; the gender-specific maximum is skipped and noted.

```

[R44] Relationship {id} (parent_child): parent Person {pid} birth year {py} — child Person {cid} birth year {cy} — gap of {gap} years is below minimum of 15; probable merge error
[R44] Relationship {id} (parent_child): female parent Person {pid} birth year {py} — child Person {cid} birth year {cy} — gap of {gap} years exceeds maternal maximum of 50; probable merge error
[R44] Relationship {id} (parent_child): male parent Person {pid} birth year {py} — child Person {cid} birth year {cy} — gap of {gap} years exceeds paternal maximum of 65; probable merge error
[R44] Relationship {id} (parent_child): parent gender unknown — maximum age check skipped

```

---

### R45 — Minimum marriage age `[Python]` *(GC13)*

For any Person linked to a marriage `Event` via `person_event`, the gap between the Person's birth year and the marriage Event date must be at least 15 years, net of age tolerance. A gap below 15 years is flagged as a merge error candidate.

**Birth year sourcing:** The Person's birth year is taken from their `is_primary = True` birth Event where one exists. Where no primary birth Event is available, the birth year is estimated from the Person's linked Records (the earliest age-as-recorded field, adjusted to the record year). Where no birth year can be established by either route, the rule is skipped and noted as unevaluated.

**Tolerance:** ±2 years applied to birth year estimate before computing the gap.

```

[R45] Person {id}: marriage Event {eid} dated {marriage_date} — birth year {by} (from {source}) places Person at age {age} at marriage; minimum age is 15; probable merge error

```

*`{source}` is `'is_primary birth Event'` or `'estimated from Records'` to make the derivation traceable in the warning output.*

---

### R46 — Lifespan boundary `[Python]` *(GC01)*

For any Person linked to a Record via `person_record`, the `record.date` of that Record must fall within the Person's concluded lifespan. A record date more than 5 years outside the lifespan bounds is flagged regardless of the linkage score.

**Lifespan bounds:**
- Lower bound: the date of the Person's `is_primary = True` birth Event; or, where no primary birth Event exists, the date of the Person's `is_primary = True` baptism Event; or, where neither exists, a birth year estimated from the Person's linked Records (earliest age-as-recorded adjusted to record year). The source of the lower bound is included in the warning output for traceability.
- Upper bound: the date of the Person's `is_primary = True` death Event where known; otherwise unbounded.

**Tolerance:** ±5 years applied to both bounds before flagging. This accommodates dating uncertainty on the Event itself without suppressing genuine boundary violations.

Where neither a lower nor an upper bound can be established from the Person's concluded Events or linked Records, the rule is skipped and noted as unevaluated.

```

[R46] person_record (person_id={pid}, record_id={rid}): record date {date} is more than 5 years outside Person lifespan bounds [{lower}–{upper}] (lower from {source}); probable merge error

```

*`{source}` is `'is_primary birth Event'`, `'is_primary baptism Event'`, or `'estimated from Records'`.*

---

## 7. Pending Rules — New Evidence-Layer Objects

The following rules cover `recorded_relationship`, `record_similarity`, and `training_labels`. These tables are present in the v3.0 schema but their validation rules have not yet been formally specified. Rules are marked **[Pending]** — they are placeholders that document intent; no Python enforcement exists yet.

---

### R47 — Required fields present on RecordedRelationship `[Pending]`

Every RecordedRelationship must have `recorded_relationship_id`, `recorded_person_id_1`, `recorded_person_id_2`, and `type`. Both FK columns must resolve to existing RecordedPersons (R48 covers referential integrity). `type` must be non-null and draw from the Relationship type vocabulary (couple, parent_child, sibling) extended with a similarity type for Splink-derived scores.

RecordedPersons linked by a RecordedRelationship may belong to the same Record or to different Records (the cross-census case). No DB constraint currently enforces the vocabulary on `type`; Python enforcement is the sole gate.

```

[R47] RecordedRelationship {id}: required field '{field}' is absent or null
[R47] RecordedRelationship {id}: type='{val}' is not a valid recorded relationship type

```

---

### R48 — RecordedRelationship foreign keys `[Pending]`

`RecordedRelationship.recorded_person_id_1` and `recorded_person_id_2` must each resolve to an existing RecordedPerson. The self-reference prohibition from R22 applies by analogy: the two RecordedPerson IDs must not be equal.

DB enforcement: `REFERENCES recorded_person` on both FK columns (if the table carries these constraints); `CHECK (recorded_person_id_1 != recorded_person_id_2)`.

```

[R48] RecordedRelationship {id}: recorded_person_id_1={val} does not resolve to a RecordedPerson
[R48] RecordedRelationship {id}: recorded_person_id_2={val} does not resolve to a RecordedPerson
[R48] RecordedRelationship {id}: recorded_person_id_1 and recorded_person_id_2 must not be equal

```

---

### R49 — Required fields present on RecordSimilarity `[Pending]`

Every RecordSimilarity must have `record_similarity_id`, `record_id_1`, `record_id_2`, and `score`. `score` must be a real number in [0.0, 1.0] (null is not permitted — a RecordSimilarity without a score is meaningless). `record_id_1` and `record_id_2` must not be equal.

RecordSimilarity has no conclusion-layer counterpart. It records an algorithmic measurement between two Records, not an assertion about Persons. No FK to the conclusion layer is required or permitted.

```

[R49] RecordSimilarity {id}: required field '{field}' is absent or null
[R49] RecordSimilarity {id}: score={val} is not in valid range [0.0–1.0]
[R49] RecordSimilarity {id}: record_id_1 and record_id_2 must not be equal

```

---

### R50 — training_labels integrity `[Pending]`

`training_labels` was built to support Splink EM training and has been retired at the conceptual level (see `conceptual_model.md` v2.5 §3). The table remains in the v3.0 schema pending removal in the implementation phase; no new rows should be written to it. This rule is a placeholder to flag any unexpected writes.

When the table is removed from the schema, R50 will be retired alongside it.

```

[R50] training_labels: unexpected row (unique_id_l={l}, unique_id_r={r}) — table is retired; no new rows should be written

```

---

## 8. Rule Summary Table

The following table summarises all rules, their description, and their enforcement locus.

| Rule | Description | Enforcement |
|---|---|---|
| R01 | Required fields on Repository | DB + Python |
| R02 | Required fields on Source | DB + Python |
| R03 | Required fields on Record | DB + Python |
| R04 | Required fields on Record event fields | DB + Python (via R03/R36) |
| R05 | Required fields on RecordedPerson (role nullable from v3.0) | DB + Python |
| R06 | Required fields on Person | DB + Python |
| R07 | Required fields on Relationship | DB + Python |
| R08 | Required fields on Event | DB + Python |
| R09 | Required fields on PlaceAuthority | DB + Python |
| R10 | Name object completeness | **Retired** |
| R11 | Repository has no upstream FK | N/A |
| R12 | Source → Repository FK | DB + Python |
| R13 | Record → Source FK | DB + Python |
| R14 | RecordedEvent → Record FK | **Retired** |
| R15 | RecordedPerson → Record FK | DB + Python |
| R16 | Person FK arrays | DB + Python |
| R17 | Relationship FK arrays | DB + Python |
| R18 | Event FK arrays | DB + Python |
| R19 | PlaceAuthority / place_record FKs | DB + Python |
| R20 | One event per Record | DB (structural) |
| R21 | At least one RecordedPerson per Record | Python only |
| R22 | Relationship self-reference prohibition | DB only |
| R23 | Person ↔ Relationship bidirectionality | **Retired** |
| R24 | Person ↔ Event bidirectionality | **Retired** |
| R25 | Relationship ↔ Event bidirectionality | **Retired** |
| R26 | RecordedEvent ↔ Event Record consistency | **Retired** |
| R27 | Evidence-layer isolation | **Retired** |
| R28 | Source type vocabulary | DB + Python |
| R29 | Event type vocabulary | DB + Python |
| R30 | Date qualifier vocabulary | DB + Python |
| R31 | RecordedPerson role vocabulary (includes `unknown`; null exempt) | DB + Python |
| R32 | Person gender vocabulary | DB + Python |
| R33 | Name type vocabulary | **Retired** |
| R34 | Relationship type vocabulary | DB + Python |
| R35 | Confidence vocabulary | **Retired** |
| R36 | Date format | Python only |
| R37 | record_parameters keys match record_parameter_names | Python only |
| R38 | Linkage score range [0.0–1.0] or null (manual assertion) | DB + Python |
| R39 | Verified flag values {0, 1} | DB + Python |
| R40 | Birth Event `is_primary` cardinality (exactly 1) | Python only (GC04) |
| R41 | Death Event `is_primary` cardinality (exactly 1 when death Events exist) | Python only (GC05) |
| R42 | Census Record singularity per source | Python only (GC07) |
| R43 | Life event sequence (qualifier-aware interval comparison) | Python only (GC02) |
| R44 | Parent age range (minimum 15yr; maternal max 50yr; paternal max 65yr) | Python only (GC12) |
| R45 | Minimum marriage age (birth year from is_primary Event) | Python only (GC13) |
| R46 | Lifespan boundary (bounds from is_primary Events) | Python only (GC01) |
| R47 | Required fields on RecordedRelationship | **Pending** |
| R48 | RecordedRelationship FK integrity | **Pending** |
| R49 | Required fields on RecordSimilarity | **Pending** |
| R50 | training_labels write guard (retired table) | **Pending** |

**Python-only rules** (require active Python enforcement): R21, R36, R37, R40, R41, R42, R43, R44, R45, R46.
**Retired rules** (no longer meaningful in the relational model): R10, R14, R23, R24, R25, R26, R27, R33, R35.
**DB-only rule** (no Python action needed): R22.
**Pending rules** (intent documented; no Python enforcement yet): R47, R48, R49, R50.

---

## 9. Execution Order and Dependency

Rules are executed in the following order. Later rules depend on earlier ones having passed.

1. **Structural rules (R01–R09)** — object well-formedness. No cross-object lookups. Safe to run in isolation as pre-write checks.
2. **Referential integrity rules (R12–R19)** — pre-write checks that referenced IDs exist. In normal operation the DB enforces these; Python checks them to produce actionable error messages before attempting an insert.
3. **Consistency rules (R21–R22)** — cross-object invariants. R20 is now structural (DB-enforced); R26 is retired.
4. **Vocabulary and format rules (R28–R39)** — controlled values, date formats, and scoring column constraints. Run last among the schema rules to separate structural problems from vocabulary problems in the error output.
5. **Genealogical constraint rules (R40–R46)** — domain knowledge checks. Run after all schema rules are clean. Depend on the conclusion layer being populated; skipped for objects with unresolved birth year or lifespan bounds. Produce warnings rather than hard errors.
6. **Pending rules (R47–R50)** — not yet enforced. See §7 for intent.

When a referential integrity error is present, downstream consistency rules that would traverse the broken reference are skipped for the affected object:

```

[SKIP] Consistency checks for {ObjectType} {id} skipped: unresolved foreign key(s) from R12–R19

```

When a birth year or lifespan bound cannot be established for a Person, genealogical constraint rules that require it are skipped and noted:

```

[SKIP] R{nn} for Person {id} skipped: birth year not determinable from concluded Events or linked Records

```

---

## 10. Validation Entry Points

**`validate(conn) -> list[str]`** — full validation of all Python-only rules against the current database state. `conn` is an open SQLite connection. Queries the database directly. Returns a flat list of error strings. An empty list means the dataset is valid with respect to all Python-enforced rules. (DB-enforced rules are assumed to hold if the database was written through the normal Python layer with `PRAGMA foreign_keys = ON`.)

**Pre-write structural checks** — structural and vocabulary validation of a single object in isolation, without referential integrity, consistency, or genealogical constraint checks. Used during ingestion to give immediate feedback before a new object is committed to the database. Currently implemented as inline checks in repo functions rather than a dedicated single-entry-point function; this may be consolidated in a future refactor.

**Known code bug:** The existing pre-write check for `RecordedPerson` still treats `role` as required and will flag null roles as an error. This is incorrect as of v3.0. See R05 for details.

**`validate_genealogical(conn, person_id: int) -> list[str]`** — runs all genealogical constraint rules (R40–R46) for a single Person and their associated Events, Relationships, and linked Records. `conn` is an open SQLite connection. Returns a flat list of warning strings. Can be run in batch across all Persons via `validate(conn)` (which calls this function per Person in the conclusion layer). Formerly described as `DataStore.validate_genealogical()`; the `DataStore` class has been removed.

---

## 11. Validation Error Format

Every error string follows a fixed format:

```

[Rnn] {ObjectType} {id}: {human-readable description}

```

Examples:

```

[R03] Record 47: raw_text is absent or empty
[R13] Record 47: source_id=999 does not resolve to a Source
[R29] Record 88: event_type='occupation' is not a valid event type
[R36] Record 12: date='April 1890' is not a valid ISO 8601 partial date
[R40] Person 23: has 0 birth Events marked is_primary — exactly 1 required; rebuild-consensus may not have run
[R40] Person 23: has 2 birth Events marked is_primary — exactly 1 permitted; probable data integrity error
[R41] Person 31: has 2 death Events but none marked is_primary — exactly 1 required when death Events exist; rebuild-consensus may not have run
[R43] Person 23: sequence violation — marriage date 1878 (exact) precedes birth date 1880 (exact); intervals do not overlap; probable merge error
[R43] Person 56: sequence check birth-before-baptism skipped — qualifier 'before' on Event 14 does not bound the comparison in the required direction
[R44] Relationship 7 (parent_child): parent Person 12 birth year 1870 — child Person 23 birth year 1858 — gap of -12 years is below minimum of 15; probable merge error
[R44] Relationship 9 (parent_child): male parent Person 4 birth year 1820 — child Person 88 birth year 1890 — gap of 70 years exceeds paternal maximum of 65; probable merge error
[R45] Person 44: marriage Event 19 dated 1872 — birth year 1860 (from is_primary birth Event) places Person at age 12 at marriage; minimum age is 15; probable merge error
[R46] person_record (person_id=12, record_id=203): record date 1901 is more than 5 years outside Person lifespan bounds [1800–1895] (lower from is_primary birth Event); probable merge error

```

The `[Rnn]` prefix is machine-parseable. The object type and id are always present so errors can be correlated back to database rows. Genealogical constraint warnings (R40–R46) are distinguishable from schema errors by their rule code range.

---

## Changelog

| Version | Date | Change |
|---|---|---|
| 2.1 | May 2026 | Initial version for v2.1 schema |
| 2.2 | May 2026 | Revised for SQLite. Added enforcement locus annotations. Added Repository structural rule (R01). Renumbered rules throughout. Retired R23 (Person↔Relationship bidirectionality), R24 (Person↔Event bidirectionality), R25 (Relationship↔Event bidirectionality), R27 (evidence-layer isolation) — all superseded by junction table architecture. R22 (self-reference) reclassified as DB-only. Corrected erroneous reference to Place.date_qualifier in date qualifier rule. Added rule summary table. |
| 2.3 | May 2026 | Retired R10 (name object completeness) and R33 (name type vocabulary) — both superseded by `person_name` table constraints. Python-only rules reduced from 6 to 4: R20, R21, R26, R36. |
| 2.4 | May 2026 | Retired R35 (confidence vocabulary) — `confidence` removed from `relationship` and `event` tables. Added R38 (linkage score range, DB + Python) and R39 (verified flag values, DB + Python) covering the new scoring columns on `person_record`, `event_record`, `relationship_record`, `place_record`. Updated rule summary table and execution order. |
| 2.5 | May 2026 | Added `genealogical_constraints.md` to preamble. Added fifth rule category — genealogical constraint rules. Added §6 (Genealogical Constraint Rules) with R40 (birth Event singularity, GC04), R41 (death Event singularity, GC05), R42 (census Record singularity per source, GC07), R43 (life event sequence, GC02), R44 (minimum and maximum parent age, GC12), R45 (minimum marriage age, GC13), R46 (lifespan boundary, GC01). Added `validate_genealogical()` entry point to §9. Extended execution order in §8 to include genealogical constraint category and added SKIP message for unevaluable persons. Renumbered §§6–9 to §§7–10. Updated rule summary table. Added R40–R46 examples to §10 error format. |
| 2.6 | May 2026 | Updated R38 (linkage score range) to permit null scores for manually-asserted linkages. Updated rule text, DB enforcement expression, and rule summary table. |
| 2.7 (schema) | May 2026 | No validation rule changes for place_authority addition. |
| 2.8 (schema) | June 2026 | Retired R14 (`recorded_event` removed) and R26 (`event_recorded_event` removed). R04 merged into R03/R36. R20 reclassified as DB-structural. R23 updated (no `person_relationship` table). R25 updated (no `relationship_event` table). R29, R30, R36, R43, R46 updated to reference `record.event_type` / `record.date` instead of `recorded_event` fields. Rule summary table and Python-only/retired rule lists updated. |
| 2.7 (rules) | 18 June 2026 | R05 updated: `role` nullable from schema v3.0; `validate_object()` over-strictness flagged as known code bug; "role is absent or empty" error message retired. R09 and R19 updated: `place` conclusion object retired; `place_authority` is now the structural place table; R09 rewritten for PlaceAuthority required fields; R19 rewritten for `place_record` FK integrity against `place_authority`. R31 updated: `'unknown'` added to role vocabulary; null role explicitly exempt from vocabulary check; DB `CHECK` expression updated to `role IS NULL OR role IN (...)`. §1 overview entry point reference updated to remove DataStore class. §9 (Validation Entry Points) rewritten: `DataStore.` prefix removed; `validate(conn)` and `validate_genealogical(conn, person_id)` correct signatures documented; pre-write check described as inline repo-level rather than single-function; known code bug for null role noted. §7 (Pending Rules) added: R47 (RecordedRelationship structural), R48 (RecordedRelationship FK integrity), R49 (RecordSimilarity structural), R50 (training_labels write guard). Rule summary table extended with R47–R50; pending rule classification list added. Execution order updated to reference pending rules. Sections renumbered: former §7–§10 are now §8–§11. |
| 2.9 | 24 June 2026 | Status notice added. §6 (R40–R46) and `src/review/validator.py` superseded by the new review layer design (session 18). Document retained as historical record. See `ROADMAP.md` §5.9 for the new design. |
| 2.8 (rules) | 18 June 2026 | R40 rewritten: "birth Event singularity" replaced by "birth Event `is_primary` cardinality" — rule now checks that exactly one birth Event is marked `is_primary`, not that at most one birth Event exists; two- and zero-primary cases produce distinct messages; relationship-scoped scope note added. R41 rewritten: same restructuring as R40 for death Events; fire condition restricted to Persons with at least one death Event linked. R43 redesigned: qualifier-aware interval table added covering all seven qualifier values; `before`/`after` asymmetric handling and skip logic documented; adult baptism exception clarified to specify which RecordedPerson is checked; implementation gap between this specification and the current `validator.py` placeholder explicitly flagged; new error message format includes qualifier in output. R44 updated: title changed to "Parent age range"; paternal maximum of 65 years added alongside existing maternal maximum of 50 years; gender-unknown skip case documented; `is_primary` birth Event sourcing specified. R45 updated: birth year sourcing changed to `is_primary` birth Event with Record-estimated fallback; error message format updated to include derivation source. R46 updated: lifespan bounds changed to source from `is_primary` birth/baptism/death Events explicitly; error message format updated to include bound source. §8 rule summary table updated for R40, R41, R43, R44, R45, R46. §11 error format examples extended for R40, R41, R43, R44, R45, R46. |

---

*Related documents: `conceptual_model.md`, `data_dictionary.md`, `database_schema.md`, `reconstruction_algorithms.md`, `genealogical_constraints.md`*

*Schema version: 3.0 — 18 June 2026 (rules v2.8)*
```
