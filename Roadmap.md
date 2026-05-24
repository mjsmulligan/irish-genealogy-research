# Genealogy Research Assistant (GRA) — Project Roadmap

*May 2026*

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
| Database layer | `src/db.py` | 🔶 Partial | `open_db()`, `init_db()`, `build_record_url()` specified; DataStore read/write methods pending implementation |
| Schema DDL | `src/db/schema.sql` | 🔶 Partial | DDL specified in `database_schema.md`; canonical `.sql` file may not yet match v2.4 |
| Seed data | `src/db/seed.sql` | 🔶 Partial | 12 sources and 7 repositories defined in `repositories.md`; SQL seed file pending |
| Migrations | `src/db/migrations/` | 🔜 Pending | Migration scripts for v2.1→v2.2→v2.3→v2.4 not yet written |
| Validator | `src/validator.py` | 🔜 Pending | All 46 rules specified; implementation pending |
| Service layer | `src/service.py` | 🔜 Pending | `service_api.md` v1.0 complete; implementation pending |
| Reconstruction | `src/reconstruction.py` | 🔜 Pending | Algorithms fully specified; implementation pending |
| Linkage | `src/linkage/` | 🔜 Pending | Splink integration, feature extractors, candidate generation |
| Test suite | `tests/` | 🔜 Pending | v1 suite retired; v2.1+ suite not yet written |

**Implementation status summary:** The project is documentation-complete for its core data model, validation, reconstruction, and service layers. Implementation is at an early stage — the gap between specification and working code is the primary execution risk.

---

## 2. Work Queue

Ordered by dependency. Items within a tier can proceed in parallel.

### Tier 1 — Complete the specification layer

**session_bootstrap.md** *(next session)*
The final pending document. Defines how Claude loads context at the start of a research session. Must account for four session types: transcription, linkage, reasoning, and narrative (new). The narrative session type — producing family histories and place histories — is a first-class use case as of May 2026.

**database_schema.md v2.5**
Required to support `service_api.md` v1.0. Flags and leads (surfaced by the pipeline, reviewed by the researcher) require new DB tables not yet specified. The `score` column nullability issue (manual assertions have no algorithm score) is an open design question that must be resolved before this version can be written — see §3.

### Tier 2 — Foundation implementation

**`src/db/schema.sql`** — canonical DDL matching `database_schema.md` v2.4 exactly. The reference implementation all other modules depend on.

**`src/db/seed.sql`** — INSERT statements for the 12 sources and 7 repositories defined in `repositories.md` v1.2.

**`src/db.py`** — `open_db()`, `init_db()`, `build_record_url()`, and the full DataStore read/write methods for all ten first-class objects.

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
*Blocks: narrative session type in `session_bootstrap.md`, future narrative pipeline*

The narrative output use case (family histories, place histories, and longer-form research documents) is a confirmed use case as of May 2026. The architecture is not yet designed. Key questions:

- Does narrative generation go through the service API (Claude calls `ResearchService` methods and synthesises prose), or does it require a separate narrative pipeline with its own document model?
- What is the output format? Markdown for research documents; structured script format for video-style output?
- How does the researcher review and annotate a narrative output? Is it a separate workflow from the evidence/conclusion review cycle?

**Status:** Use case confirmed; architecture not designed. Must be resolved before `session_bootstrap.md` can fully specify the narrative session type.

---

### OD-04 — Splink backend compatibility
*Blocks: `src/linkage/`, `src/reconstruction.py`*

`reconstruction_algorithms.md` §9.1 specifies a Splink configuration sketch using `DuckDBAPI`. Splink supports multiple backends (DuckDB, SQLite, Spark). The project database is SQLite. Whether Splink operates directly on the SQLite file via `SQLiteAPI` or loads data into DuckDB for linkage workloads and writes results back to SQLite needs a concrete decision before implementation begins.

**Status:** Splink's SQLite backend has performance limitations for large datasets. DuckDB operates in-memory or on separate files. The decision affects the `open_db()` connection model and the reconstruction entry points.

---

## 4. Roadmap

### Near term — complete the platform core

1. Resolve OD-01 (score nullability) → write `database_schema.md` v2.5
2. Write `session_bootstrap.md` with four session types including narrative
3. Implement Tier 2 (database foundation)
4. Implement Tier 3 (validation + test suite)

### Medium term — reconstruction and service

5. Resolve OD-04 (Splink backend) → implement Tier 4 (reconstruction pipeline)
6. Seed name variant table from `reconstruction_algorithms.md` Appendix A
7. Implement Tier 5 (service layer)
8. First research session on Tullynaught test data → calibrate derived confidence (resolve OD-02)

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

---

*This document should be updated at the start of each working session to reflect progress and any new decisions or open questions.*
