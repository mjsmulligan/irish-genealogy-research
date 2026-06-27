# Genealogy Research Assistant (GRA) — Project Roadmap

*26 June 2026 (session R3 transcription discovery)*

______________________________________________________________________

## 0. Latest Update (27 June 2026 — Age Variance Analysis & Threshold Tuning)

**Person linkage improved from 17.4% to 21.1% (+3.7pp)** by lowering resolution threshold from 0.65 to 0.60.

Root cause analysis (SQL-driven):
- Compared linked persons across censuses (173 valid pairs)
- Found age variance: mean +11 years (not +10), stdev 3.3, within ±7 covering 94.2%
- Splink name matching with Term Frequency adjustment heavily penalizes common names:
  - "Robert" (34 occ), "Bustard" (20 occ) → "Robert Bustard" exact match scores only 0.528
  - Many valid cross-census matches fall in 0.50–0.65 range due to TF penalty
- Solution: Lower threshold to 0.60 to capture TF-penalized common names
- No Splink feature changes required (avoids double-linking issues from 0.55 threshold test)

Validation:
- All 59 integration tests pass
- No data integrity issues
- No clustering corruption
- Improvements align with domain knowledge (common surnames in rural Irish census)

Next: Further tuning via Splink EM parameter calibration or selective TF adjustment for cross-census matching.

______________________________________________________________________

## 1. Current State

### Documentation

| Document | Status | Notes |
|---|---|---|
| `docs/conceptual_model.md` | ✅ Complete (v2.8) | |
| `docs/data_dictionary.md` | ✅ Complete (v2.7) | |
| `docs/database_schema.md` | ✅ Complete (v3.2) | |
| `docs/repositories.md` | ✅ Complete (v1.6) | |
| `docs/validation_rules.md` | ✅ Complete (v2.8) | |
| `docs/reconstruction_algorithms.md` | ✅ Complete (v1.3) | |
| `docs/genealogical_constraints.md` | ✅ Complete (v1.3) | |
| `ROADMAP.md` | ✅ Current | |

### Implementation

| Layer | Status | Notes |
|---|---|---|
| Foundation | ✅ Complete (v3.2) | Schema v3.2: scores allowed for all relationship types |
| Evidence | ✅ Complete (v3.2) | `add-evidence` CLI complete: [1/5]–[5/5] |
| Conclusion | ✅ Complete | `conclude` CLI: [1/3]–[3/3] |
| Testing | ✅ Complete | `tests/test_pipeline.py`: 59 tests passing (100%), fixed-fixture exact assertions |
| Review | ✅ Complete (v2.0) | `src/review/`: `report.py`, `findings.py`, `priority.py`, `runner.py`. `validator.py` deleted. CLI: `python -m src.cli review`. First run + training session next. |

______________________________________________________________________

## 2. Implementation

### 2.1 Foundation & Database management ✅

### 2.2 Evidence Layer ✅

Five-step pipeline via `cli add-evidence`:

1. Ingest CSV → record + recorded_person (`src/evidence/census.py`) ✅
1. Assign role relationships from household role pairs (`src/evidence/role_relationships.py`) ✅
1. Place resolution → place_record linkage (`src/evidence/place_resolution.py`) ✅
1. Splink record similarity, household-level (`src/evidence/similarity.py`) ✅
1. Splink person similarity, person-level (`src/evidence/similarity.py`) ✅

### 2.3 Conclusion Layer ✅

Three-step pipeline via `cli conclude`:

1. **Person Resolution** — Union-Find clustering on person similarity ≥ 0.65 (`src/conclusion/person_resolution.py`) ✅
1. **Relationship Resolution** — household matching → Person creation + Relationship conclusions (`src/conclusion/relationship_resolution.py`) ✅
1. **Event Resolution** — census, calculated birth, and marriage Events (`src/conclusion/event_resolution.py`) ✅

### 2.4 Integration Test Harness ✅

`tests/test_pipeline.py` — 59 tests. See §4 for exact counts.

______________________________________________________________________

## 3. Work Queue

