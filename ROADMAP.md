# Genealogy Research Assistant (GRA) — Project Roadmap

*21 June 2026*

---

## 1. Current State

### Documentation

| Document | Status | Notes |
|---|---|---|
| `docs/conceptual_model.md` | ✅ Complete (v2.8) | |
| `docs/data_dictionary.md` | ✅ Complete (v2.7) | |
| `docs/database_schema.md` | ✅ Complete (v3.1) | |
| `docs/repositories.md` | ✅ Complete (v1.6) | |
| `docs/validation_rules.md` | ✅ Complete (v2.8) | |
| `docs/reconstruction_algorithms.md` | ✅ Complete (v1.3) | |
| `docs/genealogical_constraints.md` | ✅ Complete (v1.3) | |
| `ROADMAP.md` | ✅ Current | |

### Implementation

| Layer | Status | Notes |
|---|---|---|
| Foundation | ✅ Complete (v3.1) | |
| Evidence | ✅ Complete (v3.1) | `add-evidence` CLI complete: [1/5]–[5/5] |
| Conclusion | ✅ Complete | `conclude` CLI: [1/3]–[3/3] |
| Testing | ✅ Complete | `tests/test_pipeline.py`: 59 tests, fixed-fixture exact assertions |
| Review | 🔜 Planned | `src/review/` redesign (item 13) |

---

## 2. Implementation

### 2.1 Foundation & Database management ✅

### 2.2 Evidence Layer ✅

Five-step pipeline via `cli add-evidence`:

1. Ingest CSV → record + recorded_person (`src/evidence/census.py`) ✅
2. Assign role relationships from household role pairs (`src/evidence/role_relationships.py`) ✅
3. Place resolution → place_record linkage (`src/evidence/place_resolution.py`) ✅
4. Splink record similarity, household-level (`src/evidence/similarity.py`) ✅
5. Splink person similarity, person-level (`src/evidence/similarity.py`) ✅

### 2.3 Conclusion Layer ✅

Three-step pipeline via `cli conclude`:

1. **Person Resolution** — Union-Find clustering on person similarity ≥ 0.65 (`src/conclusion/person_resolution.py`) ✅
2. **Relationship Resolution** — household matching → Person creation + Relationship conclusions (`src/conclusion/relationship_resolution.py`) ✅
3. **Event Resolution** — census, calculated birth, and marriage Events (`src/conclusion/event_resolution.py`) ✅

### 2.4 Integration Test Harness ✅

`tests/test_pipeline.py` — 59 tests. See §4 for exact counts.

---

## 3. Work Queue

| # | Item | Priority | Notes |
|---|---|---|---|
| 7 | Stale schema-version footers: audit all `docs/` files | Low | |
| 11 | Remove `training_labels` from `schema.sql` and `training_repo.py` | Low | Conceptually retired; removal deferred |
| 12 | Hierarchical household feature for person similarity: add RecordSimilarity score as a Splink comparison level to boost confidence when households match | Medium | Deferred to v1.1 post first clean run |
| 13 | **Review layer redesign** (`src/review/validator.py`). Reframe from constraint enforcer to researcher report module. Port to PostgreSQL. Add `review` CLI command. | High (v2.0) | See note below |
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
| 27 | **`census.py` stale `sqlite3` import** — `src/evidence/census.py` imports `sqlite3` at line 9 (import never used post-migration). Remove. | Low | See §5.7 |
| 28 | **`fetch_places.py` stale `sqlite3` import and type hints** — `fetch_places.py` imports `sqlite3` (line 10) and uses it in the `write_to_db()` function comment and main() `--db` handling, which calls `open_db(args.db)` with a path argument that `open_db()` no longer accepts (it reads `DATABASE_URL`). The standalone `--db` CLI path in `fetch_places.main()` is broken. | Medium | See §5.8 |
| 29 | **`seed_places.py` stale `sqlite3` import and type hint** — `seed_places.py` imports `sqlite3` (not used post-migration) and type-hints `conn: sqlite3.Connection`. Remove import, fix hint to `psycopg2.extensions.connection`. | Low | See §5.7 |
| 30 | **`place_repo.py` unused function** — `get_unlinked_place_tokens()` duplicates the evidence-collection logic already in `place_resolution.py`'s `_collect_evidence_tokens()`. It is not called from any active module. Remove or consolidate. | Low | |
| 31 | **`person_repo.py` dead `next_ids()` function** — `next_ids()` pre-calculates IDs for person, relationship, event, and person_name tables and is linked to the old bulk-insert pattern. The new RETURNING pattern (used in `create_person()`) makes this unnecessary. Verify no callers remain, then remove. | Low | |
| 32 | **`role_relationships.py` score/score_version always None** — role-pair RecordedRelationships insert `score=None, score_version=None` even though the relationship has a well-defined prior score (e.g. 0.90 for couple). The schema CHECK `(type = 'similarity') = (score IS NOT NULL)` enforces that non-similarity types must have NULL score — this is intentional, but it means the prior scores in `constants.py` are never persisted. Consider whether priors should live in the schema or stay as in-memory constants for the conclusion layer to reference. | Medium | Design decision needed |

---

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

**Authoritative place data (logainm, 21 June 2026):**
- 33 townlands total; `Croaghnakern` and `Rooney's Island` uninhabited
- `Drumenny Upper` is logainm canonical; census uses `Drummenny Upper` (double-m); JW=0.987

**Floor counts (pin after first clean run — item 15):**
`FLOOR_RECORD_SIMS`, `FLOOR_PERSON_SIMS`, `FLOOR_PERSONS`, `FLOOR_RELATIONSHIPS`, `FLOOR_EVENTS`

---

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

---

## 6. Release Plan

- **v1.x (Current):** Foundation, evidence, and conclusion layers complete. Integration test harness complete. Priority next steps: item 15 (pin test counts), items 17 and 23 (correctness).
- **v2.0 (Target):** Review layer (`src/review/`) redesign (item 13). Full-scale Irish Census ingestion.
- **v3.0 (Long-term):** Parish and civil BMD ingest.

---

## 7. Version History

| Date | Milestone / Change |
|---|---|
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
