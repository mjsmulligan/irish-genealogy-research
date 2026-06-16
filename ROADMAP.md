# Genealogy Research Assistant (GRA) — Project Roadmap

*16 June 2026 — v1.6*

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
| `ROADMAP.md` | v1.6 | ✅ This document | — |

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
| Service layer | `src/service.py` | 🔜 Pending | Stub in place; flag/lead tables needed first (service_api.md §10.3) |
| Test suite | `tests/test_place_authority.py` | ✅ 33/33 passing | Place authority: normalisation, CSV, DB, resolution, hierarchy |

**Verified against real data (Tullynaught DED):**
- Tullynaught DED: 1 DED + 33 townlands loaded; 17 townlands correctly store NULL barony/civil_parish
- Census 1901, 1911, and 1926 NAI downloads ingest correctly
- Place resolution matches "Straniss" → "Straness" via Jaro-Winkler
- Cross-census linkage first test run: 3881 persons across 3 sources; 264 auto-committed at mean score 0.918; 3291 proposals queued
- 16 merged pairs with birth year delta > 5 identified in first run (test DB wiped; will retest with relationship features)

**Development environment:** VSCode with GitHub integration. Repository: https://github.com/mjsmulligan/irish-genealogy-research

**Housekeeping:** `genealogy.db` should be removed from git tracking — run `git rm --cached genealogy.db`.

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
```

---

## 3. Release Plan

### Release 1 — Full census pipeline (1901, 1911, 1926)

| # | Milestone | Status |
|---|---|---|
| R1-0 | Place authority seeding (logainm API + CSV) | ✅ Complete |
| R1-1 | Place resolution + household inference | ✅ Complete |
| R1-2 | Cross-census Splink person linkage (1901↔1911↔1926) | ✅ Complete — first test run done; relationship features added |
| R1-3 | Validator (R40–R46 genealogical constraint rules) | ✅ Complete |
| R1-3a | Codebase refactor (cli/db/ingest/dal/pipeline separation) | ✅ Complete — 16 June 2026 |
| R1-4 | Person Browser basics (source coverage, merge error flags) | 🔜 Next — depends on service layer + flag/lead schema |

### Release 2 — Civil registration and parish registers

Civil registration sources (birth, marriage, death) and Catholic parish registers. Planned modules:
- `src/pipeline/core.py` — shared Person/Relationship/Event commit logic extracted from `household_inference.py`
- `src/pipeline/registration_inference.py`
- `src/pipeline/parish_inference.py`

### Release 3 and beyond

Land records, military sources, folklore, service layer, consumer front ends.

---

## 4. Work Queue

### Tier 3a — Service layer prerequisites

**flag and lead tables** 🔜 — DDL specified in `service_api.md` §10.3. Required before service layer can be implemented.

**`service_api.md` §6.1 correction** 🔜 — `get_proposals` return shape documents `record_id` but `training_labels` stores person-to-person proposals. Spec needs updating to reflect `proposal_type='person_person'` with `person_id_2`.

**`review.py` fix** 🔜 (deferred, separate session) — must query `training_labels WHERE decision='proposed'`. The correct query is now implemented in `src/dal/training_repo.get_proposals()`.

### Tier 3b — Linkage quality iteration

- Term-frequency adjustment for `surname_norm` — deferred until 3–4 DEDs ingested
- Review 190 near-commit proposals (score 0.80–0.85) after relationship features run — if ≥80% correct, consider lowering AUTO_COMMIT_THRESHOLD to 0.82
- Monitor birth year delta violations — R1 test had 16 merges with delta > 5

### Tier 4 — Service layer

`src/service.py` — ResearchService class. Stub in place. Implement once flag/lead tables are in schema.

### Tier 5 — Consumers

Claude consumer, Lovable UI, MCP server.

---

## 5. Open Decisions

### OD-02 — Derived confidence function

Provisional placeholder (record count → low/medium/high) in place. Real multi-source scored linkages now available after R1-2. Revisit after reviewing linkage quality with relationship features.

---

## 6. Version History

| Version | Date | Change |
|---|---|---|
| 1.0 | May 2026 | Initial ROADMAP |
| 1.1 | May 2026 | Tier 1 and 2 complete; Tullynaught 1911 tested |
| 1.2 | May 2026 | R1-1 complete; Release Plan added; R1-2 as next milestone |
| 1.3 | May 2026 | Schema v2.6 (OD-01 resolved); census date fixes; 1926 normaliser corrected; migration added |
| 1.4 | May 2026 | Place authority redesign complete. PlaceAuthority added to foundational layer (flat schema, logainm.ie source). `src/fetch_places.py` and updated `src/seed_places.py` implemented. `src/reconstruction/place_resolution.py` v2.0. Schema v2.7. 33 tests passing. |
| 1.5 | June 2026 | Schema v2.8: RecordedEvent merged into Record; junction tables reduced from 9 to 5. R1-2 and R1-3 complete. Linkage first test run completed (3881 persons, 264 merged). Relationship features added to census feature extractor. Explicit `place-resolve`, `household`, `link` CLI commands added. OD-04 resolved (DuckDBAPI). TF adjustment deferred to multi-DED scale. |
| 1.6 | 16 June 2026 | Codebase refactor complete (R1-3a). `src/reconstruction/` retired — replaced by `src/pipeline/`. `src/db.py` retired — replaced by `src/db/db.py` (connection only) and `src/cli.py` (sole entry point). `src/ingest/census.py` extracted. `src/dal/` created (6 repos; training_repo.get_proposals fix). `src/pipeline/pipeline.py` created as stage orchestrator. `score-evidence` and `validate` CLI commands added. `jellyfish` replaced by `rapidfuzz` in requirements.txt. |
