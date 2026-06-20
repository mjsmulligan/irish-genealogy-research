# Genealogy Research Assistant (GRA)

*grá — Irish for love*

A probabilistic genealogy research platform combining a PostgreSQL knowledge base, authoritative place data from logainm.ie, record linkage scoring, genealogical domain reasoning, and comprehensive validation. Evidence and conclusion layers strictly separated. Designed for Irish genealogy research at townland scale.

Schema version: 3.1 (June 2026)  
Evidence layer: Complete and verified (21 June 2026)

---

## Project Status

> → See [`ROADMAP.md`](ROADMAP.md) for current work queue, open decisions, and what to focus on next.

---

## Repository Structure

```text
irish-genealogy-research/
│
├── archive/                           # Deprecated/inactive documentation
│
├── docs/                              # Schema and system documentation
│
├── src/
│   ├── cli.py                         # Sole entry point — argparse + dispatch only
│   ├── constants.py                   # Centralised constants (thresholds, score versions, source IDs)
│   │
│   ├── db/                            # Schema lifecycle and utilities
│   │   ├── db.py                      # Connection (psycopg2/Supabase), init, schema version check
│   │   ├── schema.sql                 # Complete DDL (v3.1, PostgreSQL)
│   │   ├── seed.sql                   # Repository and source seed data
│   │   ├── fetch_places.py            # logainm API fetcher → DB or CSV
│   │   ├── seed_places.py             # CSV → place_authority loader
│   │   ├── reset_pipeline.py          # Pipeline reset utility (deprecated)
│   │   └── migrations/
│   │       └── archive_sqlite/        # SQLite migrations (retired)
│   │
│   ├── ingest/                        # Evidence layer: record ingestion
│   │   └── census.py                  # ingest_census — NAI CSV → record + recorded_person
│   │
│   ├── evidence/                      # Evidence layer: post-ingest derivation
│   │   ├── role_relationships.py      # Role-pair → RecordedRelationship (ingest-time)
│   │   └── similarity.py             # Splink household similarity → RecordSimilarity
│   │
│   ├── dal/                           # Data access layer
│   │   ├── source_repo.py
│   │   ├── record_repo.py
│   │   ├── recorded_relationship_repo.py
│   │   ├── record_similarity_repo.py
│   │   ├── place_repo.py
│   │   ├── person_repo.py
│   │   ├── relationship_repo.py
│   │   ├── event_repo.py
│   │   └── training_repo.py
│   │
│   └── pipeline/                      # Conclusion-layer reconstruction stages (legacy)
│       ├── pipeline.py                # Stage orchestrator
│       ├── place_resolution.py        # Stage 2: authority-based place matching
│       ├── household_inference.py     # Stage 3: household structure → conclusions
│       ├── linkage.py                 # Stage 4: cross-census Splink person linkage
│       ├── scoring.py                 # Stage 5: rebuild event consensus (is_primary)
│       ├── debug.py                   # Linkage and consensus debug logging
│       ├── validator.py               # Genealogical constraint rules R40–R46
│       └── features/
│           └── census.py              # Splink feature extractor (psycopg2)
│
└── tests/
```

---

## CLI Usage

```bash
# Initialise database (Supabase/PostgreSQL — DATABASE_URL must be set)
python -m src.cli init

# Seed place authority from logainm.ie (requires LOGAINM_API_KEY)
python -m src.cli fetch-places --logainm-id 111482 --api-key YOUR_KEY

# Or seed from a pre-fetched CSV
python -m src.cli seed-places --file tullynaught_places.csv

# Add evidence: Complete 4-step pipeline runs automatically
# [1/4] Ingest CSV → record + recorded_person
# [2/4] Assign role-pair RecordedRelationships
# [3/4] Run place resolution (links records to place_authority)
# [4/4] Run Splink similarity (cross-census household matching)
python -m src.cli add-evidence --source 3 --file tests/tullynaught_1901.csv
python -m src.cli add-evidence --source 4 --file tests/tullynaught_1911.csv
python -m src.cli add-evidence --source 5 --file tests/tullynaught_1926.csv

# Inspect
python -m src.cli summary

# Clear and re-run
python -m src.cli clear-evidence      # wipes evidence + conclusions; preserves place_authority
python -m src.cli clear-conclusions   # wipes conclusion layer only; preserves evidence
```

**Supported ingest sources:** Census 1901 (source 3), Census 1911 (source 4), Census 1926 (source 5).

**Environment:** Set `DATABASE_URL` in `.env` before running any command. Format: `postgresql://postgres:[password]@db.[project-ref].supabase.co:5432/postgres`

---

## Requirements

```
psycopg2-binary
python-dotenv
splink>=4.0
rapidfuzz>=3.0
pandas>=2.0
pytest>=8.0
```
