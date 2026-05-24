# Irish Genealogy Research

A probabilistic genealogy research system combining record linkage scoring, genealogical domain reasoning, and comprehensive validation. Evidence and conclusion layers strictly separated. Designed for Irish genealogy research at townland scale with Python + Claude two-collaborator model.

Schema version: **2.1** (May 2026) — Docs version: **2.5**

---

## Documentation

| File | Status | Description |
|---|---|---|
| `docs/conceptual_model.md` | ✅ v2.2 | Three-layer architecture, ten first-class objects, data flow, worked example |
| `docs/data_dictionary.md` | ✅ v2.3 | Field-level definitions for all objects, types, constraints, controlled vocabularies |
| `docs/repositories.md` | ✅ v1.2 | 12 pre-populated sources across 7 repositories with deep link templates |
| `docs/validation_rules.md` | ✅ v2.5 | 46 rules (R01–R46) across five categories: structural, referential, consistency, vocabulary, genealogical constraints |
| `docs/database_schema.md` | ✅ v2.4 | SQLite DDL, junction table design, index strategy, scoring and verification tracking |
| `docs/reconstruction_algorithms.md` | ✅ v1.0 | Record linkage scoring, Fellegi-Sunter, Jaro-Winkler, place resolution, Person/Event linkage |
| `docs/genealogical_constraints.md` | ✅ v1.1 | 22 domain constraints: chronological, singularity, source eligibility, biological plausibility, co-residency, community patterns |
| `docs/service_api.md` | ✅ v1.0 | Service layer API, research scope, knowledge retrieval, evidence queries, pipeline state, researcher signals |
| `docs/session_bootstrap.md` | 🔜 Pending | Context-loading guidance for transcription, linkage, and reasoning sessions |

---

## Repository Structure

```
irish-genealogy-research/
│
├── docs/                              # Schema and system documentation
│   ├── conceptual_model.md            # Three-layer architecture and design principles
│   ├── data_dictionary.md             # Object definitions and controlled vocabularies
│   ├── repositories.md                # Source catalogue with deep link templates
│   ├── validation_rules.md            # 46 validation rules (structural, referential, consistency, vocabulary, genealogical)
│   ├── database_schema.md             # SQLite DDL, indexes, scoring, verification tracking
│   ├── reconstruction_algorithms.md   # Probabilistic record linkage, Fellegi-Sunter, Jaro-Winkler
│   ├── genealogical_constraints.md    # 22 genealogical constraints driving scoring and reasoning
│   ├── service_api.md                 # Service layer for research operations and Claude sessions
│   └── session_bootstrap.md           # (pending) Session context loading
│
├── src/                               # Python source
│   ├── db/
│   │   ├── schema.sql                 # Complete DDL (CREATE TABLE + CREATE INDEX)
│   │   ├── migrations/                # Versioned migration scripts
│   │   └── seed.sql                   # Source and repository seed data
│   ├── db.py                          # Database layer: open_db(), init_db(), DataStore, build_record_url()
│   ├── validator.py                   # Validation framework: 46 rules across all categories
│   ├── service.py                     # Service layer: ResearchService API for Claude and UI consumers
│   ├── reconstruction.py              # Linkage scoring: Fellegi-Sunter, Jaro-Winkler, genealogical constraints
│   ├── linkage/                       # Record linkage algorithms and candidate generation
│   └── utils/                         # Shared utilities
│
├── tests/                             # Pytest test suite
│
├── requirements.txt                   # jellyfish, jsonschema, pytest, black
├── .gitignore                         # genealogy.db gitignored
└── README.md
```

> **Note:** The `data/` directory tree (per-object JSON files) is retired as of schema v2.1. All research data is stored in `genealogy.db` (SQLite), which is gitignored.

---

## System Architecture

### Three-Layer Data Model

The system uses a strict evidence/conclusion separation:

**Foundational Layer** — Repository, Source  
Institutional and bibliographic context, shared across the entire dataset.

**Evidence Layer** — Record, RecordedEvent, RecordedPerson  
Verbatim assertions extracted directly from historical sources. Never points to conclusions.

**Conclusion Layer** — Person, Relationship, Event, Place  
Researcher assertions, mutable and supported by evidence. All linkages to evidence are reversible.

### Validation Framework

**46 rules** across five categories, executed in order:

1. **Structural** (R01–R09) — required fields, non-empty constraints
2. **Referential Integrity** (R12–R19) — foreign key resolution
3. **Consistency** (R20–R26) — cross-object invariants (e.g., exactly one RecordedEvent per Record)
4. **Vocabulary and Format** (R28–R39) — controlled values, date formats, score ranges
5. **Genealogical Constraints** (R40–R46) — domain knowledge checks:
   - Birth/death/census singularity
   - Life event sequence and chronological ordering
   - Parent age and marriage age plausibility
   - Lifespan boundaries for record-person linkage

Enforcement is distributed: SQLite constraints enforce what they can (NOT NULL, CHECK, UNIQUE, REFERENCES), Python validation runs before writes and for cross-object checks.

### Probabilistic Reasoning Framework

**22 genealogical constraints** (GC01–GC22) layer domain knowledge onto record linkage scoring:

- **Chronological** — lifespan boundaries, event sequencing, census age drift
- **Singularity** — birth, death, marriage, census uniqueness per person
- **Source Eligibility** — which sources to search given person's profile (birth year, gender, role)
- **Biological Plausibility** — parent age (15–70 year gaps), marriage age (15+ years), sibling spacing
- **Co-residency** — household membership expectations (household head + spouse + children)
- **Community Patterns** — naming conventions, witness/godparent networks, occupational consistency
- **Record-Specific** — death registration informant as relationship signal, geographical coherence

All constraints are probabilistic weightings, not hard filters. Violations adjust linkage scores or surface as researcher flags.

### Service API

The service layer (`service.py`) is the single interface for all consumers:

- **Research scope definition** — filter by surname, townland, date range, sources
- **Knowledge retrieval** — person, relationship, event, place queries with full provenance
- **Evidence queries** — search records, find unlinked records, browse by source
- **Pipeline state** — proposals, flags, leads, auto-committed linkages
- **Researcher signals** — verify, reject, annotate linkages; create/assert conclusions; resolve flags
- **Session bootstrap** — context loading for Claude sessions

---

## The Two-Collaborator Model

**Python handles:**
- Schema validation and referential integrity
- SQLite I/O and batch ingestion
- Probabilistic record linkage (Fellegi-Sunter, Jaro-Winkler, constraint penalties)
- Genealogical constraint evaluation
- Pipeline execution and proposal generation

**Claude handles:**
- Verbatim transcription of source images
- Ambiguous record interpretation and structured data extraction
- Reasoning about conflicting evidence
- Hypothesis generation and narrative synthesis
- Validation of system proposals and researcher feedback

**Service API bridges both:** Python provides the knowledge base; Claude accesses it through the service layer to assist with research sessions.

---

## Getting Started

```bash
# Requires Python 3.12, SQLite 3.35.0+
pip install -r requirements.txt

# Initialise the database
python -c "from src.db import init_db; init_db('genealogy.db')"
```

> **Tests:** The v1 test suite is retired. A v2.1+ test suite covering all validation categories and object types is a pending work item.

---

*Designed for Irish genealogy research at townland scale. Evidence from civil registrations (1864+), census returns (1901, 1911, 1926), land records (Griffith's Valuation, Tithe Applotment), parish registers, and military/folklore sources.*
