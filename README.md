# Genealogy Research Assistant (GRA)

*grá — Irish for love*

A probabilistic genealogy research platform combining a SQLite knowledge base, record linkage scoring, genealogical domain reasoning, and comprehensive validation. Evidence and conclusion layers strictly separated. Designed for Irish genealogy research at townland scale, with an expanding vision for narrative output and multi-consumer access.

Schema version: **2.6** (May 2026) — Docs version: **2.6**

---

## Project Status

> **→ See [`ROADMAP.md`](ROADMAP.md) for current work queue, open decisions, and what to focus on next.**

The ROADMAP is the primary orchestration document for GRA. It tracks implementation status across all modules, open design decisions that block downstream work, and the near/medium/long-term roadmap. Start there at the beginning of each working session.

---

## Documentation

| File | Status | Description |
|---|---|---|
| `docs/conceptual_model.md` | ✅ v2.2 | Three-layer architecture, ten first-class objects, data flow, worked example |
| `docs/data_dictionary.md` | ✅ v2.4 | Field-level definitions for all objects; full NAI census role mapping; sibling relationship activated |
| `docs/repositories.md` | ✅ v1.4 | 12 pre-populated sources across 7 repositories; Sources 3 and 5 corrected against actual NAI schemas |
| `docs/validation_rules.md` | ✅ v2.6 | 46 rules (R01–R46) across five categories; R38 updated for nullable score |
| `docs/database_schema.md` | ✅ v2.6 | SQLite DDL; score/score_version nullable; migration script added |
| `docs/reconstruction_algorithms.md` | ✅ v1.1 | Record linkage scoring; expanded role-pair rules; sibling inference |
| `docs/genealogical_constraints.md` | ✅ v1.2 | 22 domain constraints: chronological, singularity, source eligibility, biological plausibility, co-residency, community patterns |
| `docs/service_api.md` | ✅ v1.0 | Service layer API, research scope, knowledge retrieval, evidence queries, pipeline state, researcher signals |
| `docs/session_bootstrap.md` | ✅ v1.0 | Ingest and update knowledge session protocols |
| `ROADMAP.md` | ✅ v1.4 | Work queue, implementation status, open decisions, project roadmap |

---

## Repository Structure

```
irish-genealogy-research/
│
├── docs/                              # Schema and system documentation
│   ├── conceptual_model.md
│   ├── data_dictionary.md
│   ├── repositories.md
│   ├── validation_rules.md
│   ├── database_schema.md
│   ├── reconstruction_algorithms.md
│   ├── genealogical_constraints.md
│   ├── service_api.md
│   └── session_bootstrap.md
│
├── src/                               # Implementation
│   ├── db/
│   │   ├── schema.sql                 # Complete DDL (v2.6)
│   │   ├── migrations/
│   │   │   └── migrate_25_to_26.sql   # v2.5 → v2.6 migration
│   │   └── seed.sql                   # Source and repository seed data
│   ├── reconstruction/
│   │   ├── __init__.py                # Package entry points (all four stages)
│   │   ├── place_resolution.py        # Stage 2: townland normalisation and Place conclusions
│   │   ├── household_inference.py     # Stage 3: census household structure → Person/Relationship/Event
│   │   ├── linkage.py                 # Stage 4: cross-census Splink person linkage and merge
│   │   └── features/
│   │       ├── __init__.py
│   │       └── census.py              # Feature extractor for census sources (1901/1911/1926)
│   ├── db.py                          # Database layer: open_db(), init_db(), DataStore, CLI
│   ├── validator.py                   # Validation framework: R40–R46 genealogical constraint rules
│   └── service.py                     # Service layer: API for research clients (pending)
│
├── tests/                             # Test suite (pending)
│
├── requirements.txt                   # Dependencies (includes splink>=4.0)
├── .gitignore                         # genealogy.db gitignored
├── ROADMAP.md
└── README.md
```

---

## System Architecture

### Three-Layer Data Model

**Foundational Layer** — Repository, Source
**Evidence Layer** — Record, RecordedEvent, RecordedPerson
**Conclusion Layer** — Person, Relationship, Event, Place

### Reconstruction Pipeline

The pipeline runs automatically after every ingest:

```
1. Ingest       → Evidence layer populated (Records, RecordedEvents, RecordedPersons)
2. Place        → Townland variants normalised; Place conclusions auto-committed     ✅
3. Person       → Household structure inferred; Person/Relationship/Event created    ✅
4. Linkage      → Cross-census Splink person linkage; duplicate Persons merged       ✅
5. Analysis     → Community queries, graph traversal, GEDCOM export                 🔜 future
```

**Stage 4 detail:** Splink runs in-memory via DuckDB against a feature view extracted from SQLite. Match probability ≥ 0.85 triggers an automatic merge (lower person_id is canonical — all junction rows re-pointed, duplicate Person deleted). Scores 0.30–0.85 are written as proposals for researcher review. Results are written back to `genealogy.db`.

**Source-specific feature extraction:** Each source type has a dedicated feature extractor in `src/reconstruction/features/`. Census feature extraction is implemented. Civil registration and parish register extractors are planned for Release 2.

### Validation Framework

**46 rules** across five categories:

1. **Structural** (R01–R09) — required fields, non-empty constraints
2. **Referential Integrity** (R12–R19) — foreign key resolution
3. **Consistency** (R20–R26) — cross-object invariants
4. **Vocabulary and Format** (R28–R39) — controlled values, date formats, score ranges
5. **Genealogical Constraints** (R40–R46) — domain knowledge checks:
   - Birth/death/census singularity
   - Life event sequence and chronological ordering
   - Parent age and marriage age plausibility
   - Lifespan boundaries for record-person linkage

Entry points: `validate(conn)`, `validate_object(obj_type, obj)`, `validate_genealogical(conn, person_id)`.

---

## Getting Started

```bash
# Requires Python 3.12, SQLite 3.35.0+
pip install -r requirements.txt

# Initialise a fresh database
python -m src.db init

# Ingest a census CSV — runs full pipeline automatically
# (place resolution → household inference → cross-census linkage)
python -m src.db ingest --source 4 --file tests/1911_Tullynaught.csv
python -m src.db ingest --source 3 --file tests/1901_Tullynaught.csv
python -m src.db ingest --source 5 --file tests/1926_Tullynaught.csv

# Print knowledge base summary
python -m src.db summary

# Re-run reconstruction pipeline (repair/admin mode only)
python -m src.db reconstruct

# Run genealogical validation across all persons
python -m src.validator --db genealogy.db

# Validate a single person
python -m src.validator --db genealogy.db --person 42

# Use a non-default database path with any command
python -m src.db --db path/to/custom.db summary
```

**Supported ingest sources:** Census 1901 (source 3), Census 1911 (source 4), and Census 1926 (source 5) using the NAI download CSV format. Additional source handlers are planned for Release 2.

---

*Designed for Irish genealogy research at townland scale. Evidence from civil registrations (1864+), census returns (1901, 1911, 1926), land records (Griffith's Valuation, Tithe Applotment), parish registers, and military/folklore sources.*
