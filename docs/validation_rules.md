# Irish Genealogy Research — Validation Rules

*Version 2.5 — May 2026*
*Audience: Developers and data engineers. This document is the authoritative specification for all validation rules enforced by the Python validation layer. It is the companion to `data_dictionary.md`, `conceptual_model.md`, `database_schema.md`, and `genealogical_constraints.md`.*

---

## 1. Overview

### Validation in a relational database

The move from JSON files to SQLite changes the distribution of enforcement responsibility. The database now enforces a significant subset of the rules that previously required Python code. This document reflects that shift.

Rules are annotated with their enforcement locus:

- **[DB]** — enforced by a SQLite constraint (`NOT NULL`, `CHECK`, `UNIQUE`, `REFERENCES`). A violation raises a constraint error on insert or update and cannot reach the Python layer.
- **[Python]** — enforced exclusively by the Python validator. The database schema cannot express this invariant declaratively.
- **[DB + Python]** — the database enforces what it can; Python enforces the remainder or validates before write.
- **[Retired]** — the rule is no longer meaningful in the relational model and has been removed.

The Python validator's role has shifted from *checking a loaded dataset for consistency* to *validating objects before they are written to the database*. The two entry points reflect this: `DataStore.validate()` for full dataset checks, and `DataStore.validate_object()` for pre-write single-object checks.

### Rule categories

Rules are grouped into five categories, executed in order:

1. **Structural rules** — well-formedness of individual objects
2. **Referential integrity rules** — foreign keys resolve to existing objects
3. **Consistency rules** — cross-object invariants
4. **Vocabulary and format rules** — controlled values and date formats
5. **Genealogical constraint rules** — domain knowledge checks derived from `genealogical_constraints.md`; near-zero probability violations flagged as merge error candidates

Each rule carries a code in the form `[Rnn]`. Error messages always include the rule code and the primary key of the offending object. The validator returns a flat list of error strings. A dataset is considered valid when the list is empty.

---

## 2. Structural Rules

Structural rules check that required fields are present, non-null, and non-empty on every object, independent of any other object.

### R01 — Required fields present on Repository `[DB + Python]`

Every Repository must have `repository_id`, `name`, and `url`. Both `name` and `url` must be non-null and non-empty.

DB enforcement: `NOT NULL` and `CHECK (trim(name) != '')`, `CHECK (trim(url) != '')` on the `repository` table.
Python enforcement: pre-write validation via `validate_object()`.

```
[R01] Repository {id}: required field '{field}' is absent or empty
```

---

### R02 — Required fields present on Source `[DB + Python]`

Every Source must have `source_id`, `title`, `type`, and `repository_id`. All must be non-null and, for string fields, non-empty.

DB enforcement: `NOT NULL` and `CHECK` constraints on the `source` table.
Python enforcement: pre-write validation via `validate_object()`.

```
[R02] Source {id}: required field '{field}' is absent or empty
```

---

### R03 — Required fields present on Record `[DB + Python]`

Every Record must have `record_id`, `source_id`, and `raw_text`. `raw_text` must be non-null and non-empty after stripping whitespace. A whitespace-only `raw_text` is treated as absent.

DB enforcement: `NOT NULL` and `CHECK (trim(raw_text) != '')` on the `record` table.
Python enforcement: pre-write validation via `validate_object()`.

```
[R03] Record {id}: raw_text is absent or empty
[R03] Record {id}: required field '{field}' is absent or null
```

---

### R04 — Required fields present on RecordedEvent `[DB + Python]`

Every RecordedEvent must have `recorded_event_id`, `record_id`, and `type`. `type` must be non-null and non-empty.

DB enforcement: `NOT NULL` constraints on the `recorded_event` table.
Python enforcement: pre-write validation via `validate_object()`.

```
[R04] RecordedEvent {id}: required field '{field}' is absent or null
```

---

### R05 — Required fields present on RecordedPerson `[DB + Python]`

