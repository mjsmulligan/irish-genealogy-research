# Irish Genealogy Research — Data Dictionary

*Version 2.7 — 17 June 2026*
*Audience: Developers, data engineers, and transcription sessions. This document is the authoritative reference for every field on every object.*

______________________________________________________________________

## 1. Conventions

### Field Types

| Type | Description |
|---|---|
| `integer` | Whole number, used for primary and foreign keys |
| `string` | Variable length text |
| `boolean` | True or false |
| `real` | Floating-point number |
| `date` | Partial or full ISO 8601 date string |
| `array[integer]` | Array of integer foreign keys |
| `array[string]` | Array of string values |
| `object` | Embedded key-value structure — stored as JSON |

### Date Format

Date fields accept ISO 8601 strings or partial dates: `YYYY`, `YYYY-MM`, or `YYYY-MM-DD`.

### Required vs Optional

| Marker | Meaning |
|---|---|
| `YES` | Field must be present and non-null |
| `NO` | Field is optional |
| `CONDITIONAL` | Required only when a specified condition is met |

______________________________________________________________________

## 2. Foundational Layer

### 2.1 Repository

| Field | Type | Required | Description |
|---|---|---|---|
| repository_id | integer | YES | Primary key |
| name | string | YES | Full institutional name |
| url | string | YES | Base URL of the repository website |
| notes | string | NO | Free text notes |

______________________________________________________________________

### 2.2 Source

| Field | Type | Required | Description |
|---|---|---|---|
| source_id | integer | YES | Primary key |
| repository_id | integer | YES | Foreign key to Repository |
| title | string | YES | Name of the source |
| type | string | YES | Source type — see §6.1 |
| coverage_from | integer | NO | Start year of source coverage |
| coverage_to | integer | NO | End year of source coverage |
| source_url | string | NO | URL of the source collection landing page |
| record_url_template | string | NO | URL template with `{placeholder}` tokens |
| source_parameters | object | NO | Source-level URL parameter constants (JSON) |
| record_parameter_names | array[string] | NO | Per-Record placeholder names (JSON array) |
| column_schema | array[string] | NO | CSV column names for parsing `raw_text` (JSON array) |
| citation | string | NO | Formatted bibliographic citation |
| notes | string | NO | Free text notes |

______________________________________________________________________

### 2.3 PlaceAuthority

Authoritative place identities seeded from logainm.ie or added manually. Not researcher conclusions — these are reference facts. The hierarchy is expressed as denormalised columns (flat schema) rather than a separate junction table.

| Field | Type | Required | Description |
|---|---|---|---|
| place_id | integer | YES | Synthetic primary key |
| logainm_id | integer | NO | logainm.ie numeric identifier. Unique where present; null for manually-added entities |
| name_en | string | YES | Canonical English place name |
| place_type | string | YES | Place type — see §6.10 |
| parent_name | string | NO | Name of the immediate parent entity (e.g. the DED under which this townland was fetched) |
| parent_id | integer | NO | logainm_id of the immediate parent |
| parent_type | string | NO | place_type of the immediate parent |
| ded_name | string | NO | Name of the District Electoral Division containing this place |
| ded_id | integer | NO | logainm_id of the DED |
| county_name | string | NO | Name of the county |
| county_id | integer | NO | logainm_id of the county |
| barony_name | string | NO | Name of the barony (null where not in logainm) |
| barony_id | integer | NO | logainm_id of the barony |
| civil_parish_name | string | NO | Name of the civil parish (null where not in logainm) |
| civil_parish_id | integer | NO | logainm_id of the civil parish |
| latitude | real | NO | WGS84 latitude |
| longitude | real | NO | WGS84 longitude |
| logainm_url | string | NO | Permalink to logainm.ie entry; null for manually-added entities |
| notes | string | NO | Free text — used for manually-added entities or variant notes |

**Hierarchy note:** A townland may lack barony and civil_parish values if logainm does not record them for that townland. This is a data quality characteristic of the source, not a model deficiency. The ded_id and county_id are typically populated for all townlands.

**Church parishes:** logainm.ie does not catalogue church (Catholic) parishes. These are added manually with `logainm_id = NULL`. Membership of a church parish is recorded by adding the townland rows with the `parent_type = 'church_parish'` where applicable — or more commonly queried via a researcher-maintained lookup outside the core schema.

______________________________________________________________________

## 3. Evidence Layer

### 3.1 Record

| Field | Type | Required | Description |
|---|---|---|---|
| record_id | integer | YES | Primary key |
| source_id | integer | YES | Foreign key to Source |
| record_parameters | object | NO | Record-level URL parameter values (JSON) |
| raw_text | string | YES | Verbatim ingest string — sacrosanct, never modified |
| notes | string | NO | Free text notes on ingest |

______________________________________________________________________

