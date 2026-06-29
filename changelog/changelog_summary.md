# GRA — Changelog Summary

Complete session history for the Genealogy Research Assistant project. Detailed session files are linked where they exist.

---

## 28 June 2026 — Genealogy Layer (`src/genealogy/`)

Detailed file: [`session_changelog_2026-06-28b.md`](session_changelog_2026-06-28b.md)

Full pipeline validation audit followed by architectural refactor. The core finding: genealogical domain knowledge had no authoritative home — it was duplicated across three modules with inconsistent tolerances, partially bypassed, and mixed with pipeline orchestration logic.

**Decision:** `src/validation/` retired. New `src/genealogy/` module created as the materialisation of `docs/genealogical_constraints.md`. Three sub-modules: `names.py` (Irish name variant and gender dictionaries), `ages.py` (census age tolerance rules), `constraints.py` (pairwise evaluation, DB sweeps, deletion). Single public interface via `__init__.py`.

**Bugs fixed in the same pass:**

- **Age tolerance** (B1): flat ±2 years replaced by per-pair tolerances from `CENSUS_AGE_TOLERANCE` dict (1901↔1911: ±3, 1911↔1926: ±3, 1901↔1926: ±4). Was a material contributor to false negatives pushing `PERSON_RESOLUTION_THRESHOLD` to 0.45.
- **Deletion only one side of flagged pair** (B2): `recorded_person_id_2` was always a copy of `recorded_person_id_1` in the flagged pair dict. `remove_flagged_linkages()` now deletes both linkages per pair.
- **`classify_forename()` never returned `'exact'`** (B3): the highest Splink comparison tier (`name_first_name_variant = 'exact'`) was permanently dead. Fixed — canonical names (dict keys) now return `'exact'`, aliases return `'approved'`.
- **`household_same_census_errors` always zero** (B4): field declared but never assigned. Stale field removed; `check_household_coherence()` returns distinct counts.
- **Inline `{3: 1901, 4: 1911, 5: 1926}` dict** (B5): appeared in five files independently. All replaced by `CENSUS_YEAR` from `src/genealogy/ages.py`.
- **Deferred import in `relationship_resolution.py`** (B6): `from src.validation import validate_age_progression` inside function body replaced by top-level import from `src.genealogy`.
- **Duplicate `william` key in `APPROVED_NAME_VARIANTS`** (B7): second entry silently overwrote first, losing three variant aliases.

**Six callers updated:** `census_person.py`, `similarity.py`, `person_resolution.py`, `relationship_resolution.py`, `validation_cleanup.py`, `cli.py`.

**`validate-linkages` CLI output** updated: heading renamed to "GENEALOGICAL CONSTRAINT REPORT"; gender flips now shown as a distinct violation count.

**ROADMAP items added:** 42 (`validation_rules.md` consolidation into `genealogical_constraints.md`), 43 (`is_primary = TRUE` sweep in `findings.py`), 44 (sequence check prefer `is_primary` dates), 45 (marriage singularity finding GC3.3), 46 (N+1 query fix in `findings.py`), 47 (`find_link_conflicts_resolved` placeholder — implement or remove).

---

## 28 June 2026 — Household Resolution (New Conclusion Pipeline Step)

Detailed file: [`session_changelog_2026-06-28.md`](session_changelog_2026-06-28.md)

Gap identified from review reports: Persons only created when a RecordedPerson matched across multiple census years. Households where some members linked cross-census and others did not were left partially resolved.

**New step [3/5]: `household_resolution`.** If at least one RecordedPerson in a household has become a Person (anchor), any remaining unlinked RecordedPerson connected to that anchor via a RecordedRelationship is promoted to a Person conclusion. Co-presence alone is not sufficient — a RecordedRelationship path is required, which naturally excludes visitors, boarders, and other non-family roles. Operates within a single census only. Score inherited from the RecordedRelationship prior (0.75–0.90). After Person creation, Relationship conclusions derived from the fuller household.

**New: `src/conclusion/household_utils.py`.** Shared helpers extracted from `relationship_resolution.py`: `get_household_members`, `ensure_relationship`, `create_relationships_from_household`. Both `relationship_resolution.py` and `household_resolution.py` import from here.

