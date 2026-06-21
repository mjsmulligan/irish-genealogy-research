# Genealogy Research Assistant (GRA)

*grá — Irish for love*

A probabilistic genealogy research platform combining a PostgreSQL knowledge base, authoritative place data from logainm.ie, record linkage scoring, genealogical domain reasoning, and comprehensive validation. Evidence and conclusion layers strictly separated. Designed for Irish genealogy research at townland scale.

Schema version: 3.1 (June 2026)  
Implementation: Complete — all three layers (foundation, evidence, conclusion)

---

## Project Status

> → See [`ROADMAP.md`](ROADMAP.md) for current work queue and version history.

---

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
│   ├── review/                        # Review layer — researcher report module (planned)
│   │   └── validator.py               # R40–R46 rules; redesign pending (ROADMAP item 13)
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
│       └── training_repo.py
│
└── tests/
    ├── tullynaught_1901.csv
    ├── tullynaught_1911.csv
    └── tullynaught_1926.csv
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