### 3.2 Record event fields

Event attributes are stored directly on the `record` table rather than in a separate `recorded_event` table. Because every Record documents exactly one event, the 1:1 join was eliminated in schema v2.8.

The following fields on `record` carry the event data:

| Field | Type | Required | Description |
|---|---|---|---|
| event_type | string | YES | Event type — see §6.2 |
| date_as_recorded | string | NO | Verbatim date string as it appears in the source; exempt from date format validation |
| date | date | NO | Normalised ISO 8601 date — validated by Python (R36) |
| date_qualifier | string | NO | Date qualifier — see §6.3 |
| place_as_recorded | string | NO | Verbatim place name exactly as it appears in the source |

______________________________________________________________________

### 3.3 RecordedPerson

| Field | Type | Required | Description |
|---|---|---|---|
| recorded_person_id | integer | YES | Primary key |
| record_id | integer | YES | Foreign key to Record |
| name_as_recorded | string | YES | Verbatim name including original spelling |
| role | string | NO | Role in the record — see §6.4. Nullable since schema v3.0 (some sources do not state a role) |
| age_as_recorded | string | NO | Verbatim age |
| age | integer | NO | Normalised integer age |
| sex_as_recorded | string | NO | Sex exactly as recorded |
| occupation_as_recorded | string | NO | Occupation exactly as recorded |
| place_as_recorded | string | NO | Place of origin or residence exactly as recorded |
| notes | string | NO | Transcription observations |

______________________________________________________________________

### 3.4 RecordedRelationship

A relationship between two RecordedPerson rows, asserted directly by a source (a stated census household role pairing) or computed by an algorithm (a cross-census candidate-match score). Requires no Person to exist on either side. See conceptual_model.md §4.7.

| Field | Type | Required | Description |
|---|---|---|---|
| recorded_relationship_id | integer | YES | Primary key |
| recorded_person_id_1 | integer | YES | Foreign key to RecordedPerson |
| recorded_person_id_2 | integer | YES | Foreign key to RecordedPerson. May belong to the same Record as `recorded_person_id_1` (a stated household role pairing) or to a different Record entirely (a cross-census candidate match) |
| type | string | YES | Relationship type — see §6.7. `couple` / `parent_child` / `sibling` for source-stated relationships; `similarity` for an algorithmic candidate-match comparison |
| score | real | CONDITIONAL | Required when `type = similarity`; null otherwise |
| score_version | string | CONDITIONAL | Algorithm version that produced `score`; null when `score` is null |
| notes | string | NO | Free text notes |

______________________________________________________________________

### 3.5 RecordSimilarity

An algorithmic comparison between two Records — for example, a score suggesting the same household's return appears in two different census years. Has no conclusion-layer counterpart: it records a measurement, not an assertion. See conceptual_model.md §4.8.

| Field | Type | Required | Description |
|---|---|---|---|
| record_similarity_id | integer | YES | Primary key |
| record_id_1 | integer | YES | Foreign key to Record |
| record_id_2 | integer | YES | Foreign key to Record being compared against `record_id_1` |
| score | real | YES | Similarity score in [0.0, 1.0] |
| score_version | string | YES | Algorithm version that produced `score` |
| notes | string | NO | Free text notes |

______________________________________________________________________

### 3.6 NameVariant — Evidence (derived)

| Field | Type | Required | Description |
|---|---|---|---|
| name_variant_id | integer | YES | Primary key |
| recorded_person_id | integer | YES | Foreign key to RecordedPerson |
| variant_value | string | YES | The normalised name string |
| variant_type | string | YES | How the variant was produced — see §6.9 |
| algorithm_version | string | YES | Version string of the producing algorithm |
| notes | string | NO | Free text notes |

______________________________________________________________________

## 4. Conclusion Layer

### 4.1 Person

| Field | Type | Required | Description |
|---|---|---|---|
| person_id | integer | YES | Primary key |
| label | string | YES | Researcher convenience label |
| gender | string | NO | Concluded gender — see §6.5 |
| names | array[object] | NO | Typed name array — stored in `person_name` table |
| recorded_person_ids | array[integer] | NO | Foreign keys to RecordedPersons (via `person_recorded_person`) — Person's evidence correspondence per conceptual_model.md v2.6 Rule 2 |
| event_ids | array[integer] | NO | Foreign keys to Events (via `person_event`) |
| relationship_ids | array[integer] | NO | Foreign keys to Relationships — queried via `relationship.person_id_1` / `person_id_2` |
| private | boolean | NO | Whether Person is flagged for limited display |
| notes | string | NO | Free text notes |

______________________________________________________________________

### 4.2 Relationship

