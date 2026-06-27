# Genealogy Research Assistant (GRA)

*grá — Irish for love*

A probabilistic genealogy research platform combining a PostgreSQL knowledge base, authoritative place data from logainm.ie, record linkage scoring, genealogical domain reasoning, and comprehensive validation. Evidence and conclusion layers strictly separated. Designed for Irish genealogy research at townland scale.

Schema version: 4.0 (June 2026)  
**Threshold version**: 3.0 — Person resolution at 0.45 (optimized for genealogical coverage)  
Implementation: Complete — all four layers (foundation, evidence, conclusion, review)

______________________________________________________________________

## Project Status

> → See [`ROADMAP.md`](ROADMAP.md) for current work queue and version history.

______________________________________________________________________

## Repository Structure

```text
irish-genealogy-research/
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
│   │   └── seed_places.py             # CSV → place_authority loader
│   │
│   ├── evidence/                      # Evidence layer steps 1–5
│   │   ├── census.py                  # [1/5] ingest_census — NAI CSV → record + recorded_person
│   │   ├── role_relationships.py      # [2/5] Role-pair → RecordedRelationship
│   │   ├── place_resolution.py        # [3/5] Place string → place_authority linkage
│   │   ├── similarity.py              # [4/5] + [5/5] Splink record + person similarity
│   │   └── features/
│   │       ├── census.py              # Splink household feature extractor
│   │       └── census_person.py       # Splink person feature extractor
│   │
│   ├── conclusion/                    # Conclusion layer steps 1–3
│   │   ├── person_resolution.py       # [1/3] Cluster RecordedPersons → Person conclusions
│   │   ├── relationship_resolution.py # [2/3] Household matching → Relationship conclusions
│   │   └── event_resolution.py        # [3/3] Census + birth + marriage Event conclusions
│   │
│   ├── review/                        # Review layer — researcher report module
│   │   ├── report.py                  # ReportItem + Report dataclasses; JSON + Markdown serialisers
│   │   ├── findings.py                # Nine v1.0 finding functions (GC01, GC02, GC04, GC05, GC07, GC12, GC13, unlinked, single-census)
│   │   ├── priority.py                # Priority scoring: tier base score × scope multiplier → integer rank
│   │   └── runner.py                  # run_review(), write_report() → reports/ dir
│   │
│   └── dal/                           # Data access layer
│       ├── source_repo.py
│       ├── record_repo.py
│       ├── recorded_relationship_repo.py
│       ├── record_similarity_repo.py
│       ├── place_repo.py
│       ├── person_repo.py
│       ├── relationship_repo.py
│       ├── event_repo.py
│       ├── conclusion_log_repo.py
│       └── training_repo.py
│
├── reports/                           # Review report output (gitignored; .gitkeep tracks dir)
│
└── tests/
    ├── test_pipeline.py               # Integration test harness (59 tests, 100% pass)
    ├── tullynaught_1901.csv
    ├── tullynaught_1911.csv
    └── tullynaught_1926.csv
```

______________________________________________________________________

## CLI Usage

```bash
# Initialise database (Supabase/PostgreSQL — DATABASE_URL must be set)
python -m src.cli init

# Seed place authority from logainm.ie (requires LOGAINM_API_KEY)
python -m src.cli fetch-places --logainm-id 111482 --api-key YOUR_KEY

# Or seed from a pre-fetched CSV
python -m src.cli seed-places --file tullynaught_places.csv

# Add evidence: 5-step pipeline runs automatically per CSV
# [1/5] Ingest CSV → record + recorded_person
# [2/5] Assign role-pair RecordedRelationships
# [3/5] Run place resolution (links records to place_authority)
# [4/5] Run Splink record similarity (cross-census household matching)
# [5/5] Run Splink person similarity (cross-census person matching)
python -m src.cli add-evidence --source 3 --file tests/tullynaught_1901.csv
python -m src.cli add-evidence --source 4 --file tests/tullynaught_1911.csv
python -m src.cli add-evidence --source 5 --file tests/tullynaught_1926.csv

# Build conclusions from evidence
# [1/3] Person resolution  — cluster RecordedPersons into Person conclusions
# [2/3] Relationship resolution — create Relationships from household structure
# [3/3] Event resolution   — create census, birth, and marriage Events
python -m src.cli conclude

# Inspect
python -m src.cli summary

# Run research review — produces prioritised findings report (JSON + Markdown)
python -m src.cli review

# Clear and re-run
python -m src.cli clear-evidence      # wipes evidence + conclusions; preserves place_authority
python -m src.cli clear-conclusions   # wipes conclusion layer only; preserves evidence

# View reports
# Generated reports are written to reports/ with JSON + Markdown formats
# Example: reports/report_20260626_233433.{json,md}
```

**Supported ingest sources:** Census 1901 (source 3), Census 1911 (source 4), Census 1926 (source 5).

**Environment:** Set `DATABASE_URL` in `.env` before running any command. Format: `postgresql://postgres:[password]@db.[project-ref].supabase.co:5432/postgres`

______________________________________________________________________

## Testing

Run the end-to-end integration test suite (59 tests covering all layers):

```bash
# Via pytest (CLI)
pytest tests/test_pipeline.py -v

# Run a single test
pytest tests/test_pipeline.py::test_schema_version -v

# Run tests by pattern
pytest -k "evidence" -v
```

**VSCode:** Open Testing tab (beaker icon) and click play to run tests or individual test functions. Press F5 to launch via debugger.

**Setup:** Tests require:
1. PostgreSQL running locally (`localhost:5432/gra_test`)
2. Database initialized: `python -m src.cli init`
3. Place authority seeded: `python -m src.cli fetch-places --logainm-id 111482 --api-key YOUR_KEY`

**Database switching:** Edit `.env` to switch between local and cloud:
```
DATABASE_ENVIRONMENT=local    # local PostgreSQL on localhost:5432
DATABASE_ENVIRONMENT=cloud    # Supabase (requires network access)
```

______________________________________________________________________

## Requirements

```
psycopg2-binary
python-dotenv
splink>=4.0
rapidfuzz>=3.0
pandas>=2.0
pytest>=8.0
```