**Modified: `relationship_resolution.py`.** Three extracted functions removed; imports added from `household_utils`. Unused `Optional` and `defaultdict` imports removed.

**Modified: `src/constants.py`.** `SCORE_VERSION_HOUSEHOLD_EXTENSION = "household_extension_v1.0"` added.

**Modified: `src/cli.py`.** Conclusion pipeline wired as [1/5]–[5/5]. All step counters, docstrings, and help text updated.

**ROADMAP items added:** 40 (test harness coverage for new step), 41 (household contradiction validation — review layer finding, warning-level, deferred until item 40 complete). No schema changes; no migration required.

---

## 27 June 2026 — Splink v1.2–v1.3, Threshold Tuning, Phase 1 Analysis

**Sessions 27 & 28 + supporting analysis files**

Detailed files:
- [`SESSION_27_SUMMARY.md`](SESSION_27_SUMMARY.md) — Phase 3 regression analysis, test infrastructure, pipeline restoration
- [`SESSION_28_SUMMARY.md`](SESSION_28_SUMMARY.md) — CLI optimisation, probabilistic matching variance acceptance, test infrastructure
- [`IMPLEMENTATION_COMPLETE.md`](IMPLEMENTATION_COMPLETE.md) — Phase 3 implementation detail
- [`DEPLOYMENT_READY.md`](DEPLOYMENT_READY.md) — v1.3 deployment approval (0.50 threshold)
- [`PERFORMANCE_ANALYSIS.md`](PERFORMANCE_ANALYSIS.md) — Performance analysis and optimisation results
- [`PHASE3_SUMMARY.md`](PHASE3_SUMMARY.md) — Phase 3 (Role Consistency Weighting) implementation
- [`PHASE3_ACTUAL_RESULTS.md`](PHASE3_ACTUAL_RESULTS.md) — Measured results vs expected
- [`PHASE3_REAL_MEASUREMENT.md`](PHASE3_REAL_MEASUREMENT.md) — Local test database measurement
- [`PHASE3_REGRESSION_ANALYSIS.md`](PHASE3_REGRESSION_ANALYSIS.md) — Regression detected and root-caused
- [`PHASE3_FIX_COMPLETE.md`](PHASE3_FIX_COMPLETE.md) — Regression fix verified
- [`SESSION_SUMMARY.md`](SESSION_SUMMARY.md) — Pipeline fix and test infrastructure
- [`WORK_COMPLETED.md`](WORK_COMPLETED.md) — Test infrastructure and Phase 3 metrics
- [`TEST_SETUP_SUMMARY.md`](TEST_SETUP_SUMMARY.md) — Clean database state and metrics definitions

**Summary of changes:**

