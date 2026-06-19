# Genealogy Research Assistant (GRA) — Project Roadmap

*19 June 2026*

---

## 1. Current State

### Documentation

| Document | Status | Notes |
|---|---|---|
| `docs/conceptual_model.md` | ✅ Complete (v2.7) | RecordedRelationship + RecordSimilarity added as Evidence-layer objects; Event consensus arbitration (`is_primary`) formalised as Rule 9; `training_labels` retired; Rule 2 generalised to an evidence-correspondence principle (Person→RecordedPerson, Relationship→RecordedRelationship, Event→Record), resolving the Relationship evidence-FK open decision and correcting Person's evidence target to match |
| `docs/data_dictionary.md` | ✅ Complete (v2.7) | Aligned with conceptual_model.md v2.7: added §3.4 RecordedRelationship, §3.5 RecordSimilarity; added `event.is_primary`; fixed `recorded_person.role` Required marker and added `unknown` to role vocab; renamed `Person.record_ids`→`recorded_person_ids` and `Relationship.record_ids`→`recorded_relationship_ids` with matching junction-table renames |
| `docs/database_schema.md` | ✅ Complete (v3.1) | Full DDL pass: `schema.sql` drift resolved (`place_authority` restored, obsolete `place` table removed, `event.is_primary` and `training_labels` + indexes added to the DDL). §6 rewritten to describe the actual `src/dal/` repo-per-table pattern (no `DataStore` class exists). Carries forward v2.7 target design not yet in code, marked `[target]`: `recorded_relationship`/`record_similarity` tables; `person_record`→`person_recorded_person` and `relationship_record`→`relationship_recorded_relationship` renames (FK target also changes, per Rule 2). `training_labels`'s conceptual retirement documented without removing it from the DDL |
| `docs/repositories.md` | ⚠️ Drift identified (v1.5) | Repository 8 (logainm.ie) and Source 13 (place_authority) added. Two stale CLI commands in §4 remain unfixed — see Work Queue item 12 |
| `docs/validation_rules.md` | ✅ Complete (v2.8) | DataStore API reference removed from §10; correct entry points (`validate(conn)`, `validate_genealogical(conn, person_id)`) documented. Known code bug in `validate_object()` (role still treated as required) documented at R05 and §10 — fix is a code task, not a doc task; see Work Queue item 16 |
| `docs/reconstruction_algorithms.md` | ✅ Complete (v1.3) | Items 17–20 resolved: §2 Place Resolution rewritten to remove retired Place-conclusion concept (now `place_authority` + `place_record` pattern throughout); Jellyfish replaced by rapidfuzz; phonetic blocking removed; co-occupant overlap changed from Jaccard to Szymkiewicz–Simpson; junction table DDL example updated to v3.1 rename targets with cross-reference note |
| `docs/genealogical_constraints.md` | ✅ Complete (v1.3) | 22 GC-coded constraints |
| `ROADMAP.md` | ✅ Complete | Doc table corrected (19 June); new Work Queue items 16–21 added from doc audit; item 21 resolved (19 June) |

---

## 2. Implmentation Rebuild

This section outlines the plan for a complete rebuild of the code based on the updated docs and changes to the logic.  This supercedes work items mentioned below as the rebuild may result in entire python modules being rewritten or replaced.

The rebuild will follow the three layer architecture of gra - foundation, evidence, conclusions. We should also implement the code in such a way that we could call each layer as a seperate task, e.g. foundation runs once (apart from places) but `cli add_evidence` would essentially replace `cli ingest` and `cli conclusions` would run conclusion steps in the pipeline.

2.1 Foundation & Database management

The foundation layer is the most stable in gra. It's purpose is straightforward which is loading the info regarding repositories and sources.  The only dynamic part of the foundation layer is seeding places from logainm.  This is considered an 'on demand' seeding as preloading all 51000 townlands in Ireland is an unnecessary (and expensive) overhead.

It also is responsible for the database setup. This makes sense as database setup is a prerequisite for seeding.

Therefore from a logic perspective much of the code should still be valid.  However, there are 2 changes I want to introduce at this point, one minor and one major.

- minor: running code reviews has shown up there is a over reliance on hardcoded values. It makes sense then at tis point to introduce a constants file to keep the overall codebase clean.
- major: we have discussed this before, but the rebuild is a good time to migrate from sqlite to supabase. This will also be a good point to validate the modularity of our DAL that would allow us to change back end without a major rewrite across the codebase.

2.2. Evidence Layer