Every RecordedPerson must have `recorded_person_id`, `record_id`, `name_as_recorded`, and `role`. Both `name_as_recorded` and `role` must be non-null and non-empty after stripping whitespace.

DB enforcement: `NOT NULL` and `CHECK` constraints on the `recorded_person` table.
Python enforcement: pre-write validation via `validate_object()`.

```
[R05] RecordedPerson {id}: name_as_recorded is absent or empty
[R05] RecordedPerson {id}: role is absent or empty
[R05] RecordedPerson {id}: required field '{field}' is absent or null
```

---

### R06 — Required fields present on Person `[DB + Python]`

Every Person must have `person_id` and `label`. `label` must be non-null and non-empty.

DB enforcement: `NOT NULL` and `CHECK (trim(label) != '')` on the `person` table.
Python enforcement: pre-write validation via `validate_object()`.

```
[R06] Person {id}: required field '{field}' is absent or empty
```

---

### R07 — Required fields present on Relationship `[DB + Python]`

Every Relationship must have `relationship_id`, `type`, `person_id_1`, and `person_id_2`. All must be non-null.

DB enforcement: `NOT NULL` constraints on the `relationship` table.
Python enforcement: pre-write validation via `validate_object()`.

```
[R07] Relationship {id}: required field '{field}' is absent or null
```

---

### R08 — Required fields present on Event `[DB + Python]`

Every Event must have `event_id` and `type`. Both must be non-null and non-empty.

DB enforcement: `NOT NULL` constraints on the `event` table.
Python enforcement: pre-write validation via `validate_object()`.

```
[R08] Event {id}: required field '{field}' is absent or empty
```

---

### R09 — Required fields present on Place `[DB + Python]`

Every Place must have `place_id` and `name`. `name` must be non-null and non-empty.

DB enforcement: `NOT NULL` and `CHECK (trim(name) != '')` on the `place` table.
Python enforcement: pre-write validation via `validate_object()`.

```
[R09] Place {id}: required field '{field}' is absent or empty
```

---

### R10 — Name object completeness `[Retired]`

**Retired.** `Person.names` was previously stored as a JSON array in a TEXT column, making structural validation of individual name entries Python-only. Names are now stored in the `person_name` table, where `NOT NULL` and `CHECK (trim(value) != '')` enforce field presence, and `CHECK (type IN (...))` enforces vocabulary. Both R10 and R33 are superseded by the table structure.

---

## 3. Referential Integrity Rules

In the relational schema, all single-column foreign keys are enforced by `REFERENCES` constraints with `PRAGMA foreign_keys = ON`. A violation raises a SQLite constraint error on insert or update and cannot reach the Python layer.

All junction table foreign keys are likewise enforced at the DB level — an attempt to insert a row referencing a non-existent primary key is rejected immediately.

Python's residual responsibility in this section is **pre-write validation**: before constructing INSERT statements, `validate_object()` should confirm that referenced IDs exist in the DataStore. This catches errors earlier and produces friendlier error messages than raw SQLite constraint errors.

### R11 — Repository → (no upstream FK) `[N/A]`

Repository is a root object with no foreign keys. No referential integrity rule applies.

---

### R12 — Source → Repository `[DB + Python]`

`Source.repository_id` must resolve to an existing Repository.

DB enforcement: `REFERENCES repository (repository_id)` on the `source` table.

```
[R12] Source {id}: repository_id={val} does not resolve to a Repository
```

---

### R13 — Record → Source `[DB + Python]`

`Record.source_id` must resolve to an existing Source.

DB enforcement: `REFERENCES source (source_id)` on the `record` table.

```
[R13] Record {id}: source_id={val} does not resolve to a Source
```

---

### R14 — RecordedEvent → Record `[DB + Python]`

`RecordedEvent.record_id` must resolve to an existing Record.

DB enforcement: `REFERENCES record (record_id)` on the `recorded_event` table.

