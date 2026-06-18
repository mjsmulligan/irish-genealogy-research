# Genealogy Research Assistant (GRA) — Project Roadmap

*18 June 2026*

---

## 1. Current State

### Documentation

| Document | Status | Notes |
|---|---|---|
| `docs/conceptual_model.md` | ✅ Complete (v2.6) | RecordedRelationship + RecordSimilarity added as Evidence-layer objects; Event consensus arbitration (`is_primary`) formalised as Rule 9; `training_labels` retired; Rule 2 generalised to an evidence-correspondence principle (Person→RecordedPerson, Relationship→RecordedRelationship, Event→Record), resolving the Relationship evidence-FK open decision and correcting Person's evidence target to match |
| `docs/data_dictionary.md` | ✅ Complete (v2.7) | Aligned with conceptual_model.md v2.6: added §3.4 RecordedRelationship, §3.5 RecordSimilarity; added `event.is_primary`; fixed `recorded_person.role` Required marker and added `unknown` to role vocab; renamed `Person.record_ids`→`recorded_person_ids` and `Relationship.record_ids`→`recorded_relationship_ids` with matching junction-table renames |
| `docs/repositories.md` | ✅ Complete | Repository 8 (logainm.ie) and Source 13 (place_authority) added |
| `docs/validation_rules.md` | ⚠️ Drift identified | R40–R46 implemented; retired rules updated; still references an obsolete `DataStore.validate_genealogical(...)` API — actual entry points are plain functions in `validator.py` |
| `docs/database_schema.md` | ✅ Complete (v3.1) | Full DDL pass: `schema.sql` drift resolved (`place_authority` restored, obsolete `place` table removed, `event.is_primary` and `training_labels` + indexes added to the DDL). §6 rewritten to describe the actual `src/dal/` repo-per-table pattern (no `DataStore` class exists). Carries forward v2.6/v2.7 target design not yet in code, marked `[target]`: `recorded_relationship`/`record_similarity` tables; `person_record`→`person_recorded_person` and `relationship_record`→`relationship_recorded_relationship` renames (FK target also changes, per Rule 2). `training_labels`'s conceptual retirement documented without removing it from the DDL |
| `docs/reconstruction_algorithms.md` | ✅ Complete | Updated for schema v2.8; event linkage simplified |
| `docs/genealogical_constraints.md` | ✅ Complete | 22 GC-coded constraints (v1.2) |
| `ROADMAP.md` | ✅ Complete | Updated structure and remediation queue |

---

## 2. Implementation Table

| Module | File(s) | Status | Notes |
|---|---|---|---|
| Place fetcher | `src/db/fetch_places.py` | ✅ Complete | Moved to `src/db/` |
| Place seeder | `src/db/seed_places.py` | ✅ Complete | Moved to `src/db/` |
| Pipeline reset | `src/db/reset_pipeline.py` | ✅ Complete | Utility added to `src/db/` |
| Household inference | `src/pipeline/household_inference.py` | ⚠️ Pending redesign | Current implementation creates Person + Relationship eagerly from census role-pairs and links a census Event to those Persons in one pass. Per conceptual_model.md v2.5, role-pair relationship inference is superseded by ingest-time RecordedRelationship capture; Person-creation timing needs a more intentional redesign; census Event creation needs a home once it can't assume Persons already exist. Not yet implemented — design only. |

---

## 3. Release Plan

* **v1.x (Current):** Stabilize schema (v3.0), complete documentation drift remediation, and verify pipeline against Tullynaught DED test data.
  * **Architecture rebuild (started 17 June 2026):** Multi-session pass rebuilding from conceptual model → data layer → implementation, in that order, incorporating everything learned from R1 so far. Conceptual model phase complete (v2.6). Data layer phase complete: `data_dictionary.md` (v2.7) and `database_schema.md` (v3.1) both done. **Implementation phase is next** — see Work Queue item 15.
* **v2.0 (Target):** Implementation of full-scale Irish Census (1901–1926) ingestion and analysis.
* **v3.0 (Long-term):** Analysis layer: community queries, graph traversal, and automated GEDCOM export.

---

## 4. Work Queue

| # | Item | Status |
|---|---|---|
| 2 | Migration scripts: `migrate_28_to_29.sql` / `migrate_29_to_30.sql` created. | ✅ Resolved (17 Jun) |
| 5 | Path drift: `fetch_places.py` / `seed_places.py` / `reset_pipeline.py` location corrected to `src/db/`. | ✅ Resolved (17 Jun) |
| 6 | genealogical_constraints.md version: Sync to v1.2. | ✅ Resolved (17 Jun) |
| 7 | Update stale schema footers: Audit all `docs/` files to reflect v3.0. | 🔜 |
| 8 | conceptual_model.md: RecordedRelationship, RecordSimilarity, Event consensus arbitration (Rule 9), Person/Relationship singularity rationale, `training_labels` retirement, stale CLI fix. | ✅ Resolved (17 Jun) |
| 9 | data_dictionary.md: align with conceptual_model.md v2.5 — add `event.is_primary`, document RecordedRelationship/RecordSimilarity, fix `recorded_person.role` Required marker, add `unknown` to role vocab. | ✅ Resolved (17 Jun) |
| 10 | database_schema.md: full DDL pass to match `schema.sql` (`place_authority` CREATE TABLE, remove obsolete `place` table, `event.is_primary`, `training_labels` table + indexes, rewrite §6 DataStore section to reflect the actual `src/dal/` repo-per-table pattern, fix worked example, rename `person_record`→`person_recorded_person` and `relationship_record`→`relationship_recorded_relationship` per the v2.6/v2.7 evidence-correspondence rename, add `recorded_relationship` and `record_similarity` tables). | ✅ Resolved (18 Jun) |
| 11 | Remove `training_labels` from `schema.sql`, `linkage.py`, and `training_repo.py`. | 🔜 (deferred to implementation phase of rebuild) |
| 12 | repositories.md: fix stale CLI examples (`python -m src.fetch_places` / `python -m src.db seed-places` → `python -m src.cli fetch-places` / `seed-places`). | 🔜 |
| 13 | validation_rules.md: fix references to obsolete `DataStore.validate_genealogical(...)` API; assign R-numbers to the `recorded_relationship`/`record_similarity` CHECK constraints documented but unnumbered in `database_schema.md` v3.1 §5. | 🔜 |
| 14 | conceptual_model.md v2.6: generalised Rule 2 to an evidence-correspondence principle (Person→RecordedPerson, Relationship→RecordedRelationship, Event→Record); resolved the Relationship evidence-FK open decision and corrected Person's evidence target to match. | ✅ Resolved (17 Jun) |
| 15 | Implementation phase: build the v3.1 target schema in code — add `recorded_relationship` and `record_similarity` to `schema.sql`, write `migrate_30_to_31.sql`, rename `person_record`→`person_recorded_person` and `relationship_record`→`relationship_recorded_relationship` (including the FK target change from `record_id` to `recorded_person_id`/`recorded_relationship_id`), update `person_repo.py`/`relationship_repo.py` and the `household_inference.py`/`linkage.py` callers accordingly. | 🔜 (data layer phase now complete; this is the next phase) |

