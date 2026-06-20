# Genealogy Research Assistant (GRA) — Project Roadmap

*20 June 2026*

---

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
| Foundation | ✅ Complete (v3.1) | SQLite retired; PostgreSQL / Supabase; `constants.py`; new DAL files; `clear-evidence` / `clear-conclusions` CLI commands |
| Evidence | 🔄 In progress | `add-evidence` CLI complete: ingest + RecordedRelationship + RecordSimilarity (Splink). Conclusion-layer wiring deferred. |
| Conclusion | 🔜 Planned | Design deferred pending evidence layer completion |

---

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

- Ingest record to database from CSV ✅
- Assign role relationships based on record ✅
- Run Splink similarity across records ✅

All three steps run automatically each time a new CSV is ingested via `cli add-evidence`, which replaces `cli ingest`. `cli clear-evidence` clears all evidence and conclusion objects.

**What remains:** RecordSimilarity output is not yet consumed by the conclusion layer. The conclusion layer redesign (§2.3) will determine how RecordSimilarity rows are promoted into Person and Relationship conclusions.

### 2.3 Conclusion Layer

The conclusion layer is the most complex rebuild; a detailed plan will be produced once the evidence layer is complete. The key insight at this point is that although we talk about a "researcher" here, we want to build a more powerful system where conclusions could be created by heuristics, LLM (or agent), and obviously a human researcher (likely mediated through a UI).

---

## 3. Release Plan

* **v1.x (Current):** Stabilize schema (v3.1), complete implementation rebuild layer by layer.
  * Foundation complete (20 June 2026). Evidence layer complete (20 June 2026). Conclusion layer is next.
* **v2.0 (Target):** Full-scale Irish Census (1901–1926) ingestion and analysis.
* **v3.0 (Long-term):** Ingest of parish and civil BMD.

---

## 4. Work Queue

| # | Item | Status |
|---|---|---|
| 2 | Test harness: integration tests covering all three layers (foundation → evidence → conclusion) using Tullynaught/Clogher CSV fixtures. One fixture, real Supabase connection, end-to-end pipeline exercised. Deferred until conclusion layer is complete. | 🔜 |
| 7 | Update stale schema-version footers: audit all `docs/` files and update date/version lines to reflect current versions. | 🔜 |
| 11 | Remove `training_labels` from `schema.sql`, `linkage.py`, and `training_repo.py`. | 🔜 (deferred to conclusion phase) |

---

## 5. Open Decisions

* **Person-creation timing:** When/how should a Person conclusion be minted, now that `household_inference`'s immediate-creation-after-ingest approach is judged too eager? Needs a deliberate, more intentional design. Will be part of the conclusion layer planning session.
* **Census Event creation:** Once Person creation is no longer automatic and immediate, where does census Event creation (currently bundled into `household_inference`) live, and how does it eventually link to Persons? Will be part of the conclusion layer planning session.

---

## 6. Version History

| Date | Milestone / Change |
|---|---|
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
