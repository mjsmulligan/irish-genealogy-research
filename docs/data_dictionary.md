# Irish Genealogy Research — Data Dictionary

*Version 2.2 — May 2026*
*Audience: Developers, data engineers, and transcription sessions. This document is the authoritative reference for every field on every object. It defines field names, types, constraints, and controlled vocabulary values with GEDCOMx alignment notes.*

---

## 1. Conventions

### Field Types

| Type | Description |
|---|---|
| `integer` | Whole number, used for primary and foreign keys |
| `string` | Variable length text |
| `boolean` | True or false |
| `date` | Partial or full date string — see Date Format below |
| `array[integer]` | Array of integer foreign keys |
| `array[string]` | Array of string values |
| `array[object]` | Array of embedded objects |
| `object` | Embedded key-value structure — stored as JSON |

### Date Format

Date fields accept ISO 8601 strings or partial dates in the following forms only:

| Format | Example | Meaning |
|---|---|---|
| `YYYY` | `1857` | Year only |
| `YYYY-MM` | `1901-04` | Year and month |
| `YYYY-MM-DD` | `1890-01-10` | Full date |

Text dates, circa prefixes, and non-ISO separators are not valid. Verbatim date strings from sources are stored on `RecordedEvent.date_as_recorded` and are not subject to this constraint.

### Required vs Optional

| Marker | Meaning |
|---|---|
| `YES` | Field must be present and non-null |
| `NO` | Field is optional |
| `CONDITIONAL` | Required only when a specified condition is met |

### Namespace Conventions

| Prefix | Namespace | Usage |
|---|---|---|
| gedcomx | `http://gedcomx.org/` | Standard GEDCOMx controlled vocabulary |
| local | `http://irishgenealogy.local/gedcomx/` | Irish-specific extensions with no GEDCOMx equivalent |

GEDCOMx URIs are reference metadata only. Stored values in the database use short codes as defined in each controlled vocabulary table below.

---

## 2. Foundational Layer

### 2.1 Repository

The physical or digital institution holding historical source material.

| Field | Type | Required | Description |
|---|---|---|---|
| repository_id | integer | YES | Primary key |
| name | string | YES | Full institutional name |
| url | string | YES | Base URL of the repository website |
| notes | string | NO | Free text notes |

---

### 2.2 Source

A specific document collection, register volume, or digital asset held by a Repository.

| Field | Type | Required | Description |
|---|---|---|---|
| source_id | integer | YES | Primary key |
| repository_id | integer | YES | Foreign key to Repository |
| title | string | YES | Name of the source |
| type | string | YES | Source type — see §6.1 |
| coverage_from | integer | NO | Start year of source coverage |
| coverage_to | integer | NO | End year of source coverage |
| source_url | string | NO | URL of the source collection landing page |
| record_url_template | string | NO | URL template for constructing deep links to individual Records. Placeholders use `{parameter_name}` syntax. At runtime, placeholders are filled by merging `source_parameters` (Source-level constants) with `record_parameters` (Record-level values). Null for sources that do not support direct linking. |
| source_parameters | object | NO | Source-level identifier constants required to fill placeholders in `record_url_template`. Keys are placeholder names; values are the fixed string or integer values that are the same for every Record in this Source (e.g. `{"vtls_id": 634016}` for an NLI microfilm, or `{"release_id": "A"}` for a pension collection release). Null when all template placeholders are Record-level. |
| record_parameter_names | array[string] | NO | Ordered list of placeholder names in `record_url_template` that must be supplied per Record via `Record.record_parameters`. Null when the source does not support direct linking. Complement of `source_parameters` — together they account for every placeholder in the template. |
| column_schema | array[string] | NO | Ordered list of CSV column names for parsing `raw_text`. Null for narrative sources using a transcription workflow. |
| citation | string | NO | Formatted bibliographic citation (Elizabeth Shown Mills style) |
| notes | string | NO | Free text notes |

**Deep link construction** — the Python layer constructs a deep link for any Record by: (1) retrieving the parent Source's `record_url_template`, `source_parameters`, and `record_parameter_names`; (2) retrieving the Record's `record_parameters`; (3) merging both parameter sets; (4) substituting each `{placeholder}` in the template with its resolved value. An error is raised if any placeholder remains unresolved after the merge.

---

## 3. Evidence Layer

### 3.1 Record

The core administrative boundary for data extraction. One entry in a source — one row of a register, one census household, one valuation line.

