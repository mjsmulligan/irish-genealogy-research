# Genealogy Research Assistant (GRA) — Project Roadmap

*21 June 2026*

______________________________________________________________________

## 1. Current State

### Documentation

| Document | Status | Notes |
|---|---|---|
| `docs/conceptual_model.md` | ✅ Complete (v2.8) | RecordedRelationship + RecordSimilarity added as Evidence-layer objects; Event consensus arbitration (`is_primary`) formalised as Rule 9; `training_labels` retired; Rule 2 generalised to an evidence-correspondence principle (Person→RecordedPerson, Relationship→RecordedRelationship, Event→Record) |
| `docs/data_dictionary.md` | ✅ Complete (v2.7) | Aligned with conceptual_model.md v2.7: added §3.4 RecordedRelationship, §3.5 RecordSimilarity; added `event.is_primary`; fixed `recorded_person.role` Required marker and added `unknown` to role vocab; renamed junction tables per Rule 2 |
| `docs/database_schema.md` | ✅ Complete (v3.1) | Full DDL pass; all v3.1 target tables and renames reflected |
| `docs/repositories.md` | ✅ Complete (v1.6) | Repository 8 (logainm.ie) and Source 13 (place_authority) added; stale CLI commands fixed |
| `docs/validation_rules.md` | ✅ Complete (v2.8) | DataStore API reference removed; R40–R50 complete; known code bug in `validate_object()` flagged at R05 |
| `docs/reconstruction_algorithms.md` | ✅ Complete (v1.3) | Place-conclusion concept removed; Jellyfish → rapidfuzz; Jaccard → Szymkiewicz–Simpson; junction table renames applied |
| `docs/genealogical_constraints.md` | ✅ Complete (v1.3) | 22 GC-coded constraints |
| `ROADMAP.md` | ✅ Current | Pruned completed items; foundation implementation complete |

### Implementation

| Layer | Status | Notes |
|---|---|---|
| Foundation | ✅ Complete (v3.1) | SQLite retired; PostgreSQL / Supabase; `constants.py`; new DAL files; `clear-evidence` / `clear-conclusions` CLI commands; place authority loading via logainm.ie API |
| Evidence | ✅ Complete (v3.1) | `add-evidence` CLI complete: [1/5] ingest + [2/5] RecordedRelationship + [3/5] place resolution + [4/5] RecordSimilarity (household-level) + [5/5] PersonSimilarity (person-level). Full PostgreSQL compatibility verified with test data. |
| Conclusion | ✅ Complete | `conclude` CLI: [1/3] person resolution + [2/3] relationship resolution + [3/3] event resolution (census, birth, marriage events). Repository restructured: `src/pipeline/` removed; evidence modules live in `src/evidence/`, conclusion modules in `src/conclusion/`. `validator.py` moved to `src/review/` (review layer redesign pending — see work queue item 13). |
| Review | 🔜 Planned | `src/review/` created. Researcher-facing report module: surfaces areas needing attention rather than enforcing hard constraints. Redesign planned for next session (item 13). |

______________________________________________________________________

## 2. Implementation Rebuild

This section outlines the plan for a complete rebuild of the code based on the updated docs and changes to the logic. This supersedes work items relating to code in the work queue.

The rebuild follows the three-layer architecture of GRA — foundation, evidence, conclusions. Each layer is callable as a discrete CLI stage: `cli init` (foundation, once), `cli add-evidence` (evidence, per CSV), `cli conclusions` (conclusion pipeline).

### 2.1 Foundation & Database management ✅

The foundation layer is the most stable in GRA. Its purpose is straightforward: loading repository and source metadata, seeding places from logainm on demand, and managing database setup (a prerequisite for seeding).

Changes introduced in this layer:

- **Minor:** `src/constants.py` — centralises hardcoded values (score versions, thresholds, source IDs) previously scattered across pipeline modules.
- **Major:** SQLite retired; migrated to PostgreSQL / Supabase. DAL isolation validated — no pipeline module required SQL changes.