| # | Item | Priority | Notes |
|---|---|---|---|
| 35 | ~~**`/transcription` scope design.**~~ | ~~High (R3)~~ | ✅ **Superseded (session 26 June 2026).** Transcription pipeline spawned as a separate repo (item 39). `src/transcription/` will not be built within GRA. |
| 38 | **`export-vocab` CLI command.** Aggregate census name/place distributions by parish from the evidence layer and export to a vocabulary file (`{parish_id}_vocab.json`) for consumption by the transcription pipeline's confidence scoring module. Blocked on vocabulary file contract — dedicated session required to define format and field structure before implementation. | Medium (R3) | After vocabulary file contract session. See §5.10. |
| 39 | **Spawn transcription repo.** Create new GitHub repository for the NLI Catholic parish register transcription pipeline. The CSV schemas defined 25 June 2026 (register index, parish baptism, parish marriage) plus bounding box envelope fields are the formal interface contract with GRA. GRA's only dependency on this repo is the CSV output it produces. | High (R3) | Prerequisite for parish ingest implementation (item 36). |
| 36 | **Parish ingest pipeline.** Implement `src/evidence/parish.py`: parish baptism CSV → Record + RecordedPersons (child, father, mother, sponsors) + RecordedRelationships (child→father, child→mother, child→sponsor). Marriage CSV → Record + RecordedPersons (groom, bride, witnesses) + RecordedRelationships (couple, groom→witness, bride→witness). New role vocab: `sponsor`. New relationship type vocab: `sponsor`, `witness`. | High (R3) | After transcription scope design. After data dictionary and schema updated. |
| 37 | **Data dictionary update for parish records.** Add `sponsor` to `RecordedPerson` role vocabulary. Add `sponsor` and `witness` to `RecordedRelationship` type vocabulary. Document three-state transcription field convention: empty (absent in source), `[?]` (illegible), value (as written). | Medium (R3) | Before parish ingest implementation. |
| 7 | Stale schema-version footers: audit all `docs/` files | Low | |
| 11 | Remove `training_labels` from `schema.sql` and `training_repo.py` | Low | Conceptually retired; removal deferred |
| 12 | ~~**Hierarchical household feature for person similarity**~~ | ~~Medium~~ | ✅ **Complete (v1.1 activated, production-ready).** Root cause of clustering corruption identified and fixed: prior design used global MAX score, losing pair-specific context. Redesigned `_build_household_score_lookup()` to return (record_id, source_id, target_source_id) → score tuples. Now computes per-source household matches: Record A from 1901 gets separate max scores toward 1911 and 1926. Person features now include `household_match_score_to_3`, `_to_4`, `_to_5` (all present in all DataFrames). Splink comparison activated with OR logic across source-specific columns. **Results (Tullynaught):** Person similarity pairs +1.4%, high-confidence pairs +33.3%, person linkage +15.2% (479→552), unlinked persons -2.3pp (84.9%→82.6%). No clustering corruption. All 59 tests pass. |
| ~~13~~ | ~~**Review layer implementation** (`src/review/`). Replace `validator.py` with a researcher report module.~~ | ~~High (v2.0)~~ | ✅ **Complete (session 19).** `report.py`, `findings.py`, `priority.py`, `runner.py` created. `validator.py` deleted. CLI: `python -m src.cli review`. Nine v1.0 finding types. First run + training session next. |
| 34 | **Test harness: schema v4.0 updates.** Add tests covering: (a) `reviewer` seeded rows present after init; (b) `conclusion_log` populated after `conclude` run (person, relationship, event creates); (c) `status='active'` default on all three conclusion tables; (d) migration 002 idempotency check. Update `SCHEMA_VERSION` assertion from 32 → 40. | High | Next session |
| 14 | `place_resolution.py` stale `sqlite3.Connection` type hints at lines 99 and 181 — fix when next touching that file | Low | Cosmetic only; works at runtime |
| 15 | Pin exact similarity and conclusion counts in `test_pipeline.py` after first confirmed clean run. Five TODO-marked constants: `FLOOR_RECORD_SIMS`, `FLOOR_PERSON_SIMS`, `FLOOR_PERSONS`, `FLOOR_RELATIONSHIPS`, `FLOOR_EVENTS` | High | Next session |
| 16 | ~~**`src/ingest/` orphan module**~~ | ~~Medium~~ | ✅ Already removed in prior session; confirmed absent from zip. |
| 17 | ~~**`src/pipeline/features/` import path**~~ | ~~High~~ | ✅ Created `src/evidence/features/` package with `census.py` (`build_census_household_features`) and `census_person.py` (`build_census_person_features`). Updated both imports in `similarity.py`. `src/pipeline/` already absent. |
| 18 | ~~**`record_repo.py` stale query**~~ | ~~High~~ | ✅ `get_unprocessed_census_records()` rewritten as `NOT EXISTS` with correlated join on `rp.record_id = r.record_id` (the correct column — `person_recorded_person` has no `record_id`). |
| 19 | ~~**`record_repo.py` duplicate function**~~ | ~~Low~~ | ✅ Removed `get_recorded_persons()` (identical to `get_recorded_persons_for_record()`). |
| 20 | **Manual ID management in DAL** — `record_repo.py`, `person_repo.py`, `relationship_repo.py`, `event_repo.py` pre-calculate `MAX(...) + 1` IDs and use `OVERRIDING SYSTEM VALUE` inserts. Migrate all writes to RETURNING throughout. | Medium | See §5.4 |
| 27 | ~~**`census.py` stale `sqlite3` import**~~ | ~~Low~~ | ✅ Removed `import sqlite3`; fixed `ingest_census` type hint to `psycopg2.extensions.connection`; added `import psycopg2.extensions`. |
| 28 | ~~**`fetch_places.py` stale `sqlite3` import and broken `--db` path**~~ | ~~Medium~~ | ✅ Removed `import sqlite3`; removed `--db` CLI arg; `main()` now always connects via `open_db()` (DATABASE_URL); updated module docstring to remove `--db` examples. |
| 29 | ~~**`seed_places.py` stale `sqlite3` import and type hint**~~ | ~~Low~~ | ✅ Removed `import sqlite3`; fixed `seed_places()` type hint; added `import psycopg2.extensions`. |
| 30 | ~~**`place_repo.py` unused function**~~ | ~~Low~~ | ✅ Removed `get_unlinked_place_tokens()`. |
| 31 | ~~**`person_repo.py` dead `next_ids()` function**~~ | ~~Low~~ | ✅ Removed `next_ids()`. No callers. |
| 21 | ~~**`relationship_resolution.py` age gap is hardcoded**~~ | ~~High~~ | ✅ Fixed: census_gap derived from record dates; passed through `_match_households` → `_match_score`. Correct window for all cross-census pairs. |
| 22 | ~~**`relationship_resolution.py` name matching is exact**~~ | ~~High~~ | ✅ Fixed: JaroWinkler ≥ 0.85 via `rapidfuzz.distance.JaroWinkler.similarity`. |
| 23 | ~~**`relationship_resolution.py` rp1/rp2 assigned same Person**~~ | ~~Critical~~ | ✅ Fixed: removed in-memory dict mutation; re-fetch household members from DB after Person assignments before calling `_create_relationships_from_household`. |
| 24 | ~~**`relationship_resolution.py` relationship evidence not recorded**~~ | ~~High~~ | ✅ Fixed: `_ensure_relationship()` now looks up matching RecordedRelationships and populates `relationship_recorded_relationship`. |
| 25 | ~~**`event_resolution.py` census event per RecordedPerson**~~ | ~~High~~ | ✅ Fixed: Pass 1 now creates one census Event per Record; all Persons in the household are linked via `person_event`; one `event_record` link per Record. |
| 26 | **`event_resolution.py` marriage event date_qualifier** — `_create_marriage_event()` passes `date_qualifier=None` when date is also None. Schema CHECK allows NULL date_qualifier; however the docstring says "date=NULL (census doesn't record marriage date)" — consider using `date_qualifier='estimated'` to signal inference rather than true absence. Minor consistency point. | Low | See §5.6 |
| ~~27~~ | ~~**`census.py` stale `sqlite3` import**~~ | ~~Low~~ | ✅ Removed (session 14) |
| ~~28~~ | ~~**`fetch_places.py` stale `sqlite3` import and type hints**~~ | ~~Medium~~ | ✅ Fixed (session 14) |
| ~~29~~ | ~~**`seed_places.py` stale `sqlite3` import and type hint**~~ | ~~Low~~ | ✅ Fixed (session 14) |
| ~~30~~ | ~~**`place_repo.py` unused function**~~ | ~~Low~~ | ✅ Removed (session 14) |
| ~~31~~ | ~~**`person_repo.py` dead `next_ids()` function**~~ | ~~Low~~ | ✅ Removed (session 14) |
| ~~32~~ | ~~**`role_relationships.py` score/score_version always None**~~ | ~~Medium~~ | ✅ **Fixed (session 15).** Schema v3.2 allows scores for all relationship types. Role-pair RecordedRelationships now insert proper prior scores (0.75-0.90) with `score_version=SCORE_VERSION_ROLE_PAIR`. Migration applied: `src/db/migrations/001_allow_scores_all_relationship_types.sql` |
| 33 | **Place normalization test alignment** — `test_evidence_place_authority_complete` was checking exact string matches but place resolution uses normalization (handles "X or Y" compounds and double consonant variants). Test now uses `normalize_place_name()` for both seeded and expected names before comparing. | Low | ✅ Fixed (session 15) |

