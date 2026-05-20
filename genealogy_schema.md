# Irish Genealogy Research Schema v1.3

## 1. Preamble

### Design Principles

This schema defines a lightweight genealogical data model for personal Irish genealogy research. It is inspired by the GEDCOMx conceptual model but deliberately simplified for a two-collaborator environment (Python + Claude).

**Core principles:**

- **Evidence/conclusion separation** — the Record layer contains only verbatim transcriptions. No interpretation occurs at the Record level. Conclusions are expressed exclusively through Facts, Relationships, and Events.
- **GEDCOMx lite** — the schema adopts GEDCOMx conceptual architecture and URI vocabulary without implementing the full specification. When in doubt about a design decision, consult GEDCOMx.
- **File-based** — data is stored as JSON files. No database server required. Portable and human-readable.
- **Relational by reference** — objects link to each other via integer IDs. Python enforces referential integrity on load.
- **Two-tier architecture** — a global layer (Repositories, Sources, Places) is shared across all projects and bootstrapped once. A project layer (Records through to Persons) is community-scoped and grows over time.
- **External place authority** — Place objects link to townlands.ie and logainm.ie rather than maintaining an internal place hierarchy. Irish placename complexity is delegated to authoritative external sources.
- **Townland as primary scope anchor** — Irish administrative boundaries (DEDs, civil registration districts, ecclesiastical parishes) do not align across source types. The townland is the one unit stable across all sources and is used as the primary project scope definition.
- **Lightweight** — first class objects are kept to a minimum. Attribution, formal argument objects, and multi-researcher machinery are deliberately excluded. These simplifications are deliberate choices, not oversights.

### The Two-Collaborator Model

**Python handles:**
- Schema validation and referential integrity
- File I/O and batch ingestion
- Record linkage scoring (Fellegi-Sunter, Jaro-Winkler)
- Deterministic data manipulation and deduplication
- Place bootstrap automation against townlands.ie and logainm.ie APIs
- ID registry management within each project

**Claude handles:**
- Verbatim transcription of source images (small batches, fresh sessions)
- Ambiguous record interpretation
- Reasoning about conflicting evidence
- Hypothesis generation and narrative synthesis

### GEDCOMx Vocabulary

Controlled vocabulary values use GEDCOMx URIs where available. Custom types for Irish-specific concepts use the format:

```
http://irishgenealogy.local/gedcomx/{TypeName}
```

### ID Namespace

**Global IDs** — `repository_id`, `source_id`, and `place_id` are globally unique across all projects. They are assigned from the shared global layer and resolved against global directories during validation.

**Project-scoped IDs** — all other IDs (`record_id`, `named_individual_id`, `person_id`, `relationship_id`, `fact_id`, `event_id`) are scoped to a single project. They start from 1 within each project. The same ID value may appear in different projects without conflict.

---

## 2. Data Model

### 2.1 Object Summary

The schema has ten first-class objects organised into two tiers and three layers:

**Global tier** — shared infrastructure, bootstrapped once, independent of any project:
- Repository
- Source
- Place

**Project tier — Evidence layer** — faithful representation of what archives contain. No interpretation:
- Record
- NamedIndividual

**Project tier — Conclusion layer** — researcher assertions supported by evidence. Subject to revision:
- Person
- Relationship
- Fact
- Event

**Project manifest** — project scope definition:
- Project

### 2.2 Data Flow

```
Repository
  └── Source
        └── Record
              └── NamedIndividual
                      └── Event (via roles)
                            ├── Fact ──────► Person
                            └── Relationship
```

Each arrow represents a different kind of work:

| Transition | Work performed |
|---|---|
| Repository → Source | Provenance — source situated within its holding institution |
| Source → Record | Archival work — transcription and citation |
| Record → NamedIndividual | Extraction — person-shaped data pulled from record verbatim |
| NamedIndividual → Event | Grouping — participants assembled around a real-world occurrence |
| Event → Fact | Conclusion — synthesised assertion about a person or relationship |
| Fact → Person | Identity — concluded biography constituted by facts |
| NamedIndividual → Person | Linkage assertion (via Person.named_individual_ids) |

