# Genealogy Research Assistant (GRA)

*grá — Irish for love*

A probabilistic genealogy research platform combining a SQLite knowledge base, authoritative place data from logainm.ie, record linkage scoring, genealogical domain reasoning, and comprehensive validation. Evidence and conclusion layers strictly separated. Designed for Irish genealogy research at townland scale.

Schema version: 3.0 (June 2026)

---

## Project Status

> → See [`ROADMAP.md`](ROADMAP.md) for current work queue, open decisions, and what to focus on next.

---

## Repository Structure

irish-genealogy-research/
│
├── archive/                           # Deprecated/Inactive documentation
│
├── docs/                              # Schema and system documentation
│
├── src/
│   ├── cli.py                         # Sole entry point — argparse + dispatch only
│   │
│   ├── db/                            # Schema lifecycle and utilities
│   │   ├── db.py                      # Connection, init, schema version check
│   │   ├── schema.sql                 # Complete DDL (v3.0)
│   │   ├── seed.sql                   # Repository and source seed data
│   │   ├── fetch_places.py            # logainm API fetcher → DB or CSV
│   │   ├── seed_places.py             # CSV → place_authority loader
│   │   ├── reset_pipeline.py          # Pipeline reset utility
│   │   └── migrations/
│   │       ├── migrate_25_to_26.sql
│   │       ├── migrate_26_to_27.sql
│   │       ├── migrate_27_to_28.sql
│   │       ├── migrate_28_to_29.sql
│   │       └── migrate_29_to_30.sql
│   │
│   ├── ingest/                        # Evidence layer population
│   │   └── census.py                  # ingest_census — NAI CSV → DB
│   │
│   ├── dal/                           # Data access layer
│   │   └── ...                        # (All repositories: place, record, person, event, relationship, training)
│   │
│   └── pipeline/                      # Post-ingest reconstruction stages
│       ├── pipeline.py                # Stage orchestrator
│       ├── place_resolution.py        # Stage 2: authority-based place matching
│       ├── household_inference.py     # Stage 3: household structure → conclusions
│       ├── linkage.py                 # Stage 4: cross-census Splink person linkage
│       ├── scoring.py                 # Stage 5: rebuild event consensus (is_primary)
│       ├── debug.py                   # Linkage and consensus debug logging
│       ├── validator.py               # Genealogical constraint rules R40–R46
│       └── features/
│           └── census.py              # Splink feature extractor
│
└── tests/
    └── test_place_authority.py

---

## CLI Usage

# Seed place authority from logainm.ie (requires LOGAINM_API_KEY)
python -m src.cli fetch-places --logainm-id 111482 --db genealogy.db

# Or seed from a pre-fetched CSV
python -m src.cli seed-places --file tullynaught_places.csv

# Ingest census records
python -m src.cli ingest --source 3 --file tests/1901_Tullynaught.csv
python -m src.cli ingest --source 4 --file tests/1911_Tullynaught.csv
python -m src.cli ingest --source 5 --file tests/1926_Tullynaught.csv

# Full post-ingest pipeline (place resolution → household → linkage → consensus)
python -m src.cli reconstruct

# Or run stages individually
python -m src.cli place-resolve
python -m src.cli household
python -m src.cli link
python -m src.cli score-evidence

# Inspect
python -m src.cli summary

# Validate genealogical constraints
python -m src.cli validate

**Supported ingest sources:** Census 1901 (source 3), Census 1911 (source 4), Census 1926 (source 5). Additional sources planned for Release 2.

**Logainm API key:** Required for fetch-places. Set via LOGAINM_API_KEY environment variable or --api-key argument.

---

## requirements.txt

splink>=4.0
rapidfuzz>=3.0
pandas>=2.0
jsonschema>=4.0
pytest>=8...
