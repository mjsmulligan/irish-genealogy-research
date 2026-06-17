# Irish Genealogy Research — Conceptual Data Model

*Version 2.6 — 17 June 2026*
*Audience: All roles. This document defines the what and why of the data model. It contains no implementation detail.*

---

## 1. Design Principles

This system is built around a strict separation between what historical sources *say* and what the researcher *concludes*. That separation is the foundational architectural principle from which everything else follows.

**Evidence before conclusion.** The evidence layer records only what archives contain, verbatim and without interpretation. The conclusion layer records only what the researcher asserts, supported by evidence. Nothing crosses that boundary implicitly.

**Records as the unit of evidence.** A Record is the natural unit of archival research. A researcher asks: is this record about this person? Is this record about this event? The Record is the bridge between evidence and conclusion.

**Convergent evidence drives confidence.** A conclusion supported by a single record is a hypothesis. A conclusion supported by multiple independent records converging on the same assertion is a finding. The model is designed to accumulate evidence against conclusions over time.

**Symmetry between layers.** The evidence layer and conclusion layer mirror each other structurally. RecordedPerson corresponds to Person; RecordedRelationship corresponds to Relationship. Event field data (type, date, place) is captured verbatim on the Record itself, keeping the evidence unit cohesive and query paths simple. RecordSimilarity is the one evidence-layer object with no conclusion-layer counterpart by design — it records a comparison, not an assertion about the world, so there is nothing for it to mirror.

**Place is authoritative, not concluded.** Places are seeded from an external authority (logainm.ie) before research begins. The linkage from a recorded place string to an authoritative place identity is a conclusion — but the place identity itself is not. This gives Splink a stable, high-quality place anchor rather than a researcher-derived cluster centroid.

**Relationships are evidence too.** A census role pairing (head/spouse, head/son) or a civil or parish register's named parties (groom and bride, father of bride) asserts a relationship between two individuals as directly as a Record asserts an occurrence. That assertion requires no Person to exist on either side first — RecordedRelationship captures a relationship between two RecordedPerson rows in the evidence layer, the same way Record captures an occurrence, independent of any Person conclusion. A household's relational structure can be fully evidenced before a single Person exists.

**Comparison is evidence, not conclusion.** An algorithmic similarity score between two pieces of evidence — two Records that might describe the same household, or two RecordedPersons who might be the same individual — is itself a fact worth recording, distinct from a decision to act on it. RecordSimilarity (between Records) and the `similarity` type on RecordedRelationship (between RecordedPersons) hold these scores without asserting that a match is real, keeping measurement and judgment separate.

**Conflicting evidence can yield conflicting conclusions.** Where evidence genuinely disagrees — two Records giving a person different birth years — the model permits more than one Event of the same type to coexist as competing conclusions, with exactly one marked `is_primary` as the current best estimate (see Rule 9). This does not apply uniformly. Person has no equivalent, because it is the anchor every other conclusion and linkage hangs from — forking it would fork the model. Relationship also does not currently use this mechanism, by pragmatic judgment that conflicting relationship-type evidence is rare; this is a deliberate scope decision, not a structural constraint the way Person's is.

**GEDCOMx alignment.** Where GEDCOMx vocabulary and concepts apply, they are adopted. Custom types for Irish-specific concepts use the namespace `http://irishgenealogy.local/gedcomx/{TypeName}`.

---

## 2. Three-Layer Architecture

The model is organised into three distinct logical layers.

### Foundational Layer

Standalone infrastructure entities providing institutional, bibliographic, and geographical context. They exist independently of any single record or conclusion and are shared across the entire dataset. Place authority is foundational — townland identities are facts seeded from logainm.ie, not researcher assertions.

### Evidence Layer

Verbatim assertions extracted directly from historical sources, together with the relationships and comparisons that can be drawn directly between those assertions. This layer documents exactly what a source says — preserving raw data, original spellings, and contemporary context without interpretation — and extends to relationships a source states directly between two recorded individuals (RecordedRelationship), and to algorithmic comparisons between evidence units (RecordSimilarity). Nothing in this layer is a researcher assertion; a stated household role and a Splink similarity score are both facts about the evidence, not facts about the world.

### Conclusion Layer

The analytical layer where historical reality is synthesised by the researcher. Conclusions are evaluated, mutable assertions supported by evidence. They are subject to revision as new evidence emerges.

---

## 3. Object Summary

The model has ten first-class objects across three layers.

```
Foundational:   Repository     Source     PlaceAuthority
Evidence:       Record         RecordedPerson    RecordedRelationship    RecordSimilarity
Conclusion:     Person         Relationship       Event
```