```
[R14] RecordedEvent {id}: record_id={val} does not resolve to a Record
```

---

### R15 — RecordedPerson → Record `[DB + Python]`

`RecordedPerson.record_id` must resolve to an existing Record.

DB enforcement: `REFERENCES record (record_id)` on the `recorded_person` table.

```
[R15] RecordedPerson {id}: record_id={val} does not resolve to a Record
```

---

### R16 — Person foreign keys `[DB + Python]`

Each entry in `Person.record_ids` must resolve to an existing Record. Each entry in `Person.event_ids` must resolve to an existing Event. Each entry in `Person.relationship_ids` must resolve to an existing Relationship.

DB enforcement: `REFERENCES` constraints on all three junction tables (`person_record`, `person_event`, `person_relationship`). A junction row referencing a non-existent ID is rejected.

```
[R16] Person {id}: record_id={val} does not resolve to a Record
[R16] Person {id}: event_id={val} does not resolve to an Event
[R16] Person {id}: relationship_id={val} does not resolve to a Relationship
```

---

### R17 — Relationship foreign keys `[DB + Python]`

`Relationship.person_id_1` and `Relationship.person_id_2` must each resolve to an existing Person. Each entry in `Relationship.record_ids` must resolve to an existing Record. Each entry in `Relationship.event_ids` must resolve to an existing Event.

DB enforcement: `REFERENCES person` on both FK columns; `REFERENCES` constraints on junction tables `relationship_record` and `relationship_event`.

```
[R17] Relationship {id}: person_id_1={val} does not resolve to a Person
[R17] Relationship {id}: person_id_2={val} does not resolve to a Person
[R17] Relationship {id}: record_id={val} does not resolve to a Record
[R17] Relationship {id}: event_id={val} does not resolve to an Event
```

---

### R18 — Event foreign keys `[DB + Python]`

`Event.place_id`, when present, must resolve to an existing Place. Each entry in `Event.person_ids` must resolve to an existing Person. `Event.relationship_id`, when present, must resolve to an existing Relationship. Each entry in `Event.record_ids` must resolve to an existing Record. Each entry in `Event.recorded_event_ids` must resolve to an existing RecordedEvent.

DB enforcement: `REFERENCES place` and `REFERENCES relationship` on the `event` table; `REFERENCES` constraints on junction tables `event_person`, `event_record`, `event_recorded_event`.

```
[R18] Event {id}: place_id={val} does not resolve to a Place
[R18] Event {id}: person_id={val} does not resolve to a Person
[R18] Event {id}: relationship_id={val} does not resolve to a Relationship
[R18] Event {id}: record_id={val} does not resolve to a Record
[R18] Event {id}: recorded_event_id={val} does not resolve to a RecordedEvent
```

---

### R19 — Place foreign keys `[DB + Python]`

Each entry in `Place.record_ids`, when present, must resolve to an existing Record.

DB enforcement: `REFERENCES record` on junction table `place_record`.

```
[R19] Place {id}: record_id={val} does not resolve to a Record
```

---

## 4. Consistency Rules

### R20 — Exactly one RecordedEvent per Record `[DB + Python]`

Every Record must have exactly one RecordedEvent whose `record_id` points to it.

DB enforcement: `UNIQUE (record_id)` on the `recorded_event` table prevents more than one RecordedEvent per Record (upper bound). The lower bound — zero RecordedEvents — cannot be enforced declaratively and remains Python-only.

Python enforcement: after inserting a Record, the validator must confirm that exactly one RecordedEvent exists for it before the Record is considered committed.

```
[R20] Record {id}: has 0 RecordedEvents — exactly 1 required
```

*(The over-count case — more than one RecordedEvent — cannot be produced by a valid insert due to the DB UNIQUE constraint and therefore produces no error message.)*

---

### R21 — At least one RecordedPerson per Record `[Python]`

