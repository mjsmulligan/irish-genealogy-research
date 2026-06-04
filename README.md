# Genealogy Research Assistant (GRA)

*grá — Irish for love*

A probabilistic genealogy research platform combining a SQLite knowledge base, authoritative place data from logainm.ie, record linkage scoring, genealogical domain reasoning, and comprehensive validation. Evidence and conclusion layers strictly separated. Designed for Irish genealogy research at townland scale.

Schema version: **2.8** (June 2026)

---

## Project Status

> **→ See [`ROADMAP.md`](ROADMAP.md) for current work queue, open decisions, and what to focus on next.**

---

## Documentation

| File | Status | Description |
|---|---|---|
| `docs/conceptual_model.md` | ✅ v2.4 | Three-layer architecture; event fields inline on Record |
| `docs/data_dictionary.md` | ✅ v2.6 | Field-level definitions; flat PlaceAuthority schema; full NAI census role mapping |
| `docs/repositories.md` | ✅ v1.5 | 13 sources across 8 repositories; logainm.ie added |
| `docs/validation_rules.md` | ✅ v2.6 | 46 rules (R01–R46) |
| `docs/database_schema.md` | ✅ v2.8 | SQLite DDL; RecordedEvent merged into Record; 5 junction tables |
| `docs/reconstruction_algorithms.md` | ✅ v1.2 | Record linkage scoring; role-pair rules; sibling inference; updated for v2.8 |
| `docs/genealogical_constraints.md` | ✅ v1.2 | 22 domain constraints (GC01–GC22) |
| `docs/service_api.md` | ✅ v1.0 | Service layer API |
| `docs/session_bootstrap.md` | ✅ v1.0 | Ingest and update knowledge session protocols |
| `ROADMAP.md` | ✅ v1.5 | Work queue, open decisions, project roadmap |

---

## Repository Structure

```
irish-genealogy-research/
│
├── docs/                              # Schema and system documentation
│
├── src/                               # Implementation
│   ├── db/
│   │   ├── schema.sql                 # Complete DDL (v2.8)
│   │   ├── seed.sql                   # Repository and source seed data
│   │   └── migrations/
│   │       ├── migrate_25_to_26.sql
│   │       ├── migrate_26_to_27.sql   # place → place_authority
│   │       └── migrate_27_to_28.sql   # recorded_event merged into record
│   ├── reconstruction/
│   │   ├── __init__.py
│   │   ├── place_resolution.py        # Stage 2: authority-based place matching
│   │   ├── household_inference.py     # Stage 3: household structure → conclusions
│   │   ├── linkage.py                 # Stage 4: cross-census Splink person linkage
│   │   └── features/
│   │       └── census.py              # Splink feature extractor (name, age, place, relationships)
│   ├── db.py                          # Database layer and CLI
│   ├── fetch_places.py                # logainm API fetcher → DB or CSV
│   ├── seed_places.py                 # CSV → place_authority loader
│   └── validator.py                   # Genealogical constraint rules R40–R46
│
└── tests/
    └── test_place_authority.py        # 33 tests: schema, CSV, resolution, hierarchy
```

---

## System Architecture

### Three-Layer Data Model

**Foundational Layer** — Repository, Source, PlaceAuthority
Institutional, bibliographic, and geographical reference data. PlaceAuthority entries are seeded from logainm.ie before research begins — they are facts, not conclusions.

**Evidence Layer** — Record, RecordedPerson
Verbatim assertions from historical sources. Each Record carries its event fields inline (`event_type`, `date`, `place_as_recorded`). Never points to conclusions.

**Conclusion Layer** — Person, Relationship, Event
Researcher assertions, mutable and supported by evidence.

### Reconstruction Pipeline

```
0. Place seeding  → place_authority populated from logainm.ie        ✅ implemented
1. Ingest         → Evidence layer populated                          ✅ implemented
2. Place          → Evidence strings matched to place_authority       ✅ implemented
3. Household      → Census structure → Person/Relationship/Event      ✅ implemented
4. Linkage        → Cross-census Splink person linkage                ✅ implemented
5. Analysis       → Community queries, graph traversal, GEDCOM        🔜 future
```

### Linkage Features

The Splink linkage model compares persons across census years on:
- Surname and forename (Jaro-Winkler)
- Estimated birth year (absolute difference ±2/5/10 years)
- Resolved townland (`place_id` exact match)
- Concluded spouse name (Jaro-Winkler — high discriminating power)
- Concluded child name set (Jaccard overlap)
- Concluded sibling name set (Jaccard overlap)

Relationship features are drawn from the conclusion layer and require household inference to have run first. They are null — not zero — for persons with no concluded relationships, so Splink's NullLevel correctly treats absence of information differently from confirmed non-overlap.

---

## Getting Started

```bash
pip install -r requirements.txt

# Initialise database
python -m src.db init

# Seed place authority from logainm.ie (requires LOGAINM_API_KEY)
python -m src.fetch_places --logainm-id 111482 --db genealogy.db

# Or seed from a pre-fetched CSV
python -m src.db seed-places --file tullynaught_places.csv

# Ingest census records
python -m src.db ingest --source 3 --file tests/1901_Tullynaught.csv
python -m src.db ingest --source 4 --file tests/1911_Tullynaught.csv
python -m src.db ingest --source 5 --file tests/1926_Tullynaught.csv

# Reconstruct per source (place resolution + household inference)
python -m src.db reconstruct --source 3
python -m src.db reconstruct --source 4
python -m src.db reconstruct --source 5

# Cross-census linkage (run once all sources are reconstructed)
python -m src.db link

# Inspect
python -m src.db summary
```

### Explicit Pipeline Stages

For finer control, each reconstruction stage can be run independently:

```bash
python -m src.db place-resolve           # stage 2: resolve all unresolved place strings
python -m src.db household --source 4   # stage 3: household inference for one source
python -m src.db link                    # stage 4: cross-census linkage across all persons
```

**Supported ingest sources:** Census 1901 (source 3), Census 1911 (source 4), Census 1926 (source 5). Additional sources planned for Release 2.

**Logainm API key:** Required for `fetch_places`. Set via `LOGAINM_API_KEY` environment variable or `--api-key` argument.

---

## requirements.txt

```
splink>=4.0
jellyfish>=1.0
pandas>=2.0
jsonschema>=4.0
pytest>=8.0
requests>=2.31
black
```

---

*Designed for Irish genealogy research at townland scale. Evidence from civil registrations (1864+), census returns (1901, 1911, 1926), land records (Griffith's Valuation, Tithe Applotment), parish registers, and military/folklore sources. Place authority from logainm.ie.*
