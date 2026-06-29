# Genealogy Research Assistant (GRA) — Project Roadmap

*Last updated: 29 June 2026*

---

## 1. Latest Update (29 June 2026)

Roadmap low-hanging-fruit pass (items 7, 14, 26, 43, 47) plus systematic foundation and evidence layer review.

**Roadmap items closed:** Item 7 (stale doc footers — `database_schema.md` and `reconstruction_algorithms.md` updated); Item 14 (`place_resolution.py` sqlite3 type hints — all three fixed, psycopg2.extensions import added); Item 47 (`find_link_conflicts_resolved` removed from `run_all_findings()`). Items 26 and 43 de-scoped (design intent confirmed).

**Bugs fixed in evidence/genealogy layer review:**

- **B1 — `jean` in `IRISH_MALE_NAMES` (wrong):** Jean as a written name in Irish census records is female (French female name). Removed from MALE set, added to FEMALE set. Also removed `jean` from `john`\'s variant set in `APPROVED_NAME_VARIANTS` — Seán/Jean phonetic similarity does not make written Jean a John variant for Splink matching.
- **B2 — `pat` and `fran` in both gender sets:** `infer_gender` checks MALE first, so `Pat Smith` and `Fran Kelly` always returned `'M'`. This caused false gender-flip violations for valid Patricia/Pat and Frances/Fran cross-census pairs. Both removed from both sets — ambiguous names now correctly return `None` (conservative; no false flip triggered).
- **B3 — `constraints.py` used explicit `DictCursor` override:** Both DB-sweeping functions overrode the connection\'s default `RealDictCursor` with `DictCursor` unnecessarily. Removed the overrides; `psycopg2.extras` import cleaned up.
- **B4 — `record_repo.py` docstring stale path:** Said `src/ingest/` (doesn\'t exist); corrected to `src/evidence/census.py`.

Full detail: [`changelog/changelog_summary.md`](changelog/changelog_summary.md)

---

## 2. Current State

### Documentation

| Document | Version | Status |
|---|---|---|
| `docs/conceptual_model.md` | v2.8 | ✅ Current |
| `docs/data_dictionary.md` | v2.7 | ✅ Current |
| `docs/database_schema.md` | v3.2 | ✅ Current |
| `docs/repositories.md` | v1.6 | ✅ Current |
| `docs/genealogical_constraints.md` | v1.3 | ✅ Current — sole authority for constraint rules and GC codes |
| `docs/validation_rules.md` | v2.8 | ⚠ Pending consolidation into `genealogical_constraints.md` (item 42) |
| `docs/reconstruction_algorithms.md` | v1.3 | ✅ Current |
| `docs/review_layer.md` | v1.0 | ✅ Current |
| `ROADMAP.md` | — | ✅ Current |

### Implementation

| Layer | Status | Notes |
|---|---|---|
| Foundation | ✅ Complete (v3.2) | Schema v4.3: scores allowed for all relationship types |
| Evidence | ✅ Complete | `add-evidence` CLI: steps [1/5]–[5/5] |
| Conclusion | ✅ Complete | `conclude` CLI: steps [1/5]–[5/5] |
| Genealogy | ✅ Complete | `src/genealogy/`: names, ages, constraints — replaces `src/validation/` |
| Testing | ✅ Complete | 59 tests passing (100%), fixed-fixture exact assertions |
| Review | ✅ Complete (v2.0) | `report.py`, `findings.py`, `priority.py`, `runner.py`. First run + training session next. |

---

## 3. Implementation

### 3.1 Foundation & Database Management ✅

### 3.2 Evidence Layer ✅

Five-step pipeline via `python -m src.cli add-evidence`:

1. Ingest CSV → Record + RecordedPerson (`src/evidence/census.py`)
2. Assign role relationships from household role pairs (`src/evidence/role_relationships.py`)
3. Place resolution → `place_record` linkage (`src/evidence/place_resolution.py`)
4. Splink record similarity, household-level (`src/evidence/similarity.py`)
5. Splink person similarity, person-level (`src/evidence/similarity.py`)

### 3.3 Conclusion Layer ✅

Five-step pipeline via `python -m src.cli conclude`:

1. **Person Resolution** — Union-Find clustering on person similarity ≥ 0.45 (`src/conclusion/person_resolution.py`)
2. **Relationship Resolution** — household matching → Person creation + Relationship conclusions (`src/conclusion/relationship_resolution.py`)
3. **Household Resolution** — anchor-extension for unlinked household members (`src/conclusion/household_resolution.py`)
4. **Event Resolution** — census, calculated birth, and marriage Events (`src/conclusion/event_resolution.py`)
5. **Validation Cleanup** — genealogical constraint sweep via `src/genealogy/` (`src/conclusion/validation_cleanup.py`)

### 3.4 Integration Test Harness ✅

`tests/test_pipeline.py` — 59 tests. See §5 for exact counts.

---

## 4. Work Queue

Active and open items only. Completed items are in §8 (Version History).

| # | Item | Priority | Notes |
|---|---|---|---|
| 15 | **Pin floor counts in test harness.** Five TODO-marked constants: `FLOOR_RECORD_SIMS`, `FLOOR_PERSON_SIMS`, `FLOOR_PERSONS`, `FLOOR_RELATIONSHIPS`, `FLOOR_EVENTS` — pin after first confirmed clean run. | High | Next session |
| 20 | **Manual ID management in DAL.** `record_repo.py`, `person_repo.py`, `relationship_repo.py`, `event_repo.py` pre-calculate `MAX(...) + 1` IDs and use `OVERRIDING SYSTEM VALUE` inserts. Migrate all writes to RETURNING throughout. | Medium | |
| 26 | **`event_resolution.py` marriage event `date_qualifier`.** De-scoped: `NULL` is intentional — it signals true absence (census doesn't record marriage date), not inference. Module header at line 29 documents this. | Low | ✅ De-scoped |
| 34 | **Test harness: schema v4.0 updates.** Add tests covering: (a) `reviewer` seeded rows present after init; (b) `conclusion_log` populated after `conclude` run; (c) `status='active'` default on all three conclusion tables; (d) migration 002 idempotency. Update `SCHEMA_VERSION` assertion from 32 → 40. | High | Next session |
| 7 | **Stale schema-version footers.** `database_schema.md` footer referenced `PRAGMA user_version` and v3.0; `reconstruction_algorithms.md` footer said "v3.1 target" and referenced non-existent `session_bootstrap.md`. Both corrected. | Low | ✅ Done 29 June 2026 |
| 11 | **Remove `training_labels`** from `schema.sql` and `training_repo.py`. Conceptually retired (v2.5). `training_repo.py` not imported anywhere in `src/`; `cli.py` only references table name in reset/truncate lists. Requires a schema migration bump to remove. | Low | Pending migration |
| 14 | **`place_resolution.py` stale type hints** — `sqlite3.Connection` at three locations (lines 112, 137 inline comment, 194). Added `import psycopg2.extensions`; all three corrected. | Low | ✅ Done 29 June 2026 |
| 36 | **Parish ingest pipeline.** Implement `src/evidence/parish.py`: baptism CSV → Record + RecordedPersons (child, father, mother, sponsors) + RecordedRelationships; marriage CSV → Record + RecordedPersons (groom, bride, witnesses) + RecordedRelationships. Blocked on item 37 (data dictionary) and item 39 (transcription repo CSV output). | High (R3) | |
| 37 | **Data dictionary update for parish records.** Add `sponsor` to RecordedPerson role vocabulary. Add `sponsor` and `witness` to RecordedRelationship type vocabulary. Document three-state transcription field convention: empty (absent), `[?]` (illegible), value (as written). | Medium (R3) | Before item 36 |
| 38 | **`export-vocab` CLI command.** Aggregate census name/place distributions by parish and export to `{parish_id}_vocab.json` for the transcription pipeline's confidence scoring module. Blocked on vocabulary file contract — dedicated session required. See §6.2. | Medium (R3) | After vocabulary contract session |
| 39 | **Spawn transcription repo.** Create new GitHub repository for the NLI Catholic parish register transcription pipeline. The three CSV schemas (register index, parish baptism, parish marriage) plus bounding box envelope fields are the formal interface contract with GRA. | High (R3) | Prerequisite for item 36 |
| 40 | **Test harness: household_resolution coverage.** Add tests for `src/conclusion/household_resolution.py` and `src/conclusion/household_utils.py`. Cases to cover: (a) anchor-extension creates Person for unlinked spouse/child; (b) anchor as non-head (Case B/C); (c) no RecordedRelationship to anchor — member skipped; (d) score inherited from RecordedRelationship prior; (e) idempotency (re-run adds no duplicate Persons or Relationships). Update step-counter assertions from [4/4] to [5/5]. | High | After household_resolution merged |
| 41 | **Household contradiction validation (review layer).** After `household_resolution` is proven in production, add a validation finding that flags Relationship conclusions contradicted by intra-census household evidence — e.g. two Persons concluded as `couple` whose RecordedPersons appear in the same household as `head` and `son`. Warning-level only at v1; auto-action to be decided after first review run. | Medium | After item 40 |
| 42 | **`validation_rules.md` → `genealogical_constraints.md` consolidation.** Two documents cover overlapping content with two numbering schemes (R-codes and GC-codes). `genealogical_constraints.md` v1.4 is the sole authority; code references GC codes only. Merge remaining `validation_rules.md` content; retire the file or reduce it to a pointer. Update `review_layer.md` §6.1 reference. | Medium | |
| 43 | **`is_primary = 1` → `is_primary = TRUE` sweep in `findings.py`.** De-scoped: `event.is_primary` is `INTEGER CHECK (is_primary IN (0, 1))` — not BOOLEAN. `= 1` is the correct SQL predicate now. Revisit if column type migrates to BOOLEAN. | Low | ✅ De-scoped |
| 44 | **Sequence check should prefer `is_primary` dates (`find_life_event_sequence_violations()`).** Currently uses `earliest_year()` across all events of a type — a non-primary event with a bad date can trigger a spurious violation. Use `_derive_birth_year()` / `_derive_death_year()` helpers instead. | Medium | |
| 45 | **Marriage singularity (GC06) not in findings layer.** Birth (GC04) and death (GC05) have singularity findings; marriage does not. Add `find_marriage_singularity_violation()`. See `genealogical_constraints.md` GC06. | Medium | |
| 46 | **N+1 birth/death year queries in `findings.py`.** `_derive_birth_year()` / `_derive_death_year()` issue 2–3 queries per person in per-person loops. Pre-fetch all birth/death years for active persons in a single query at `run_all_findings()` start. | High | Before Donegal-scale data |
| 47 | **`find_link_conflicts_resolved()` permanent placeholder.** Removed from `run_all_findings()`. Function and taxonomy entry retained with deferred-status note for when `conclusion_log` audit trail persistence is implemented. | Low | ✅ Done 29 June 2026 |

---

## 5. Test Harness Reference

**Exact Tullynaught counts (fixed fixtures, 21 June 2026):**

| Metric | Value | Derivation |
|---|---|---|
| Records — 1901 | 263 | CSV unique `image_group` values |
| Records — 1911 | 240 | CSV unique `image_group` values |
| Records — 1926 | 212 | CSV unique `image_group` values |
| Records — total | 715 | Sum |
| Recorded persons — 1901 | 1,193 | CSV row count |
| Recorded persons — 1911 | 1,080 | CSV row count |
| Recorded persons — 1926 | 894 | CSV row count |
| Recorded persons — total | 3,167 | Sum |
| Role rels — couple | 347 | Role-pair rule simulation |
| Role rels — parent_child | 2,624 | Role-pair rule simulation |
| Role rels — sibling | 2,952 | Role-pair rule simulation |
| Role rels — total | 5,923 | Sum |
| Place links | 715 | 100% match rate — all 31 inhabited townlands pass JW ≥ 0.88 |
| Birth year plausibility | 1807–1928 | Max age 92 in 1901 → 1807; age 0 in 1926 → 1928 |

**Authoritative place data (logainm, 23 June 2026):**
- 33 townlands total; `Croaghnakern` and `Rooney's Island` uninhabited
- `Drummenny Upper` is logainm canonical (double-m); normalization handles consonant variants
- Compound names like "Tullyleague or Tullybrook" normalized to primary name (first part)

**Floor counts (item 15 — pin after first clean run):**
`FLOOR_RECORD_SIMS`, `FLOOR_PERSON_SIMS`, `FLOOR_PERSONS`, `FLOOR_RELATIONSHIPS`, `FLOOR_EVENTS`

---

## 6. Design Notes

### 6.1 Review Layer

Spec: [`docs/review_layer.md`](docs/review_layer.md)

`ReportItem`/`Report` data structures, finding taxonomy (v1.0 implemented + deferred), priority scoring, and output format are all defined there. The retired `src/review/validator.py` and its rule codes (R40–R46) are documented in [`docs/validation_rules.md`](docs/validation_rules.md).

---

### 6.2 Vocabulary File Contract (open — dedicated session required)

GRA will export a parish-level name/place vocabulary file consumed by the transcription pipeline's confidence scoring module. This is the primary interface between GRA's evidence layer and the transcription repo beyond the CSV schemas.

**Design principles agreed (26 June 2026):**
- File existence check only in the transcription pipeline — no hard dependency. If absent, confidence scoring is skipped.
- Confidence adjustment is a signal, not a correction — transcription value never changes.
- Census data used post-transcription only (preserves recorded-as-is contract).
- Raw counts preferred over normalised frequencies.
- Gendered forename sets for accurate confidence matching.
- Townlands as a separate set from surnames (different semantic role, stronger signal).

**GRA-side implementation:** `python -m src.cli export-vocab --parish <parish_id> --output <path>`

**File naming convention:** `{parish_id}_vocab.json`

**Format and field structure:** not yet decided. Dedicated session required before either repo implements against this contract. See item 38.

---

## 7. Release Targets

- **v1.x (Current):** Foundation, evidence, and conclusion layers complete. Integration test harness complete. Priority next steps: item 15 (pin test counts), item 34 (test harness v4.0 updates), item 40 (household_resolution test coverage), item 41 (household contradiction validation).
- **v2.0 (Target):** Review layer complete ✅. First run + training session against Supabase. Full-scale Irish Census ingestion.
- **v3.0 (Long-term):** Parish and civil BMD ingest. Depends on transcription repo (item 39) producing CSV output and parish ingest pipeline (item 36) consuming it.

---

## 8. Version History

Full session history with links to detailed changelog files: [`changelog/changelog_summary.md`](changelog/changelog_summary.md)

| Date | Milestone |
|---|---|
| 28 June 2026 | `src/validation/` retired. `src/genealogy/` created as materialisation of `genealogical_constraints.md`. Seven bugs fixed: age tolerances (±2 flat → ±3/±4 per census pair), deletion of both sides of flagged pairs, `classify_forename()` `'exact'` return, `household_same_census_errors` always zero, five duplicate inline source-year dicts, deferred import in `relationship_resolution.py`, duplicate dict key in `APPROVED_NAME_VARIANTS`. Six callers updated. `genealogical_constraints.md` v1.4: `[→ Validation rule candidate]` pattern retired; §10 implementation table rewritten against actual code. |
| 28 June 2026 | Household resolution new conclusion step [3/5]. Anchor-extension for unlinked household members via RecordedRelationship paths. `household_utils.py` extracted. Conclusion pipeline 3-step → 5-step. |
| 26 June 2026 | R3 transcription pipeline discovery. Spawned as independent repo. Hybrid HTR pipeline designed. Bounding box fields added to CSV schemas. Vocabulary file contract drafted. |
| 25 June 2026 | R3 parish records early discovery. Recorded-as-is contract. Three-file register structure. `sponsor` and `witness` vocabulary added. |
| 24 June 2026 | Review layer design (session 18) and implementation (session 19) complete. `validator.py` replaced by four-module report system. |
| 23 June 2026 | Schema v4.0: `reviewer` table, `conclusion_log`, `status`/`pending_delete_at` on conclusion tables. Test suite 100% (59/59). Schema v3.2. |
| 22 June 2026 | Dead code removal. `src/evidence/features/` package created. `NOT EXISTS` query fix. Stale `sqlite3` imports removed. |
| 21 June 2026 | Critical conclusion layer bug fixes (items 21–25). Integration test harness (59 tests). Conclusion layer complete. Evidence layer complete with PostgreSQL. |
| 20 June 2026 | Foundation complete (v3.1). SQLite → PostgreSQL / Supabase migration. Evidence layer implementation. |
| 17–19 June 2026 | Conceptual model v2.5. RecordedRelationship, RecordSimilarity. `database_schema.md` v3.2. Doc audit. |
| 16 June 2026 | Schema v3.0: `event.is_primary`, nullable roles. |
| Early June 2026 | Schema v2.8: RecordedEvent merged into Record; junction tables 9→5. First full linkage test. |
| 24 May 2026 | Foundation & R1-1. Initial GRA roadmap. Place resolution and household inference. |