The evidence layer has grown with the new logic and is now taking on tasks that were further downstream previously.  What was previously a simple ingest is now a key part of the pipeline.  The key steps we will need to implement here (in pipeline running order).

- ingest record to database from CSV
- assign role relationships based on record
- run splink similarity across records

With this updated evidence layer, these steps should automatically run each time there is a new csv file ingested. `cli add_evidence` now replaces `cli ingest`.  There is also a reset command `cli clear_evidence` which will clear all evidence and conclusion objects.

2.3. Conclusion Layer

The conclusion layer is the most complex rebuild and we create a detailed plan once we have the other layers.  The key insight here at this time is that although we talk about 'researcher' here, we want to build a more powerful system where conclusions could be created by hueristics, llm (or agent) and obviously human researcher (likely mediated through a UI).

## 3. Release Plan

* **v1.x (Current):** Stabilize schema (v3.0), complete documentation drift remediation, and verify pipeline against Tullynaught DED test data.
  * **Architecture rebuild (started 17 June 2026):** Multi-session pass rebuilding from conceptual model → data layer → implementation, in that order, incorporating everything learned from R1 so far. Conceptual model phase complete (v2.7). Data layer phase complete: `data_dictionary.md` (v2.7) and `database_schema.md` (v3.1) both done. `reconstruction_algorithms.md` now fully aligned (v1.3). **Implementation phase is next** — see Section 2.
* **v2.0 (Target):** Implementation of full-scale Irish Census (1901–1926) ingestion and analysis.
* **v3.0 (Long-term):** Ingest of parish and civil BMD.

---

## 4. Work Queue

| # | Item | Status |
|---|---|---|
| 2 | Migration scripts: `migrate_28_to_29.sql` / `migrate_29_to_30.sql` created. | ✅ Resolved (17 Jun) |
| 5 | Path drift: `fetch_places.py` / `seed_places.py` / `reset_pipeline.py` location corrected to `src/db/`. | ✅ Resolved (17 Jun) |
| 6 | `genealogical_constraints.md` version: Sync to v1.2. | ✅ Resolved (17 Jun) |
| 7 | Update stale schema-version footers: audit all `docs/` files and update date/version lines to reflect current versions. | 🔜 |
| 8 | `conceptual_model.md`: RecordedRelationship, RecordSimilarity, Event consensus arbitration (Rule 9), Person/Relationship singularity rationale, `training_labels` retirement, stale CLI fix. | ✅ Resolved (17 Jun) |
| 9 | `data_dictionary.md`: align with conceptual_model.md v2.5 — add `event.is_primary`, document RecordedRelationship/RecordSimilarity, fix `recorded_person.role` Required marker, add `unknown` to role vocab. | ✅ Resolved (17 Jun) |
| 10 | `database_schema.md`: full DDL pass to match `schema.sql` (`place_authority` CREATE TABLE, remove obsolete `place` table, `event.is_primary`, `training_labels` table + indexes, rewrite §6 DataStore section to reflect the actual `src/dal/` repo-per-table pattern, fix worked example, rename `person_record`→`person_recorded_person` and `relationship_record`→`relationship_recorded_relationship` per the v2.7 evidence-correspondence rename, add `recorded_relationship` and `record_similarity` tables). | ✅ Resolved (18 Jun) |
| 11 | Remove `training_labels` from `schema.sql`, `linkage.py`, and `training_repo.py`. | 🔜 (deferred to implementation phase) |
| 12 | `repositories.md` §4: fix two stale CLI commands (`python -m src.fetch_places` → `python -m src.cli fetch-places`; `python -m src.db seed-places` → `python -m src.cli seed-places`). | 🔜 |
| 13 | `validation_rules.md`: assign R-numbers to the `recorded_relationship`/`record_similarity` CHECK constraints documented but unnumbered in `database_schema.md` v3.1 §5. | 🔜 |
| 14 | `conceptual_model.md` v2.6: generalised Rule 2 to an evidence-correspondence principle; resolved the Relationship evidence-FK open decision. | ✅ Resolved (17 Jun) |
| 15 | Implementation phase: build the v3.1 target schema in code — add `recorded_relationship` and `record_similarity` to `schema.sql`, write `migrate_30_to_31.sql`, rename `person_record`→`person_recorded_person` and `relationship_record`→`relationship_recorded_relationship` (including the FK target change from `record_id` to `recorded_person_id`/`recorded_relationship_id`), update `person_repo.py`/`relationship_repo.py` and the `household_inference.py`/`linkage.py` callers accordingly. | Superceded by rebuild plan|
| 16 | Fix `validate_object()` in `src/pipeline/validator.py`: remove `role` from `_REQUIRED` and `_NON_EMPTY` for `recorded_person` (role is nullable since schema v3.0); remove dead `'place'` obj_type entry (Place conclusion retired — `place_authority` is the structural table). | Superceded by rebuild plan |
| 17 | `reconstruction_algorithms.md` §2 (Place Resolution): rewrite to remove retired Place-conclusion concept. Replace all "Place conclusion" language with `place_authority` + `place_record` pattern. Specific fixes: §2.1 output description; §2.4 `place.name` → `place_authority.name_en`; §2.5 "new Place conclusion is created" → `place_record` row linking to existing `place_authority` entry; §1.1 pipeline sequence step 2. **Must precede the place resolution implementation session.** | ✅ Resolved (19 Jun) |
| 18 | `reconstruction_algorithms.md` §1.5 (Library stack): replace Jellyfish with rapidfuzz throughout; update `pip install` example. | ✅ Resolved (19 Jun) |
| 19 | `reconstruction_algorithms.md` §3 (Person linkage): confirm whether co-occupant overlap score should use Szymkiewicz–Simpson rather than Jaccard (same departure-asymmetry rationale as the name-set change made in R1-2). Update if confirmed. | ✅ Resolved (19 Jun) |
| 20 | `reconstruction_algorithms.md`: add cross-reference note in §1 pointing to `database_schema.md` §1 for v3.1 junction rename targets (`person_record`→`person_recorded_person`, `relationship_record`→`relationship_recorded_relationship`). | ✅ Resolved (19 Jun) |
| 21 | `archive/future_ideas.md` §1.1 and §1.3: update references to `service_api.md §10.3` (now archived) — note that the flag/lead schema design is simply deferred, not documented in any active reference. | ✅ Resolved (19 Jun) |

