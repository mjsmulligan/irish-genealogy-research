# Genealogy Research Assistant (GRA)

*grá — Irish for love*

A probabilistic genealogy research platform combining a SQLite knowledge base, authoritative place data from logainm.ie, record linkage scoring, genealogical domain reasoning, and comprehensive validation. Evidence and conclusion layers strictly separated. Designed for Irish genealogy research at townland scale.

Schema version: **2.7** (May 2026)

---

## Project Status

> **→ See [`ROADMAP.md`](ROADMAP.md) for current work queue, open decisions, and what to focus on next.**

---

## Documentation

| File | Status | Description |
|---|---|---|
| `docs/conceptual_model.md` | ✅ v2.3 | Three-layer architecture; PlaceAuthority as foundational object |
| `docs/data_dictionary.md` | ✅ v2.5 | Field-level definitions; flat PlaceAuthority schema; full NAI census role mapping |
| `docs/repositories.md` | ✅ v1.5 | 13 sources across 8 repositories; logainm.ie added |
| `docs/validation_rules.md` | ✅ v2.6 | 46 rules (R01–R46) |
| `docs/database_schema.md` | ✅ v2.7 | SQLite DDL; PlaceAuthority flat table; migration v2.6→v2.7 |
| `docs/reconstruction_algorithms.md` | ✅ v1.1 | Record linkage scoring; role-pair rules; sibling inference |
| `docs/genealogical_constraints.md` | ✅ v1.2 | 22 domain constraints (GC01–GC22) |
| `docs/service_api.md` | ✅ v1.0 | Service layer API |
| `docs/session_bootstrap.md` | ✅ v1.0 | Ingest and update knowledge session protocols |
| `ROADMAP.md` | ✅ v1.4 | Work queue, open decisions, project roadmap |

---

## Repository Structure

```
irish-genealogy-research/
│
├── docs/                              # Schema and system documentation
│
├── src/                               # Implementation
│   ├── db/
│   │   ├── schema.sql                 # Complete DDL (v2.7)
│   │   ├── seed.sql                   # Repository and source seed data
│   │   └── migrations/
│   │       ├── migrate_25_to_26.sql
│   │       └── migrate_26_to_27.sql   # place → place_authority
│   ├── reconstruction/
│   │   ├── __init__.py
│   │   ├── place_resolution.py        # Stage 2: authority-based place matching
│   │   └── household_inference.py     # Stage 3: household structure → conclusions
│   ├── db.py                          # Database layer and CLI
│   ├── fetch_places.py                # logainm API fetcher → DB or CSV
│   ├── seed_places.py                 # CSV → place_authority loader
│   └── validator.py                   # Validation framework (pending)
│
└── tests/
    └── test_place_authority.py        # 33 tests: schema, CSV, resolution, hierarchy
```

---

## System Architecture

### Three-Layer Data Model

**Foundational Layer** — Repository, Source, PlaceAuthority
Institutional, bibliographic, and geographical reference data. PlaceAuthority entries are seeded from logainm.ie before research begins — they are facts, not conclusions.

**Evidence Layer** — Record, RecordedEvent, RecordedPerson
Verbatim assertions from historical sources. Never points to conclusions.

**Conclusion Layer** — Person, Relationship, Event
Researcher assertions, mutable and supported by evidence.

### Place Authority (New in v2.7)

Places are no longer researcher conclusions — they are authoritative identities from logainm.ie, Ireland's official placename authority. Each PlaceAuthority row carries the full administrative hierarchy as flat columns:

```
place_id | logainm_id | name_en   | place_type | ded_name    | county_name | barony_name | civil_parish_name | latitude   | longitude
---------|------------|-----------|------------|-------------|-------------|-------------|-------------------|------------|----------
1        | 111482     | Tullynaught | ded       | Tullynaught | Donegal     |             |                   | 54.6455    | -8.0435
2        | 14300      | Straness  | townland   | Tullynaught | Donegal     | Tirhugh     | Drumhome          | 54.6638    | -7.9794
```

Hierarchy queries are simple WHERE clauses:
```sql
-- All townlands in Drumhome civil parish
SELECT * FROM place_authority WHERE civil_parish_id = 785 AND place_type = 'townland';

-- All records in Tullynaught DED
SELECT r.* FROM record r
JOIN place_record pr ON pr.record_id = r.record_id
JOIN place_authority pa ON pa.place_id = pr.place_id
WHERE pa.ded_id = 111482;
```

### Reconstruction Pipeline

```
0. Place seeding  → place_authority populated from logainm.ie        ✅ implemented
1. Ingest         → Evidence layer populated                          ✅ implemented
2. Place          → Evidence strings matched to place_authority       ✅ implemented
3. Person         → Household structure → Person/Relationship/Event   ✅ implemented
4. Linkage        → Cross-source Splink person linkage                🔜 next
5. Analysis       → Community queries, graph traversal, GEDCOM        🔜 future
```

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

# Run reconstruction (place resolution + household inference)
python -m src.db reconstruct --source 4

# Inspect
python -m src.db summary
```

**Supported ingest sources:** Census 1901 (source 3), Census 1911 (source 4), Census 1926 (source 5). Additional sources planned for Release 2.

**Logainm API key:** Required for `fetch_places`. Set via `LOGAINM_API_KEY` environment variable or `--api-key` argument.

---

## requirements.txt

```
jellyfish>=1.0
jsonschema>=4.0
pytest>=8.0
requests>=2.31
black
```

---

*Designed for Irish genealogy research at townland scale. Evidence from civil registrations (1864+), census returns (1901, 1911, 1926), land records (Griffith's Valuation, Tithe Applotment), parish registers, and military/folklore sources. Place authority from logainm.ie.*