Two paths were considered, built, and rejected. PlaceMembership — a junction table for place hierarchy — was rejected in favour of the flat denormalised hierarchy on PlaceAuthority; see §4.3. `training_labels` — a table for Person-merge proposals awaiting researcher review — was implemented, used, and then retired as a dead end. The gap it leaves (recording a candidate match before committing to it) is now reached for differently: as a `similarity` type on RecordedRelationship, evidence-side rather than conclusion-side.

---

## 4. Object Definitions

### 4.1 Repository — Foundational

The physical or digital institution, archive, or library that holds historical source material.

Examples: National Library of Ireland, General Register Office Ireland, National Archives of Ireland, Ancestry.com, logainm.ie.

---

### 4.2 Source — Foundational

A specific document collection, register volume, or digital asset held by a Repository. A Source defines the context shared by all Records ingested from it.

Source type `place_authority` is used for the logainm.ie source. This source type does not produce Records in the normal sense — PlaceAuthority entries are seeded directly into the foundational layer rather than processed through the evidence pipeline.

---

### 4.3 PlaceAuthority — Foundational

An authoritative identity for a real-world geographical location, seeded from logainm.ie or added manually for entities logainm does not cover (notably church parishes).

PlaceAuthority uses a **flat schema**: the administrative hierarchy (county, barony, civil parish, DED) is expressed as denormalised columns on each row rather than through a separate junction table. This mirrors the logainm API response structure directly and makes hierarchy queries simple WHERE clauses rather than multi-table joins.

A townland row carries all of its parent contexts simultaneously:

```
Straness (townland)
  ded_name = "Tullynaught",  ded_id = 111482
  county_name = "Donegal",   county_id = 100013
  barony_name = "Tirhugh",   barony_id = 52
  civil_parish_name = "Drumhome", civil_parish_id = 785
```

**Why flat rather than a junction table?** A junction table (PlaceMembership) would be more normalised but adds join complexity for the most common query pattern — "all records in civil parish X" — with no practical benefit at the scale of this system. The denormalised columns also directly match the logainm API output, making ingestion straightforward and the data easy to inspect.

**Overlapping hierarchies** (a townland belonging to a DED for electoral purposes, a civil parish for administrative purposes, and a church parish for ecclesiastical purposes) are handled by the separate hierarchy columns. Church parishes are the one entity type not covered by logainm; they are added manually with `logainm_id = NULL`.

**The primary key** is a synthetic `place_id`. `logainm_id` is a unique nullable attribute — present for logainm-sourced entries, null for manually-added entries.

**Seeding workflow:**
1. Use `python -m src.cli fetch-places --logainm-id <DED_ID> --db genealogy.db` to fetch a DED and its townlands from the logainm API and write directly to the database.
2. Alternatively, use `python -m src.cli fetch-places --logainm-id <DED_ID> --csv places.csv` to export for inspection, then `python -m src.cli seed-places --file places.csv` to load.
3. For manual entries (church parishes), add rows to the CSV with `logainm_id` blank and import via seed-places.

Place seeding must precede record ingest and reconstruction. Place resolution (stage 2 of reconstruction) matches `place_as_recorded` strings against the authority table — if the table is empty, resolution cannot run.

---

### 4.4 Record — Evidence

The core administrative and contextual boundary for data extraction. A Record represents a single entry in a source — one row of a register, one line of a valuation, one census household. It is the unit on which all evidence extraction operates and the unit to which all conclusions point as their justifying evidence.

---

### 4.5 Record event fields — Evidence

Each Record carries the event attributes of the occurrence it documents directly as columns: `event_type`, `date_as_recorded`, `date`, `date_qualifier`, and `place_as_recorded`. These are verbatim or normalised from the source without interpretation — the same semantics that RecordedEvent previously provided, now inline on the Record itself. Because every Record documents exactly one event (a design invariant), the separate RecordedEvent table added a mandatory join without adding information. Merging these fields into Record eliminates that join from every query in the reconstruction pipeline.

---

### 4.6 RecordedPerson — Evidence

One or more individuals documented within a parent Record. RecordedPerson captures the verbatim name spelling, stated age, and raw role exactly as the record states them.

---

### 4.7 RecordedRelationship — Evidence

A relationship between two RecordedPerson rows, asserted either directly by a source or computed by an algorithm. The two RecordedPersons may belong to the same Record — a stated census household role pairing — or to different Records entirely, such as a cross-census comparison ahead of any merge decision. RecordedRelationship uses the same type vocabulary as the conclusion-layer Relationship (`couple`, `parent_child`, `sibling`) for source-stated relationships, plus a `similarity` type carrying an algorithmic score for candidate person-matching (the RecordedPerson-pair equivalent of RecordSimilarity below).

Unlike Relationship, RecordedRelationship requires no Person to exist on either side: recording that a source states "X is recorded as wife of Y", or that two RecordedPersons score 0.91 on a Splink comparison, is evidence in its own right, independent of whether X or Y has yet been concluded to be a real-world individual.