---

## 5. Open Decisions

* **Pipeline Reset:** Decide if `reset_pipeline.py` should be exposed via `src.cli` or kept as a standalone utility. - **Decision** reset_pipeline superceded by rebuild plan, but we should introduce two commands in cli - `cli clear_conclusions` which clears all conclusions from the database and `cli clear_evidence` which clears all evidence and conclusions.
* **Source Expansion:** Prioritize Griffith's Valuation vs. Tithe Applotment for the next ingest module. - **Decision** - postponed. The next ingest target after census will be BMD.  But this should be a future release.
* **Person-creation timing:** When/how should a Person conclusion be minted, now that `household_inference`'s immediate-creation-after-ingest approach is judged too eager? Needs a deliberate, more intentional design (conceptual model session, 17 June 2026). This will be part of the rebuild conclusion planning.
* **Census Event creation:** Once Person creation is no longer automatic and immediate, where does census Event creation (currently bundled into `household_inference`) live, and how does it eventually link to Persons? This will be part of the rebuild conclusion planning.

---

## 6. Version History

| Date | Milestone / Change |
|---|---|
| 19 June 2026 (manual update) | Made manual changes to the roadmap. The biggest change is the updated Section 2 which outlines the code rebuild plan which will be a large work item.  This also supercedes work items relating to code in the work queue items list.  Also addressed open issues. |
| 19 June 2026 (session 7) | **`future_ideas.md` v1.2.** Resolved Work Queue item 21: updated §1.1 and §1.3 to remove stale `service_api.md §10.3` references. Both sections now note that the flag/lead DDL design is deferred and `service_api.md` is archived and no longer an active reference. |
| 19 June 2026 (session 6) | **`reconstruction_algorithms.md` v1.3.** Resolved Work Queue items 17–20. §2 Place Resolution fully rewritten: removed all Place-conclusion language, reframed resolution as linking Records to the pre-seeded `place_authority` table via `place_record`; §2.5 now describes the unresolved-string flagging workflow (fetch-places / manual add / re-run) instead of conclusion creation. §1.5 library stack updated: Jellyfish replaced by rapidfuzz throughout (`rapidfuzz.distance.JaroWinkler.similarity`); phonetic (Soundex/Metaphone) blocking removed from §4.1 normalisation pipeline, §5.1 blocking rule 2 (now surname Jaro-Winkler fallback), and §9.1 Splink sketch. §5.3 co-occupant overlap score changed from Jaccard to Szymkiewicz–Simpson with departure-asymmetry rationale. §1.6 junction table DDL example updated to v3.1 rename targets with cross-reference note. Opportunistic fixes: §5.2 comparison table, §7.2 place language, §6.1 prose reference annotated, §8.1 SQL examples noted as pre-v3.1, §9.2 entry points updated (`DataStore` → `conn`). §3 release plan gating clause removed (items 17 and 18 no longer block implementation phase). |
| 19 June 2026 (session 5) | **Doc audit.** Full read of all docs against code (repomix export). Findings: `reconstruction_algorithms.md` §2 has a blocking issue (Place-conclusion language throughout, despite the Place conclusion object being retired); §1.5 names Jellyfish rather than rapidfuzz; Jaccard used for co-occupant overlap (likely should be Szymkiewicz–Simpson). `validate_object()` in `validator.py` still treats `role` as required and carries a dead `'place'` obj_type entry. `repositories.md` §4 has two stale CLI commands (pre-existing item 12). `validation_rules.md` DataStore issue was already resolved in v2.8 — ROADMAP status corrected from ⚠️ to ✅. `conceptual_model.md` version corrected from v2.6 to v2.7 in ROADMAP table. New work queue items 16–21 added. |
| 18 June 2026 (session 4) | **Data layer rebuild complete — `database_schema.md` v3.1.** Pulled the actual `schema.sql` and `src/dal/*.py` from the repo to ground the rewrite rather than guessing: confirmed `place_authority` already exists in code (the doc's DDL just never carried it), confirmed `training_labels` is fully implemented with the exact decision-lifecycle/index DDL now reflected in §3, and discovered along the way that `name_variant` is defined in schema but has no DAL writer anywhere — flagged in §1 and §6 rather than silently fixed. Resolved all `database_schema.md` drift items: restored `place_authority`, removed the obsolete `place` table, added `event.is_primary` and `training_labels` to the DDL, rewrote §6 to describe the real `src/dal/` repo-per-table pattern in place of the nonexistent `DataStore` class. Carried the v2.6/v2.7 target design (RecordedRelationship, RecordSimilarity, the Person/Relationship evidence-correspondence rename) into the DDL, marked `[target]` throughout and called out explicitly in §1 and §9 as not yet reflected in `PRAGMA user_version`. Data layer phase of the architecture rebuild (conceptual model → data dictionary → database schema) is now complete; implementation phase is next (Work Queue item 15). |
| 17 June 2026 (session 3) | **Data layer alignment:** Resolved the open Relationship evidence-FK decision in favour of RecordedRelationship, generalised as Rule 2 (evidence correspondence) and applied symmetrically to Person→RecordedPerson; conceptual_model.md bumped to v2.6. Aligned data_dictionary.md to v2.7: added RecordedRelationship/RecordSimilarity field tables, `event.is_primary`, fixed `recorded_person.role` nullability and `unknown` vocab, renamed `Person`/`Relationship` evidence FKs and their junction tables to match. Data layer phase of the architecture rebuild now complete for `data_dictionary.md`; `database_schema.md` is next. |
| 17 June 2026 (session 2) | **Conceptual model v2.5:** Added RecordedRelationship and RecordSimilarity as Evidence-layer objects, recording relationships and algorithmic similarity between evidence units without requiring a conclusion. Formalised Event consensus arbitration as Rule 9 — competing Events of the same type may coexist per Person, exactly one marked `is_primary`; Person and Relationship explicitly excluded, for different reasons. Retired `training_labels` as a considered-and-built-then-rejected path. Fixed stale CLI examples and the stale "eleven objects" count. Identified that `database_schema.md`'s prior "Complete" status was inaccurate (DDL out of sync with `schema.sql`) and corrected it here. Started the multi-session architecture rebuild: conceptual model → data layer → implementation. |
| 17 June 2026 | **Consolidation:** Resolved path drift, implemented migration scripts (v2.8→v3.0), restored roadmap structure, archived inactive documentation, and sync'd constraint versioning to v1.2. |
| 16 June 2026 | **Schema v3.0:** Finalized (`event.is_primary`, nullable roles). Linkage correctness pass: `link_only`, `_UnionFind`, Positional pairing, Per-merge transactions. |
| Early June 2026 | **Schema v2.8:** RecordedEvent merged into Record; junction tables 9→5. First full linkage test (3881 persons, 264 merged). Relationship features added. |
| 24 May 2026 | **Foundation & R1-1:** Initial GRA roadmap/rename established. Tier 1/2 complete; Tullynaught 1911 verified. Implemented place resolution and household inference (R1-1); established Release Plan (R1–R3). |