### 2.2 Evidence Layer ✅

The evidence layer has grown with the new logic and now takes on tasks that were further downstream previously. What was previously a simple ingest is now a key part of the pipeline. The key steps (in pipeline running order):

1. Ingest record to database from CSV (`src/evidence/census.py`) ✅
1. Assign role relationships based on record ✅
1. Run place resolution to link records to place_authority ✅
1. Run Splink similarity across records (household-level) ✅
1. Run Splink similarity across recorded persons (person-level) ✅

All five steps run automatically each time a new CSV is ingested via `cli add-evidence`, which replaces `cli ingest`. `cli clear-evidence` clears all evidence and conclusion objects.

**Design fixes:**

- **21 June 2026 (step 3):** Place resolution was integrated into the evidence pipeline to run before Splink. This ensures place_id is populated for Splink's blocking rules, which require place data for optimal matching.
- **21 June 2026 (step 5):** Person-level similarity added as final evidence step. Writes to `recorded_relationship` with `type='similarity'`. Person features: name, birth year, sex, place. Hierarchical household score feature deferred to v1.1 (ROADMAP item 12).

**Evidence layer is complete.** RecordSimilarity and person-level similarity (via RecordedRelationship type='similarity') are ready for consumption by the conclusion layer. The conclusion layer redesign (§2.3) will use these similarity scores for Person Resolution (clustering RecordedPersons into Person conclusions).

### 2.3 Conclusion Layer ✅

The conclusion layer runs via `cli conclude` and produces Person, Relationship, and Event conclusions from the evidence layer in three steps:

1. **Person Resolution** — clusters RecordedPersons into Person conclusions using person-level similarity scores (threshold 0.65) via connected-components / Union-Find. Orphans (no similarity matches above threshold) are passed to Relationship Resolution. ✅
1. **Relationship Resolution** — uses high-similarity household pairs (RecordSimilarity ≥ 0.85) to create or link Persons for matched RecordedPersons, then creates Relationships (couple, parent_child, sibling) from household roles. Detects merge candidates (spouse triangulation). ✅
1. **Event Resolution** — three passes: (a) one census Event per linked RecordedPerson; (b) calculated birth Events per Person from census ages (birth years within ±2 years collapse to one event; diverging years produce multiple events with is_primary arbitrated by vote count); (c) one marriage Event per couple Relationship (date=NULL, additive — BMD ingestion will add dated events later). ✅

**Repository restructure (21 June 2026):** `src/pipeline/` removed entirely. Files redistributed:

- `place_resolution.py`, `features/` → `src/evidence/`
- `validator.py` → `src/review/` (review layer — redesign planned for v2.0, ROADMAP item 13)
- `linkage.py`, `debug.py`, `household_inference.py`, `pipeline.py`, `scoring.py` → deleted (superseded by conclusion layer)

______________________________________________________________________

## 3. Release Plan

- **v1.x (Current):** Implementation rebuild complete — all three layers done (foundation 20 June, evidence 21 June, conclusion 21 June). Next: integration tests.
- **v2.0 (Target):** Review layer (`src/review/`) — researcher report module redesign (ROADMAP item 13). Full-scale Irish Census (1901–1926) ingestion and analysis.
- **v3.0 (Long-term):** Ingest of parish and civil BMD.

______________________________________________________________________

## 4. Work Queue

