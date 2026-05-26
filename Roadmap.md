# Genealogy Research Assistant (GRA) — Project Roadmap

*May 2026 — v1.2*

---

## 1. Current State

### Documentation

| Document | Version | Status | Notes |
|---|---|---|---|
| `docs/conceptual_model.md` | v2.2 | ✅ Complete | Three-layer architecture, ten first-class objects |
| `docs/data_dictionary.md` | v2.4 | ✅ Complete | All fields, controlled vocabularies, full NAI census role mapping |
| `docs/repositories.md` | v1.3 | ✅ Complete | 12 sources, 7 repositories, deep link templates |
| `docs/validation_rules.md` | v2.5 | ✅ Complete | 46 rules across 5 categories incl. genealogical constraints |
| `docs/database_schema.md` | v2.5 | ✅ Complete | Full SQLite DDL, indexes, junction tables, scoring |
| `docs/reconstruction_algorithms.md` | v1.1 | ✅ Complete | Fellegi-Sunter, Jaro-Winkler, constraint application, expanded role-pair rules |
| `docs/genealogical_constraints.md` | v1.2 | ✅ Complete | 22 GC-coded constraints (GC01–GC22) |
| `docs/service_api.md` | v1.0 | ✅ Complete | Service layer API, research scope, pipeline state |
| `docs/session_bootstrap.md` | v1.0 | ✅ Complete | Ingest and update knowledge session protocols |
| `ROADMAP.md` | v1.2 | ✅ This document | — |

### Implementation

| Module | File(s) | Status | Notes |
|---|---|---|---|
| Database layer | `src/db.py` | ✅ Complete | `open_db()`, `init_db()`, `build_record_url()`, Census 1901/1911/1926 NAI ingest with 1926 QA-clean field normalization, `print_summary()`, CLI |
| Schema DDL | `src/db/schema.sql` | ✅ Complete | DDL at v2.5 — all tables, indexes, constraints |
| Seed data | `src/db/seed.sql` | ✅ Complete | 12 sources and 7 repositories |
| Place resolution | `src/reconstruction/place_resolution.py` | ✅ Complete | Townland normalisation, Jaro-Winkler clustering, auto-commit to Place conclusions |
| Household inference | `src/reconstruction/household_inference.py` | ✅ Complete | Census role-pair rules → Person/Relationship/Event conclusions |
| Migrations | `src/db/migrations/` | 🔜 Pending | Migration scripts not yet written |
| Validator | `src/validator.py` | 🔜 Pending | All 46 rules specified; implementation pending |
| Cross-census linkage | `src/reconstruction/` | 🔜 Next | Splink person linkage across 1901/1911/1926 |
| Service layer | `src/service.py` | 🔜 Pending | `service_api.md` v1.0 complete; implementation pending |
| Test suite | `tests/` | 🔜 Pending | v1 suite retired; v2.5+ suite not yet written |

**Verified against real data:** Census 1901, 1911 and 1926 NAI downloads for Tullynaught DED can be ingested through the same census ingest pipeline. The 1926 importer preserves QA-clean fields such as `aform_name`, `updated_relationship_to_head`, `updated_age`, `updated_sex`, and `updated_religion`. Reconstruction pipeline tested: place resolution and household inference produce correct conclusion-layer output (persons, relationships, events, places) from census evidence.

---

## 2. Release Plan

GRA is developed in releases scoped by source type.

### Release 1 — Full census pipeline (1901, 1911, 1926)

The three NAI census sources are structurally identical and handled by the same inference engine. Release 1 is complete when all three census years can be ingested, reconstructed, and linked into a unified conclusion layer for a target community.

**Milestones:**

| # | Milestone | Status |
|---|---|---|
| R1-1 | Place resolution + household inference | ✅ Complete |
| R1-2 | Cross-census Splink person linkage (1901↔1911↔1926) | 🔜 Next |
| R1-3 | Validator (R40–R46 genealogical constraint rules) | 🔜 Pending |
| R1-4 | Person Browser basics (source coverage, merge error flags) | 🔜 Pending |

### Release 2 — Civil registration and parish registers

Civil registration sources (birth, marriage, death) and Catholic parish registers share a role vocabulary that overlaps heavily with the census event roles. Release 2 adds source-specific inference modules and refactors the shared commit logic into `src/reconstruction/core.py`.

**Planned modules:**

- `src/reconstruction/core.py` — shared Person/Relationship/Event commit logic extracted from household_inference.py
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

**`src/db/schema.sql`** ✅ — canonical DDL at schema v2.5.

**`src/db/seed.sql`** ✅ — INSERT statements for 12 sources and 7 repositories.

**`src/db.py`** ✅ — `open_db()`, `init_db()`, `build_record_url()`, Census 1901/1911/1926 NAI ingest, `print_summary()`, and CLI entry points (`init`, `ingest`, `summary`, `reconstruct`). Verified against Tullynaught 1911 dataset.