### 2.3 Entity Relationship Diagram

```
┌──────────────┐
│  REPOSITORY  │
│ repository_id│
└──────┬───────┘
       │ 1:N
┌──────▼──────┐
│   SOURCE    │
│  source_id  │
└──────┬──────┘
       │ 1:N
┌──────▼──────┐         ┌─────────────┐
│   RECORD    │────────►│    PLACE    │
│  record_id  │         │  place_id   │
│  source_id  │         └─────────────┘
└──────┬──────┘                ▲
       │ 1:N                   │
┌──────▼──────────────┐        │
│  NAMED INDIVIDUAL   │        │
│ named_individual_id │        │
│    record_id        │        │
└──────┬──────────────┘        │
       │ N:N (via roles)       │
┌──────▼──────┐                │
│    EVENT    │────────────────┤
│  event_id   │                │
│  record_ids │                │
│  fact_ids   │                │
│  roles[]    │                │
└──────┬──────┘                │
       │ 1:N                   │
┌──────▼──────┐                │
│    FACT     │────────────────┘
│   fact_id   │
│  person_id  │──────────────────────┐
│ relation_id │                      │
│  event_id   │         ┌────────────▼────────┐
│ record_ids  │         │       PERSON         │
└─────────────┘         │     person_id        │
                        │  named_individual_ids│◄── linkage assertion
                        │     fact_ids         │
                        │   relationship_ids   │
                        └──────────┬───────────┘
                                   │ N:N
                        ┌──────────▼───────────┐
                        │     RELATIONSHIP      │
                        │   relationship_id     │
                        │    person_id_1        │
                        │    person_id_2        │
                        │     fact_ids          │
                        └───────────────────────┘
```

**Key:**
- Global tier objects: Repository, Source, Place
- Project evidence layer objects: Record, NamedIndividual
- Project conclusion layer objects: Person, Relationship, Fact, Event
- The linkage assertion (NamedIndividual → Person) is the boundary between evidence and conclusion layers
- Place is referenced independently by Record, Event, and Fact
- Repository and Source are global; all other objects are project-scoped

---

## 3. Object Definitions

### 3.1 Repository

A Repository represents an institution or website that holds one or more Sources. It is a global object, shared across all projects, and defined once in the global layer.