| # | Item | Status |
|---|---|---|
| 2 | Test harness: integration tests covering all three layers (foundation → evidence → conclusion) using Tullynaught/Clogher CSV fixtures. One fixture, real Supabase connection, end-to-end pipeline exercised. | 🔜 |
| 7 | Update stale schema-version footers: audit all `docs/` files and update date/version lines to reflect current versions. | 🔜 |
| 11 | Remove `training_labels` from `schema.sql` and `training_repo.py`. | 🔜 |
| 12 | Person similarity hierarchical feature: Add household similarity score as a Splink comparison level to boost person match confidence when households strongly match. Deferred to v1.1 after integration tests pass. | 🔜 (v1.1) |
| 13 | **Review layer redesign** (`src/review/`). Reframe `validator.py` from constraint enforcer to researcher report module. Rules should surface areas needing attention rather than flagging violations. Design notes: R40/R41/R43 now apply to primary Events only; R42 becomes a conclusion-pipeline guardrail rather than a post-hoc check; scope broadens to include flagged items from the conclusion layer (merge candidates, unresolved birth conflicts, unlinked places, persons with no birth event, etc.). Port to PostgreSQL as part of redesign. Add `review` CLI command. | 🔜 (v2.0) |

______________________________________________________________________

## 5. Open Decisions

All open decisions from the conclusion layer design phase have been resolved:

- **Person-creation timing:** Resolved. Persons are created in batch by `person_resolution.py` (clustering) and `relationship_resolution.py` (household matching), not eagerly at ingest time. `household_inference.py` deleted.
- **Census Event creation:** Resolved. Census Events are created by `event_resolution.py` pass 1, after Persons exist. They are linked to Persons via `person_event` and to Records via `event_record`.

______________________________________________________________________

## 6. Version History

