# Irish Genealogy Research — Conceptual Data Model

*Version 2.2 — May 2026*
*Audience: All roles. This document defines the what and why of the data model. It contains no implementation detail.*

---

## 1. Design Principles

This system is built around a strict separation between what historical sources *say* and what the researcher *concludes*. That separation is the foundational architectural principle from which everything else follows.

**Evidence before conclusion.** The evidence layer records only what archives contain, verbatim and without interpretation. The conclusion layer records only what the researcher asserts, supported by evidence. Nothing crosses that boundary implicitly.

**Records as the unit of evidence.** A Record is the natural unit of archival research. A researcher asks: is this record about this person? Is this record about this event? The Record is the bridge between evidence and conclusion.

**Convergent evidence drives confidence.** A conclusion supported by a single record is a hypothesis. A conclusion supported by multiple independent records converging on the same assertion is a finding. The model is designed to accumulate evidence against conclusions over time.

**Symmetry between layers.** The evidence layer and conclusion layer mirror each other structurally. RecordedPerson corresponds to Person. RecordedEvent corresponds to Event. This symmetry makes the linkage between layers explicit and consistent.

**GEDCOMx alignment.** Where GEDCOMx vocabulary and concepts apply, they are adopted. Custom types for Irish-specific concepts use the namespace `http://irishgenealogy.local/gedcomx/{TypeName}`.

---

## 2. Three-Layer Architecture

The model is organised into three distinct logical layers.

### Foundational Layer

Standalone infrastructure entities providing institutional and bibliographic context. They exist independently of any single record or conclusion and are shared across the entire dataset.

### Evidence Layer

Verbatim assertions extracted directly from historical sources. This layer documents exactly what a source says — preserving raw data, original spellings, and contemporary context without interpretation. Nothing in this layer is a researcher assertion.

### Conclusion Layer

The analytical layer where historical reality is synthesised by the researcher. Conclusions are evaluated, mutable assertions supported by evidence. They are subject to revision as new evidence emerges.

---

## 3. Object Summary

The model has ten first-class objects across three layers.

```
Foundational:   Repository     Source
Evidence:       Record         RecordedEvent      RecordedPerson
Conclusion:     Person         Relationship       Event           Place
```

---

## 4. Object Definitions

### 4.1 Repository — Foundational

The physical or digital institution, archive, or library that holds historical source material.

Examples: National Library of Ireland, General Register Office Ireland, National Archives of Ireland, Ancestry.com.

---

### 4.2 Source — Foundational

A specific document collection, register volume, or digital asset held by a Repository. A Source defines the context shared by all Records ingested from it.

A Source carries three operationally important fields:

**column_schema** — an ordered list of column names describing the CSV structure of raw_text fields across all child Records. This allows any raw_text string to be parsed back into its constituent fields by column position, providing a permanent audit trail from conclusion back to ingest.

**record_url_template** — a URL template containing `{placeholder}` tokens that the Python layer fills at runtime to construct a deep link to any individual Record within the source.

**source_parameters and record_parameter_names** — deep link construction requires two distinct kinds of identifiers. Some are constant across every Record in the Source — for example, the microfilm identifier (`vtls_id`) for an NLI parish register volume, or the release batch identifier (`release_id`) for a pension collection. These are Source-level constants stored in `source_parameters`. Others vary per Record — the page number, image identifier, or document ID that points to a specific entry. These are Record-level values stored on each Record in `record_parameters`, and the expected parameter names are declared on the Source in `record_parameter_names`. At runtime, the Python layer merges both sets to fill every placeholder in the template. This two-level split reflects the institutional reality: some identifying context belongs to the source collection as a whole, not to any individual record within it.

Examples: Civil Marriage Registrations Boyle District 1890, NLI Catholic Parish Registers Ballyoughter Microfilm vtls000634016, Griffith's Valuation Donegal 1857.

---

### 4.3 Record — Evidence

The core administrative and contextual boundary for data extraction. A Record represents a single entry in a source — one row of a register, one line of a valuation, one census household. It is the unit on which all evidence extraction operates and the unit to which all conclusions point as their justifying evidence.

**raw_text** is the verbatim ingest string, typically a CSV row. It is sacrosanct — it preserves exactly what was ingested before any parsing or interpretation.

**record_parameters** is a structured object carrying the Record-level identifier values required to fill the per-Record placeholders in the parent Source's `record_url_template`. Keys must match the names declared in `Source.record_parameter_names`. For sources where all template placeholders are Source-level constants, `record_parameters` is null.

A Record has exactly one child RecordedEvent and one or more child RecordedPersons. In the rare case where a single physical entry documents two discrete events, it is modelled as two separate Records.

---

