# Genealogy Research Assistant (GRA) — Project Roadmap

*May 2026 — v1.3*

---

## 1. Current State

### Documentation

| Document | Version | Status | Notes |
|---|---|---|---|
| `docs/conceptual_model.md` | v2.2 | ✅ Complete | Three-layer architecture, ten first-class objects |
| `docs/data_dictionary.md` | v2.4 | ✅ Complete | All fields, controlled vocabularies, full NAI census role mapping |
| `docs/repositories.md` | v1.4 | ✅ Complete | Sources 3 and 5 corrected against actual NAI download schemas; census_night added |
| `docs/validation_rules.md` | v2.6 | ✅ Complete | R38 updated for nullable score |
| `docs/database_schema.md` | v2.6 | ✅ Complete | Score/score_version nullable; migration script added |
| `docs/reconstruction_algorithms.md` | v1.1 | ✅ Complete | Fellegi-Sunter, Jaro-Winkler, constraint application, expanded role-pair rules |
| `docs/genealogical_constraints.md` | v1.2 | ✅ Complete | 22 GC-coded constraints (GC01–GC22) |
| `docs/service_api.md` | v1.0 | ✅ Complete | Service layer API, research scope, pipeline state |
| `docs/session_bootstrap.md` | v1.0 | ✅ Complete | Ingest and update knowledge session protocols |
| `ROADMAP.md` | v1.3 | ✅ This document | — |

### Implementation

| Module | File(s) | Status | Notes |
|---|---|---|---|
| Database layer | `src/db.py` | ✅ Complete | `open_db()`, `init_db()`, `build_record_url()`, Census 1901/1911/1926 NAI ingest, `print_summary()`, CLI. Census date bug fixed (1901/1926 were using 1911 date). `ingest_census_1911` renamed to `ingest_census`. 1926 normaliser corrected against actual NAI schema. |
| Schema DDL | `src/db/schema.sql` | ✅ Complete | v2.6 — score/score_version nullable on all four linkage junction tables |
| Seed data | `src/db/seed.sql` | ✅ Complete | 12 sources and 7 repositories |
| Migration | `src/db/migrations/migrate_25_to_26.sql` | ✅ Complete | Converts v2.5 → v2.6; sentinel (0.0, '') rows converted to (NULL, NULL) |
| Place resolution | `src/reconstruction/place_resolution.py` | ✅ Complete | Townland normalisation, Jaro-Winkler clustering, auto-commit to Place conclusions |
| Household inference | `src/reconstruction/household_inference.py` | ✅ Complete | Census role-pair rules → Person/Relationship/Event conclusions |
| Migrations | `src/db/migrations/` | ✅ v2.5→v2.6 | `migrate_25_to_26.sql` added this session |
| Validator | `src/validator.py` | 🔜 Pending | All 46 rules specified; implementation pending |
| Cross-census linkage | `src/reconstruction/` | 🔜 Next | Splink person linkage across 1901/1911/1926; blocked on OD-04 |
| Service layer | `src/service.py` | 🔜 Pending | `service_api.md` v1.0 complete; implementation pending |
| Test suite | `tests/` | 🔜 Pending | NAI schema header CSVs added (1901, 1911, 1926) as authoritative schema references; test suite not yet written |

**Verified against real data:** Census 1901, 1911, and 1926 NAI downloads for Tullynaught DED can be ingested through the same census ingest pipeline. Reconstruction pipeline tested: place resolution and household inference produce correct conclusion-layer output from census evidence. Census night dates corrected to 1901-03-31, 1911-04-02, 1926-04-18.

**Development environment:** VSCode with GitHub integration in place. Repository is public at https://github.com/mjsmulligan/irish-genealogy-research.

**Housekeeping item:** `genealogy.db` is currently committed to the repository. It should be removed and added to `.gitignore`. The `.gitignore` already lists `genealogy.db` but the file was committed before the ignore rule took effect — run `git rm --cached genealogy.db` to untrack it without deleting the local file.

---

## 2. Release Plan

GRA is developed in releases scoped by source type.

### Release 1 — Full census pipeline (1901, 1911, 1926)

The three NAI census sources are structurally identical and handled by the same inference engine. Release 1 is complete when all three census years can be ingested, reconstructed, and linked into a unified conclusion layer for a target community.

**Milestones:**

| # | Milestone | Status |
|---|---|---|
| R1-1 | Place resolution + household inference | ✅ Complete |
| R1-2 | Cross-census Splink person linkage (1901↔1911↔1926) | 🔜 Next — blocked on OD-04 |
| R1-3 | Validator (R40–R46 genealogical constraint rules) | 🔜 Pending |
| R1-4 | Person Browser basics (source coverage, merge error flags) | 🔜 Pending |

### Release 2 — Civil registration and parish registers

