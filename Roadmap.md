# Genealogy Research Assistant (GRA) — Project Roadmap

*May 2026 — v1.1*

---

## 1. Current State

### Documentation

| Document | Version | Status | Notes |
|---|---|---|---|
| `docs/conceptual_model.md` | v2.2 | ✅ Complete | Three-layer architecture, ten first-class objects |
| `docs/data_dictionary.md` | v2.3 | ✅ Complete | All fields, controlled vocabularies, scoring columns |
| `docs/repositories.md` | v1.2 | ✅ Complete | 12 sources, 7 repositories, deep link templates |
| `docs/validation_rules.md` | v2.5 | ✅ Complete | 46 rules across 5 categories incl. genealogical constraints |
| `docs/database_schema.md` | v2.4 | ✅ Complete | Full SQLite DDL, indexes, junction tables, scoring |
| `docs/reconstruction_algorithms.md` | v1.1 | ✅ Complete | Fellegi-Sunter, Jaro-Winkler, constraint application |
| `docs/genealogical_constraints.md` | v1.2 | ✅ Complete | 22 GC-coded constraints (GC01–GC22) |
| `docs/service_api.md` | v1.0 | ✅ Complete | Service layer API, research scope, pipeline state |
| `docs/session_bootstrap.md` | — | 🔜 Pending | Next priority — see §2 |
| `ROADMAP.md` | v1.0 | ✅ This document | — |

### Implementation

| Module | File | Status | Notes |
|---|---|---|---|
| Database layer | `src/db.py` | ✅ Complete | `open_db()`, `init_db()`, `build_record_url()`, Census 1901/1911 NAI ingest, `print_summary()`, CLI |
| Schema DDL | `src/db/schema.sql` | ✅ Complete | DDL at v2.5 — all tables, indexes, constraints |
| Seed data | `src/db/seed.sql` | ✅ Complete | 12 sources and 7 repositories |
| Migrations | `src/db/migrations/` | 🔜 Pending | Migration scripts not yet written |
| Validator | `src/validator.py` | 🔜 Pending | All 46 rules specified; implementation pending |
| Service layer | `src/service.py` | 🔜 Pending | `service_api.md` v1.0 complete; implementation pending |
| Reconstruction | `src/reconstruction.py` | 🔜 Pending | Algorithms fully specified; implementation pending |
| Linkage | `src/linkage/` | 🔜 Pending | Splink integration, feature extractors, candidate generation |
| Test suite | `tests/` | 🔜 Pending | v1 suite retired; v2.1+ suite not yet written |

**Verified against real data:** Census 1911 NAI download for Tullynaught DED (1,080 persons, 240 households, 31 townlands) ingested cleanly. One parse note (blank relation_to_head mapped to `principal`). Evidence layer populated; conclusion layer awaiting reconstruction pipeline.

---

## 2. Work Queue

Ordered by dependency. Items within a tier can proceed in parallel.

### Tier 1 — Specification layer ✅ Complete

All specification documents are complete. `session_bootstrap.md` v1.0 defines ingest and update knowledge session protocols. Scope narrowed from original design: GRA is a knowledge base platform; research and narrative are future consumer applications.

### Tier 2 — Foundation implementation ✅ Complete

**`src/db/schema.sql`** ✅ — canonical DDL at schema v2.5.

**`src/db/seed.sql`** ✅ — INSERT statements for 12 sources and 7 repositories.

**`src/db.py`** ✅ — `open_db()`, `init_db()`, `build_record_url()`, Census 1901/1911 NAI ingest, `print_summary()`, and CLI entry points (`init`, `ingest`, `summary`). Verified against Tullynaught 1911 dataset.

### Tier 3 — Validation and testing

**`src/validator.py`** — all 46 rules (R01–R46). Entry points: `DataStore.validate()`, `DataStore.validate_object()`, `DataStore.validate_genealogical(person_id)`.

**`tests/`** — test suite covering all five validation categories, all ten object types, and the five Python-only rules (R20, R21, R26, R36, R37). Genealogical constraint rules (R40–R46) require fixture data with known violations.

### Tier 4 — Reconstruction pipeline

**`src/reconstruction.py`** — place resolution, initial construction, incremental linkage, derived confidence, GEDCOM export. Depends on Splink and Jellyfish (`requirements.txt` already includes Jellyfish; Splink to be added).

**`src/linkage/`** — source-specific feature extractors, name normalisation pipeline, name variant table seeding (Appendix A of `reconstruction_algorithms.md`), Splink configuration.

### Tier 5 — Service layer

**`src/service.py`** — `ResearchService` class with all methods defined in `service_api.md` v1.0. Depends on database layer and reconstruction pipeline being stable.

### Tier 6 — Consumers

**Session bootstrap (Claude consumer)** — once `session_bootstrap.md` is complete, Claude can operate as a research assistant via the service API in structured sessions.