### 4.4 RecordedEvent — Evidence

A flat collection of attributes describing an occurrence exactly as written within a parent Record. RecordedEvent captures the verbatim date string, textual place name, and event type as the source states them — without normalisation or interpretation.

RecordedEvent and RecordedPerson are parallel, flat structures. They do not nest inside one another. They are bound together solely by their shared parent Record.

Every Record produces exactly one RecordedEvent. Irish records are overwhelmingly considered to be anchored to a date and place even when those fields are not explicitly stated in the source — the date and place fields may be null, but the RecordedEvent always exists.

---

### 4.5 RecordedPerson — Evidence

One or more individuals documented within a parent Record. RecordedPerson captures the verbatim name spelling, stated age, and raw role exactly as the record states them.

The role field is particularly significant — it carries the implied relational information between participants (groom, bride, father, witness, occupier) that the conclusion layer will use to assert Relationships. RecordedPerson does not itself assert any relationship; it only records what the source states.

---

### 4.6 Person — Conclusion

A concluded identity representing a real-world individual as asserted by the researcher. A Person is constituted by their associated Events and the Relationships they participate in.

The linkage assertion connecting Records to this Person — the researcher's judgment that a given Record is about this Person — is expressed via **record_ids** on the Person. This is a conclusion and remains completely mutable if the researcher revises their judgment.

The **label** field is a researcher convenience only and carries no evidential weight.

The reconstruction algorithm that operates on this layer asks: are these Records about the same Person? RecordedPerson attributes (name, age, role) are the features the algorithm reads to score that question, but the linkage target is the Record, not the RecordedPerson.

---

### 4.7 Relationship — Conclusion

A concluded assertion about a connection between two specific Persons. A Relationship is independent of any single Event — it accumulates evidence from multiple Records over time, and confidence in the Relationship grows as independent Records converge on the same assertion.

A Relationship points directly to one or more Records as its justifying evidence. The roles on the RecordedPersons within those Records provide the evidential basis for the relationship type.

A Relationship can carry its own Events — for example, a marriage date and place is an Event on the Relationship itself rather than on either Person individually, following GEDCOMx convention.

For directionality: in a ParentChild relationship, person_id_1 is always the parent and person_id_2 is always the child. For Couple, the two persons are interchangeable.

A future **RecordedRelationship** evidence-layer object is reserved as an extension point for cases where formal evidence-layer linkage between RecordedPersons is required, for example in sibling relationship scoring. It is not part of the current model.

---

### 4.8 Event — Conclusion

A concluded assertion about a discrete real-world occurrence, representing the researcher's synthesis of what happened, when, and where. Event is the counterpart to RecordedEvent in the conclusion layer.

An Event groups the People who participated in an occurrence and optionally references the Relationship that defines the principal connection between them — for example, a marriage Event references the Couple Relationship to distinguish bride and groom from witnesses.

An Event points to one or more Records as its justifying evidence. Confidence in the Event grows as independent Records converge on the same occurrence.

The reconstruction algorithm that operates on this layer asks: are these Records about the same Event? RecordedEvent attributes (date, place, type) are the features the algorithm reads to score that question.

### 4.9 Place — Conclusion

A concluded assertion that one or more verbatim place strings found in Records refer to the same real-world geographical location. Place is a researcher conclusion, not a foundational authority — the act of determining that "Stranass", "Straniss", and "Strandness" all refer to the same townland is an interpretive judgment, not an objective fact.

Place points to one or more Records as the evidence base for that judgment. External links to townlands.ie and logainm.ie serve as reference authorities — they inform the researcher's conclusion but do not make it. A unique spelling variant or transcription error in a single record is handled by the researcher's judgment, documented and mutable like any other conclusion.

Place hierarchy (townland → civil parish → barony → county), Irish language name, historical name variants, and geographic coordinates are retrievable from the external sources via the linked URLs.

---

## 5. Data Flow

```
Repository
  └── Source
        └── Record  ─────────────────────────────────┐
              ├── RecordedEvent                        │ evidence
              └── RecordedPerson                       │ linkage
                                                       │
              ┌──────────────────────────────────────── ┘
              │
              ├──► Person        (this Record is about this Person)
              ├──► Event         (this Record documents this Event)
              ├──► Relationship  (this Record evidences this Relationship)
              └──► Place         (this Record contains this place name)
```

The Record is the pivot point of the entire model. Everything above it is provenance. Everything to the right is conclusion. Evidence never points to conclusions — only conclusions point to evidence.

---

## 6. Core Operational Rules

**Rule 1 — The flat evidence pair.** RecordedEvent and RecordedPerson are flat, parallel structures bound solely by their shared parent Record. They do not nest inside one another and they are not direct linkage targets for conclusion-layer objects.