| Field | Type | Required | Description |
|---|---|---|---|
| record_id | integer | YES | Primary key |
| source_id | integer | YES | Foreign key to Source |
| record_parameters | object | NO | Record-level identifier values required to fill the Record-specific placeholders in the parent Source's `record_url_template`. Keys must match the names listed in `Source.record_parameter_names`. For example: `{"image_number": 42}` for an NLI parish register page, or `{"folder_id": "births_1890_001", "image_id": "0042"}` for a civil registration. Null for sources that do not support direct linking or where all parameters are Source-level. |
| raw_text | string | YES | Verbatim ingest string exactly as received — typically a CSV row for structured sources, a transcribed passage for narrative sources. Sacrosanct — never modified after ingest. |
| notes | string | NO | Free text notes on the ingest or transcription |

---

### 3.2 RecordedEvent

An occurrence exactly as described within a parent Record. Captures verbatim date, place, and type without normalisation. Contains no foreign keys to conclusion-layer objects.

| Field | Type | Required | Description |
|---|---|---|---|
| recorded_event_id | integer | YES | Primary key |
| record_id | integer | YES | Foreign key to Record. Exactly one RecordedEvent per Record. |
| type | string | YES | Event type as recorded — see §6.2 |
| date_as_recorded | string | NO | Verbatim date string exactly as it appears in the source (e.g. "10th Jany 1890", "Jan 1890") |
| date | date | NO | Normalised ISO 8601 date or partial date derived from date_as_recorded |
| date_qualifier | string | NO | Date qualifier — see §6.3 |
| place_as_recorded | string | NO | Verbatim place name exactly as it appears in the source |
| notes | string | NO | Free text notes |

---

### 3.3 RecordedPerson

An individual documented within a parent Record, captured verbatim without interpretation. Contains no foreign keys to conclusion-layer objects.

| Field | Type | Required | Description |
|---|---|---|---|
| recorded_person_id | integer | YES | Primary key |
| record_id | integer | YES | Foreign key to Record |
| name_as_recorded | string | YES | Verbatim name exactly as it appears in the source, including original spelling |
| role | string | YES | Role in the record — see §6.4 |
| age_as_recorded | string | NO | Verbatim age exactly as recorded (e.g. "28", "about 30", "inf") |
| age | integer | NO | Normalised integer age derived from age_as_recorded |
| sex_as_recorded | string | NO | Sex or gender exactly as recorded |
| occupation_as_recorded | string | NO | Occupation exactly as recorded |
| place_as_recorded | string | NO | Place of origin or residence exactly as recorded |
| notes | string | NO | Transcription observations |

---

## 4. Conclusion Layer

### 4.1 Person

A concluded identity representing a real-world individual as asserted by the researcher.

| Field | Type | Required | Description |
|---|---|---|---|
| person_id | integer | YES | Primary key |
| label | string | YES | Researcher convenience label — carries no evidential weight |
| gender | string | NO | Concluded gender — see §6.5 |
| names | array[object] | NO | Typed name array — see Name Object below |
| record_ids | array[integer] | NO | Foreign keys to Records concluded to be about this Person. This is the primary linkage assertion. |
| event_ids | array[integer] | NO | Foreign keys to Events this Person participated in |
| relationship_ids | array[integer] | NO | Foreign keys to Relationships involving this Person |
| private | boolean | NO | Whether Person is flagged for limited display. Default false. |
| notes | string | NO | Free text notes |

**Name Object**

| Field | Type | Required | Description |
|---|---|---|---|
| value | string | YES | The name string |
| type | string | YES | Name type — see §6.6 |

---

### 4.2 Relationship

A concluded assertion about a connection between two specific Persons. Independent of any single Event — accumulates evidence from multiple Records over time.

| Field | Type | Required | Description |
|---|---|---|---|
| relationship_id | integer | YES | Primary key |
| type | string | YES | Relationship type — see §6.7 |
| person_id_1 | integer | YES | Foreign key to Person. For ParentChild: the parent. For Couple: either person. |
| person_id_2 | integer | YES | Foreign key to Person. For ParentChild: the child. For Couple: either person. |
| record_ids | array[integer] | NO | Foreign keys to Records evidencing this Relationship. Confidence grows as independent Records converge. |
| event_ids | array[integer] | NO | Foreign keys to Events associated with this Relationship |
| confidence | string | NO | Confidence level — see §6.8 |
| notes | string | NO | Researcher reasoning supporting this Relationship conclusion |