```json
{
  "repository_id": 1,
  "name": "National Archives of Ireland",
  "url": "https://www.nationalarchives.ie",
  "location": "Dublin, Ireland",
  "notes": null
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| repository_id | integer | YES | Primary key — globally unique |
| name | string | YES | Full name of the institution or website |
| url | string | NO | Base URL of the repository |
| location | string | NO | Physical location of the institution |
| notes | string | NO | Free text notes |

---

### 3.2 Source

A Source represents a specific archival collection or register within a Repository. It is a global object, shared across all projects. Sources accumulate as projects expand into new areas — the canonical bootstrap set covers the primary online Irish sources, and additional sources are added as needed.

```json
{
  "source_id": 1,
  "repository_id": 3,
  "title": "Griffith's Valuation",
  "type": "valuation",
  "collection": "Valuation of Ireland 1847-1864",
  "date_from": 1847,
  "date_to": 1864,
  "source_url": "https://www.askaboutireland.ie/griffiths-valuation",
  "physical_location": null,
  "citation": "Griffith's Valuation (1857), Askaboutireland.ie (https://www.askaboutireland.ie/griffiths-valuation), accessed May 2026.",
  "notes": null
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| source_id | integer | YES | Primary key — globally unique |
| repository_id | integer | YES | Foreign key to Repository |
| title | string | YES | Name of the source |
| type | string | YES | Source type — see controlled vocabulary |
| collection | string | NO | Collection name or microfilm reference within the repository |
| date_from | integer | NO | Start year of source coverage |
| date_to | integer | NO | End year of source coverage |
| source_url | string | NO | URL of the source collection |
| physical_location | string | NO | Physical location for non-digital sources |
| citation | string | NO | Formatted bibliographic citation (Elizabeth Shown Mills style) |
| notes | string | NO | Free text notes |

---

### 3.3 Place

A Place represents an Irish townland. Place is a global object, shared across all projects. Place delegates complexity to external authoritative sources rather than maintaining an internal hierarchy or name variant list.

```json
{
  "place_id": 12,
  "name": "Straness",
  "townland_ie_url": "https://www.townlands.ie/donegal/raphoe/aughnish/straness/",
  "logainm_id": 12345,
  "logainm_url": "https://www.logainm.ie/en/12345",
  "notes": null
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| place_id | integer | YES | Primary key — globally unique |
| name | string | YES | Common working name of the townland |
| townland_ie_url | string | NO | Permalink to townlands.ie entry |
| logainm_id | integer | NO | Logainm.ie numeric identifier |
| logainm_url | string | NO | Permalink to logainm.ie entry |
| notes | string | NO | Free text notes |

Place hierarchy (townland → civil parish → barony → county), Irish language name, historical name variants, and geographic coordinates are all retrievable from the external sources via the linked URLs.

---

### 3.4 Project

A Project defines the geographic scope of a community research effort. It is anchored to a set of townlands — the one administrative unit stable across all Irish source types. Administrative boundaries (DEDs, civil registration districts, ecclesiastical parishes) are recorded as navigation metadata rather than scope definitions, since they do not align across source types.

A project has its own ID namespace for all project-scoped objects. Sources accumulate within a project over time as new source types are added to the same community research.

```json
{
  "project_id": "straness_area",
  "title": "Straness and Surrounding Townlands",
  "county": "Donegal",
  "barony": "Raphoe",
  "townlands": ["Straness", "Aghlem", "Meenadreen", "Tawnagh"],
  "census_deds": ["Clogher", "Tullynaught"],
  "civil_districts": ["Raphoe"],
  "rc_parishes": ["Aughnish"],
  "coi_parishes": ["Raymoghy"],
  "created": "2026-05",
  "notes": null
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| project_id | string | YES | Unique identifier — slug format, no spaces |
| title | string | YES | Human-readable project title |
| county | string | YES | County of primary research geography |
| barony | string | NO | Barony of primary research geography |
| townlands | array | YES | Canonical scope — list of townland names |
| census_deds | array | NO | DEDs covering these townlands — navigation aid for census sources |
| civil_districts | array | NO | Registrar's Districts covering these townlands — navigation aid for civil registration |
| rc_parishes | array | NO | Catholic parishes covering these townlands |
| coi_parishes | array | NO | Church of Ireland parishes covering these townlands |
| created | string | NO | Creation date in YYYY-MM format |
| notes | string | NO | Free text notes |

---

### 3.5 Record

A Record represents a specific entry within a Source. It is a faithful digital representation of what the archive contains. **The Record layer contains no interpretation whatsoever.** It does not reference Person objects. It does not assert meaning about the names or roles it contains.

The `verbatim` field is sacrosanct — it must contain the entry exactly as found in the source, including original spelling.

The `data` field contains structured key-value pairs whose keys are defined by the `record_type`. Their semantics are defined at a higher level, not by the Record itself.

```json
{
  "record_id": 1,
  "source_id": 1,
  "record_type": "valuation_entry",
  "date": "1857",
  "date_qualifier": "exact",
  "place_as_recorded": "Straness",
  "record_url": "https://www.askaboutireland.ie/...",
  "image_path": null,
  "verbatim": "John Mulligan, Straness, house and land...",
  "data": {
    "occupier": "John Mulligan",
    "lessor": "Earl of Leitrim",
    "land_value": "10s 6d"
  },
  "notes": null
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| record_id | integer | YES | Primary key — project-scoped |
| source_id | integer | YES | Foreign key to Source — resolved against global sources |
| record_type | string | YES | Record type — see controlled vocabulary |
| date | string | NO | ISO 8601 date or partial date (e.g. "1857", "1901-04-01") |
| date_qualifier | string | NO | Date qualifier — see controlled vocabulary |
| place_as_recorded | string | NO | Verbatim place name as it appears in the record |
| record_url | string | NO | Permalink to the specific record |
| image_path | string | NO | Path to local image of the source (e.g. microfilm photo) |
| verbatim | string | YES | Verbatim transcription of the record entry |
| data | object | NO | Structured key-value pairs specific to record_type |
| notes | string | NO | Free text notes on the transcription |

---

### 3.6 NamedIndividual

A NamedIndividual represents a person as they appear in a single Record — the Record's own picture of a human being, extracted faithfully without interpretation. It is a pure evidence object and makes no linkage assertion to a concluded Person.

NamedIndividual is the object on which Python record linkage algorithms (Fellegi-Sunter, Jaro-Winkler) operate. The linkage assertion — which Person this NamedIndividual represents — lives exclusively on the Person object via `named_individual_ids`.

```json
{
  "named_individual_id": 201,
  "record_id": 1,
  "label": "John Mulligan (Griffiths 1857 Straness)",
  "name_as_recorded": "John Mulligan",
  "gender_as_recorded": "M",
  "age_as_recorded": null,
  "year_of_birth_as_recorded": null,
  "place_as_recorded": "Straness",
  "role_as_recorded": "occupier",
  "notes": null
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| named_individual_id | integer | YES | Primary key — project-scoped |
| record_id | integer | YES | Foreign key to Record |
| label | string | YES | Researcher convenience label (auto-generatable from name + record) |
| name_as_recorded | string | YES | Verbatim name exactly as it appears in the record |
| gender_as_recorded | string | NO | Gender as the record states it — not normalised |
| age_as_recorded | integer | NO | Raw age figure as recorded |
| year_of_birth_as_recorded | integer | NO | Year of birth if stated directly rather than as age |
| place_as_recorded | string | NO | Verbatim place name as it appears in the record |
| role_as_recorded | string | NO | Role in the record verbatim (head, occupier, witness etc.) |
| notes | string | NO | Transcription observations or linkage candidates |

---

### 3.7 Person

A Person is a concluded identity — a real-world individual as asserted by the researcher. A Person is constituted by their Facts. The `label` field is a researcher convenience only and carries no evidential weight.

The linkage assertion connecting NamedIndividuals to this Person lives in `named_individual_ids`. This is a conclusion — the same NamedIndividual could be linked to a different Person if the researcher revises their judgement.

Names are stored as a typed array following the GEDCOMx Name model, accommodating Irish language forms, anglicised variants, and maiden names.

```json
{
  "person_id": 42,
  "label": "John Mulligan of Straness (working)",
  "gender": "male",
  "private": false,
  "names": [
    {"value": "John Mulligan", "type": "http://gedcomx.org/BirthName"},
    {"value": "Seán Ó Maolagáin", "type": "http://gedcomx.org/AlsoKnownAs"}
  ],
  "named_individual_ids": [201, 202, 203],
  "fact_ids": [101, 102, 103],
  "relationship_ids": [1, 3],
  "notes": null
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| person_id | integer | YES | Primary key — project-scoped |
| label | string | YES | Working identifier for researcher use only |
| gender | string | NO | Gender — see controlled vocabulary |
| private | boolean | NO | Whether person is flagged for limited display (default false) |
| names | array | NO | Typed name array — see controlled vocabulary for name types |
| named_individual_ids | array | NO | Linkage assertion — NamedIndividuals concluded to be this Person |
| fact_ids | array | NO | Bidirectional references to Facts for this Person |
| relationship_ids | array | NO | Bidirectional references to Relationships involving this Person |
| notes | string | NO | Free text notes |

---

### 3.8 Relationship

A Relationship is a concluded assertion about an association between two Persons. It is a conclusion and carries a confidence level. Directionality is implied by relationship_type — for `ParentChild`, person_id_1 is always the parent and person_id_2 is always the child. For `Couple`, the two persons are interchangeable.

```json
{
  "relationship_id": 1,
  "relationship_type": "http://gedcomx.org/Couple",
  "person_id_1": 42,
  "person_id_2": 67,
  "fact_ids": [105],
  "record_ids": [1, 2],
  "confidence": "http://gedcomx.org/High",
  "notes": null
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| relationship_id | integer | YES | Primary key — project-scoped |
| relationship_type | string | YES | GEDCOMx relationship type URI |
| person_id_1 | integer | YES | Foreign key to Person (role defined by relationship_type) |
| person_id_2 | integer | YES | Foreign key to Person (role defined by relationship_type) |
| fact_ids | array | NO | Facts about the relationship itself (e.g. divorce) |
| record_ids | array | NO | Records directly evidencing this relationship |
| confidence | string | NO | GEDCOMx confidence URI |
| notes | string | NO | Reasoning behind the relationship conclusion |

---

### 3.9 Fact

A Fact is a concluded assertion about a single Person or a single Relationship. It is the core conclusion unit of the model. A Fact points to one or more Records as its evidence. The reasoning connecting evidence to conclusion lives in the `notes` field.

Exactly one of `person_id` or `relationship_id` must be populated — never both, never neither.

```json
{
  "fact_id": 101,
  "person_id": 42,
  "relationship_id": null,
  "event_id": 1,
  "fact_type": "http://gedcomx.org/Marriage",
  "date": "1890-01-10",
  "date_qualifier": "exact",
  "place_id": 12,
  "record_ids": [1, 2],
  "confidence": "http://gedcomx.org/High",
  "notes": "Corroborated by both civil registration and church register"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| fact_id | integer | YES | Primary key — project-scoped |
| person_id | integer | CONDITIONAL | Foreign key to Person — required if relationship_id is null |
| relationship_id | integer | CONDITIONAL | Foreign key to Relationship — required if person_id is null |
| event_id | integer | NO | Foreign key to Event (if this Fact is part of a discrete event) |
| fact_type | string | YES | GEDCOMx fact type URI |
| date | string | NO | ISO 8601 date or partial date |
| date_qualifier | string | NO | Date qualifier — see controlled vocabulary |
| place_id | integer | NO | Foreign key to Place — resolved against global places |
| record_ids | array | YES | One or more Records evidencing this Fact |
| confidence | string | NO | GEDCOMx confidence URI |
| notes | string | NO | Reasoning connecting evidence to conclusion |

---

### 3.10 Event

An Event is a grouping mechanism for Facts and Relationships associated with a discrete real-world occurrence. It resolves the problem of constructing person cards from independent Facts by providing an explicit event container.

EventRoles reference NamedIndividuals — not concluded Persons — because participation in an event is an evidence-layer observation. The linkage from NamedIndividual to Person remains a separate conclusion on the Person object.

```json
{
  "event_id": 1,
  "event_type": "http://gedcomx.org/Marriage",
  "date": "1890-01-10",
  "date_qualifier": "exact",
  "place_id": 12,
  "record_ids": [1, 2],
  "fact_ids": [101, 102],
  "relationship_ids": [1],
  "roles": [
    {"named_individual_id": 201, "role": "http://gedcomx.org/Principal"},
    {"named_individual_id": 202, "role": "http://gedcomx.org/Principal"},
    {"named_individual_id": 203, "role": "http://gedcomx.org/Witness"}
  ],
  "notes": null
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| event_id | integer | YES | Primary key — project-scoped |
| event_type | string | YES | GEDCOMx event type URI |
| date | string | NO | ISO 8601 date or partial date (reconciled across records) |
| date_qualifier | string | NO | Date qualifier — see controlled vocabulary |
| place_id | integer | NO | Foreign key to Place — resolved against global places |
| record_ids | array | NO | Records evidencing this event |
| fact_ids | array | NO | Facts grouped under this event |
| relationship_ids | array | NO | Relationships grouped under this event |
| roles | array | NO | EventRole objects — NamedIndividuals and their roles |
| notes | string | NO | Free text notes |

**EventRole object:**

| Field | Type | Required | Description |
|---|---|---|---|
| named_individual_id | integer | YES | Foreign key to NamedIndividual |
| role | string | YES | GEDCOMx role type URI |

---

## 4. Controlled Vocabularies

### 4.1 Source Types

| Value | Description |
|---|---|
| `valuation` | Griffith's Valuation or similar land valuation |
| `tithe` | Tithe Applotment Books |
| `census` | Census return |
| `birth_registration` | Civil birth registration |
| `death_registration` | Civil death registration |
| `marriage_registration` | Civil marriage registration |
| `parish_register` | Church parish register (baptism, marriage, burial) |
| `military` | Military records — witness statements, pension files |
| `folklore` | Folklore or schools collection |
| `manuscript` | NLI or other manuscript collection |
| `gravestone` | Gravestone inscription |
| `directory` | Trade or street directory |

### 4.2 Record Types

| Value | Description | Typical data fields |
|---|---|---|
| `valuation_entry` | Griffith's Valuation entry | occupier, lessor, immediate_lessor, land_value, building_value |
| `tithe_entry` | Tithe Applotment entry | occupier, land_value, tithe_amount |
| `census_return` | Census household return | head, relationship, age, sex, occupation, birthplace, religion, literacy |
| `birth_registration` | Civil birth registration | child, father, mother, informant, occupation_father |
| `death_registration` | Civil death registration | deceased, age, cause, informant, occupation |
| `marriage_registration` | Civil marriage registration | groom, bride, father_groom, father_bride, witness_1, witness_2 |
| `baptism_entry` | Parish baptism register | child, father, mother, godfather, godmother, celebrant |
| `marriage_entry` | Parish marriage register | groom, bride, witness_1, witness_2, celebrant |
| `burial_entry` | Parish burial register | deceased, age, celebrant |
| `witness_statement` | Bureau of Military History witness statement | witness, subject, period, places |
| `pension_application` | Military Service Pension application | applicant, service_period, unit, family_details |
| `schools_collection` | Duchas Schools Collection entry | school, collector, topic, persons_named |
| `manuscript_entry` | NLI or other manuscript | free-form data fields |

### 4.3 Date Qualifiers

| Value | Description |
|---|---|
| `exact` | Date is precisely known |
| `about` | Approximate date (ABT in GEDCOM) |
| `before` | Known to be before this date |
| `after` | Known to be after this date |
| `between` | Between two dates — use notes to specify range |
| `estimated` | Estimated from other evidence |
| `calculated` | Calculated from other known facts |

### 4.4 Gender Values

| Value | Description |
|---|---|
| `male` | Male |
| `female` | Female |
| `unknown` | Gender not determinable from evidence |

### 4.5 Confidence Levels (GEDCOMx URIs)

| URI | Description |
|---|---|
| `http://gedcomx.org/High` | Strong convergent evidence, high certainty |
| `http://gedcomx.org/Medium` | Some evidence, reasonable but not certain |
| `http://gedcomx.org/Low` | Weak or single-source evidence, speculative |

### 4.6 Relationship Types (GEDCOMx URIs)

| URI | Description | Directionality |
|---|---|---|
| `http://gedcomx.org/Couple` | Married or partnered pair | Symmetric |
| `http://gedcomx.org/ParentChild` | Parent to child | person_id_1 = parent, person_id_2 = child |

### 4.7 Name Types (GEDCOMx URIs)

| URI | Description |
|---|---|
| `http://gedcomx.org/BirthName` | Name given at birth |
| `http://gedcomx.org/MarriedName` | Name adopted on marriage |
| `http://gedcomx.org/AlsoKnownAs` | Alternative name or Irish language form |
| `http://gedcomx.org/Nickname` | Informal name |

### 4.8 Fact Types (GEDCOMx URIs)

| URI | Description |
|---|---|
| `http://gedcomx.org/Birth` | Birth event |
| `http://gedcomx.org/Death` | Death event |
| `http://gedcomx.org/Baptism` | Baptism |
| `http://gedcomx.org/Burial` | Burial |
| `http://gedcomx.org/Marriage` | Marriage |
| `http://gedcomx.org/Residence` | Residence at a place |
| `http://gedcomx.org/Occupation` | Occupation |
| `http://gedcomx.org/Religion` | Religious affiliation |
| `http://gedcomx.org/MaritalStatus` | Marital status |
| `http://gedcomx.org/Emigration` | Emigration event |
| `http://gedcomx.org/MilitaryService` | Military service |

### 4.9 Event Types (GEDCOMx URIs)

| URI | Description |
|---|---|
| `http://gedcomx.org/Marriage` | Marriage ceremony |
| `http://gedcomx.org/Baptism` | Baptism ceremony |
| `http://gedcomx.org/Burial` | Burial |
| `http://gedcomx.org/Census` | Census enumeration |
| `http://gedcomx.org/Emigration` | Emigration |
| `http://gedcomx.org/MilitaryService` | Military service event |

### 4.10 Event Role Types (GEDCOMx URIs)

| URI | Description |
|---|---|
| `http://gedcomx.org/Principal` | Primary subject of the event |
| `http://gedcomx.org/Witness` | Witness to the event |
| `http://gedcomx.org/Officiator` | Celebrant or officiant |
| `http://gedcomx.org/Informant` | Person providing information |

---

## 5. Validation Rules

The following rules are enforced by Python on load. The validator takes a project path as its primary argument (`--project /path/to/project`). Global layer objects are resolved from the shared global directories; project-scoped objects are resolved within the specified project directory.

1. **Referential integrity — global** — `source_id` references on Record must resolve to objects in the global `/sources` directory. `place_id` references on Fact and Event must resolve to objects in the global `/places` directory. `repository_id` references on Source must resolve to objects in the global `/repositories` directory.
2. **Referential integrity — project** — every project-scoped foreign key (`record_id`, `named_individual_id`, `person_id`, `event_id`, `relationship_id`, `fact_id`) must resolve to an existing object within the same project.
3. **Fact subject constraint** — exactly one of `person_id` or `relationship_id` must be non-null on every Fact.
4. **Bidirectional consistency — Facts** — if Person 42 lists fact_id 101, then Fact 101 must reference person_id 42. Python flags mismatches.
5. **Bidirectional consistency — NamedIndividuals** — if Person 42 lists named_individual_id 201, no other Person within the same project may also claim named_individual_id 201. Python flags conflicts.
6. **Verbatim required** — every Record must have a non-empty `verbatim` field.
7. **Name required on NamedIndividual** — every NamedIndividual must have a non-empty `name_as_recorded` field.
8. **Record ids on Fact** — every Fact must have at least one entry in `record_ids`.
9. **EventRole references NamedIndividual** — every role entry on Event must reference a valid `named_individual_id`, not a `person_id`.
10. **Controlled vocabulary** — `record_type`, `date_qualifier`, `gender`, `confidence`, `relationship_type`, `fact_type`, `event_type`, and `role` values must be drawn from the defined vocabularies.
11. **Date format** — date fields must be valid ISO 8601 strings or partial dates in the form `YYYY`, `YYYY-MM`, or `YYYY-MM-DD`.
12. **Project townlands** — every `place_as_recorded` on a NamedIndividual should resolve to a townland listed in the project manifest. Python warns (does not error) on mismatches to accommodate variant spellings.

---

## 6. File Structure

```
/irish_genealogy/
  /repositories/              — global, shared across all projects
    repositories.json

  /sources/                   — global, shared across all projects
    source_001_griffiths.json
    source_002_tithe.json
    source_003_census_1901.json
    source_004_census_1911.json
    source_005_census_1926.json
    source_006_irishgenealogy.json
    source_007_nli_rc_registers.json
    source_008_bmh_statements.json
    source_009_mspc.json
    source_010_duchas_schools.json

  /places/                    — global, shared across all projects
    places.json

  /projects/
    /straness_area/           — example project
      project.json
      /records
        records_griffiths.json
        records_census_1901.json
        records_census_1911.json
        records_census_1926.json
      /named_individuals
        named_individuals_griffiths.json
        named_individuals_census_1901.json
      /persons
        persons.json
      /relationships
        relationships.json
      /facts
        facts.json
      /events
        events.json

    /other_project/
      project.json
      ...

  project_template.json       — scaffold for new projects
  schema_v1.3.md
```

---

## 7. Bootstrap Source Registry

The following ten sources and seven repositories are pre-populated in the global layer. They cover the primary online Irish genealogical sources and are available to all projects without any setup.

### Repositories

| repository_id | Name | URL |
|---|---|---|
| 1 | National Archives of Ireland | nationalarchives.ie |
| 2 | National Library of Ireland | nli.ie |
| 3 | Askaboutireland.ie | askaboutireland.ie |
| 4 | irishgenealogy.ie | irishgenealogy.ie |
| 5 | Central Statistics Office | cso.ie |
| 6 | Military Archives | militaryarchives.ie |
| 7 | Duchas.ie | duchas.ie |

### Sources

| source_id | Title | repository_id | Type |
|---|---|---|---|
| 1 | Griffith's Valuation | 3 | valuation |
| 2 | Tithe Applotment Books | 1 | tithe |
| 3 | Census 1901 | 1 | census |
| 4 | Census 1911 | 1 | census |
| 5 | Census 1926 | 5 | census |
| 6 | Irish Genealogy | 4 | birth_registration / marriage_registration / death_registration / parish_register |
| 7 | Catholic Parish Registers | 2 | parish_register |
| 8 | Bureau of Military History Witness Statements | 6 | military |
| 9 | Military Service Pensions Collection | 6 | military |
| 10 | Duchas Schools Collection | 7 | folklore |

---

## 8. Session Bootstrap Guidance

### Transcription Session
Bring into context:
- This schema document (sections 3.5 Record, 3.6 NamedIndividual, sections 4.1–4.2 vocabularies)
- Source citation for the images being transcribed
- Current max IDs for `record_id` and `named_individual_id` within the active project
- Output format: JSON array of Record objects each with nested NamedIndividual objects

Claude produces verbatim transcriptions only. No interpretation. No Person references.

### Linkage Session
Bring into context:
- This schema document (sections 3.6 NamedIndividual, 3.7 Person, section 5 validation rules)
- Candidate NamedIndividual clusters from Python record linkage scoring
- Existing Person objects under consideration

Claude reasons about whether candidate NamedIndividuals represent the same concluded Person. Python ingests approved linkage assertions into Person.named_individual_ids.

### Reasoning Session
Bring into context:
- This schema document (full)
- Relevant existing Persons, Facts, Events, and Records under consideration
- The specific research question or record cluster being analysed

Claude reasons about linkage, conflicts, and conclusions. Python ingests any new Facts, Relationships, or Events produced.

### Data Processing Session
Bring into context:
- This schema document (sections 3, 4, 5)
- Current project file structure state
- Specific processing task (linkage scoring, deduplication, validation)

---

*Schema version 1.3.1 — produced May 2026*
*Based on GEDCOMx Conceptual Model — http://gedcomx.org/conceptual-model/v1*

---

## Changelog

| Version | Date | Change |
|---|---|---|
| 1.0 | May 2026 | Initial schema — seven first class objects |
| 1.1 | May 2026 | Added `citation` field to Source |
| 1.2 | May 2026 | Added NamedIndividual as eighth first class object; updated Person with `named_individual_ids`; updated EventRoles to reference NamedIndividuals not Persons; added data model section with flow diagram and ER diagram; added Linkage Session to bootstrap guidance; updated validation rules |
| 1.3 | May 2026 | Added Repository as ninth first-class object; added Project as tenth first-class object; introduced two-tier architecture (global layer: Repository, Source, Place; project layer: all other objects); Source loses repository string fields, gains repository_id foreign key; ID namespace formally defined (global vs project-scoped); project scope anchored to townland set not DED; administrative boundaries (DED, civil district, parish) demoted to navigation metadata on Project; bootstrap source registry (10 sources, 7 repositories) added to schema; tithe and military source and record types added to controlled vocabularies; file structure updated for two-tier layout; validation rules updated for global/project resolution; MilitaryService added to Fact and Event type vocabularies |
| 1.3.1 | May 2026 | place_id removed from Record — place normalisation is a conclusion and belongs exclusively on Fact and Event; place_as_recorded added to Record as verbatim evidence field; validation rule 1 updated accordingly |
