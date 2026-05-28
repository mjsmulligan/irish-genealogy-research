# Genealogy Research Assistant (GRA) — Project Roadmap

*May 2026 — v1.4*

---

## 1. Current State

### Documentation

| Document | Version | Status | Notes |
|---|---|---|---|
| `docs/conceptual_model.md` | v2.2 | ✅ Complete | Three-layer architecture, ten first-class objects |
| `docs/data_dictionary.md` | v2.4 | ✅ Complete | All fields, controlled vocabularies, full NAI census role mapping |
| `docs/repositories.md` | v1.4 | ✅ Complete | Sources 3 and 5 corrected against actual NAI download schemas |
| `docs/validation_rules.md` | v2.6 | ✅ Complete | R40–R46 genealogical constraint rules; R38 updated for nullable score |
| `docs/database_schema.md` | v2.6 | ✅ Complete | Score/score_version nullable; migration script added |
| `docs/reconstruction_algorithms.md` | v1.1 | ✅ Complete | Fellegi-Sunter, Jaro-Winkler, constraint application, expanded role-pair rules |
| `docs/genealogical_constraints.md` | v1.2 | ✅ Complete | 22 GC-coded constraints (GC01–GC22) |
| `docs/service_api.md` | v1.0 | ✅ Complete | Service layer API, research scope, pipeline state |
| `docs/session_bootstrap.md` | v1.0 | ✅ Complete | Ingest and update knowledge session protocols |
| `ROADMAP.md` | v1.4 | ✅ This document | — |

### Implementation

| Module | File(s) | Status | Notes |
|---|---|---|---|
| Database layer | `src/db.py` | ✅ Complete | `open_db()`, `init_db()`, `build_record_url()`, Census 1901/1911/1926 NAI ingest, `print_summary()`, CLI. Ingest now triggers full pipeline automatically. |
| Schema DDL | `src/db/schema.sql` | ✅ Complete | v2.6 — score/score_version nullable on all four linkage junction tables |
| Seed data | `src/db/seed.sql` | ✅ Complete | 12 sources and 7 repositories |
| Migration | `src/db/migrations/migrate_25_to_26.sql` | ✅ Complete | Converts v2.5 → v2.6 |
| Place resolution | `src/reconstruction/place_resolution.py` | ✅ Complete | Townland normalisation, Jaro-Winkler clustering, auto-commit to Place conclusions |
| Household inference | `src/reconstruction/household_inference.py` | ✅ Complete | Census role-pair rules → Person/Relationship/Event conclusions |
| Census feature extractor | `src/reconstruction/features/census.py` | ✅ Complete | Flat feature DataFrame for Splink from census Person conclusions |
| Cross-census linkage | `src/reconstruction/linkage.py` | ✅ Implemented — test pending | Splink DuckDBAPI, auto-commit ≥0.85, propose 0.30–0.85, lower person_id merge |
| Validator | `src/validator.py` | ✅ Complete | R40–R46 genealogical constraint rules; `validate()`, `validate_object()`, `validate_genealogical()` |
| Service layer | `src/service.py` | 🔜 Pending | `service_api.md` v1.0 complete; implementation pending |
| Test suite | `tests/` | 🔜 Pending | NAI schema header CSVs in place as authoritative schema references |

**Verified against real data:** Census 1901, 1911, and 1926 NAI downloads for Tullynaught DED ingested (715 records, 3,167 recorded persons). Cross-census linkage implementation complete; end-to-end pipeline test pending.

**Development environment:** VSCode with GitHub integration. Repository: https://github.com/mjsmulligan/irish-genealogy-research

**Housekeeping item:** `genealogy.db` should be untracked — run `git rm --cached genealogy.db` if not already done.

---

## 2. Release Plan

### Release 1 — Full census pipeline (1901, 1911, 1926)