Every Record must have at least one RecordedPerson whose `record_id` points to it. SQLite cannot enforce a minimum child-row count declaratively.

```
[R21] Record {id}: has no RecordedPersons — at least 1 required
```

---

### R22 — Relationship self-reference prohibition `[DB]`

`Relationship.person_id_1` and `Relationship.person_id_2` must not be equal. Enforced by `CHECK (person_id_1 != person_id_2)` on the `relationship` table. A violating insert is rejected by the DB; this rule requires no Python enforcement and generates no Python error message.

*Documented here for completeness. No Python action required.*

---

### R23 — Bidirectional consistency: Person ↔ Relationship `[Retired]`

**Retired.** In the JSON model, `Person.relationship_ids` was a list maintained independently of the `Relationship` object, and drift between the two was possible. In the relational schema, the `person_relationship` junction table is the single source of truth for this association. There is no second list to diverge from. The invariant is structurally enforced by the schema.

---

### R24 — Bidirectional consistency: Person ↔ Event `[Retired]`

**Retired.** Same reasoning as R23. The `person_event` junction table is the single source of truth. `Person.event_ids` and `Event.person_ids` are both derived by querying the same junction table rows; they cannot diverge.

---

### R25 — Bidirectional consistency: Relationship ↔ Event `[Retired]`

**Retired.** Same reasoning as R23 and R24. The `relationship_event` junction table is the single source of truth. `Relationship.event_ids` and the `Event.relationship_id` back-reference cannot produce a mismatch that the DB permits to exist.

---

### R26 — RecordedEvent ↔ Event Record consistency `[Python]`

If an Event includes a `recorded_event_id` in `event_recorded_event`, then the parent `record_id` of that RecordedEvent must also appear in `event_record` for the same Event. A RecordedEvent cannot be cited as evidence for an Event while its parent Record is not.

This cross-table invariant cannot be expressed as a declarative constraint in SQLite and remains Python-only.

```
[R26] Event {id}: recorded_event_id={val} is included but its parent record_id={rec_id} is not in Event.record_ids
```

---

### R27 — Evidence-layer objects contain no conclusion-layer foreign keys `[Retired]`

**Retired.** In the JSON model, this rule detected cases where a conclusion-layer foreign key had been written into a RecordedEvent or RecordedPerson object. In the relational schema, the `recorded_event` and `recorded_person` tables have no columns for `person_id`, `event_id`, `relationship_id`, or `place_id`. The violation is architecturally impossible. No rule text is needed.

---

## 5. Vocabulary and Format Rules

### R28 — Source type controlled vocabulary `[DB + Python]`

`Source.type` must be one of the values defined in §6.1 of the data dictionary.

Valid values: `valuation`, `tithe`, `census`, `birth_registration`, `marriage_registration`, `death_registration`, `parish_register`, `military`, `folklore`.

DB enforcement: `CHECK (type IN (...))` on the `source` table.

```
[R28] Source {id}: type='{val}' is not a valid source type
```

---

### R29 — Event type controlled vocabulary `[DB + Python]`

`RecordedEvent.type` and `Event.type` must each be one of the values defined in §6.2 of the data dictionary.

Valid values: `birth`, `baptism`, `marriage`, `death`, `burial`, `census`, `residence`, `emigration`, `valuation`, `tithe`, `military_service`, `pension`, `folklore`.

DB enforcement: `CHECK (type IN (...))` on both `recorded_event` and `event` tables.

```
[R29] RecordedEvent {id}: type='{val}' is not a valid event type
[R29] Event {id}: type='{val}' is not a valid event type
```

---

### R30 — Date qualifier controlled vocabulary `[DB + Python]`

`RecordedEvent.date_qualifier` and `Event.date_qualifier`, when present, must each be one of the values defined in §6.3 of the data dictionary. `Place` has no `date_qualifier` field; the previous reference to it was erroneous and has been removed.

Valid values: `exact`, `about`, `before`, `after`, `between`, `estimated`, `calculated`.

