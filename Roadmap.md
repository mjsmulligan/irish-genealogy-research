# Genealogy Research Assistant (GRA) — Project Roadmap

*May 2026 — v1.4*

---

## 1. Current State

### Documentation

| Document | Version | Status | Notes |
|---|---|---|---|
| `docs/conceptual_model.md` | v2.3 | ✅ Complete | PlaceAuthority added to foundational layer; flat hierarchy design |
| `docs/data_dictionary.md` | v2.5 | ✅ Complete | PlaceAuthority flat schema; place_type vocabulary; place_authority source type |
| `docs/repositories.md` | v1.5 | ✅ Complete | Repository 8 (logainm.ie) and Source 13 (place_authority) added |
| `docs/validation_rules.md` | v2.6 | ✅ Complete | R38 updated for nullable score |
| `docs/database_schema.md` | v2.7 | ✅ Complete | PlaceAuthority flat table; place_membership retired; migration v2.6→v2.7 |
| `docs/reconstruction_algorithms.md` | v1.1 | ✅ Complete | Fellegi-Sunter, Jaro-Winkler, constraint application |
| `docs/genealogical_constraints.md` | v1.2 | ✅ Complete | 22 GC-coded constraints |
| `docs/service_api.md` | v1.0 | ✅ Complete | Service layer API |
| `docs/session_bootstrap.md` | v1.0 | ✅ Complete | Ingest and update knowledge session protocols |
| `ROADMAP.md` | v1.4 | ✅ This document | — |

### Implementation

| Module | File(s) | Status | Notes |
|---|---|---|---|
| Database layer | `src/db.py` | ✅ Complete | Schema v2.7; `seed-places` CLI updated to single `--file` arg |
| Schema DDL | `src/db/schema.sql` | ✅ Complete | v2.7 — `place_authority` flat table; `place` retired; `place_authority` source type |
| Seed data | `src/db/seed.sql` | ✅ Complete | 12 sources, 7 repositories, Repository 8 (logainm.ie) |
| Migration | `src/db/migrations/migrate_26_to_27.sql` | ✅ Complete | Migrates place → place_authority; drops place_membership |
| Place fetcher | `src/fetch_places.py` | ✅ Complete | logainm API → DB direct write or CSV export; CSV round-trip; manual entry support |
| Place seeder | `src/seed_places.py` | ✅ Complete | CSV → place_authority; idempotent; delegates to fetch_places |
| Place resolution | `src/reconstruction/place_resolution.py` | ✅ Complete | v2.0 — authority-based matching; unresolved flagging; hierarchy queries |
| Household inference | `src/reconstruction/household_inference.py` | ✅ Complete | Census role-pair rules → Person/Relationship/Event conclusions |
| Test suite | `tests/test_place_authority.py` | ✅ 33/33 passing | Covers: normalisation, CSV load/validation, DB insert, idempotency, resolution, hierarchy queries, real CSV round-trip |
| Validator | `src/validator.py` | 🔜 Pending | All 46 rules specified |
| Cross-census linkage | `src/reconstruction/linkage.py` | 🔜 Next | Splink person linkage 1901↔1911↔1926 |
| Service layer | `src/service.py` | 🔜 Pending | `service_api.md` v1.0 complete |

**Verified against real data:**
- Tullynaught DED logainm fetch: 1 DED + 33 townlands, all loaded correctly
- 17 townlands correctly store NULL barony/civil_parish (genuine logainm gap, not a bug)
- 16 townlands correctly linked to Drumhome civil parish (civil_parish_id=785)
- Census 1901, 1911, and 1926 NAI downloads for Tullynaught ingest correctly
- Place resolution matches "Straniss" → "Straness" (logainm 14300) via Jaro-Winkler

**Development environment:** VSCode with GitHub integration. Repository: https://github.com/mjsmulligan/irish-genealogy-research

**Housekeeping:** `genealogy.db` should be removed from git tracking — run `git rm --cached genealogy.db`.

---

## 2. Workflow: Place Authority First