---

### 4.8 RecordSimilarity — Evidence

An algorithmic comparison between two Records — for example, a Splink score suggesting the same household's return appears in two different census years, ahead of any household-level conclusion. RecordSimilarity has no conclusion-layer counterpart by design: it records a measurement, not an assertion about the world. It is the Record-pair complement to the `similarity` type on RecordedRelationship, which serves the equivalent purpose between two RecordedPersons.

---

### 4.9 Person — Conclusion

A concluded identity representing a real-world individual as asserted by the researcher. Constituted by associated Events and Relationships, supported by linked RecordedPerson rows — the same evidentiary correspondence Relationship has to RecordedRelationship (Rule 2).

Person has no primary/alternate variant — unlike Event, exactly one Person represents a given concluded identity. Every other conclusion and linkage in the model is anchored to a `person_id`, so allowing competing Person conclusions would fork everything downstream of it. Uncertainty about identity must be resolved before a Person is concluded, not represented afterward.

---

### 4.10 Relationship — Conclusion

A concluded assertion about a connection between two specific Persons. Independent of any single Event — accumulates evidence from multiple RecordedRelationship rows over time.

Like Person, Relationship does not currently support primary/alternate variants. This is a scope decision rather than a structural necessity: conflicting relationship-type evidence (a source implying both `sibling` and `cousin` for the same pair) is judged rare enough not to warrant the added complexity, unlike Person, where a single identity is structurally load-bearing.

---

### 4.11 Event — Conclusion

A concluded assertion about a discrete real-world occurrence, representing the researcher's synthesis of what happened, when, and where. `Event.place_id` references `PlaceAuthority` directly — not a concluded place, but an authoritative place identity.

Unlike Person and Relationship, Event permits multiple competing conclusions of the same type for the same Person: where evidence disagrees — two Records giving different birth years — both candidate Events can coexist. Exactly one Event per (Person, event_type) pair is marked `is_primary`, the current best estimate; see Rule 9 in §6.

---

## 5. Data Flow

```
FOUNDATIONAL
  Repository ── Source

EVIDENCE
  Source ── Record ── RecordedPerson
  RecordedPerson ◄──► RecordedPerson    via RecordedRelationship
                                           (semantic: couple / parent_child / sibling
                                            algorithmic: similarity — person-matching score)
  Record         ◄──► Record            via RecordSimilarity
                                           (algorithmic: similarity — record-matching score;
                                            no conclusion-layer counterpart)

CONCLUSION
  RecordedPerson         ──► Person            (this RecordedPerson is about this Person)
  Record                 ──► Event              (this Record documents this Event)
  RecordedRelationship   ──► Relationship       (this RecordedRelationship evidences this Relationship)
  Record                 ──► PlaceAuthority     (this Record's place string refers to this authority)

PlaceAuthority  ←── logainm.ie API / manual CSV
  (hierarchy expressed as flat columns: ded_id, county_id, barony_id, civil_parish_id)
```

The Record/RecordedPerson pair remains the pivot of the evidence layer: everything above is provenance, everything below is conclusion. RecordedRelationship and RecordSimilarity sit beside that pivot as evidence-to-evidence facts — a relationship between two RecordedPersons, or a similarity score between two Records — neither requiring a conclusion to exist. As with every other linkage in the model, the underlying foreign keys run from conclusion to evidence, never the reverse (Rule 5); the arrows above describe what each evidence object supports, not which table owns the foreign key. PlaceAuthority is foundational and sits outside this flow entirely — it is seeded before ingest begins.

---

## 6. Core Operational Rules

**Rule 1 — Evidence cohesion.** Event fields (`event_type`, `date_as_recorded`, `date`, `date_qualifier`, `place_as_recorded`) and RecordedPerson rows are the structured evidence content of a Record. Event fields live directly on the Record; RecordedPersons are child rows keyed to the Record. RecordedRelationship (between RecordedPersons) and RecordSimilarity (between Records) are likewise evidence-layer content. None of these carry foreign keys to conclusion-layer objects.

**Rule 2 — Evidence correspondence.** Each conclusion-layer object points to the evidence object that most specifically corresponds to it: Person to RecordedPerson, Relationship to RecordedRelationship. Event points to Record directly, since event fields are captured on the Record itself (Rule 1, Rule 3) rather than on a separate per-event evidence row — there is no more specific object to point to.

**Rule 3 — One event per Record.** Each Record documents exactly one event. The event fields on the Record express this directly. A physical source entry documenting two discrete events is modelled as two Records.

**Rule 4 — Relationship independence.** A Relationship is independent of any Event.

**Rule 5 — Conclusions point to evidence; evidence never points to conclusions.**