| Field | Type | Required | Description |
|---|---|---|---|
| relationship_id | integer | YES | Primary key |
| type | string | YES | Relationship type — see §6.7 |
| person_id_1 | integer | YES | For ParentChild: the parent. For Couple: either person. |
| person_id_2 | integer | YES | For ParentChild: the child. For Couple: either person. |
| recorded_relationship_ids | array[integer] | NO | Foreign keys to RecordedRelationships (via `relationship_recorded_relationship`) evidencing this Relationship |
| event_ids | array[integer] | NO | Foreign keys to Events associated with this Relationship |
| notes | string | NO | Researcher reasoning |

______________________________________________________________________

### 4.3 Event

| Field | Type | Required | Description |
|---|---|---|---|
| event_id | integer | YES | Primary key |
| type | string | YES | Event type — see §6.2 |
| is_primary | boolean | YES | Whether this Event is the current best-estimate conclusion among possibly-competing Events of the same type for the same Person; exactly one true per (person, type) pair, re-derived idempotently as evidence changes (Rule 9) |
| date | date | NO | Concluded ISO 8601 date |
| date_qualifier | string | NO | Date qualifier — see §6.3 |
| place_id | integer | NO | Foreign key to PlaceAuthority (not a conclusion — an authority reference) |
| person_ids | array[integer] | NO | Foreign keys to Persons who participated |
| relationship_id | integer | NO | Foreign key to Relationship — principal connection |
| record_ids | array[integer] | NO | Foreign keys to Records evidencing this Event |
| notes | string | NO | Researcher reasoning |

______________________________________________________________________

## 5. Cross-Layer Linkage Summary

| Conclusion object | Evidence linkage | Description |
|---|---|---|
| Person.recorded_person_ids | → RecordedPerson | RecordedPersons concluded to be about this Person |
| Event.record_ids | → Record | Records concluded to document this Event |
| Event.place_id | → PlaceAuthority | Authoritative place for this Event |
| Relationship.recorded_relationship_ids | → RecordedRelationship | RecordedRelationships concluded to evidence this Relationship |
| place_record | Record → PlaceAuthority | Scored conclusion: this recorded place string refers to this authority |

### Scoring columns on linkage junction tables

The four primary linkage junction tables (`person_recorded_person`, `event_record`, `relationship_recorded_relationship`, `place_record`) carry:

| Field | Type | Required | Description |
|---|---|---|---|
| score | real | NO | Similarity score in [0.0, 1.0]; null for manually-asserted linkages |
| score_version | string | NO | Algorithm version that produced the score; null when score is null |
| verified | boolean | YES | 0 = algorithm assertion; 1 = researcher-verified. Verified rows exempt from re-scoring. |

______________________________________________________________________

## 6. Controlled Vocabularies

### 6.1 Source Types

| Code | Description |
|---|---|
| `valuation` | Land valuation survey |
| `tithe` | Tithe applotment record |
| `census` | Census household return |
| `birth_registration` | Civil birth registration |
| `marriage_registration` | Civil marriage registration |
| `death_registration` | Civil death registration |
| `parish_register` | Church parish register |
| `military` | Military history or pension record |
| `folklore` | Folklore or oral history collection |
| `place_authority` | Place authority source (logainm.ie) |

### 6.2 Event Types

| Code | Description |
|---|---|
| `birth` | Birth |
| `baptism` | Baptism ceremony |
| `marriage` | Marriage ceremony |
| `death` | Death |
| `burial` | Burial |
| `census` | Census enumeration |
| `residence` | Recorded residence at a place |
| `emigration` | Emigration |
| `valuation` | Land valuation entry |
| `tithe` | Tithe applotment entry |
| `military_service` | Military service record |
| `pension` | Pension application or record |
| `folklore` | Folklore collection entry |

### 6.3 Date Qualifiers

| Code | Description |
|---|---|
| `exact` | Date is precisely known |
| `about` | Approximate date |
| `before` | Known to be before this date |
| `after` | Known to be after this date |
| `between` | Between two dates |
| `estimated` | Estimated from other evidence |
| `calculated` | Calculated from other known facts |

### 6.4 RecordedPerson Roles

**General:**

| Code | Description |
|---|---|
| `unknown` | Role could not be determined from the source (e.g. illegible or unstated relation-to-head) |

**Census roles (NAI relation_to_head mapping):**

| Code | NAI value(s) | Description |
|---|---|---|
| `head` | Head of Family | Head of household |
| `spouse` | Wife | Spouse of head |
| `son` | Son | Son of head or spouse |
| `daughter` | Daughter | Daughter of head or spouse |
| `sibling` | Brother, Sister | Sibling of head |
| `grandchild` | Grand Son, Grand Daughter | Grandchild of head or spouse |
| `in_law` | Son in Law, Daughter in Law, etc. | Relation by marriage |
| `niece_nephew` | Niece, Nephew, Nice | Niece or nephew |
| `aunt_uncle` | Aunt, Uncle | Aunt or uncle |
| `cousin` | Cousin | Cousin |
| `mother` | Mother | Mother of head |
| `father` | Father | Father of head |
| `servant` | Servant | Domestic servant |
| `visitor` | Visitor | Visitor on census night |
| `boarder` | Boarder, Lodger | Paying lodger |