______________________________________________________________________

## 4. Test Harness Reference

**Exact Tullynaught counts (fixed fixtures, 21 June 2026):**

| Metric | Value | Derivation |
|---|---|---|
| Records — 1901 | 263 | CSV unique image_group values |
| Records — 1911 | 240 | CSV unique image_group values |
| Records — 1926 | 212 | CSV unique image_group values |
| Records — total | 715 | Sum |
| Recorded persons — 1901 | 1193 | CSV row count |
| Recorded persons — 1911 | 1080 | CSV row count |
| Recorded persons — 1926 | 894 | CSV row count |
| Recorded persons — total | 3167 | Sum |
| Role rels — couple | 347 | Role-pair rule simulation |
| Role rels — parent_child | 2624 | Role-pair rule simulation |
| Role rels — sibling | 2952 | Role-pair rule simulation |
| Role rels — total | 5923 | Sum |
| Place links | 715 | 100% match rate — all 31 inhabited townlands pass JW ≥ 0.88 |
| Birth year plausibility | 1807–1928 | Max age 92 in 1901 → born 1809 − 2 = 1807; age 0 in 1926 + 2 = 1928 |

**Authoritative place data (logainm, 23 June 2026):**

- 33 townlands total; `Croaghnakern` and `Rooney's Island` uninhabited
- `Drummenny Upper` is logainm canonical (double-m); normalization handles consonant variants
- Compound names like "Tullyleague or Tullybrook" normalized to primary name (first part)