| # | Milestone | Status |
|---|---|---|
| R1-1 | Place resolution + household inference | ✅ Complete |
| R1-2 | Cross-census Splink person linkage (1901↔1911↔1926) | ✅ Implemented — pipeline test pending |
| R1-3 | Validator (R40–R46 genealogical constraint rules) | ✅ Complete |
| R1-4 | Person Browser basics (source coverage, merge error flags) | 🔜 Next |

### Release 2 — Civil registration and parish registers

- `src/reconstruction/core.py` — shared Person/Relationship/Event commit logic extracted from `household_inference.py`
- `src/reconstruction/features/registration.py` — civil birth, marriage, death registration feature extractor
- `src/reconstruction/features/parish.py` — Catholic parish register feature extractor
- `src/reconstruction/registration_inference.py` — civil registration inference module
- `src/reconstruction/parish_inference.py` — parish register inference module

### Release 3 and beyond

Land records (Griffith's Valuation, Tithe Applotment), military sources, folklore collection, service layer, consumer front ends.

---

## 3. Work Queue

### Immediate — pipeline testing

Test the cross-census linkage pipeline against Tullynaught:

```bash
rm genealogy.db
python -m src.db init
python -m src.db ingest --source 4 --file tests/1911_Tullynaught.csv
python -m src.db ingest --source 3 --file tests/1901_Tullynaught.csv
python -m src.db ingest --source 5 --file tests/1926_Tullynaught.csv
python -m src.db summary
```

Expected: person count rises on first ingest, rises less steeply on subsequent ingests as cross-census merges reduce duplicates. Merge log should show genealogically plausible matches. Splink threshold tuning may be needed based on results.

### Tier 4 — Person Browser basics (R1-4)

Source coverage display per Person (GC08–GC11 eligibility logic) and merge error flag surfacing (R40–R46 warnings). Entry point: `DataStore.validate_genealogical(person_id)` already implemented.

### Tier 5 — Service layer

`src/service.py` — `ResearchService` class with all methods defined in `service_api.md` v1.0.

### Tier 6 — Test suite

`tests/` — covering all five validation categories, ingest pipeline, and reconstruction stages.

### Tier 7 — Consumers

Claude consumer, Lovable UI, MCP server — all depend on service layer.

---

## 4. Open Design Decisions

### OD-02 — Derived confidence function

The current implementation uses a provisional placeholder (confidence = `low` / `medium` / `high` based on record count alone). The actual derivation function — weighting mean score, record count, and source diversity — is deferred pending calibration against real scored linkage data.

**Status:** Unblocked once cross-census Splink linkage produces real score distributions from Tullynaught test run.

---

## 5. Resolved Decisions

| ID | Decision |
|---|---|
| OD-01 | Score nullable on linkage junction tables — null represents manually-asserted linkages |
| OD-03 | Narrative output is out of scope — future consumer application |
| OD-04 | Splink backend = DuckDBAPI — in-memory per linkage run, results written back to genealogy.db; SQLite remains persistent store |

---

## 6. Version History

| Version | Date | Change |
|---|---|---|
| 1.0 | May 2026 | Initial ROADMAP |
| 1.1 | May 2026 | Tier 1 and Tier 2 marked complete. Tullynaught 1911 results. OD-03 resolved. |
| 1.2 | May 2026 | R1-1 complete. Release Plan added. Cross-census linkage as R1-2. |
| 1.3 | May 2026 | Schema v2.6. OD-01 resolved. Census date bug fixed. 1926 normaliser corrected. Migration script added. OD-04 recommendation added. |
| 1.4 | May 2026 | R1-2 implemented (cross-census Splink linkage, DuckDBAPI, lower-id merge). R1-3 complete (validator R40–R46). Ingest now triggers full pipeline automatically — reconstruct is repair-mode only. Linkage architecture: source-specific feature extractors in src/reconstruction/features/, generic pipeline in linkage.py. splink>=4.0 added to requirements.txt. OD-04 resolved (DuckDBAPI confirmed at ~300k person scale). |

---

*This document should be updated at the start of each working session to reflect progress and any new decisions or open questions.*
