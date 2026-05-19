# Irish Genealogy Research Schema v1.2

## 1. Preamble

### Design Principles

This schema defines a lightweight genealogical data model for personal Irish genealogy research. It is inspired by the GEDCOMx conceptual model but deliberately simplified for a two-collaborator environment (Python + Claude).

**Core principles:**

- **Evidence/conclusion separation** — the Record layer contains only verbatim transcriptions. No interpretation occurs at the Record level. Conclusions are expressed exclusively through Facts, Relationships, and Events.
- **GEDCOMx lite** — the schema adopts GEDCOMx conceptual architecture and URI vocabulary without implementing the full specification. When in doubt about a design decision, consult GEDCOMx.
- **File-based** — data is stored as JSON files. No database server required. Portable and human-readable.
- **Relational by reference** — objects link to each other via integer IDs. Python enforces referential integrity on load.
- **External place authority** — Place objects link to townlands.ie and logainm.ie rather than maintaining an internal place hierarchy. Irish placename complexity is delegated to authoritative external sources.
- **Lightweight** — first class objects are kept to a minimum. Attribution, formal argument objects, and multi-researcher machinery are deliberately excluded. These simplifications are deliberate choices, not oversights.

### The Two-Collaborator Model

**Python handles:**
- Schema validation and referential integrity
- File I/O and batch ingestion
- Record linkage scoring (Fellegi-Sunter, Jaro-Winkler)
- Deterministic data manipulation and deduplication

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

---

## 2. Data Model

### 2.1 Object Summary

The schema has eight first class objects organised into two layers:

**Evidence layer** — faithful representation of what archives contain. No interpretation.
- Source
- Record
- Place
- NamedIndividual

**Conclusion layer** — researcher assertions supported by evidence. Subject to revision.
- Person
- Relationship
- Fact
- Event

### 2.2 Data Flow

```
Source
  └── Record
        └── NamedIndividual
                └── Event (via roles)
                      ├── Fact ──────► Person
                      └── Relationship
```

Each arrow represents a different kind of work:

| Transition | Work performed |
|---|---|
| Source → Record | Archival work — transcription and citation |
| Record → NamedIndividual | Extraction — person-shaped data pulled from record verbatim |
| NamedIndividual → Event | Grouping — participants assembled around a real-world occurrence |
| Event → Fact | Conclusion — synthesised assertion about a person or relationship |
| Fact → Person | Identity — concluded biography constituted by facts |
| NamedIndividual → Person | Linkage assertion (via Person.named_individual_ids) |

### 2.3 Entity Relationship Diagram