*v1.3 — Soundex phonetic blocking.* Replaced `substr(surname, 1, 4)` with pre-computed Soundex codes so phonetic surname variants block together (O'Brien / Brien / O Brien → B650). Blocking rules: `place_id` (primary) → soundex (secondary) → substr (fallback). Implemented in `src/evidence/similarity.py`, `src/evidence/features/census.py`, `src/evidence/features/census_person.py`.

*v1.2 — Separated name components, disabled TF.* Split `name_norm` into separate `surname_norm` and `forename_norm` Jaro-Winkler comparisons. Disabled `term_frequency_adjustments` for both — TF penalises common names (e.g. "Robert Bustard" exact match → 0.528) which is wrong for cross-census matching. EM training now learns independent weights per component.

*Threshold tuning.* Person linkage improved from 17.4% → 21.1% (+3.7pp) by lowering the resolution threshold 0.65 → 0.60. Root cause: TF penalty pushes valid cross-census matches into the 0.50–0.65 range. No feature changes required.

*Double-link prevention.* Three-part solution: (1) `_get_recorded_person_link()` detects conflicts before re-linking — Step 1 assignment preserved on conflict. (2) Orphaned Persons (zero linked RecordedPersons after relationship resolution) deleted. (3) `LinkConflict` dataclass provides audit trail; surfaced in review report as `link_conflict_resolved` finding type. All 59 tests pass.

*Phase 1 linkage analysis.* 21.1% overall linkage = ~25–34% of the linkable population after demographic loss (TB epidemic 1911–1926 accounts for 20–30% of unlinked). Analysis bug fixed: initial report used `aform_name` instead of `image_group` for 1926 household grouping. Analysis files written to `analysis/`.

---

## 26 June 2026 — R3 Transcription Pipeline Discovery

Detailed file: [`session_changelog_2026-06-26.md`](session_changelog_2026-06-26.md)

HTR strategy for NLI Catholic parish registers explored (vtls000631954, 1873–1881 baptisms — four sample images, three quality tiers). Key decisions: transcription pipeline spawned as independent repo (`src/transcription/` will not be built within GRA); hybrid tiered pipeline (image QA → layout detection → tiered HTR → field parsing → confidence adjustment → CSV); bounding box coordinates added to all three CSV schemas; census vocabulary file as loose-coupling interface (`{parish_id}_vocab.json`); Transkribus Beyond 2022 identified as best pre-trained model for Irish archival handwriting (759,000 words, 50 styles). Work queue: item 35 superseded, items 38 and 39 added. §5.10 (vocabulary file contract) added to ROADMAP.

---

## 25 June 2026 — R3 Parish Records Early Discovery

Detailed file: [`session_r3_discovery.md`](session_r3_discovery.md)

NLI Catholic parish register collection explored. LLM transcription experiments reviewed (Tawnawilly baptisms 499 records, Ballyoughter baptisms 1,310 records, Tawnawilly marriages 102 records). Six source images examined. Recorded-as-is contract established. Three-file structure per register defined (index, baptisms, marriages). `sponsor` added to RecordedPerson role vocabulary and RecordedRelationship type vocabulary; `witness` added to RecordedRelationship type vocabulary. High-res image URL pattern documented. Work queue items 35, 36, 37 added.

---

## 24 June 2026 — Review Layer Implementation (Session 19)

Detailed file: [`SESSION_19_SUMMARY.md`](SESSION_19_SUMMARY.md)

`src/review/validator.py` deleted. Four new modules created: `report.py` (ReportItem + Report dataclasses, JSON + Markdown serialisers), `findings.py` (nine v1.0 finding functions), `priority.py` (three-tier base score × scope multiplier → integer rank), `runner.py` (assembles report, writes paired JSON + Markdown to `reports/`). `validate` CLI subcommand replaced by `review`. Item 13 complete.

---

## 24 June 2026 — Review Layer Design (Session 18)

Detailed file: [`SESSION_18_SUMMARY.md`](SESSION_18_SUMMARY.md)

`src/review/validator.py` retired in full — not ported. New design derived from `genealogical_constraints.md` and conceptual model §7.4. ReportItem and Report structures defined. Nine v1.0 finding types specified; five deferred to post-training-session. Priority scoring approach agreed. Paired JSON + Markdown output to `reports/`. `validation_rules.md` updated with supersession note. §5.9 added to ROADMAP.

---

## 23 June 2026 — Schema v4.0 / Review Layer Foundation (Session 17)

Conceptual model v2.8 §7 added (Reviewer entity, conclusion log, conclusion lifecycle). `reviewer` table and append-only `conclusion_log` audit table added to schema. `status`/`pending_delete_at` added to `person`, `relationship`, and `event`. Two system reviewers seeded (`pipeline:system`, `human:unknown`). Migration `002_review_layer.sql` safe for populated databases; backfills existing conclusions as `pipeline:system`. `conclusion_log_repo.py` created with `log_action`, `log_create`, `log_update`, `log_delete`, `log_verify`, `get_or_create_reviewer`, `new_change_group`. Pipeline wired: `person_resolution.py`, `relationship_resolution.py`, `event_resolution.py` all call `log_create` after conclusion inserts. `SCHEMA_VERSION` 32 → 40. Item 34 added.

---

## 23 June 2026 — Test Suite 100% + Schema v3.2 (Session 15)

Detailed file: [`SESSION_15_SUMMARY.md`](SESSION_15_SUMMARY.md)

Item 32: fixed NULL scores in role-pair RecordedRelationships — `role_relationships.py` now passes prior scores (0.75–0.90) with `SCORE_VERSION_ROLE_PAIR`. Migration `001_allow_scores_all_relationship_types.sql` removes restrictive CHECK constraint. All 5,923 role-pair relationships now have scores. Item 33: enhanced place normalisation for "X or Y" compound names and double consonant variants. Test harness 59/59 passing (100%), up from 57/59. Schema 3.1 → 3.2.

---

## 23 June 2026 — Performance Analysis (Session 16)

Detailed file: [`SESSION_16_SUMMARY.md`](SESSION_16_SUMMARY.md)

---

## 22 June 2026 — Dead Code Removal + Feature Package (Session 14)

`src/evidence/features/` package created (`census.py` = `build_census_household_features`, `census_person.py` = `build_census_person_features`); `similarity.py` imports updated. `get_unprocessed_census_records()` rewritten as `NOT EXISTS` with correct join on `rp.record_id`. Orphan/duplicate/dead functions and stale `sqlite3` imports removed across `record_repo.py`, `place_repo.py`, `person_repo.py`, `evidence/census.py`, `fetch_places.py`, `seed_places.py`. All stale type hints fixed; broken `--db` CLI path in `fetch_places.main()` fixed. Items 16–19, 27–31 closed.

---

## 21 June 2026 — Critical Conclusion Layer Bug Fixes (Session 13)

`relationship_resolution.py`: re-fetch household members from DB after Person assignments (item 23); `_ensure_relationship()` now populates `relationship_recorded_relationship` provenance (item 24); census_gap derived from record dates and passed to `_match_score` (item 21); JaroWinkler ≥ 0.85 via rapidfuzz replaces exact name match (item 22). `event_resolution.py`: one census Event per Record with all household Persons linked via `person_event` (item 25).

---

## 21 June 2026 — Integration Test Harness + Full Code Review (Session 12)

`tests/test_pipeline.py` created: 59 tests with exact Tullynaught fixture counts. Full review of all active `src/` modules. 17 new work items added (items 16–32). Critical correctness issues identified in `relationship_resolution.py` (items 23, 24) and `event_resolution.py` (item 25).

---

## 21 June 2026 — Conclusion Layer Complete (Session 11)

`src/conclusion/` complete (`person_resolution.py`, `relationship_resolution.py`, `event_resolution.py`). `src/pipeline/` nominally retired. `cli.py` rewritten.

---

## 21 June 2026 — Evidence Layer Complete

Person-level similarity added as evidence step [5/5] (`run_person_similarity()` in `src/evidence/similarity.py`). Evidence layer verified complete with PostgreSQL. Place resolution integrated as step [3/5].

---

## 20 June 2026 — Foundation Implementation Complete (v3.1)

`src/evidence/similarity.py` created; evidence layer implementation complete. SQLite retired; migrated to PostgreSQL / Supabase. Foundation complete at v3.1.

---

## 19 June 2026 — `database_schema.md` v3.2

R47–R50 mapped to DDL-level CHECK constraints.

---

## 18–19 June 2026 — Doc Audit and Fixes

`repositories.md` v1.6, `future_ideas.md` v1.2, `reconstruction_algorithms.md` v1.3.

---

## 17–18 June 2026 — Conceptual Model v2.5 / Data Layer Alignment

RecordedRelationship and RecordSimilarity objects introduced. Rule 9 added. `data_dictionary.md` v2.7.

---

## 17 June 2026 — Consolidation

Path drift resolved. Migration scripts added. Roadmap structure restored.

---

## 16 June 2026 — Schema v3.0

`event.is_primary` added. RecordedPerson roles made nullable.

---

## Early June 2026 — Schema v2.8

RecordedEvent merged into Record. Junction tables reduced 9 → 5. First full linkage test.

---

## 24 May 2026 — Foundation & R1-1

Initial GRA roadmap. Place resolution and household inference implemented.