The introduction of PlaceAuthority changes the standard workflow. Place seeding is now a prerequisite step before any record ingest:

```bash
# 1. Initialise fresh database
python -m src.db init

# 2. Seed place authority for target area (logainm API)
python -m src.fetch_places --logainm-id 111482 --db genealogy.db

# 2a. Alternative: seed from CSV (for manual entries or pre-fetched data)
python -m src.db seed-places --file tullynaught_places.csv

# 3. Ingest census records
python -m src.db ingest --source 3 --file 1901_Tullynaught.csv
python -m src.db ingest --source 4 --file 1911_Tullynaught.csv
python -m src.db ingest --source 5 --file 1926_Tullynaught.csv

# 4. Reconstruct (place resolution + household inference)
python -m src.db reconstruct --source 4

# 5. Inspect
python -m src.db summary
```

---

## 3. Release Plan

### Release 1 — Full census pipeline (1901, 1911, 1926)

| # | Milestone | Status |
|---|---|---|
| R1-0 | Place authority seeding (logainm API + CSV) | ✅ Complete |
| R1-1 | Place resolution + household inference | ✅ Complete |
| R1-2 | Cross-census Splink person linkage (1901↔1911↔1926) | 🔜 Next |
| R1-3 | Validator (R40–R46 genealogical constraint rules) | 🔜 Pending |
| R1-4 | Person Browser basics (source coverage, merge error flags) | 🔜 Pending |

### Release 2 — Civil registration and parish registers

Civil registration sources (birth, marriage, death) and Catholic parish registers. Planned modules:
- `src/reconstruction/core.py` — shared Person/Relationship/Event commit logic
- `src/reconstruction/registration_inference.py`
- `src/reconstruction/parish_inference.py`

### Release 3 and beyond

Land records, military sources, folklore, service layer, consumer front ends.

---

## 4. Work Queue

### Tier 3 — Reconstruction pipeline ← current

**Cross-census Splink linkage (R1-2)** 🔜 — next implementation priority.

- Resolve OD-04 (SQLiteAPI vs DuckDBAPI) before starting
- Feature extraction for census: name, birth year, place_id (now a stable authority ID — better Splink signal than before), occupation, co-persons
- place_id from place_authority gives Splink a clean, stable blocking key

**Validator (R1-3)** 🔜 — R40–R46 implementation against real Tullynaught data.

### Tier 4 — Service layer

`src/service.py` — ResearchService class. Depends on reconstruction pipeline being stable.

### Tier 5 — Consumers

Claude consumer, Lovable UI, MCP server.

---

## 5. Open Decisions

### OD-02 — Derived confidence function

Provisional placeholder (record count → low/medium/high) in place. Now unblocked — real multi-source scored linkages available after cross-census Splink run. Revisit after R1-2.

### OD-04 — Splink backend (SQLiteAPI vs DuckDBAPI)

Blocks R1-2. Recommendation: start with SQLiteAPI for simplicity at townland scale. Migrate to DuckDBAPI only if performance is inadequate. Decision needed before beginning R1-2 implementation.

---

## 6. Version History

| Version | Date | Change |
|---|---|---|
| 1.0 | May 2026 | Initial ROADMAP |
| 1.1 | May 2026 | Tier 1 and 2 complete; Tullynaught 1911 tested |
| 1.2 | May 2026 | R1-1 complete; Release Plan added; R1-2 as next milestone |
| 1.3 | May 2026 | Schema v2.6 (OD-01 resolved); census date fixes; 1926 normaliser corrected; migration added |
| 1.4 | May 2026 | Place authority redesign complete. PlaceAuthority added to foundational layer (flat schema, logainm.ie source). `src/fetch_places.py` and updated `src/seed_places.py` implemented. `src/reconstruction/place_resolution.py` v2.0 (authority-based matching). Schema v2.7. Migration v2.6→v2.7. 33 tests passing against real Tullynaught data. R1-0 milestone added and marked complete. Workflow updated: place seeding now prerequisite before ingest. |