**Rule 2 — Record as evidence unit.** All conclusion-layer objects (Person, Event, Relationship, Place) point to Records as their justifying evidence — not to RecordedEvent or RecordedPerson directly. RecordedEvent and RecordedPerson are the structured attributes the reconstruction algorithm reads, not the objects it links to.

**Rule 3 — Exactly one RecordedEvent per Record.** A Record has exactly one RecordedEvent. A physical entry documenting two discrete events is modelled as two Records.

**Rule 4 — Relationship independence.** A Relationship is independent of any Event. It links two Persons directly and accumulates evidence from multiple Records. It is not owned by or nested within an Event.

**Rule 5 — Conclusions point to evidence; evidence never points to conclusions.** Evidence-layer objects (Record, RecordedEvent, RecordedPerson) contain only verbatim fields. They carry no foreign keys to conclusion-layer objects. Linkage flows exclusively from conclusion to evidence.

**Rule 6 — Convergent evidence drives confidence.** A conclusion (Person, Event, Relationship, Place) supported by a single Record is provisional. Confidence is a function of convergence across multiple independent Records. The mechanics of confidence scoring are defined in the reconstruction algorithms document.

**Rule 7 — Mutability of conclusions.** All conclusion-layer linkages are researcher assertions and remain mutable. A Record linked to a Person today may be unlinked tomorrow if new evidence changes the researcher's judgment. The evidence layer is never modified to reflect conclusion-layer revisions.

---

## 7. Worked Example — Marriage Record

The following example walks a single civil marriage registration up through all three layers.

**Source material**

Civil Marriage Registration, GRO Ireland, Boyle district, 1890.
Raw ingest string: `1890-01-10,Straness,John Mulligan,28,farmer,Mary Brennan,24,Patrick Mulligan,Thomas Brennan`

**Foundational layer**

```
Repository:  General Register Office, Ireland
Source:      Civil Marriage Registrations, Boyle District, 1890
             record_url_template: https://civilrecords.irishgenealogy.ie/churchrecords/images/marriage_returns/marriages_{year}/{folder_id}/{image_id}.pdf
             source_parameters:   null
             record_parameter_names: [year, folder_id, image_id]
```

**Evidence layer**

```
Record {
  raw_text:          "1890-01-10,Straness,John Mulligan,28,farmer,Mary Brennan,24,Patrick Mulligan,Thomas Brennan"
  record_parameters: {"year": 1890, "folder_id": "marriages_1890_001", "image_id": "0042"}
  → deep link:       https://civilrecords.irishgenealogy.ie/churchrecords/images/marriage_returns/marriages_1890/marriages_1890_001/0042.pdf
}
  ├── RecordedEvent { date_as_recorded: "1890-01-10", place_as_recorded: "Straness", type: "marriage" }
  ├── RecordedPerson { name_as_recorded: "John Mulligan", age_as_recorded: "28", occupation_as_recorded: "farmer", role: "groom" }
  ├── RecordedPerson { name_as_recorded: "Mary Brennan", age_as_recorded: "24", role: "bride" }
  ├── RecordedPerson { name_as_recorded: "Patrick Mulligan", role: "father_of_groom" }
  └── RecordedPerson { name_as_recorded: "Thomas Brennan", role: "father_of_bride" }
```

**Conclusion layer**

```
Place { Straness, Co. Roscommon }    ← Record { record_parameters.year=1890, image_id=0042 }

Person { John Mulligan }             ← Record { ... }
Person { Mary Brennan }              ← Record { ... }
Person { Patrick Mulligan }          ← Record { ... }
Person { Thomas Brennan }            ← Record { ... }

Relationship { couple, John, Mary,
  confidence: medium                 ← Record { ... }
}

Event { marriage, Place{ Straness }, 1890-01-10,
  persons: [ John, Mary, Patrick, Thomas ],
  relationship: Couple { John, Mary },
  confidence: medium                 ← Record { ... }
}
```

Note that confidence is medium at this point — a single record supports each conclusion. A corroborating parish register entry for the same marriage would raise confidence toward high across Event, Relationship, and Place.

---

*Next documents: database_schema.md, validation_rules.md, reconstruction_algorithms.md, session_bootstrap.md*

---

## Changelog

| Version | Date | Change |
|---|---|---|
| 2.1 | May 2026 | Initial v2.1 conceptual model |
| 2.2 | May 2026 | Updated §4.2 (Source) to document the two-level deep link parameter system (`source_parameters` and `record_parameter_names`). Updated §4.3 (Record) to replace `source_identifier` with `record_parameters`. Updated §7 worked example to show `record_parameters` on the Record object and the resulting constructed deep link URL. |