Civil registration sources (birth, marriage, death) and Catholic parish registers share a role vocabulary that overlaps heavily with the census event roles. Release 2 adds source-specific inference modules and refactors the shared commit logic into `src/reconstruction/core.py`.

**Planned modules:**

- `src/reconstruction/core.py` — shared Person/Relationship/Event commit logic extracted from `household_inference.py`
- `src/reconstruction/registration_inference.py` — civil birth, marriage, death registration
- `src/reconstruction/parish_inference.py` — Catholic parish register (baptism, marriage, burial)

### Release 3 and beyond

Land records (Griffith's Valuation, Tithe Applotment), military sources, folklore collection, service layer, consumer front ends.

---

## 3. Work Queue

Ordered by dependency. Items within a tier can proceed in parallel.

### Tier 1 — Specification layer ✅ Complete

All specification documents are complete.

### Tier 2 — Foundation implementation ✅ Complete

All foundation modules implemented and verified against Tullynaught test data.

### Tier 3 — Reconstruction pipeline (census)

**Place resolution + household inference** ✅ Complete.

**Cross-census Splink linkage** 🔜 — next implementation priority. Blocked on OD-04 (Splink backend decision). Once OD-04 is resolved, this is the next milestone (R1-2).

### Tier 4 — Validation

**`src/validator.py`** — all 46 rules (R01–R46). Entry points: `DataStore.validate()`, `DataStore.validate_object()`, `DataStore.validate_genealogical(person_id)`. Can now be calibrated against Tullynaught reconstruction output.

**`tests/`** — test suite covering all five validation categories and Python-only rules. NAI schema CSVs in `tests/` provide the authoritative column reference for ingest tests.

### Tier 5 — Service layer

**`src/service.py`** — `ResearchService` class with all methods defined in `service_api.md` v1.0. Depends on reconstruction pipeline being stable.

### Tier 6 — Consumers

**Claude consumer** — structured research sessions via the service API using `session_bootstrap.md` protocols.

**Lovable UI** — web front end for researcher interaction. Depends on service layer.

**MCP server** — agent access to the knowledge base. Future work once service layer is stable.

---

## 4. Open Decisions

### OD-02 — Derived confidence function

The current implementation uses a provisional placeholder (confidence = `low` / `medium` / `high` based on record count alone). The actual derivation function — weighting mean score, record count, and source diversity — is deferred until calibration data is available.

**Status:** Now unblocked — Tullynaught 1901, 1911, and 1926 are all ingested and reconstructed, providing real multi-source conclusion data to calibrate against. Revisit after cross-census Splink linkage produces scored person linkages.

---

### OD-04 — Splink backend compatibility

*Blocks: cross-census person linkage (R1-2)*

`reconstruction_algorithms.md` §9.1 specifies a Splink configuration sketch using `DuckDBAPI`. The project database is SQLite. The decision is whether Splink operates directly on the SQLite file via `SQLiteAPI` or loads data into an in-process DuckDB instance for linkage workloads and writes results back.

**Options:**

- **`SQLiteAPI`** — Splink operates directly on `genealogy.db`. Simpler architecture, no data movement. Performance limitations on large datasets but likely adequate at townland scale.
- **`DuckDBAPI`** — Splink loads feature data into an in-memory DuckDB instance. Better performance, slightly more complex: requires an ETL step to extract feature dictionaries from SQLite into a DataFrame before Splink runs, and a write-back step to commit scored linkages to SQLite.

**Recommendation:** Start with `SQLiteAPI`. Townland-scale datasets (hundreds to low thousands of Records) are well within SQLite's capability. If performance is inadequate after testing, migrate to `DuckDBAPI` — the linkage logic is the same either way, only the backend changes. Decision needed before beginning R1-2 implementation.

**Status:** Decision pending. No blocker other than making the call.

---

## 5. Version History

| Version | Date | Change |
|---|---|---|
| 1.0 | May 2026 | Initial ROADMAP |
| 1.1 | May 2026 | Tier 1 and Tier 2 marked complete. Updated implementation status with Tullynaught 1911 results. Removed OD-03 (narrative architecture) from active decisions. |
| 1.2 | May 2026 | Place resolution and household inference implemented (R1-1 complete). Added Release Plan section. Restructured work queue. Added cross-census Splink linkage as next milestone (R1-2). |
| 1.3 | May 2026 | Schema v2.6: OD-01 resolved (score nullable). Census date bug fixed. 1926 normaliser corrected. `repositories.md` v1.4 with Sources 3 and 5 corrected against actual NAI schemas. Migration script `migrate_25_to_26.sql` added. VSCode/GitHub setup noted. `genealogy.db` housekeeping item flagged. OD-02 noted as now unblocked. OD-04 recommendation added (start with SQLiteAPI). |

---

*This document should be updated at the start of each working session to reflect progress and any new decisions or open questions.*
