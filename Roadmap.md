# Genealogy Research Assistant (GRA) — Project Roadmap

*June 2026 — v1.5*

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
| `ROADMAP.md` | v1.5 | ✅ This document | — |

### Implementation

| Module | File(s) | Status | Notes |
|---|---|---|---|
| Database layer | `src/db.py` | ✅ Complete | Schema v2.8; explicit `place-resolve`, `household`, `link` CLI commands added; `reconstruct` retained as convenience |
| Schema DDL | `src/db/schema.sql` | ✅ Complete | v2.8 — RecordedEvent merged; junction tables reduced to 5 |
| Seed data | `src/db/seed.sql` | ✅ Complete | 12 sources, 8 repositories |
| Migration | `src/db/migrations/migrate_27_to_28.sql` | ✅ Complete | Merges recorded_event into record; drops redundant junction tables |
| Place fetcher | `src/fetch_places.py` | ✅ Complete | logainm API → DB direct write or CSV export |
| Place seeder | `src/seed_places.py` | ✅ Complete | CSV → place_authority; idempotent |
| Place resolution | `src/reconstruction/place_resolution.py` | ✅ Complete | v2.0 — authority-based Jaro-Winkler matching |
| Household inference | `src/reconstruction/household_inference.py` | ✅ Complete | Census role-pair rules → Person/Relationship/Event conclusions |
| Census feature extractor | `src/reconstruction/features/census.py` | ✅ Complete | Name, birth year, place_id, **spouse name, child names, sibling names** (relationship features added) |
| Cross-census linkage | `src/reconstruction/linkage.py` | ✅ Complete | Splink DuckDBAPI; merge contract; **spouse/child/sibling comparisons added**; first test run completed |
| Validator | `src/validator.py` | ✅ Complete | R40–R46 genealogical constraint rules implemented |
| Service layer | `src/service.py` | 🔜 Pending | `service_api.md` v1.0 complete; flag/lead tables needed first |
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
python -m src.db init

# 2. Seed place authority for target area (logainm API)
python -m src.fetch_places --logainm-id 111482 --db genealogy.db

# 3. Ingest census records (repeat per source)
python -m src.db ingest --source 3 --file 1901_Tullynaught.csv
python -m src.db ingest --source 4 --file 1911_Tullynaught.csv
python -m src.db ingest --source 5 --file 1926_Tullynaught.csv

# 4. Per-source reconstruction (place resolution + household inference)
python -m src.db reconstruct --source 3   # convenience: stages 2+3
python -m src.db reconstruct --source 4
python -m src.db reconstruct --source 5

# Or explicit stages:
python -m src.db place-resolve            # stage 2 — all unresolved strings
python -m src.db household --source 4    # stage 3 — one source at a time

# 5. Cross-census linkage (run once all sources are reconstructed)
python -m src.db link

# 6. Inspect
python -m src.db summary
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
| R1-4 | Person Browser basics (source coverage, merge error flags) | 🔜 Next — depends on service layer |

### Release 2 — Civil registration and parish registers

Civil registration sources (birth, marriage, death) and Catholic parish registers. Planned modules:
- `src/reconstruction/core.py` — shared Person/Relationship/Event commit logic extracted from `household_inference.py`
- `src/reconstruction/registration_inference.py`
- `src/reconstruction/parish_inference.py`

### Release 3 and beyond

Land records, military sources, folklore, service layer, consumer front ends.

---

## 4. Work Queue

### Tier 3 — Reconstruction pipeline ← current

**Linkage quality iteration** 🔜 — following first test run:
- Term-frequency adjustment for `surname_norm` — deferred until 3–4 DEDs ingested for a representative frequency distribution. High-frequency surnames at Tullynaught scale (Graham 284, Cassidy 206) are unrepresentative of the broader dataset.
- Review 190 near-commit proposals (score 0.80–0.85) after relationship features run — if ≥80% correct, consider lowering AUTO_COMMIT_THRESHOLD to 0.82
- Monitor birth year delta violations — R1 test had 16 merges with delta > 5; relationship features should reduce this

**flag and lead tables** 🔜 — needed before service layer. DDL specified in `service_api.md` §10.3.

### Tier 4 — Service layer

`src/service.py` — ResearchService class. Depends on flag/lead tables being added to schema.

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
| 1.5 | June 2026 | Schema v2.8: RecordedEvent merged into Record; junction tables reduced from 9 to 5. R1-2 and R1-3 complete. Linkage first test run completed (3881 persons, 264 merged). Relationship features added to census feature extractor (spouse name, child names, sibling names via conclusion layer). Explicit `place-resolve`, `household`, `link` CLI commands added to `db.py`; `reconstruct` retained as convenience. OD-04 resolved (DuckDBAPI). TF adjustment deferred to multi-DED scale. |