```
┌─────────────┐
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
- Evidence layer objects: Source, Record, Place, NamedIndividual
- Conclusion layer objects: Person, Relationship, Fact, Event
- The linkage assertion (NamedIndividual → Person) is the boundary between layers
- Place is referenced independently by Record, Event, and Fact

---

## 3. Object Definitions

### 3.1 Source

A Source represents a top-level archival collection or register. It is the highest level of provenance.

```json
{
  "source_id": 1,
  "title": "Griffith's Valuation",
  "type": "valuation",
  "repository": "Askaboutireland.ie",
  "repository_location": "Dublin, Ireland",
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
| source_id | integer | YES | Primary key |
| title | string | YES | Name of the source |
| type | string | YES | Source type — see controlled vocabulary |
| repository | string | YES | Institution or website holding the source |
| repository_location | string | NO | Physical location of repository |
| collection | string | NO | Collection name within the repository |
| date_from | integer | NO | Start year of source coverage |
| date_to | integer | NO | End year of source coverage |
| source_url | string | NO | URL of the source collection |
| physical_location | string | NO | Physical location for non-digital sources |
| citation | string | NO | Formatted bibliographic citation (Elizabeth Shown Mills style) |
| notes | string | NO | Free text notes |

---

### 3.2 Record

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
  "place_id": 12,
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
| record_id | integer | YES | Primary key |
| source_id | integer | YES | Foreign key to Source |
| record_type | string | YES | Record type — see controlled vocabulary |
| date | string | NO | ISO 8601 date or partial date (e.g. "1857", "1901-04-01") |
| date_qualifier | string | NO | Date qualifier — see controlled vocabulary |
| place_id | integer | NO | Foreign key to Place |
| record_url | string | NO | Permalink to the specific record |
| image_path | string | NO | Path to local image of the source (e.g. microfilm photo) |
| verbatim | string | YES | Verbatim transcription of the record entry |
| data | object | NO | Structured key-value pairs specific to record_type |
| notes | string | NO | Free text notes on the transcription |

---

### 3.3 Place

A Place represents an Irish townland. Place delegates complexity to external authoritative sources rather than maintaining an internal hierarchy or name variant list.

```json
{
  "place_id": 12,
  "name": "Straness",
  "townland_ie_url": "https://www.townlands.ie/donegal/boylagh/templecrone/straness/",
  "logainm_id": 12345,
  "logainm_url": "https://www.logainm.ie/en/12345",
  "notes": null
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| place_id | integer | YES | Primary key |
| name | string | YES | Common working name of the place |
| townland_ie_url | string | NO | Permalink to townlands.ie entry |
| logainm_id | integer | NO | Logainm.ie numeric identifier |
| logainm_url | string | NO | Permalink to logainm.ie entry |
| notes | string | NO | Free text notes |

Place hierarchy (townland → civil parish → barony → county), Irish language name, historical name variants, and geographic coordinates are all retrievable from the external sources via the linked URLs.

---

### 3.4 NamedIndividual

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
| named_individual_id | integer | YES | Primary key |
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

### 3.5 Person

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
| person_id | integer | YES | Primary key |
| label | string | YES | Working identifier for researcher use only |
| gender | string | NO | Gender — see controlled vocabulary |
| private | boolean | NO | Whether person is flagged for limited display (default false) |
| names | array | NO | Typed name array — see controlled vocabulary for name types |
| named_individual_ids | array | NO | Linkage assertion — NamedIndividuals concluded to be this Person |
| fact_ids | array | NO | Bidirectional references to Facts for this Person |
| relationship_ids | array | NO | Bidirectional references to Relationships involving this Person |
| notes | string | NO | Free text notes |

---

### 3.6 Relationship

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
| relationship_id | integer | YES | Primary key |
| relationship_type | string | YES | GEDCOMx relationship type URI |
| person_id_1 | integer | YES | Foreign key to Person (role defined by relationship_type) |
| person_id_2 | integer | YES | Foreign key to Person (role defined by relationship_type) |
| fact_ids | array | NO | Facts about the relationship itself (e.g. divorce) |
| record_ids | array | NO | Records directly evidencing this relationship |
| confidence | string | NO | GEDCOMx confidence URI |
| notes | string | NO | Reasoning behind the relationship conclusion |

---

### 3.7 Fact

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
| fact_id | integer | YES | Primary key |
| person_id | integer | CONDITIONAL | Foreign key to Person — required if relationship_id is null |
| relationship_id | integer | CONDITIONAL | Foreign key to Relationship — required if person_id is null |
| event_id | integer | NO | Foreign key to Event (if this Fact is part of a discrete event) |
| fact_type | string | YES | GEDCOMx fact type URI |
| date | string | NO | ISO 8601 date or partial date |
| date_qualifier | string | NO | Date qualifier — see controlled vocabulary |
| place_id | integer | NO | Foreign key to Place |
| record_ids | array | YES | One or more Records evidencing this Fact |
| confidence | string | NO | GEDCOMx confidence URI |
| notes | string | NO | Reasoning connecting evidence to conclusion |

---

### 3.8 Event

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
| event_id | integer | YES | Primary key |
| event_type | string | YES | GEDCOMx event type URI |
| date | string | NO | ISO 8601 date or partial date (reconciled across records) |
| date_qualifier | string | NO | Date qualifier — see controlled vocabulary |
| place_id | integer | NO | Foreign key to Place |
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
| `census` | Census return |
| `birth_registration` | Civil birth registration |
| `death_registration` | Civil death registration |
| `marriage_registration` | Civil marriage registration |
| `parish_register` | Church parish register (baptism, marriage, burial) |
| `manuscript` | NLI or other manuscript collection |
| `gravestone` | Gravestone inscription |
| `directory` | Trade or street directory |

### 4.2 Record Types

| Value | Description | Typical data fields |
|---|---|---|
| `valuation_entry` | Griffith's Valuation entry | occupier, lessor, immediate_lessor, land_value, building_value |
| `census_return` | Census household return | head, relationship, age, sex, occupation, birthplace, religion, literacy |
| `birth_registration` | Civil birth registration | child, father, mother, informant, occupation_father |
| `death_registration` | Civil death registration | deceased, age, cause, informant, occupation |
| `marriage_registration` | Civil marriage registration | groom, bride, father_groom, father_bride, witness_1, witness_2 |
| `baptism_entry` | Parish baptism register | child, father, mother, godfather, godmother, celebrant |
| `marriage_entry` | Parish marriage register | groom, bride, witness_1, witness_2, celebrant |
| `burial_entry` | Parish burial register | deceased, age, celebrant |
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

### 4.9 Event Types (GEDCOMx URIs)

| URI | Description |
|---|---|
| `http://gedcomx.org/Marriage` | Marriage ceremony |
| `http://gedcomx.org/Baptism` | Baptism ceremony |
| `http://gedcomx.org/Burial` | Burial |
| `http://gedcomx.org/Census` | Census enumeration |
| `http://gedcomx.org/Emigration` | Emigration |

### 4.10 Event Role Types (GEDCOMx URIs)

| URI | Description |
|---|---|
| `http://gedcomx.org/Principal` | Primary subject of the event |
| `http://gedcomx.org/Witness` | Witness to the event |
| `http://gedcomx.org/Officiator` | Celebrant or officiant |
| `http://gedcomx.org/Informant` | Person providing information |

---

## 5. Validation Rules

The following rules are enforced by Python on load:

1. **Referential integrity** — every foreign key (source_id, record_id, named_individual_id, person_id, place_id, event_id, relationship_id, fact_id) must resolve to an existing object.
2. **Fact subject constraint** — exactly one of `person_id` or `relationship_id` must be non-null on every Fact.
3. **Bidirectional consistency — Facts** — if Person 42 lists fact_id 101, then Fact 101 must reference person_id 42. Python flags mismatches.
4. **Bidirectional consistency — NamedIndividuals** — if Person 42 lists named_individual_id 201, no other Person may also claim named_individual_id 201. Python flags conflicts.
5. **Verbatim required** — every Record must have a non-empty `verbatim` field.
6. **Name required on NamedIndividual** — every NamedIndividual must have a non-empty `name_as_recorded` field.
7. **Record ids on Fact** — every Fact must have at least one entry in `record_ids`.
8. **EventRole references NamedIndividual** — every role entry on Event must reference a valid named_individual_id, not a person_id.
9. **Controlled vocabulary** — record_type, date_qualifier, gender, confidence, relationship_type, fact_type, event_type, and role values must be drawn from the defined vocabularies.
10. **Date format** — date fields must be valid ISO 8601 strings or partial dates in the form `YYYY`, `YYYY-MM`, or `YYYY-MM-DD`.

---

## 6. File Structure

```
/data
  /sources            — one JSON file per source (source_001.json)
  /records            — one JSON file per source batch (records_griffiths_clogher.json)
  /places             — single file (places.json)
  /named_individuals  — batched by source (named_individuals_griffiths_clogher.json)
  /persons            — one JSON file per person (person_042.json)
  /relationships      — single file or batched (relationships.json)
  /facts              — batched by person or event (facts_person_042.json)
  /events             — single file or batched (events.json)
```

---

## 7. Session Bootstrap Guidance

### Transcription Session
Bring into context:
- This schema document (section 3.2 Record, section 3.4 NamedIndividual, section 4.1-4.2 vocabularies)
- Source citation for the images being transcribed
- Output format: JSON array of Record objects each with nested NamedIndividual objects

Claude produces verbatim transcriptions only. No interpretation. No Person references.

### Linkage Session
Bring into context:
- This schema document (sections 3.4 NamedIndividual, 3.5 Person, section 5 validation rules)
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
- Current file structure state
- Specific processing task (linkage scoring, deduplication, validation)

---

*Schema version 1.2 — produced May 2026*
*Based on GEDCOMx Conceptual Model — http://gedcomx.org/conceptual-model/v1*

---

## Changelog

| Version | Date | Change |
|---|---|---|
| 1.0 | May 2026 | Initial schema — seven first class objects |
| 1.1 | May 2026 | Added `citation` field to Source |
| 1.2 | May 2026 | Added NamedIndividual as eighth first class object; updated Person with `named_individual_ids`; updated EventRoles to reference NamedIndividuals not Persons; added data model section with flow diagram and ER diagram; added Linkage Session to bootstrap guidance; updated validation rules |