**Lovable UI** — web front end for researcher interaction. Depends on service layer being stable.

**MCP server** — agent access to the knowledge base. Future work once service layer is stable. See §4.

---

## 3. Open Decisions

These are explicitly deferred design questions. Each blocks downstream work until resolved.

### OD-01 — Score nullability for manual assertions
*Blocks: `database_schema.md` v2.5, `src/db.py`*

The current schema requires `score REAL NOT NULL DEFAULT 0.0` on all four linkage junction tables. A manually-asserted linkage (researcher directly asserts "this record is about this person" without running the algorithm) has no meaningful score. `0.0` is misleading — it implies the algorithm scored it at zero rather than that no score exists.

**Options:**
- Allow `score` to be nullable (`REAL` with no `NOT NULL`). Null means "manually asserted, no algorithm score." `verified = 1` is then implied for all null-score rows.
- Keep `NOT NULL` and use a sentinel value (e.g., `-1.0`) to indicate manual assertion. Requires a vocabulary convention and a CHECK constraint update.
- Add a separate `assertion_type TEXT` column (`'algorithm'` / `'manual'`) alongside `score`, keeping score non-null but interpreting it conditionally.

**Recommendation pending:** The nullable approach is cleanest semantically. The sentinel value avoids a schema change to existing CHECK constraints. No decision taken — needs resolution before v2.5.

---

### OD-02 — Derived confidence function
*Blocks: `src/reconstruction.py` (final form)*

The current implementation uses a provisional placeholder (confidence = `low` / `medium` / `high` based on record count alone: 1 / 2 / 3+). The actual derivation function — weighting mean score, record count, and source diversity — is deferred until Tullynaught test data is available for calibration.

**Status:** Placeholder is explicitly labelled as provisional in `reconstruction_algorithms.md` §1.4. No action required until real data is ingested.

---

### OD-03 — Narrative output architecture
*Resolved: out of scope for GRA platform.*

Narrative output (family histories, place histories, video-style scripts) is confirmed as a future consumer application built on top of the GRA service layer, not a platform concern. GRA's focus is ingest, linkage, validation, and conclusions. The narrative session type has been removed from `session_bootstrap.md`. Narrative architecture will be designed when that consumer application is specified.

---

### OD-04 — Splink backend compatibility
*Blocks: `src/linkage/`, `src/reconstruction.py`*

`reconstruction_algorithms.md` §9.1 specifies a Splink configuration sketch using `DuckDBAPI`. Splink supports multiple backends (DuckDB, SQLite, Spark). The project database is SQLite. Whether Splink operates directly on the SQLite file via `SQLiteAPI` or loads data into DuckDB for linkage workloads and writes results back to SQLite needs a concrete decision before implementation begins.

**Status:** Splink's SQLite backend has performance limitations for large datasets. DuckDB operates in-memory or on separate files. The decision affects the `open_db()` connection model and the reconstruction entry points.

---

## 4. Roadmap

### Near term — validation and reconstruction

1. Resolve OD-01 (score nullability) → write `database_schema.md` v2.6 with flags/leads tables
2. Implement `src/validator.py` — all 46 rules, three entry points
3. Implement `src/reconstruction.py` — place resolution and household structure inference (the two stages that don't require Splink)
4. Write test suite covering all five Python-only rules and the three reconstruction entry points
5. Resolve OD-04 (Splink backend) → implement Splink-based person linkage

### Medium term — reconstruction and service

6. First update knowledge session on Tullynaught — place resolution and household conclusions committed
7. Implement `src/service.py` — ResearchService API
8. Ingest 1901 census for Tullynaught → first cross-source update knowledge session
9. Calibrate derived confidence function (resolve OD-02) using real Tullynaught data

### Longer term — consumers and narrative

9. Lovable UI (web research interface)
10. Design narrative output architecture (resolve OD-03)
11. Implement narrative session type — family history and place history documents
12. MCP server for agent access to the knowledge base

### Blue sky

- Video-style output in the manner of *Chloe vs. History*: structured narrative scripts grounded in the knowledge base, suitable for voice-over and visual production. Requires narrative pipeline (item 11) as a prerequisite.

---

## 5. Version History

| Version | Date | Change |
|---|---|---|
| 1.0 | May 2026 | Initial ROADMAP — current state, work queue, open decisions, roadmap. Reflects GRA rename and narrative output use case. |
| 1.1 | May 2026 | Tier 1 and Tier 2 marked complete. Updated implementation status table with verified results from Tullynaught 1911 ingest. Updated near/medium-term roadmap. Removed OD-03 (narrative architecture) from active decisions — narrative is a future consumer application, not a platform concern. |

---

*This document should be updated at the start of each working session to reflect progress and any new decisions or open questions.*