**Rule 6 — Convergent evidence drives confidence.** Where convergent evidence is not unanimous, see Rule 9.

**Rule 7 — Mutability of conclusions.** All conclusion-layer linkages are researcher assertions and remain mutable.

**Rule 8 — Place authority is foundational, not concluded.** PlaceAuthority entries are facts from an external reference authority. The linkage from a recorded place string to a PlaceAuthority entry (`place_record`) is a scored conclusion, but the PlaceAuthority identity itself is not. A researcher cannot create a PlaceAuthority entry through the normal conclusion pipeline — entries are loaded via `fetch_places` or `seed-places`.

**Rule 9 — Event consensus arbitration.** Multiple Events of the same type may exist for a single Person, representing alternative conclusions drawn from conflicting evidence. Exactly one Event per (Person, event_type) pair is marked `is_primary`, the current best estimate, determined by the volume of supporting Records and re-derived idempotently as new evidence arrives — not fixed permanently by an earlier decision. Person and Relationship do not use this mechanism: Person because it is the anchor every other conclusion and linkage depends on, so competing Person conclusions would fork the entire model beneath it; Relationship by current scope decision, since conflicting relationship-type evidence is judged rare.

**Rule 10 — Relationship evidence precedes identity.** A relationship between two individuals can be evidenced — and recorded as RecordedRelationship — before either individual is concluded to be a real-world Person. A census household's role structure, or a marriage record's named parties, asserts relationships directly from the source; it does not require Person conclusions to exist first.

**Rule 11 — Comparison is not conclusion.** A similarity score between two evidence units — two Records, or two RecordedPersons — is itself evidence, not a conclusion. RecordSimilarity (between Records) and the `similarity` type on RecordedRelationship (between RecordedPersons) record these algorithmic comparisons without asserting a match is real; turning that comparison into a conclusion still requires the Person or Relationship machinery to act on it.

---

## Changelog

| Version | Date | Change |
|---|---|---|
| 2.1 | May 2026 | Initial v2.1 conceptual model |
| 2.2 | May 2026 | Updated §4.2 (Source) and §4.3 (Record) for two-level deep link parameter system |
| 2.3 | May 2026 | Replaced Place conclusion with PlaceAuthority foundational object. Added §4.3 PlaceAuthority with flat hierarchy design rationale. Removed PlaceMembership (flat schema adopted). Updated §3 object summary, §5 data flow, §6 Rule 8. Added logainm.ie seeding workflow. Event.place_id now references PlaceAuthority. |
| 2.4 | June 2026 | Merged RecordedEvent into Record (schema v2.8). RecordedEvent removed as a first-class object. §1 symmetry principle updated. §3 object summary updated. §4.5 rewritten to describe inline event fields. §5 data flow updated. §6 Rules 1 and 3 updated. |
| 2.5 | 17 June 2026 | Added RecordedRelationship and RecordSimilarity as new Evidence-layer objects, recording relationships and algorithmic similarity between evidence units without requiring a conclusion to exist (§1, §2, §3, §4.7, §4.8). Added Event consensus arbitration as Rule 9 — competing Events of the same type may coexist per Person, with exactly one marked `is_primary`; Person and Relationship explicitly excluded from this mechanism, for different reasons (§1, §4.9, §4.10, §4.11, §6). Added Rule 10 (relationship evidence precedes identity) and Rule 11 (comparison is not conclusion). Retired `training_labels` as a considered-and-built-then-rejected path, alongside the existing PlaceMembership note (§3). Corrected object count from eleven (stale, did not match the actual object list) to ten. Updated §1 Symmetry between layers to include the RecordedRelationship/Relationship mirror and the deliberate RecordSimilarity asymmetry. Updated §2 Evidence Layer description. Updated §5 data flow diagram and explanatory paragraph. Fixed stale CLI invocation examples in §4.3 seeding workflow (`python -m src.cli fetch-places` / `seed-places`, previously incorrectly given as `src.fetch_places` / `src.db seed-places`). |
| 2.6 | 17 June 2026 (session 3) | Generalised Rule 2 from "Records as evidence unit" to an evidence-correspondence principle: Person points to RecordedPerson, Relationship to RecordedRelationship, Event continues to point to Record directly since event fields are inline on the Record (Rule 1, Rule 3). This resolves the Relationship evidence-FK item left open at the end of the v2.5 session — settled in favour of RecordedRelationship — and, on the same principle, corrects Person's evidence target from Record to RecordedPerson, which §1's symmetry principle had already implied but §5/§6 had not carried through. Updated §5 data flow diagram (`Record──►Person` → `RecordedPerson──►Person`), §4.9 Person and §4.10 Relationship wording to match; removed the now-resolved "Records (or, more precisely, RecordedRelationship rows)" hedge from §4.10. |