DB enforcement: `CHECK (date_qualifier IS NULL OR date_qualifier IN (...))` on both `recorded_event` and `event` tables.

```
[R30] RecordedEvent {id}: date_qualifier='{val}' is not a valid date qualifier
[R30] Event {id}: date_qualifier='{val}' is not a valid date qualifier
```

---

### R31 — RecordedPerson role controlled vocabulary `[DB + Python]`

`RecordedPerson.role` must be one of the values defined in §6.4 of the data dictionary.

Valid values: `principal`, `head`, `spouse`, `child`, `groom`, `bride`, `father`, `mother`, `father_of_groom`, `father_of_bride`, `godfather`, `godmother`, `witness`, `informant`, `officiator`, `occupier`, `lessor`, `deceased`.

DB enforcement: `CHECK (role IN (...))` on the `recorded_person` table.

```
[R31] RecordedPerson {id}: role='{val}' is not a valid role
```

---

### R32 — Person gender controlled vocabulary `[DB + Python]`

`Person.gender`, when present, must be one of the values defined in §6.5 of the data dictionary.

Valid values: `male`, `female`, `unknown`.

DB enforcement: `CHECK (gender IS NULL OR gender IN (...))` on the `person` table.

```
[R32] Person {id}: gender='{val}' is not a valid gender value
```

---

### R33 — Name type controlled vocabulary `[Retired]`

**Retired.** Name type vocabulary was previously Python-only because names were stored as a JSON array in a TEXT column. Names are now stored in the `person_name` table with a `CHECK (type IN (...))` constraint. Vocabulary enforcement is now DB-level, consistent with all other vocabulary rules.

---

### R34 — Relationship type controlled vocabulary `[DB + Python]`

`Relationship.type` must be one of the values defined in §6.7 of the data dictionary.

Valid values: `couple`, `parent_child`, `sibling`.

DB enforcement: `CHECK (type IN (...))` on the `relationship` table.

```
[R34] Relationship {id}: type='{val}' is not a valid relationship type
```

---

### R35 — Confidence controlled vocabulary `[Retired]`

**Retired.** `Relationship.confidence` and `Event.confidence` have been removed from the schema. Confidence was a static scalar that could not capture the per-linkage granularity required by the reconstruction algorithm. Aggregate confidence, where needed for display, is derived at query time from the `score` values across all linked Records in the relevant junction table. The `CHECK` constraints on both tables have been dropped.

---

### R36 — Date format `[Python]`

All fields typed as `date` — `RecordedEvent.date` and `Event.date` — must conform to one of three valid ISO 8601 partial date forms when non-null. SQLite has no native date type and stores these fields as TEXT; format validation is Python-only.

| Form | Pattern | Constraints |
|---|---|---|
| `YYYY` | Four-digit year | Year must be a plausible genealogical year (1500–2100) |
| `YYYY-MM` | Year and month | Month must be 01–12 |
| `YYYY-MM-DD` | Full date | Month 01–12; day 01–28/29/30/31 valid for the given month |

Note: `RecordedEvent.date_as_recorded` is a free-text verbatim field and is explicitly exempt from this rule.

Text dates, circa prefixes, non-ISO separators, two-digit years, and day or month values of zero are all invalid.

```
[R36] RecordedEvent {id}: date='{val}' is not a valid ISO 8601 partial date
[R36] Event {id}: date='{val}' is not a valid ISO 8601 partial date
```

---

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

All rules in this section are **[Python]** only. They require cross-object lookups against the existing conclusion layer and cannot be expressed as SQLite constraints. They run as part of `DataStore.validate()` and are also callable individually for targeted post-linkage checks.

**Relationship to `genealogical_constraints.md`:** Each rule cites the GC code of the constraint it formalises. The GC document is the authoritative source for the genealogical rationale; this document is the authoritative source for the validation implementation.