---

## 5. Open Decisions

* **Pipeline Reset:** Decide if `reset_pipeline.py` should be exposed via `src.cli` or kept as a standalone utility.
* **Source Expansion:** Prioritize Griffith's Valuation vs. Tithe Applotment for the next ingest module.
* **Person-creation timing:** When/how should a Person conclusion be minted, now that `household_inference`'s immediate-creation-after-ingest approach is judged too eager? Needs a deliberate, more intentional design (conceptual model session, 17 June 2026).
* **Census Event creation:** Once Person creation is no longer automatic and immediate, where does census Event creation (currently bundled into `household_inference`) live, and how does it eventually link to Persons?

---

## 6. Version History

| Date | Milestone / Change |
|---|---|
| 18 June 2026 (session 4) | **Data layer rebuild complete — `database_schema.md` v3.1.** Pulled the actual `schema.sql` and `src/dal/*.py` from the repo to ground the rewrite rather than guessing: confirmed `place_authority` already exists in code (the doc's DDL just never carried it), confirmed `training_labels` is fully implemented with the exact decision-lifecycle/index DDL now reflected in §3, and discovered along the way that `name_variant` is defined in schema but has no DAL writer anywhere — flagged in §1 and §6 rather than silently fixed. Resolved all `database_schema.md` drift items: restored `place_authority`, removed the obsolete `place` table, added `event.is_primary` and `training_labels` to the DDL, rewrote §6 to describe the real `src/dal/` repo-per-table pattern in place of the nonexistent `DataStore` class. Carried the v2.6/v2.7 target design (RecordedRelationship, RecordSimilarity, the Person/Relationship evidence-correspondence rename) into the DDL, marked `[target]` throughout and called out explicitly in §1 and §9 as not yet reflected in `PRAGMA user_version`. Data layer phase of the architecture rebuild (conceptual model → data dictionary → database schema) is now complete; implementation phase is next (Work Queue item 15). |
| 17 June 2026 (session 3) | **Data layer alignment:** Resolved the open Relationship evidence-FK decision in favour of RecordedRelationship, generalised as Rule 2 (evidence correspondence) and applied symmetrically to Person→RecordedPerson; conceptual_model.md bumped to v2.6. Aligned data_dictionary.md to v2.7: added RecordedRelationship/RecordSimilarity field tables, `event.is_primary`, fixed `recorded_person.role` nullability and `unknown` vocab, renamed `Person`/`Relationship` evidence FKs and their junction tables to match. Data layer phase of the architecture rebuild now complete for `data_dictionary.md`; `database_schema.md` is next. |
| 17 June 2026 (session 2) | **Conceptual model v2.5:** Added RecordedRelationship and RecordSimilarity as Evidence-layer objects, recording relationships and algorithmic similarity between evidence units without requiring a conclusion. Formalised Event consensus arbitration as Rule 9 — competing Events of the same type may coexist per Person, exactly one marked `is_primary`; Person and Relationship explicitly excluded, for different reasons. Retired `training_labels` as a considered-and-built-then-rejected path. Fixed stale CLI examples and the stale "eleven objects" count. Identified that `database_schema.md`'s prior "Complete" status was inaccurate (DDL out of sync with `schema.sql`) and corrected it here. Started the multi-session architecture rebuild: conceptual model → data layer → implementation. |
| 17 June 2026 | **Consolidation:** Resolved path drift, implemented migration scripts (v2.8→v3.0), restored roadmap structure, archived inactive documentation, and sync'd constraint versioning to v1.2. |
| 16 June 2026 | **Schema v3.0:** Finalized (`event.is_primary`, nullable roles). Linkage correctness pass: `link_only`, `_UnionFind`, Positional pairing, Per-merge transactions. |
| Early June 2026 | **Schema v2.8:** RecordedEvent merged into Record; junction tables 9→5. First full linkage test (3881 persons, 264 merged). Relationship features added. |
| 24 May 2026 | **Foundation & R1-1:** Initial GRA roadmap/rename established. Tier 1/2 complete; Tullynaught 1911 verified. Implemented place resolution and household inference (R1-1); established Release Plan (R1–R3). |