---

### 4.3 Event

A concluded assertion about a discrete real-world occurrence, synthesised from one or more Records.

| Field | Type | Required | Description |
|---|---|---|---|
| event_id | integer | YES | Primary key |
| type | string | YES | Event type — see §6.2 |
| date | date | NO | Concluded ISO 8601 date or partial date, reconciled across Records |
| date_qualifier | string | NO | Date qualifier — see §6.3 |
| place_id | integer | NO | Foreign key to Place — concluded place for this Event |
| person_ids | array[integer] | NO | Foreign keys to Persons who participated in this Event |
| relationship_id | integer | NO | Foreign key to Relationship — identifies the principal connection within the Event (e.g. the Couple in a marriage Event) |
| record_ids | array[integer] | NO | Foreign keys to Records evidencing this Event. Confidence grows as independent Records converge. |
| recorded_event_ids | array[integer] | NO | Foreign keys to RecordedEvents that this Event is concluded from |
| confidence | string | NO | Confidence level — see §6.8 |
| notes | string | NO | Researcher reasoning supporting this Event conclusion |

---

### 4.4 Place

A concluded assertion that one or more verbatim place strings found in Records refer to the same real-world geographical location. Place is a researcher conclusion — the normalisation of variant spellings, transcription errors, and historical name forms is an interpretive judgment, not an objective fact.

| Field | Type | Required | Description |
|---|---|---|---|
| place_id | integer | YES | Primary key |
| name | string | YES | Researcher's working name for this place |
| record_ids | array[integer] | NO | Foreign keys to Records containing place strings concluded to refer to this Place |
| townland_ie_url | string | NO | Permalink to townlands.ie entry — reference authority, not conclusion authority |
| logainm_id | integer | NO | Logainm.ie numeric identifier |
| logainm_url | string | NO | Permalink to logainm.ie entry — reference authority, not conclusion authority |
| notes | string | NO | Researcher reasoning — e.g. explanation of variant spellings linked to this Place |

Place hierarchy (townland → civil parish → barony → county), Irish language name, historical name variants, and geographic coordinates are retrievable from the external sources via the linked URLs.

---

## 5. Cross-Layer Linkage Summary

The following table summarises all linkage assertions connecting the conclusion layer to the evidence layer. All linkages are researcher conclusions and remain mutable. Evidence-layer objects contain no foreign keys to conclusion-layer objects.

| Conclusion object | Evidence linkage | Description |
|---|---|---|
| Person.record_ids | → Record | Records concluded to be about this Person |
| Event.record_ids | → Record | Records concluded to document this Event |
| Event.recorded_event_ids | → RecordedEvent | RecordedEvents this Event is synthesised from |
| Relationship.record_ids | → Record | Records evidencing this Relationship |
| Place.record_ids | → Record | Records containing place strings concluded to refer to this Place |

RecordedPerson and RecordedEvent are not direct linkage targets for conclusion-layer objects. They are the structured attributes the reconstruction algorithm reads when scoring record-to-person, record-to-event, and record-to-place linkage candidates.

---

## 6. Controlled Vocabularies

### 6.1 Source Types

| Code | GEDCOMx URI | Description |
|---|---|---|
| `valuation` | local:Valuation | Land valuation survey |
| `tithe` | local:Tithe | Tithe applotment record |
| `census` | local:Census | Census household return |
| `birth_registration` | local:BirthRegistration | Civil birth registration |
| `marriage_registration` | local:MarriageRegistration | Civil marriage registration |
| `death_registration` | local:DeathRegistration | Civil death registration |
| `parish_register` | local:ParishRegister | Church parish register (baptism, marriage, burial) |
| `military` | local:Military | Military history or pension record |
| `folklore` | local:Folklore | Folklore or oral history collection |

### 6.2 Event Types

Applies to both RecordedEvent.type and Event.type.

| Code | GEDCOMx URI | Description |
|---|---|---|
| `birth` | gedcomx:Birth | Birth |
| `baptism` | gedcomx:Baptism | Baptism ceremony |
| `marriage` | gedcomx:Marriage | Marriage ceremony |
| `death` | gedcomx:Death | Death |
| `burial` | gedcomx:Burial | Burial |
| `census` | gedcomx:Census | Census enumeration |
| `residence` | gedcomx:Residence | Recorded residence at a place |
| `emigration` | gedcomx:Emigration | Emigration |
| `valuation` | local:Valuation | Land valuation entry |
| `tithe` | local:Tithe | Tithe applotment entry |
| `military_service` | local:MilitaryService | Military service record |
| `pension` | local:Pension | Pension application or record |
| `folklore` | local:Folklore | Folklore collection entry |