### Tier 3 — Reconstruction pipeline (census)

**`src/reconstruction/place_resolution.py`** ✅ — townland normalisation pipeline, Jaro-Winkler clustering, auto-commit to Place conclusions, idempotent (safe for incremental calls).

**`src/reconstruction/household_inference.py`** ✅ — census role-pair rules from `reconstruction_algorithms.md` §6.1 producing Person, Relationship, and Event conclusions. Handles all census roles including grandchild (Person only, no auto-relationship) and in_law/cousin/niece_nephew (Person only, flagged for researcher reasoning). Idempotent.

**Cross-census Splink linkage** 🔜 — identify that John Mulligan in 1901 and John Mulligan in 1911 are the same Person. This is the next implementation priority. Requires resolving OD-04 (Splink backend) first.

### Tier 4 — Validation

**`src/validator.py`** — all 46 rules (R01–R46). Entry points: `DataStore.validate()`, `DataStore.validate_object()`, `DataStore.validate_genealogical(person_id)`. Genealogical constraint rules (R40–R46) require a populated conclusion layer to be meaningful — can run against Tullynaught reconstruction output for calibration.

**`tests/`** — test suite covering all five validation categories, all ten object types, and the Python-only rules. Genealogical constraint rules require fixture data with known violations.

### Tier 5 — Service layer

**`src/service.py`** — `ResearchService` class with all methods defined in `service_api.md` v1.0. Depends on reconstruction pipeline being stable.

### Tier 6 — Consumers

**Claude consumer** — structured research sessions via the service API using `session_bootstrap.md` protocols.

**Lovable UI** — web front end for researcher interaction. Depends on service layer.

**MCP server** — agent access to the knowledge base. Future work once service layer is stable.

---

## 4. Open Decisions

These are explicitly deferred design questions. Each blocks downstream work until resolved.

### OD-01 — Score nullability for manual assertions

The current schema requires `score REAL NOT NULL DEFAULT 0.0` on all four linkage junction tables. A manually-asserted linkage has no meaningful score — `0.0` is misleading.

**Options:**

- Allow `score` to be nullable. Null means "manually asserted, no algorithm score." `verified = 1` implied for all null-score rows.
- Keep `NOT NULL` with a sentinel value (e.g., `-1.0`). Requires a vocabulary convention and CHECK constraint update.
- Add a separate `assertion_type TEXT` column (`'algorithm'` / `'manual'`) alongside `score`.

**Recommendation pending:** The nullable approach is cleanest semantically. No decision taken.

---

### OD-02 — Derived confidence function

The current implementation uses a provisional placeholder (confidence = `low` / `medium` / `high` based on record count alone). The actual derivation function — weighting mean score, record count, and source diversity — is deferred until Tullynaught data is available for calibration.

**Status:** Placeholder is explicitly labelled as provisional in `reconstruction_algorithms.md` §1.4. Revisit after cross-census linkage produces real multi-source conclusions.

---

### OD-03 — Narrative output architecture

*Resolved: out of scope for GRA platform.*

Narrative output is confirmed as a future consumer application built on top of the GRA service layer, not a platform concern. GRA's focus is ingest, linkage, validation, and conclusions.

---

### OD-04 — Splink backend compatibility

*Blocks: cross-census person linkage*

`reconstruction_algorithms.md` §9.1 specifies a Splink configuration sketch using `DuckDBAPI`. The project database is SQLite. Whether Splink operates directly on the SQLite file via `SQLiteAPI` or loads data into DuckDB for linkage workloads and writes results back needs a concrete decision before cross-census linkage implementation begins.

**Status:** Splink's SQLite backend has performance limitations for large datasets. DuckDB operates in-memory or on separate files. Decision needed before next milestone (R1-2).

---

## 5. Version History

| Version | Date | Change |
|---|---|---|
| 1.0 | May 2026 | Initial ROADMAP — current state, work queue, open decisions, roadmap. Reflects GRA rename and narrative output use case. |
| 1.1 | May 2026 | Tier 1 and Tier 2 marked complete. Updated implementation status table with verified results from Tullynaught 1911 ingest. Updated near/medium-term roadmap. Removed OD-03 (narrative architecture) from active decisions. |
| 1.2 | May 2026 | Place resolution and household inference implemented (R1-1 complete). Added Release Plan section with R1/R2/R3 boundaries. Restructured work queue to reflect reconstruction split into place_resolution.py and household_inference.py. Added cross-census Splink linkage as next milestone (R1-2). Updated implementation table. Noted future core.py refactor for Release 2 source-specific inference modules. |

---

*This document should be updated at the start of each working session to reflect progress and any new decisions or open questions.*
