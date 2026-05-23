# Irish Genealogy Research

GEDCOMx-lite schema for personal Irish genealogy research — SQLite-backed, evidence/conclusion separated, Python + Claude two-collaborator model.

Schema version: **2.1** (May 2026) — Docs version: **2.4**

---

## Documentation

| File | Status | Description |
|---|---|---|
| `docs/conceptual_model.md` | ✅ v2.2 | Three-layer architecture, ten first-class objects, data flow, worked example |
| `docs/data_dictionary.md` | ✅ v2.3 | Field-level definitions for all objects, types, constraints, controlled vocabularies |
| `docs/repositories.md` | ✅ v1.2 | 12 pre-populated sources across 7 repositories with deep link templates |
| `docs/validation_rules.md` | ✅ v2.4 | 39 rules (R01–R39) across four categories with enforcement locus and error codes |
| `docs/database_schema.md` | ✅ v2.4 | SQLite DDL, junction table design, index strategy, worked example |
| `docs/reconstruction_algorithms.md` | ✅ v1.0 | Record linkage scoring, Fellegi-Sunter, Jaro-Winkler, place resolution, Person/Event linkage |
| `docs/session_bootstrap.md` | 🔜 Pending | Context-loading guidance for transcription, linkage, and reasoning sessions |

---

## Repository Structure

```
irish-genealogy-research/
│
├── docs/                              # Schema documentation
│   ├── conceptual_model.md            # Architecture, data flow, ER diagram
│   ├── data_dictionary.md             # Object and field definitions
│   ├── repositories.md                # Source and repository catalogue
│   ├── validation_rules.md            # Rules R01–R39 with error codes
│   ├── database_schema.md             # SQLite DDL, indexes, worked example
│   ├── reconstruction_algorithms.md   # Record linkage, Fellegi-Sunter, place resolution
│   └── session_bootstrap.md           # (pending) Context-loading guidance
│
├── src/                               # Python source
│   ├── db/
│   │   ├── schema.sql                 # Canonical CREATE TABLE + CREATE INDEX statements
│   │   ├── migrations/                # Versioned migration scripts
│   │   └── seed.sql                   # Repositories + sources from repositories.md
│   ├── db.py                          # open_db(), init_db(), build_record_url(), DataStore read/write
│   ├── validator.py                   # DataStore.validate() and validate_object(), rules R01–R39
│   ├── linkage/                       # Record linkage scoring
│   └── utils/                         # Shared helpers
│
├── tests/                             # Pytest test suite (pending rewrite for v2.1)
│
├── requirements.txt                   # jellyfish, jsonschema, pytest, black
├── .gitignore                         # genealogy.db gitignored
└── README.md
```

> **Note:** The `data/` directory tree (per-object JSON files) is retired as of schema v2.1. All research data is stored in `genealogy.db` (SQLite), which is gitignored.

---

## Schema Overview

The v2.1 schema uses a **three-layer architecture** with ten first-class objects:

**Foundational** — Repository, Source

**Evidence** — Record, RecordedEvent, RecordedPerson

**Conclusion** — Person, Relationship, Event, Place

Key design principles:

- Evidence and conclusion layers are strictly separated — evidence never points to conclusions
- Exactly one `RecordedEvent` per `Record`; enforced by `UNIQUE (record_id)` in the DB
- `Person.record_ids` is the primary linkage assertion — not `RecordedPerson`
- `Relationship` is independent of `Event` and carries its own `event_ids`
- Many-to-many relationships implemented as junction tables (`person_record`, `event_person` etc.)
- `Person.names` stored in a dedicated `person_name` table for indexed name search
- Deep links constructed at runtime by merging `source_parameters` (Source-level constants) with `record_parameters` (Record-level values)
- Controlled vocabulary uses short codes as stored values (`"high"/"medium"/"low"`, `"couple"/"parent_child"` etc.)
- GEDCOMx URIs (`http://gedcomx.org/`) are reference metadata only, not stored values
- Irish-specific extensions use the `http://irishgenealogy.local/gedcomx/` namespace

---

## Validation

39 rules across four categories, annotated with enforcement locus:

- **[DB]** — SQLite constraint (`NOT NULL`, `CHECK`, `UNIQUE`, `REFERENCES`)
- **[Python]** — Python validator only
- **[DB + Python]** — DB enforces what it can; Python validates before write

Python-only rules (active enforcement required): **R20** (lower bound: exactly one RecordedEvent per Record), **R21** (at least one RecordedPerson per Record), **R26** (RecordedEvent ↔ Event Rec[...]

Two entry points: `DataStore.validate()` for full dataset checks; `DataStore.validate_object()` for pre-write single-object checks.

---

## The Two-Collaborator Model

**Python handles:** schema validation and referential integrity, SQLite I/O and batch ingestion, record linkage scoring (Fellegi-Sunter, Jaro-Winkler), deterministic deduplication.

**Claude handles:** verbatim transcription of source images, ambiguous record interpretation, reasoning about conflicting evidence, hypothesis generation and narrative synthesis.

---

## Getting Started

```bash
# Requires Python 3.12, SQLite 3.35.0+
pip install -r requirements.txt

# Initialise the database
python -c "from src.db import init_db; init_db('genealogy.db')"
```

> **Tests:** The v1 test suite (`test_validator.py`) is retired. A v2.1 test suite covering the five Python-only rules and all ten object types is a pending work item.

---

*Based on the [GEDCOMx Conceptual Model](http://gedcomx.org/conceptual-model/v1)*
