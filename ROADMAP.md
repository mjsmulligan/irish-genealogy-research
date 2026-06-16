# Genealogy Research Assistant (GRA) — Project Roadmap

*16 June 2026 — v1.7*

---

## 1. Current State

### Documentation

| Document | Version | Status | Notes |
|---|---|---|---|
| `docs/conceptual_model.md` | v2.4 | ✅ Complete | RecordedEvent merged into Record |
| `docs/data_dictionary.md` | v2.6 | ✅ Complete | RecordedEvent removed; event fields inline on Record |
| `docs/repositories.md` | v1.5 | ✅ Complete | Repository 8 (logainm.ie) and Source 13 (place_authority) added |
| `docs/validation_rules.md` | v2.6 | ✅ Complete | R40–R46 implemented; retired rules updated for schema v2.8 |
| `docs/database_schema.md` | v2.8 | ✅ Complete | RecordedEvent merged into Record; junction table count 9→5; migration v2.7→v2.8 |
| `docs/reconstruction_algorithms.md` | v1.2 | ✅ Complete | Updated for schema v2.8; event linkage simplified |
| `docs/genealogical_constraints.md` | v1.2 | ✅ Complete | 22 GC-coded constraints |
| `docs/service_api.md` | v1.0 | ✅ Complete | Service layer API; flag/lead tables still needed in schema |
| `docs/session_bootstrap.md` | v1.0 | ✅ Complete | Ingest and update knowledge session protocols |
| `ROADMAP.md` | v1.7 | ✅ This document | — |

### Implementation

| Module | File(s) | Status | Notes |
|---|---|---|---|
| CLI entry point | `src/cli.py` | ✅ Complete | Sole entry point; argparse + dispatch only; `score-evidence` and `validate` commands added |
| Database layer | `src/db/db.py` | ✅ Complete | Connection, init, schema version check; no CLI |
| Schema DDL | `src/db/schema.sql` | ✅ Complete | v3.0 — is_primary on Event |
| Seed data | `src/db/seed.sql` | ✅ Complete | 12 sources, 8 repositories |
| Census ingest | `src/ingest/census.py` | ✅ Complete | ingest_census — NAI CSV → DB (sources 3, 4, 5) |
| DAL — places | `src/dal/place_repo.py` | ✅ Complete | place_authority, place_record queries |
| DAL — records | `src/dal/record_repo.py` | ✅ Complete | record, recorded_person queries (read-only) |
| DAL — persons | `src/dal/person_repo.py` | ✅ Complete | person, person_name, person_record queries |
| DAL — events | `src/dal/event_repo.py` | ✅ Complete | event, event_record, person_event queries |
| DAL — relationships | `src/dal/relationship_repo.py` | ✅ Complete | relationship, relationship_record queries |
| DAL — training | `src/dal/training_repo.py` | ✅ Complete | training_labels; get_proposals uses decision='proposed' |
| Pipeline orchestrator | `src/pipeline/pipeline.py` | ✅ Complete | Stage sequencing only; no SQL; no argparse |
| Place fetcher | `src/pipeline/fetch_places.py` | ✅ Complete | logainm API → DB direct write or CSV export |
| Place seeder | `src/pipeline/seed_places.py` | ✅ Complete | CSV → place_authority; idempotent |
| Place resolution | `src/pipeline/place_resolution.py` | ✅ Complete | v2.0 — authority-based Jaro-Winkler matching |
| Household inference | `src/pipeline/household_inference.py` | ✅ Complete | Census role-pair rules → Person/Relationship/Event conclusions |
| Census feature extractor | `src/pipeline/features/census.py` | ✅ Complete | Name, birth year, place_id, spouse/child/sibling names |
| Cross-census linkage | `src/pipeline/linkage.py` | ✅ Complete | Splink DuckDBAPI; merge contract; spouse/child/sibling comparisons |
| Event consensus | `src/pipeline/scoring.py` | ✅ Complete | rebuild_consensus — is_primary arbitration by plurality vote |
| Debug logging | `src/pipeline/debug.py` | ✅ Complete | Linkage and consensus debug log writer |
| Validator | `src/pipeline/validator.py` | ✅ Complete | R40–R46 genealogical constraint rules |
| Service layer | `src/service.py` | 🚫 Removed | Moved to future_ideas.md; focus shifted to analysis pipeline |
| Test suite | `tests/test_place_authority.py` | ✅ 33/33 passing | Place authority: normalisation, CSV, DB, resolution, hierarchy |

**Verified against real data (Tullynaught DED):**
- Tullynaught DED: 1 DED + 33 townlands loaded; 17 townlands correctly store NULL barony/civil_parish[span_0](start_span)[span_0](end_span)
- Census 1901, 1911, and 1926 NAI downloads ingest correctly[span_1](start_span)[span_1](end_span)
- Place resolution matches "Straniss" → "Straness" via Jaro-Winkler[span_2](start_span)[span_2](end_span)
- Cross-census linkage first test run: 3881 persons across 3 sources; 264 auto-committed at mean score 0.918; 3291 proposals queued[span_3](start_span)[span_3](end_span)
- 16 merged pairs with birth year delta > 5 identified in first run (test DB wiped; will retest with relationship features)[span_4](start_span)[span_4](end_span)

**Development environment:** VSCode with GitHub integration. Repository: https://github.com/mjsmulligan/irish-genealogy-research[span_5](start_span)[span_5](end_span)

**Housekeeping:** `genealogy.db` should be removed from git tracking — run `git rm --cached genealogy.db`.[span_6](start_span)[span_6](end_span)

---

## 2. Workflow

```bash
# 1. Initialise fresh database
python -m src.cli init

# 2. Seed place authority for target area (logainm API)
python -m src.cli fetch-places --logainm-id 111482 --db genealogy.db

# 3. Ingest census records (repeat per source)
python -m src.cli ingest --source 3 --file 1901_Tullynaught.csv
python -m src.cli ingest --source 4 --file 1911_Tullynaught.csv
python -m src.cli ingest --source 5 --file 1926_Tullynaught.csv

# 4. Full post-ingest pipeline (all stages, all sources)
python -m src.cli reconstruct

# Or explicit stages:
python -m src.cli place-resolve       # stage 2 — all unresolved place strings
python -m src.cli household           # stage 3 — all sources
python -m src.cli link                # stage 4 — cross-census linkage
python -m src.cli score-evidence      # stage 5 — rebuild event consensus

# 5. Inspect and validate
python -m src.cli summary
python -m src.cli validate