**Event roles (civil registration, parish register, other):**

| Code | Description |
|---|---|
| `principal` | Primary subject of the record |
| `groom` | Groom in marriage record |
| `bride` | Bride in marriage record |
| `father_of_groom` | Father of groom |
| `father_of_bride` | Father of bride |
| `godfather` | Godfather in baptism record |
| `godmother` | Godmother in baptism record |
| `witness` | Witness to an event |
| `informant` | Person providing information to registrar |
| `officiator` | Celebrant or officiant |
| `occupier` | Land occupier in valuation or tithe record |
| `lessor` | Lessor in valuation record |
| `deceased` | Deceased person in death or burial record |

### 6.5 Gender Values

| Code | Description |
|---|---|
| `male` | Male |
| `female` | Female |
| `unknown` | Gender not determinable |

### 6.6 Name Types

| Code | Description |
|---|---|
| `birth_name` | Name given at birth |
| `married_name` | Name adopted on marriage |
| `also_known_as` | Alternative name or Irish language form |
| `nickname` | Informal name |

### 6.7 Relationship Types

| Code | Directionality | Description |
|---|---|---|
| `couple` | Symmetric | Married or partnered pair |
| `parent_child` | person_id_1 = parent, person_id_2 = child | Parent to child |
| `sibling` | Symmetric | Sibling pair |

**RecordedRelationship extension:** `RecordedRelationship.type` additionally accepts `similarity` — an algorithmic candidate-match score between two RecordedPersons, carried in `score`/`score_version` (see §3.4). `similarity` is evidence-layer only and is not a valid value for the conclusion-layer `Relationship.type`.

### 6.8 Confidence Levels

**Retired as a stored field.** Aggregate confidence is derived at query time from the distribution of `score` values on linkage junction rows.

### 6.9 Name Variant Types

| Code | Description |
|---|---|
| `anglicised` | Anglicised form derived from an Irish-language name |
| `irish` | Irish-language form |
| `phonetic` | Phonetic encoding (Soundex or Metaphone) |
| `normalised` | Lowercased, stripped of diacritics and punctuation |

### 6.10 Place Types

| Code | Description |
|---|---|
| `province` | One of the four Irish provinces |
| `county` | County (civil) |
| `barony` | Barony |
| `civil_parish` | Civil parish |
| `ded` | District Electoral Division (census administrative unit) |
| `townland` | Townland — the atomic unit for place resolution |
| `church_parish` | Church/Catholic parish — not in logainm; manually added |
| `town` | Town or village |

______________________________________________________________________

## Changelog

| Version | Date | Change |
|---|---|---|
| 2.1 | May 2026 | Initial v2.1 data dictionary |
| 2.2 | May 2026 | Two-level deep link parameter system |
| 2.3 | May 2026 | Removed confidence from Relationship/Event; added NameVariant, scoring columns |
| 2.4 | May 2026 | Expanded RecordedPerson roles for full NAI census vocabulary |
| 2.5 | May 2026 | Replaced Place conclusion with PlaceAuthority foundational object. Added §2.3 PlaceAuthority with full flat-schema field table. Added §6.10 Place Types vocabulary. Updated §5 linkage summary to reflect place_record → PlaceAuthority. Added source type `place_authority` to §6.1. Removed PlaceMembership (flat schema adopted). |
| 2.6 | June 2026 | Merged RecordedEvent into Record (schema v2.8). §3.2 replaced with inline event fields on `record`. Removed `Event.recorded_event_ids` from §4.3 and §5. Updated `Person.relationship_ids` description to reflect removal of `person_relationship` junction table. |
| 2.7 | 17 June 2026 | Aligned with conceptual_model.md v2.6. Added §3.4 RecordedRelationship and §3.5 RecordSimilarity field tables (renumbered NameVariant to §3.6). Added `event.is_primary` (§4.3, Rule 9). Fixed `recorded_person.role` Required marker from YES to NO (nullable since schema v3.0) and added `unknown` to §6.4. Per the Rule 2 evidence-correspondence resolution: renamed `Person.record_ids` → `Person.recorded_person_ids` (via `person_recorded_person`) and `Relationship.record_ids` → `Relationship.recorded_relationship_ids` (via `relationship_recorded_relationship`); `Event.record_ids` unchanged. Updated §5 linkage summary and scoring-columns junction table list accordingly. Added `similarity` as a RecordedRelationship-only extension to §6.7 Relationship Types. |
