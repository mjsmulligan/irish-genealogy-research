# Genealogy Research Assistant (GRA) — Project Roadmap

*Last updated: 27 June 2026*

---

## 1. Latest Update (27 June 2026)

Splink v1.2–v1.3: separated surname/forename features, disabled TF adjustment, added Soundex phonetic blocking for Irish surname variants. Threshold tuned 0.65→0.60 (+3.7pp linkage). Double-link prevention implemented (conflict detection, orphan cleanup, audit trail). Phase 1 linkage analysis complete: 21.1% overall = ~25–34% of the linkable population after demographic loss.

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
| `docs/validation_rules.md` | v2.8 | ✅ Current |
| `docs/reconstruction_algorithms.md` | v1.3 | ✅ Current |
| `docs/genealogical_constraints.md` | v1.3 | ✅ Current |
| `docs/review_layer.md` | v1.0 | ✅ Current |
| `ROADMAP.md` | — | ✅ Current |

### Implementation

| Layer | Status | Notes |
|---|---|---|
| Foundation | ✅ Complete (v3.2) | Schema v3.2: scores allowed for all relationship types |
| Evidence | ✅ Complete | `add-evidence` CLI: steps [1/5]–[5/5] |
| Conclusion | ✅ Complete | `conclude` CLI: steps [1/3]–[3/3] |
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

Three-step pipeline via `python -m src.cli conclude`:

1. **Person Resolution** — Union-Find clustering on person similarity ≥ 0.60 (`src/conclusion/person_resolution.py`)
2. **Relationship Resolution** — household matching → Person creation + Relationship conclusions (`src/conclusion/relationship_resolution.py`)
3. **Event Resolution** — census, calculated birth, and marriage Events (`src/conclusion/event_resolution.py`)

### 3.4 Integration Test Harness ✅

`tests/test_pipeline.py` — 59 tests. See §5 for exact counts.

---

## 4. Work Queue

Active and open items only. Completed items are in §8 (Version History).

| # | Item | Priority | Notes |
|---|---|---|---|
| 15 | **Pin floor counts in test harness.** Five TODO-marked constants: `FLOOR_RECORD_SIMS`, `FLOOR_PERSON_SIMS`, `FLOOR_PERSONS`, `FLOOR_RELATIONSHIPS`, `FLOOR_EVENTS` — pin after first confirmed clean run. | High | Next session |
| 20 | **Manual ID management in DAL.** `record_repo.py`, `person_repo.py`, `relationship_repo.py`, `event_repo.py` pre-calculate `MAX(...) + 1` IDs and use `OVERRIDING SYSTEM VALUE` inserts. Migrate all writes to RETURNING throughout. | Medium | |
| 26 | **`event_resolution.py` marriage event `date_qualifier`.** `_create_marriage_event()` passes `date_qualifier=None` when date is also None. Consider using `'estimated'` to signal inference rather than true absence. Minor consistency point. | Low | |
| 34 | **Test harness: schema v4.0 updates.** Add tests covering: (a) `reviewer` seeded rows present after init; (b) `conclusion_log` populated after `conclude` run; (c) `status='active'` default on all three conclusion tables; (d) migration 002 idempotency. Update `SCHEMA_VERSION` assertion from 32 → 40. | High | Next session |
| 7 | **Stale schema-version footers** — audit all `docs/` files. | Low | |
| 11 | **Remove `training_labels`** from `schema.sql` and `training_repo.py`. Conceptually retired (v2.5); removal deferred. | Low | |
| 14 | **`place_resolution.py` stale type hints** — `sqlite3.Connection` at lines 99 and 181. Cosmetic only; fix when next touching that file. | Low | |
| 36 | **Parish ingest pipeline.** Implement `src/evidence/parish.py`: baptism CSV → Record + RecordedPersons (child, father, mother, sponsors) + RecordedRelationships; marriage CSV → Record + RecordedPersons (groom, bride, witnesses) + RecordedRelationships. Blocked on item 37 (data dictionary) and item 39 (transcription repo CSV output). | High (R3) | |
| 37 | **Data dictionary update for parish records.** Add `sponsor` to RecordedPerson role vocabulary. Add `sponsor` and `witness` to RecordedRelationship type vocabulary. Document three-state transcription field convention: empty (absent), `[?]` (illegible), value (as written). | Medium (R3) | Before item 36 |
| 38 | **`export-vocab` CLI command.** Aggregate census name/place distributions by parish and export to `{parish_id}_vocab.json` for the transcription pipeline's confidence scoring module. Blocked on vocabulary file contract — dedicated session required. See §6.2. | Medium (R3) | After vocabulary contract session |
| 39 | **Spawn transcription repo.** Create new GitHub repository for the NLI Catholic parish register transcription pipeline. The three CSV schemas (register index, parish baptism, parish marriage) plus bounding box envelope fields are the formal interface contract with GRA. | High (R3) | Prerequisite for item 36 |
| 40 | **Test harness: household_resolution coverage.** Add tests for `src/conclusion/household_resolution.py` and `src/conclusion/household_utils.py`. Cases to cover: (a) anchor-extension creates Person for unlinked spouse/child; (b) anchor as non-head (Case B/C); (c) no RecordedRelationship to anchor — member skipped; (d) score inherited from RecordedRelationship prior; (e) idempotency (re-run adds no duplicate Persons or Relationships). Update step-counter assertions from [4/4] to [5/5]. | High | After household_resolution merged |
| 41 | **Household contradiction validation (review layer).** After `household_resolution` is proven in production, add a validation finding that flags Relationship conclusions contradicted by intra-census household evidence — e.g. two Persons concluded as `couple` whose RecordedPersons appear in the same household as `head` and `son`. Warning-level only at v1; auto-action to be decided after first review run. | Medium | After item 40 |

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
| 27 June 2026 | Splink v1.3 phonetic blocking. v1.2 separated name components, disabled TF adjustment. Threshold 0.65→0.60 (+3.7pp linkage). Double-link prevention. Phase 1 linkage analysis complete. |
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