| Date | Milestone / Change |
|---|---|
| 21 June 2026 (session 11) | **Conclusion layer implementation complete. Repository restructured.** `src/conclusion/` complete: `person_resolution.py` (Union-Find clustering, threshold 0.65), `relationship_resolution.py` (household similarity matching, merge candidate detection), `event_resolution.py` (census + calculated birth + marriage events, ±2yr birth-year tolerance, is_primary consensus). `src/pipeline/` removed entirely: `place_resolution.py` and `features/` moved to `src/evidence/`; `validator.py` moved to `src/conclusion/` (PostgreSQL port pending, ROADMAP item 13); `linkage.py`, `debug.py`, `household_inference.py`, `pipeline.py`, `scoring.py` deleted. `cli.py` rewritten: old `place-resolve`, `household`, `link`, `score-evidence`, `reconstruct` commands removed; new `conclude` command added. `src/__init__.py` rewritten. Open design decisions (person-creation timing, census Event placement) closed. |
| 21 June 2026 (session 10) | **Person-level similarity added as evidence step [5/5].** Created `src/pipeline/features/census_person.py` (person feature extractor from evidence layer: name, birth year, sex, place). Extended `src/evidence/similarity.py` with `run_person_similarity()` and `PersonSimilarityResult`. Splink person-level matching writes to `recorded_relationship` with `type='similarity'`. Wired into `cli add-evidence` as final step. `src/constants.py` updated: `SCORE_VERSION_PERSON_SIMILARITY`, `BATCH_SIZE_PERSON_SIMILARITY`. Hierarchical household score feature deferred to v1.1 (ROADMAP item 12). **Tested end-to-end:** Retroactive run on existing Tullynaught 1901↔1911 data produced 330 person similarity pairs (score range 0.30-0.68), all correctly stored. Sample matches show correct name/age progression across 10-year census gap. **Conclusion layer design session:** Person Resolution strategy confirmed as batch creation after evidence linkage (Strategy B). Person clustering via connected components on similarity scores (threshold 0.85). Ready to implement conclusion layer. |
| 21 June 2026 | **Evidence layer verified complete with PostgreSQL.** PostgreSQL compatibility fixes applied across evidence pipeline: `record_repo.py` (column aliases for COALESCE), `role_relationships.py` (score=NULL for non-similarity types per CHECK constraint), `place_resolution.py` (cursor pattern, SQL placeholders, rapidfuzz JaroWinkler API). Place resolution integrated into `add-evidence` workflow as step [3/4] before Splink — design fix ensures place_id populated for Splink blocking rules. Test data restored from git history (tullynaught_1901/1911/1926.csv). Evidence pipeline fully tested end-to-end: 503 households, 2273 people, 4310 relationships, 503 place links (100% resolved), 138 cross-census similarities. **Evidence layer complete and production-ready.** |
| 20 June 2026 | **Evidence layer implementation complete.** `src/evidence/similarity.py` created: Splink household-level similarity across all census source pairs, writing to `record_similarity` with per-source-pair transaction boundary and `BATCH_SIZE_RECORD_SIMILARITY` hook. `src/pipeline/features/census.py` rewritten for psycopg2 (DAL isolation). `src/constants.py` updated: `CHILD_DEPARTURE_AGE`, `SCORE_VERSION_RECORD_SIMILARITY`, `BATCH_SIZE_RECORD_SIMILARITY` added; `CENSUS_SOURCE_IDS` and `SOURCE_ID_*` regrouped. `cli add-evidence` wired: now runs all three evidence steps ([1/3] ingest, [2/3] role-relationships, [3/3] similarity). Known drift: `CENSUS_SOURCE_IDS` still locally defined in `linkage.py`, `household_inference.py`, `validator.py` — to be cleaned up when those files are next touched. |
| 20 June 2026 | **Foundation implementation complete (v3.1).** SQLite retired; migrated to PostgreSQL / Supabase. New files: `src/constants.py`, `src/dal/recorded_relationship_repo.py`, `src/dal/record_similarity_repo.py`, `.env.example`. Rewritten: `src/db/schema.sql` (Postgres DDL; `recorded_relationship`, `record_similarity`, `gra_meta`; junction renames), `src/db/seed.sql` (Postgres syntax), `src/db/db.py` (psycopg2; `DATABASE_URL` from env), `src/cli.py` (`clear-evidence`/`clear-conclusions`; `--db` arg removed). All 7 DAL files: `conn.execute()` → cursor pattern; `?` → `%s`; junction renames applied; constants imported from `src/constants.py`. `reset_pipeline.py` flagged deprecated. SQLite migrations archived to `src/db/migrations/archive_sqlite/`. ROADMAP pruned: completed work queue items removed, version history consolidated. |
| 19 June 2026 (session 9) | **`database_schema.md` v3.2.** Resolved Work Queue item 13: §5 Validation Rule Mapping — R47–R50 mapped to DDL-level CHECK constraints. |
| 19 June 2026 (session 8) | **`repositories.md` v1.6.** Fixed two stale CLI commands (item 12). |
| 19 June 2026 (session 7) | **`future_ideas.md` v1.2.** Removed stale `service_api.md §10.3` references (item 21). |
| 19 June 2026 (session 6) | **`reconstruction_algorithms.md` v1.3.** Items 17–20 resolved: Place-conclusion removed; rapidfuzz throughout; Szymkiewicz–Simpson for co-occupant overlap; junction rename cross-references added. |
| 19 June 2026 (session 5) | **Doc audit.** Full read of all docs against code. New work queue items 16–21 added. |
| 18 June 2026 (session 4) | **Data layer rebuild complete — `database_schema.md` v3.1.** Grounded rewrite against actual `schema.sql` and `src/dal/*.py`. Resolved all DDL drift. `name_variant` DAL writer gap flagged. |
| 17 June 2026 (session 3) | **Data layer alignment.** Resolved Relationship evidence-FK decision; Rule 2 generalised. `data_dictionary.md` v2.7; `conceptual_model.md` v2.6. |
| 17 June 2026 (session 2) | **Conceptual model v2.5.** RecordedRelationship, RecordSimilarity, Rule 9, `training_labels` retired. Architecture rebuild started. |
| 17 June 2026 | **Consolidation.** Path drift resolved; migration scripts v2.8→v3.0; roadmap structure restored; constraint versioning synced to v1.2. |
| 16 June 2026 | **Schema v3.0.** `event.is_primary`, nullable roles. Linkage correctness pass. |
| Early June 2026 | **Schema v2.8.** RecordedEvent merged into Record; junction tables 9→5. First full linkage test. |
| 24 May 2026 | **Foundation & R1-1.** Initial GRA roadmap established. Place resolution and household inference implemented. |