**Error severity:** Rules in this section produce warnings rather than hard errors by default. A warning is a flag surfaced to the researcher for review — it does not prevent a linkage from being committed. The researcher's `verified = 1` on the relevant junction row is the mechanism for acknowledging and overriding a warning. This is consistent with the probabilistic framing of the overall system.

---

### R40 — Birth Event singularity `[Python]` *(GC04)*

A concluded `Person` may not be linked to more than one birth `Event` via `person_event`. Multiple birth Events on the same Person indicate a conclusion-layer merge error — most commonly two Records from different sources (e.g. a civil birth registration and a baptism) have been incorrectly concluded as separate birth Events rather than synthesised into one.

This rule queries `person_event` joined to `event` to count birth-type Events per Person. A count greater than one triggers the warning.

```
[R40] Person {id}: has {n} birth Events — maximum 1 permitted; probable merge error
```

---

### R41 — Death Event singularity `[Python]` *(GC05)*

A concluded `Person` may not be linked to more than one death `Event` via `person_event`. A burial Event linked to the same Person is permitted and expected — this rule checks only Events of type `death`.

```
[R41] Person {id}: has {n} death Events — maximum 1 permitted; probable merge error
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

For any concluded `Person`, the dates of their concluded life Events must follow chronological order where those dates are non-null and their uncertainty ranges do not overlap. Confirmed sequence violations indicate a merge error.

**Checks performed:**

| Check | Condition flagged |
|---|---|
| Birth before baptism | Baptism date is more than 2 years before birth date (excluding adult baptism — see below) |
| Birth before all other events | Any non-birth, non-baptism Event date precedes birth date (net of tolerance) |
| Marriage before death | Death date precedes any marriage Event date the Person participated in (net of tolerance) |
| Death before burial | Burial date precedes death date (net of tolerance) |
| Events after death | Any census, residence, valuation, tithe, or military Event date follows death date (net of tolerance) |

**Tolerance:** Where an event date carries a qualifier of `about`, `estimated`, or `calculated`, a tolerance of ±2 years is applied before flagging. A sequence violation is only confirmed if the uncertainty ranges of the two dates do not overlap.

**Adult baptism exception:** Where the baptism RecordedEvent's linked RecordedPerson has a recorded age greater than 1 year, the birth-before-baptism interval check is suppressed for that Event pair.

**Date qualifier precedence:** `exact` dates are compared directly. All other qualifiers trigger the ±2 year tolerance.

```
[R43] Person {id}: sequence violation — {event_type_1} date {date_1} precedes {event_type_2} date {date_2} (net of tolerance)
```

---

### R44 — Minimum parent age `[Python]` *(GC12)*

For any `parent_child` Relationship, the gap between the parent's concluded birth year and the child's concluded birth year must be at least 15 years, net of age tolerances on both. A gap below 15 years is a near-zero probability biological violation and is flagged as a merge error candidate.

Additionally, for a female parent (where `Person.gender = 'female'`), a gap greater than 50 years is also flagged.

This rule requires both Persons in the Relationship to have a concluded birth Event or an estimated birth year derivable from their linked Records. Where neither Person has a birth year, the rule is skipped and noted as unevaluated.

**Tolerance:** ±2 years applied to both parent and child birth year estimates before computing the gap.

```
[R44] Relationship {id} (parent_child): parent Person {pid} birth year {py} — child Person {cid} birth year {cy} — gap of {gap} years is below minimum of 15; probable merge error
[R44] Relationship {id} (parent_child): female parent Person {pid} birth year {py} — child Person {cid} birth year {cy} — gap of {gap} years exceeds maternal maximum of 50; probable merge error
```

---

### R45 — Minimum marriage age `[Python]` *(GC13)*

For any Person linked to a marriage `Event` via `person_event`, the gap between the Person's concluded birth year and the marriage Event date must be at least 15 years, net of age tolerance. A gap below 15 years is flagged as a merge error candidate.

Where the Person has no concluded birth year derivable from their linked Records, the rule is skipped and noted as unevaluated.

**Tolerance:** ±2 years applied to birth year estimate before computing the gap.

```
[R45] Person {id}: marriage Event {eid} dated {marriage_date} — concluded birth year {by} places Person at age {age} at marriage; minimum age is 15; probable merge error
```

---

### R46 — Lifespan boundary `[Python]` *(GC01)*

For any Person linked to a Record via `person_record`, the RecordedEvent date of that Record must fall within the Person's concluded lifespan. A RecordedEvent date more than 5 years outside the lifespan bounds is flagged regardless of the linkage score.

**Lifespan bounds:**
- Lower bound: concluded birth Event date, or baptism Event date where no birth Event exists, or estimated birth year derived from linked Records.
- Upper bound: concluded death Event date where known; otherwise unbounded.

**Tolerance:** ±5 years applied to both bounds before flagging.

Where neither a lower nor upper bound can be established from the Person's concluded Events, the rule is skipped and noted as unevaluated.

```
[R46] person_record (person_id={pid}, record_id={rid}): RecordedEvent date {date} is more than 5 years outside Person lifespan bounds [{lower}–{upper}]; probable merge error
```

---

## 7. Rule Summary Table

The following table summarises all rules, their description, and their enforcement locus.

| Rule | Description | Enforcement |
|---|---|---|
| R01 | Required fields on Repository | DB + Python |
| R02 | Required fields on Source | DB + Python |
| R03 | Required fields on Record | DB + Python |
| R04 | Required fields on RecordedEvent | DB + Python |
| R05 | Required fields on RecordedPerson | DB + Python |
| R06 | Required fields on Person | DB + Python |
| R07 | Required fields on Relationship | DB + Python |
| R08 | Required fields on Event | DB + Python |
| R09 | Required fields on Place | DB + Python |
| R10 | Name object completeness | **Retired** |
| R11 | Repository has no upstream FK | N/A |
| R12 | Source → Repository FK | DB + Python |
| R13 | Record → Source FK | DB + Python |
| R14 | RecordedEvent → Record FK | DB + Python |
| R15 | RecordedPerson → Record FK | DB + Python |
| R16 | Person FK arrays | DB + Python |
| R17 | Relationship FK arrays | DB + Python |
| R18 | Event FK arrays | DB + Python |
| R19 | Place FK arrays | DB + Python |
| R20 | Exactly one RecordedEvent per Record (lower bound) | Python only |
| R21 | At least one RecordedPerson per Record | Python only |
| R22 | Relationship self-reference prohibition | DB only |
| R23 | Person ↔ Relationship bidirectionality | **Retired** |
| R24 | Person ↔ Event bidirectionality | **Retired** |
| R25 | Relationship ↔ Event bidirectionality | **Retired** |
| R26 | RecordedEvent ↔ Event Record consistency | Python only |
| R27 | Evidence-layer isolation | **Retired** |
| R28 | Source type vocabulary | DB + Python |
| R29 | Event type vocabulary | DB + Python |
| R30 | Date qualifier vocabulary | DB + Python |
| R31 | RecordedPerson role vocabulary | DB + Python |
| R32 | Person gender vocabulary | DB + Python |
| R33 | Name type vocabulary | **Retired** |
| R34 | Relationship type vocabulary | DB + Python |
| R35 | Confidence vocabulary | **Retired** |
| R36 | Date format | Python only |
| R37 | record_parameters keys match record_parameter_names | Python only |
| R38 | Linkage score range [0.0–1.0] or null (manual assertion) | DB + Python |
| R39 | Verified flag values {0, 1} | DB + Python |
| R40 | Birth Event singularity | Python only (GC04) |
| R41 | Death Event singularity | Python only (GC05) |
| R42 | Census Record singularity per source | Python only (GC07) |
| R43 | Life event sequence | Python only (GC02) |
| R44 | Minimum and maximum parent age | Python only (GC12) |
| R45 | Minimum marriage age | Python only (GC13) |
| R46 | Lifespan boundary | Python only (GC01) |

**Python-only rules** (require active Python enforcement): R20, R21, R26, R36, R37, R40, R41, R42, R43, R44, R45, R46.
**Retired rules** (no longer meaningful in the relational model): R10, R23, R24, R25, R27, R33, R35.
**DB-only rule** (no Python action needed): R22.

---

## 8. Execution Order and Dependency

Rules are executed in the following order. Later rules depend on earlier ones having passed.

1. **Structural rules (R01–R09)** — object well-formedness. No cross-object lookups. Safe to run in isolation via `validate_object()`.
2. **Referential integrity rules (R12–R19)** — pre-write checks that referenced IDs exist. In normal operation the DB enforces these; Python checks them to produce actionable error messages before attempting an insert.
3. **Consistency rules (R20–R26)** — cross-object invariants. Depend on referential integrity holding.
4. **Vocabulary and format rules (R28–R39)** — controlled values, date formats, and scoring column constraints. Run last among the schema rules to separate structural problems from vocabulary problems in the error output.
5. **Genealogical constraint rules (R40–R46)** — domain knowledge checks. Run after all schema rules are clean. Depend on the conclusion layer being populated; skipped for objects with unresolved birth year or lifespan bounds. Produce warnings rather than hard errors.

When a referential integrity error is present, downstream consistency rules that would traverse the broken reference are skipped for the affected object:

```
[SKIP] Consistency checks for {ObjectType} {id} skipped: unresolved foreign key(s) from R12–R19
```

When a birth year or lifespan bound cannot be established for a Person, genealogical constraint rules that require it are skipped and noted:

```
[SKIP] R{nn} for Person {id} skipped: birth year not determinable from concluded Events or linked Records
```

---

## 9. Validation Entry Points

**`DataStore.validate() -> list[str]`** — full validation of all Python-only rules against the current database state. Queries the database directly. Returns a flat list of error strings. An empty list means the dataset is valid with respect to all Python-enforced rules. (DB-enforced rules are assumed to hold if the database was written through the normal Python layer with `PRAGMA foreign_keys = ON`.)

**`DataStore.validate_object(obj_type: str, obj: dict) -> list[str]`** — structural and vocabulary validation of a single object in isolation, without referential integrity, consistency, or genealogical constraint checks. Used during interactive ingestion to give immediate feedback before a new object is committed to the store.

**`DataStore.validate_genealogical(person_id: int) -> list[str]`** — runs all genealogical constraint rules (R40–R46) for a single Person and their associated Events, Relationships, and linked Records. Returns a flat list of warning strings. Called by the Person Browser to surface merge error candidates and anomalies alongside the source coverage display. Can also be run in batch across all Persons via `DataStore.validate()`.

---

## 10. Validation Error Format

Every error string follows a fixed format:

```
[Rnn] {ObjectType} {id}: {human-readable description}
```

Examples:

```
[R03] Record 47: raw_text is absent or empty
[R13] Record 47: source_id=999 does not resolve to a Source
[R20] Record 47: has 0 RecordedEvents — exactly 1 required
[R29] RecordedEvent 88: type='occupation' is not a valid event type
[R36] Event 12: date='April 1890' is not a valid ISO 8601 partial date
[R40] Person 23: has 2 birth Events — maximum 1 permitted; probable merge error
[R43] Person 23: sequence violation — marriage date 1878 precedes birth date 1880 (net of tolerance)
[R44] Relationship 7 (parent_child): parent Person 12 birth year 1870 — child Person 23 birth year 1858 — gap of -12 years is below minimum of 15; probable merge error
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

---

*Related documents: `conceptual_model.md`, `data_dictionary.md`, `database_schema.md`, `reconstruction_algorithms.md`, `genealogical_constraints.md`*

*Schema version: 2.4 — May 2026*