### 6.3 Date Qualifiers

| Code | GEDCOMx analog | Description |
|---|---|---|
| `exact` | — | Date is precisely known |
| `about` | ABT | Approximate date |
| `before` | BEF | Known to be before this date |
| `after` | AFT | Known to be after this date |
| `between` | BET | Between two dates — specify range in notes |
| `estimated` | EST | Estimated from other evidence |
| `calculated` | CAL | Calculated from other known facts |

### 6.4 RecordedPerson Roles

Roles are verbatim-adjacent — they normalise the raw role text from the source into a controlled value while remaining faithful to the source's meaning.

| Code | GEDCOMx URI | Description |
|---|---|---|
| `principal` | gedcomx:Principal | Primary subject of the record (general) |
| `head` | local:Head | Head of household |
| `spouse` | local:Spouse | Spouse of head (census) |
| `child` | local:Child | Child in household or baptism record |
| `groom` | local:Groom | Groom in marriage record |
| `bride` | local:Bride | Bride in marriage record |
| `father` | local:Father | Father named in record |
| `mother` | local:Mother | Mother named in record |
| `father_of_groom` | local:FatherOfGroom | Father of groom in marriage record |
| `father_of_bride` | local:FatherOfBride | Father of bride in marriage record |
| `godfather` | local:Godfather | Godfather in baptism record |
| `godmother` | local:Godmother | Godmother in baptism record |
| `witness` | gedcomx:Witness | Witness to an event |
| `informant` | gedcomx:Informant | Person providing information to registrar |
| `officiator` | gedcomx:Officiator | Celebrant or officiant |
| `occupier` | local:Occupier | Land occupier in valuation or tithe record |
| `lessor` | local:Lessor | Lessor in valuation record |
| `deceased` | local:Deceased | Deceased person in death or burial record |

### 6.5 Gender Values

| Code | GEDCOMx analog | Description |
|---|---|---|
| `male` | Male | Male |
| `female` | Female | Female |
| `unknown` | Unknown | Gender not determinable from evidence |

### 6.6 Name Types

| Code | GEDCOMx URI | Description |
|---|---|---|
| `birth_name` | gedcomx:BirthName | Name given at birth |
| `married_name` | gedcomx:MarriedName | Name adopted on marriage |
| `also_known_as` | gedcomx:AlsoKnownAs | Alternative name or Irish language form |
| `nickname` | gedcomx:Nickname | Informal name |

### 6.7 Relationship Types

| Code | GEDCOMx URI | Directionality | Description |
|---|---|---|---|
| `couple` | gedcomx:Couple | Symmetric | Married or partnered pair |
| `parent_child` | gedcomx:ParentChild | person_id_1 = parent, person_id_2 = child | Parent to child |
| `sibling` | local:Sibling | Symmetric | Sibling pair — reserved for future use |

### 6.8 Confidence Levels

Confidence is a qualitative assessment of the convergent evidence supporting a conclusion. The mechanics of confidence scoring are defined in the reconstruction algorithms document.

| Code | GEDCOMx URI | Description |
|---|---|---|
| `high` | gedcomx:High | Strong convergent evidence across multiple independent Records |
| `medium` | gedcomx:Medium | Some evidence — reasonable but not yet corroborated |
| `low` | gedcomx:Low | Weak or single-source evidence — provisional |

---

*This document should be brought into context for database implementation, ingestion engineering, and transcription sessions. Controlled vocabulary tables are the authoritative reference for all coded field values.*

*Related documents: conceptual_model.md, repositories.md, database_schema.md, validation_rules.md*

---

## Changelog

| Version | Date | Change |
|---|---|---|
| 2.1 | May 2026 | Initial v2.1 data dictionary |
| 2.2 | May 2026 | Replaced `Source.record_url_template` single-parameter model with a two-level parameter system. Added `Source.source_parameters` (Source-level URL constants), `Source.record_parameter_names` (names of Record-level placeholders), and `Record.record_parameters` (per-Record placeholder values). Removed `Record.source_identifier`. Added deep link construction note to §2.2. |