**Floor counts (pin after first clean run — item 15):**
`FLOOR_RECORD_SIMS`, `FLOOR_PERSON_SIMS`, `FLOOR_PERSONS`, `FLOOR_RELATIONSHIPS`, `FLOOR_EVENTS`

______________________________________________________________________

## 5. Code Review Findings (21 June 2026)

Full review of all active `src/` modules. Dead code in `src/pipeline/` excluded (covered by item 17).

### 5.1 Dead modules

**`src/ingest/census.py`** is a complete duplicate of `src/evidence/census.py` — same file, same content. The `src/ingest/` package appears to be the pre-rebuild location; the active module is `src/evidence/census.py`. The ingest package is never imported by any active module. Delete it (item 16).

### 5.2 Import path leaking into dead package

`src/evidence/similarity.py` imports from `src.pipeline.features.census` and `src.pipeline.features.census_person`. These feature extractors belong in `src/evidence/features/` per the stated architecture but have not been moved. This means `src/pipeline/` cannot be fully deleted until the move is completed. This is the primary blocker for item 17.

### 5.3 `record_repo.py` issues

`get_unprocessed_census_records()` has two problems:

- **Performance:** Uses `NOT IN (SELECT ... FROM person_recorded_person)` — flagged in its own docstring. At Donegal scale (168K records, ~800K persons) this will be very slow. Rewrite as `NOT EXISTS` before scale-up (item 18).
- **Potential join bug:** The subquery joins `person_recorded_person` on `record_id` but `person_recorded_person` has no `record_id` column — it links via `recorded_person_id`. The join path is `recorded_person.record_id` → `person_recorded_person.recorded_person_id`. Verify this produces correct results; the join condition may be silently wrong (item 18).

`get_recorded_persons()` and `get_recorded_persons_for_record()` are identical in purpose and body. One is unused. Remove the duplicate (item 19).

### 5.4 Manual ID management

Multiple DAL functions (`insert_record`, `insert_recorded_person`, `insert_person`, `insert_person_name`, `insert_relationship`) pre-calculate `MAX(...) + 1` IDs and pass them to `OVERRIDING SYSTEM VALUE` inserts. The RETURNING pattern already works correctly (used in `create_person()`, `_create_event()`, `insert_recorded_relationship()`). The manual pattern is not safe for concurrent access and adds unnecessary complexity. Migrate to RETURNING throughout (item 20). The `next_ids()` and `next_record_id()` / `next_recorded_person_id()` helpers become dead code once this is done.

### 5.5 `relationship_resolution.py` — three correctness issues

**Age gap hardcoded (item 21):** `_match_score()` awards 0.2 points for an age difference of 8–12 years. This only makes sense for 1901↔1911. For 1901↔1926 (25-year gap) the expected difference is ~23–27 years, meaning all cross-decade matches would score 0.0 on the age component. The actual census year gap should be passed from the record dates.

**Name matching is exact (item 22):** `_match_score()` checks `name1 == name2` for a 0.3 score contribution. NAI data has endemic spelling variation (Brigid/Bridget, Michael/Micheal, Patrick/Patk). Exact matching will miss many true positives. Replace with JaroWinkler ≥ 0.85 using `rapidfuzz`.

