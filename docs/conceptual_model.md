# Irish Genealogy Research — Conceptual Data Model

*Version 2.3 — May 2026*
*Audience: All roles. This document defines the what and why of the data model. It contains no implementation detail.*

---

## 1. Design Principles

This system is built around a strict separation between what historical sources *say* and what the researcher *concludes*. That separation is the foundational architectural principle from which everything else follows.

**Evidence before conclusion.** The evidence layer records only what archives contain, verbatim and without interpretation. The conclusion layer records only what the researcher asserts, supported by evidence. Nothing crosses that boundary implicitly.

**Records as the unit of evidence.** A Record is the natural unit of archival research. A researcher asks: is this record about this person? Is this record about this event? The Record is the bridge between evidence and conclusion.

**Convergent evidence drives confidence.** A conclusion supported by a single record is a hypothesis. A conclusion supported by multiple independent records converging on the same assertion is a finding. The model is designed to accumulate evidence against conclusions over time.

**Symmetry between layers.** The evidence layer and conclusion layer mirror each other structurally. RecordedPerson corresponds to Person. RecordedEvent corresponds to Event. This symmetry makes the linkage between layers explicit and consistent.

**Place is authoritative, not concluded.** Places are seeded from an external authority (logainm.ie) before research begins. The linkage from a recorded place string to an authoritative place identity is a conclusion — but the place identity itself is not. This gives Splink a stable, high-quality place anchor rather than a researcher-derived cluster centroid.

**GEDCOMx alignment.** Where GEDCOMx vocabulary and concepts apply, they are adopted. Custom types for Irish-specific concepts use the namespace `http://irishgenealogy.local/gedcomx/{TypeName}`.

---

## 2. Three-Layer Architecture

The model is organised into three distinct logical layers.

### Foundational Layer

Standalone infrastructure entities providing institutional, bibliographic, and geographical context. They exist independently of any single record or conclusion and are shared across the entire dataset. Place authority is foundational — townland identities are facts seeded from logainm.ie, not researcher assertions.

### Evidence Layer

Verbatim assertions extracted directly from historical sources. This layer documents exactly what a source says — preserving raw data, original spellings, and contemporary context without interpretation. Nothing in this layer is a researcher assertion.

### Conclusion Layer

The analytical layer where historical reality is synthesised by the researcher. Conclusions are evaluated, mutable assertions supported by evidence. They are subject to revision as new evidence emerges.

---

## 3. Object Summary

The model has eleven first-class objects across three layers.

```
Foundational:   Repository     Source     PlaceAuthority
Evidence:       Record         RecordedEvent      RecordedPerson
Conclusion:     Person         Relationship       Event
```

PlaceMembership was considered and rejected in favour of a flat denormalised hierarchy on PlaceAuthority — see §4.3.

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
1. Use `python -m src.fetch_places --logainm-id <DED_ID> --db genealogy.db` to fetch a DED and its townlands from the logainm API and write directly to the database.
2. Alternatively, use `python -m src.fetch_places --logainm-id <DED_ID> --csv places.csv` to export for inspection, then `python -m src.db seed-places --file places.csv` to load.
3. For manual entries (church parishes), add rows to the CSV with `logainm_id` blank and import via seed-places.

Place seeding must precede record ingest and reconstruction. Place resolution (stage 2 of reconstruction) matches `place_as_recorded` strings against the authority table — if the table is empty, resolution cannot run.

---

### 4.4 Record — Evidence

The core administrative and contextual boundary for data extraction. A Record represents a single entry in a source — one row of a register, one line of a valuation, one census household. It is the unit on which all evidence extraction operates and the unit to which all conclusions point as their justifying evidence.

---

### 4.5 RecordedEvent — Evidence

A flat collection of attributes describing an occurrence exactly as written within a parent Record. RecordedEvent captures the verbatim date string, textual place name, and event type as the source states them — without normalisation or interpretation.

---

### 4.6 RecordedPerson — Evidence

One or more individuals documented within a parent Record. RecordedPerson captures the verbatim name spelling, stated age, and raw role exactly as the record states them.

---

### 4.7 Person — Conclusion

A concluded identity representing a real-world individual as asserted by the researcher. Constituted by associated Events and Relationships, supported by linked Records.

---

### 4.8 Relationship — Conclusion

A concluded assertion about a connection between two specific Persons. Independent of any single Event — accumulates evidence from multiple Records over time.

---

### 4.9 Event — Conclusion

A concluded assertion about a discrete real-world occurrence, representing the researcher's synthesis of what happened, when, and where. `Event.place_id` references `PlaceAuthority` directly — not a concluded place, but an authoritative place identity.

---

## 5. Data Flow

```
Repository
  └── Source
        └── Record  ─────────────────────────────────────┐
              ├── RecordedEvent                            │ evidence
              └── RecordedPerson                           │ linkage
                                                           │
              ┌──────────────────────────────────────────── ┘
              │
              ├──► Person           (this Record is about this Person)
              ├──► Event            (this Record documents this Event)
              ├──► Relationship     (this Record evidences this Relationship)
              └──► PlaceAuthority   (this Record's place string refers to this authority)

PlaceAuthority  ←── logainm.ie API / manual CSV
  (hierarchy expressed as flat columns: ded_id, county_id, barony_id, civil_parish_id)
```

The Record is the pivot point of the entire model. Everything above it is provenance. Everything to the right is conclusion. Evidence never points to conclusions — only conclusions point to evidence. PlaceAuthority is foundational and sits outside this flow — it is seeded before ingest begins.

---

## 6. Core Operational Rules

**Rule 1 — The flat evidence pair.** RecordedEvent and RecordedPerson are flat, parallel structures bound solely by their shared parent Record. They do not nest inside one another.

**Rule 2 — Record as evidence unit.** All conclusion-layer objects point to Records as their justifying evidence.

**Rule 3 — Exactly one RecordedEvent per Record.**

**Rule 4 — Relationship independence.** A Relationship is independent of any Event.

**Rule 5 — Conclusions point to evidence; evidence never points to conclusions.**

**Rule 6 — Convergent evidence drives confidence.**

**Rule 7 — Mutability of conclusions.** All conclusion-layer linkages are researcher assertions and remain mutable.

**Rule 8 — Place authority is foundational, not concluded.** PlaceAuthority entries are facts from an external reference authority. The linkage from a recorded place string to a PlaceAuthority entry (`place_record`) is a scored conclusion, but the PlaceAuthority identity itself is not. A researcher cannot create a PlaceAuthority entry through the normal conclusion pipeline — entries are loaded via `fetch_places` or `seed-places`.

---

## Changelog

| Version | Date | Change |
|---|---|---|
| 2.1 | May 2026 | Initial v2.1 conceptual model |
| 2.2 | May 2026 | Updated §4.2 (Source) and §4.3 (Record) for two-level deep link parameter system |
| 2.3 | May 2026 | Replaced Place conclusion with PlaceAuthority foundational object. Added §4.3 PlaceAuthority with flat hierarchy design rationale. Removed PlaceMembership (flat schema adopted). Updated §3 object summary, §5 data flow, §6 Rule 8. Added logainm.ie seeding workflow. Event.place_id now references PlaceAuthority. |