**Same-Person assignment prevents relationship creation (item 23):** In `_get_or_create_person_for_pair()`, when a new Person is created and both `rp1` and `rp2` are linked to it, the function also sets `rp1["person_id"] = rp2["person_id"] = person_id` on the in-memory dicts passed into `_create_relationships_from_household()`. That function then sees both as sharing a Person ID and skips the couple/parent_child relationship (correctly — you can't have a relationship with yourself). But the intent is: rp1 and rp2 represent the *same person across two census years*, not two members of the same household. The relationships should be derived from the household's role structure, not the matched pair. Household members need to be re-fetched from the DB after Person assignments, not read from the mutated dicts.

**No evidence provenance on Relationships (item 24):** `_ensure_relationship()` calls `INSERT INTO relationship` but never calls `INSERT INTO relationship_recorded_relationship`. The junction table is empty after `conclude` runs. The conceptual model requires Relationship → RecordedRelationship linkage (Rule 2 evidence correspondence). The relevant RecordedRelationships already exist (created at ingest by `role_relationships.py`); they just need to be looked up and linked here.

### 5.6 `event_resolution.py` — one correctness issue, one minor point

**Census event cardinality (item 25):** Pass 1 loops over `linked_persons` within each Record and calls `_create_census_event()` for each. In a household with 8 persons all linked to Persons, this creates 8 census Events for the same Record — each with identical date and place but different person_event links. The `conceptual_model.md` intent for census Events was one Event per Record appearance (not per person), capturing that "this household was enumerated." Review the design and decide: either one Event per Record (linked to all household Persons via person_event), or one per Person (current behaviour, explicitly chosen). If the latter is deliberate, document it.

**Marriage event date_qualifier (item 26):** Minor consistency point — passing `date_qualifier=None` alongside `date=None` is schema-valid but ambiguous. `'estimated'` might better signal the inference.

### 5.7 Stale `sqlite3` imports

- `src/evidence/census.py` line 9: `import sqlite3` — unused post-migration. The function signature `ingest_census(conn: sqlite3.Connection, ...)` also has the wrong type hint (item 27).
- `src/db/seed_places.py`: imports `sqlite3`, type-hints `conn: sqlite3.Connection` (item 29).

### 5.8 `fetch_places.py` broken standalone CLI

`fetch_places.main()` handles `--db` by calling `open_db(args.db)` with a path argument. But `open_db()` no longer accepts any arguments — it reads `DATABASE_URL` from the environment. The `--db` argument is silently ignored and the function either works (if `DATABASE_URL` is set) or raises `EnvironmentError` (if not), regardless of the `--db` value. The `--db` argument should be removed from the standalone parser since it is meaningless, or `open_db()` should be documented as `DATABASE_URL`-only (item 28).

______________________________________________________________________

### 5.9 Review layer design (session 18, 24 June 2026)

The existing `src/review/validator.py` is retired in full — not ported. It is a legacy constraint enforcer from a pre-v4.0 design era. Some of its domain logic reappears in the new module as finding functions, but the old rule codes (R40–R46), entry points (`validate`, `validate_object`, `validate_genealogical`), and output format (flat list of error strings) are all superseded. The new design is derived from `genealogical_constraints.md` and conceptual model §7.4, not from the old validator.

**Design principles:**
- Read-only. The report module queries the conclusion layer; it does not write to it or to `conclusion_log`.
- Structured data first. Output is a `Report` containing typed `ReportItem` entries, rendered to JSON and Markdown.
- Iterative. First implementation covers confident findings only. Thresholds and taxonomy are tuned after training sessions against real Supabase data.
- Heterogeneous priority list. Health findings and research prompts are interleaved by priority score, not separated into sections.

**`ReportItem` fields:**
```
finding_type:        str           # controlled vocabulary
priority:            int           # 1 = highest; computed at assembly time
person_id:           int | None
relationship_id:     int | None
event_id:            int | None
record_ids:          list[int]     # evidence records underpinning the finding
title:               str           # one-line summary
detail:              str           # full explanation with specific values from the DB
recommended_action:  str | None
```

**`Report` fields:**
```
generated_at:   datetime
items:          list[ReportItem]   # sorted by priority ascending
summary:        dict               # counts by finding_type
```

**Finding taxonomy — v1.0 scope (implement first):**

| finding_type | Domain source | Notes |
|---|---|---|
| `merge_error_candidate` | GC07 | Person with 2+ active Records from same census source |
| `birth_singularity_violation` | GC04 | Multiple `is_primary=true` birth Events on one Person |
| `death_singularity_violation` | GC05 | Same for death |
| `life_event_sequence_violation` | GC02 | Chronological order broken — detail must show actual values so researcher can distinguish signal from measurement noise |
| `parent_age_implausible` | GC12 | Gap outside plausible range (< 15 yrs or > 50/70 maternal/paternal) |
| `marriage_age_implausible` | GC13 | Person under 15 at marriage date |
| `lifespan_boundary_violated` | GC01 | Record date outside concluded lifespan — detail must show actual delta |
| `unlinked_recorded_person` | — | RecordedPerson with no Person conclusion |
| `single_census_appearance` | — | Person in only one census, no concluded death Event |

**Finding taxonomy — deferred (after first training session):**

| finding_type | Notes |
|---|---|
| `source_coverage_gap` | Requires full §4 eligibility logic from `genealogical_constraints.md` |
| `household_placement_unresolved` | Requires populated relationship graph (GC15 Case 3) |
| `female_occupier_inference` | Same dependency (GC16) |
| `sibling_birth_spacing` | < 9 months gap between concluded siblings |
| `naming_pattern_lead` | Experience-dependent; low confidence (GC18) |

**Priority scoring:** Three inputs collapse to a single integer. (1) Certainty — schema-state findings (singularity violations) score highest; inferred findings (source gaps) score lower. (2) Severity — merge error candidates score higher than local findings. (3) Scope of impact — Persons with more linked RecordedPersons score higher. Exact weights tuned after first training session.

**Output:**
- `reports/report_YYYYMMDD_HHMMSS.json` — machine-readable, for training sessions and future MCP consumption
- `reports/report_YYYYMMDD_HHMMSS.md` — human-readable Markdown, for researcher review
- Both written on each run; sortable by filename to see history

**CLI:**
```
python -m src.cli review
```
No scoping arguments in v1.0. Full-database report only. Scoped review (per-person, per-finding-type) deferred to after training sessions establish what's useful.

**Module structure:**
```
src/review/
    __init__.py
    report.py      # ReportItem and Report dataclasses
    findings.py    # one function per finding_type
    priority.py    # priority scoring
    runner.py      # assembles Report from findings, writes output files
```

**`validate_object` disposition:** Pre-write structural validation is DAL-adjacent, not a researcher-facing function. It is removed from `validator.py` and not replaced in this module. If pre-write checks are needed, they live in the repo layer directly. No immediate action required — the old `validate_object` function is simply not carried forward.

______________________________________________________________________

### 5.10 Vocabulary file contract (open — dedicated session required)

GRA will export a parish-level name/place vocabulary file consumed by the transcription pipeline's confidence scoring module. This is the primary interface between GRA's evidence layer and the transcription repo beyond the CSV schemas.

**Design principles agreed (26 June 2026):**
- File existence check only in the transcription pipeline — no configuration, no hard dependency. If file absent, confidence scoring is skipped and pipeline continues.
- Confidence adjustment is a signal, not a correction — transcription value never changes.
- Census data used post-transcription only (preserves recorded-as-is contract).
- Raw counts preferred over normalised frequencies.
- Gendered forename sets for accurate confidence matching.
- Townlands as a separate set from surnames (different semantic role, stronger signal).

**GRA-side implementation:** `python -m src.cli export-vocab --parish <parish_id> --output <path>`

**File naming convention:** `{parish_id}_vocab.json`

**Format and field structure:** not yet decided. Dedicated session required before either repo implements against this contract. See item 38.

- **v1.x (Current):** Foundation, evidence, and conclusion layers complete. Integration test harness complete. Priority next steps: item 15 (pin test counts), item 34 (test harness v4.0 updates).
- **v2.0 (Target):** Review layer complete (item 13 ✅). First run + training session against Supabase. Full-scale Irish Census ingestion.
- **v3.0 (Long-term):** Parish and civil BMD ingest. Depends on transcription repo (item 39) producing CSV output and parish ingest pipeline (item 36) consuming it.

______________________________________________________________________

## 7. Version History

| Date | Milestone / Change |
|---|---|
| 26 June 2026 (session R3 transcription discovery) | **Transcription pipeline discovery complete. Spawned as separate repo.** HTR strategy explored for NLI Catholic parish registers. Four sample images from vtls000631954 (1873–1881 baptisms) reviewed — three quality tiers observed (clean, moderate, degraded). Key decisions: (1) Transcription pipeline spawned as independent repo — no coupling to GRA internals, CSV schemas as the sole interface contract. `src/transcription/` will not be built within GRA. (2) Hybrid tiered pipeline adopted: image QA triage → layout detection (universal) → tiered HTR (Kraken local / Transkribus B2022) → field parsing → census confidence adjustment → CSV assembly. (3) Layout detection is universal first pass — required on all pages because bounding box coordinates are part of the CSV output contract. (4) Bounding box coordinates added to all three CSV schemas: `image_filename`, `bbox_x_min`, `bbox_y_min`, `bbox_x_max`, `bbox_y_max` — nullable, entry-block level. (5) Census vocabulary file as loose-coupling interface: GRA exports `{parish_id}_vocab.json`; transcription pipeline reads if present, skips confidence scoring if absent. File contract format left open — dedicated session required. (6) Transkribus Beyond 2022 model identified as best available pre-trained model for Irish archival handwriting (759,000 words, 50 handwriting styles). Access via UI export (PAGE XML) — API requires Organisation plan. Used as Tier 3 HTR and ground truth source for Kraken fine-tuning. Work queue: item 35 superseded, items 38 and 39 added. §5.10 added (vocabulary file contract design notes). |
| 25 June 2026 (session R3 discovery) | **Parish records early discovery complete.** NLI Catholic parish register collection (`registers.nli.ie`) explored. LLM transcription experiments reviewed (Tawnawilly baptisms 499 records, Ballyoughter baptisms 1310 records, Tawnawilly marriages 102 records). Six source images examined (pages 4, 6, 7, 26, 31, 36). Key decisions: CSV as universal ingest contract for all sources; `/transcription` scope as separate ETL concern upstream of ingest; hybrid AI + human review transcription model; recorded-as-is as strict transcription contract (no invented disambiguation); three-file structure per register (index, baptisms, marriages); separate baptism and marriage schemas with shared envelope. `sponsor` added to both `RecordedPerson` role vocabulary and `RecordedRelationship` type vocabulary. `witness` added to `RecordedRelationship` type vocabulary. Three CSV schemas defined: register index, parish baptism, parish marriage. High-res image URL pattern documented: `registers.nli.ie/static/high/{register_id_no_vtls}/{vtls_filename}.jpg`. Work queue items 35, 36, 37 added. |
| 24 June 2026 (session 19) | **Review layer implementation complete.** `src/review/validator.py` deleted. Four new modules: `report.py` (`ReportItem` + `Report` dataclasses, JSON + Markdown serialisers), `findings.py` (nine v1.0 finding functions: `merge_error_candidate`, `birth_singularity_violation`, `death_singularity_violation`, `life_event_sequence_violation`, `parent_age_implausible`, `marriage_age_implausible`, `lifespan_boundary_violated`, `unlinked_recorded_person`, `single_census_appearance`), `priority.py` (three-tier base score × scope multiplier → integer rank), `runner.py` (assembles report, writes paired JSON + Markdown to `reports/`). `src/cli.py`: `validate` subcommand replaced by `review`. `reports/.gitkeep` added. CLI: `python -m src.cli review`. Item 13 complete. |
| 24 June 2026 (session 18) | **Review layer design complete.** `src/review/validator.py` retired in full — not ported. New design derived from `genealogical_constraints.md` and conceptual model §7.4. `ReportItem` and `Report` structures defined. Nine v1.0 finding types specified; five deferred to post-training-session. Priority scoring approach agreed. Output: paired JSON + Markdown files in `reports/` with timestamp filenames. CLI: `python -m src.cli review`. Module structure: `report.py`, `findings.py`, `priority.py`, `runner.py`. Training session workflow agreed: run report against Supabase data, review top findings with Claude, iterate on taxonomy and thresholds. Item 13 updated with full spec (§5.9). `validation_rules.md` updated with supersession note. |
| 23 June 2026 (session 17) | **Schema v4.0 — Review Layer foundation.** Conceptual model v2.8: §7 Review Layer added (Reviewer entity, conclusion log, conclusion lifecycle, reporting surface). Data dictionary v2.8: §4a Reviewer + ConclusionLog field tables; `status`/`pending_delete_at` added to Person, Relationship, Event; §6.11–6.14 vocabulary sections. `schema.sql` v4.0: `reviewer` table, `conclusion_log` append-only audit table, `status`/`pending_delete_at` columns on `person`/`relationship`/`event`, partial indexes for bin view. `seed.sql`: two system reviewers seeded (pipeline:system, human:unknown). Migration `002_review_layer.sql`: safe for populated databases; backfills existing conclusions as pipeline:system creates. `src/dal/conclusion_log_repo.py` new DAL module: `log_action`, `log_create`, `log_update`, `log_delete`, `log_verify`, `get_or_create_reviewer`, `new_change_group`, query helpers. Pipeline wired: `person_resolution.py`, `relationship_resolution.py`, `event_resolution.py` all call `log_create` after conclusion inserts. `SCHEMA_VERSION` bumped 32 → 40. Item 34 added (test harness updates for v4.0). |
| 23 June 2026 (session 15) | **Test suite complete (100% pass rate) + schema v3.2.** Item 32: Fixed NULL scores in role-pair RecordedRelationships — `role_relationships.py` now passes proper prior scores (0.75-0.90) and `SCORE_VERSION_ROLE_PAIR` when creating role-pair relationships. Schema migration `001_allow_scores_all_relationship_types.sql` removes restrictive CHECK constraint that limited scores to type='similarity' only. All 5,923 role-pair relationships now have scores. Item 33: Enhanced place normalization to handle "X or Y" compound names (takes primary/first name) and double consonant variants (normalizes to single). Updated `test_evidence_place_authority_complete` to use normalization matching. **Test harness: 59/59 passing (100%)**, up from 57/59 (96.6%). Schema version: 3.1 → 3.2. |
| 22 June 2026 (session 14) | **Dead code removal + feature package creation.** Item 17: created `src/evidence/features/` package (`census.py` = `build_census_household_features`, `census_person.py` = `build_census_person_features`); updated `similarity.py` imports; removed all stale pipeline references from docstrings. Item 18: `get_unprocessed_census_records()` rewritten as `NOT EXISTS` with correct join on `rp.record_id` (join bug confirmed and fixed). Items 16, 19, 27, 28, 29, 30, 31: removed orphan/duplicate/dead functions and stale `sqlite3` imports across `record_repo.py`, `place_repo.py`, `person_repo.py`, `evidence/census.py`, `fetch_places.py`, `seed_places.py`; fixed all stale type hints; fixed broken `--db` CLI path in `fetch_places.main()`. |
| 21 June 2026 (session 13) | **Critical bug fixes in conclusion layer.** `relationship_resolution.py`: item 23 (re-fetch household members from DB after Person assignments — prevents same-Person-id relationship skip); item 24 (`_ensure_relationship` now populates `relationship_recorded_relationship` provenance); item 21 (census_gap derived from record dates, passed to `_match_score`); item 22 (JaroWinkler ≥ 0.85 replaces exact name match). `event_resolution.py`: item 25 (one census Event per Record, all household Persons linked via `person_event`). |
| 21 June 2026 (session 12) | **Integration test harness + full code review.** `tests/test_pipeline.py`: 59 tests. Exact counts derived from Tullynaught fixtures and logainm authority data. Full code review of all active `src/` modules; 17 new work items added (items 16–32). Critical correctness issues identified in `relationship_resolution.py` (items 23, 24) and `event_resolution.py` (item 25). |
| 21 June 2026 (session 11) | **Conclusion layer implementation complete. Repository restructured.** `src/conclusion/` complete. `src/pipeline/` nominally retired (full deletion blocked pending features move — item 17). `cli.py` rewritten. |
| 21 June 2026 (session 10) | **Person-level similarity added as evidence step [5/5].** `run_person_similarity()` added to `src/evidence/similarity.py`. |
| 21 June 2026 | **Evidence layer verified complete with PostgreSQL.** Place resolution integrated as step [3/5]. |
| 20 June 2026 | **Evidence layer implementation complete.** `src/evidence/similarity.py` created. |
| 20 June 2026 | **Foundation implementation complete (v3.1).** SQLite retired; migrated to PostgreSQL / Supabase. |
| 19 June 2026 | **`database_schema.md` v3.2.** R47–R50 mapped to DDL-level CHECK constraints. |
| 18–19 June 2026 | **Doc audit and fixes.** `repositories.md` v1.6, `future_ideas.md` v1.2, `reconstruction_algorithms.md` v1.3. |
| 17–18 June 2026 | **Conceptual model v2.5 / Data layer alignment.** RecordedRelationship, RecordSimilarity, Rule 9. `data_dictionary.md` v2.7. |
| 17 June 2026 | **Consolidation.** Path drift resolved; migration scripts; roadmap structure restored. |
| 16 June 2026 | **Schema v3.0.** `event.is_primary`, nullable roles. |
| Early June 2026 | **Schema v2.8.** RecordedEvent merged into Record; junction tables 9→5. First full linkage test. |
| 24 May 2026 | **Foundation & R1-1.** Initial GRA roadmap. Place resolution and household inference implemented. |
