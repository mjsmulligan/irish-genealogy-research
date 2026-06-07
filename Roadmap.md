# Genealogy Research Assistant (GRA) — Project Roadmap

*June 2026 — v1.7*

---

## 1. Current State

### Documentation

| Document | Version | Status | Notes |
|---|---|---|---|
| `docs/conceptual_model.md` | v2.4 | ✅ Complete | RecordedEvent merged into Record |
| `docs/data_dictionary.md` | v2.6 | ✅ Complete | RecordedEvent removed; event fields inline on Record |
| `docs/repositories.md` | v1.5 | ✅ Complete | Repository 8 (logainm.ie) and Source 13 (place_authority) added |
| `docs/validation_rules.md` | v2.6 | ✅ Complete | R40–R46 implemented; retired rules updated for schema v2.8 |
| `docs/database_schema.md` | v2.8 | ✅ Complete | RecordedEvent merged into Record; junction table count 9→5; migration v2.7→v2.8 |
| `docs/reconstruction_algorithms.md` | v1.4 | ✅ Complete | Linkage improvements: age coherence gate, child departure prior, S–S metric, role-independent HH features |
| `docs/genealogical_constraints.md` | v1.2 | ✅ Complete | 22 GC-coded constraints |
| `docs/service_api.md` | v1.0 | ✅ Complete | Service layer API; flag/lead tables still needed in schema |
| `docs/session_bootstrap.md` | v1.0 | ✅ Complete | Ingest and update knowledge session protocols |
| `ROADMAP.md` | v1.6 | ✅ This document | — |

### Implementation

| Module | File(s) | Status | Notes |
|---|---|---|---|
| Database layer | `src/db.py` | ✅ Complete | Schema v2.8; explicit `place-resolve`, `household`, `link` CLI commands; `reconstruct` retained as convenience |
| Schema DDL | `src/db/schema.sql` | ✅ Complete | v2.8 — RecordedEvent merged; junction tables reduced to 5 |
| Seed data | `src/db/seed.sql` | ✅ Complete | 12 sources, 8 repositories |
| Migration | `src/db/migrations/migrate_27_to_28.sql` | ✅ Complete | Merges recorded_event into record; drops redundant junction tables |
| Place fetcher | `src/fetch_places.py` | ✅ Complete | logainm API → DB direct write or CSV export |
| Place seeder | `src/seed_places.py` | ✅ Complete | CSV → place_authority; idempotent |
| Place resolution | `src/reconstruction/place_resolution.py` | ✅ Complete | v2.0 — authority-based Jaro-Winkler matching |
| Household inference | `src/reconstruction/household_inference.py` | ✅ Complete | Census role-pair rules → Person/Relationship/Event conclusions |
| Census feature extractor | `src/reconstruction/features/census.py` | ✅ Complete | Name, birth year, place_id, spouse name, child names, sibling names |
| Cross-census linkage | `src/reconstruction/linkage.py` | ✅ Complete | **Significant improvements this session** — see notes below |
| Validator | `src/validator.py` | ✅ Complete | R40–R46 genealogical constraint rules implemented |
| Service layer | `src/service.py` | 🔜 Pending | `service_api.md` v1.0 complete; flag/lead tables needed first |
| Test suite | `tests/test_place_authority.py` | ✅ 33/33 passing | Place authority: normalisation, CSV, DB, resolution, hierarchy |

**linkage.py + census.py improvements (June 2026 — session 2, household robustness):**
- Role-independent household features: `household_surname_norm` (modal surname, stable across head changes), `adult_forenames_sorted` (all non-child members), replacing head/spouse fixed-role columns
- Szymkiewicz–Simpson replaces Jaccard for all name-set comparisons (household and person-level): `|A∩B| / min(|A|,|B|)` — correct for cross-census comparison where departure is expected
- Child departure prior: `child_forenames_young` (age ≤ 20, primary signal) and `child_forenames_older` (age > 20, spinster/bachelor pattern, softer signal); `child_forenames_sorted` retained for statistics
- Age coherence gate in `_resolve_household_persons`: `_age_coherent()` replaces birth-year-estimate comparison. Uses `|observed_age_delta - expected_census_gap| <= tol` with GC03 tolerances (±3yr for 10/15yr gaps, ±4yr for 25yr gap). Encodes the known census dates exactly.
- `build_census_features` brittle name-join fixed with positional pairing (consistent with `linkage.py`)

**linkage.py improvements (June 2026 — session 1, correctness pass):**
- `link_type` → `link_only` — eliminates intra-census pair generation; 8,606 spurious intra-census merges eliminated
- `_UnionFind` replaces `merged_set` — transitive closure, O(1) absorbed property
- `_persons_for_record` positional pairing — eliminates brittle name-join and role-collision
- Proposal write corrected — `training_labels (decision='proposed')` only; no premature `person_record` rows
- `_merge_persons` safe ID generation; per-merge transactions; `CENSUS_SOURCE_IDS` constant; TF adjustment via `.configure()` (Splink 4 API)
- `review.py` query update needed: proposals now in `training_labels WHERE decision='proposed'`

**Verified against real data (Tullynaught + Clogher DEDs):**
- Full e2e run analysed; 8,606 intra-census merges diagnosed and root-caused to `link_and_dedupe`; all fixed by `link_only`
- Place resolution: 60% null `place_id` flagged — Clogher townlands may not be fully seeded
- TF adjustment active for surname and forename

**Development environment:** VSCode with GitHub integration. Repository: https://github.com/mjsmulligan/irish-genealogy-research

**Housekeeping:** `genealogy.db` should be removed from git tracking — run `git rm --cached genealogy.db`.

---

## 2. Workflow

```bash
# 1. Initialise fresh database
python -m src.db init

# 2. Seed place authority for target area (logainm API)
python -m src.fetch_places --logainm-id 111482 --db genealogy.db

# 3. Ingest census records (repeat per source)
python -m src.db ingest --source 3 --file 1901_Tullynaught.csv
python -m src.db ingest --source 4 --file 1911_Tullynaught.csv
python -m src.db ingest --source 5 --file 1926_Tullynaught.csv

# 4. Per-source reconstruction (place resolution + household inference)
python -m src.db reconstruct --source 3   # convenience: stages 2+3
python -m src.db reconstruct --source 4
python -m src.db reconstruct --source 5

# Or explicit stages:
python -m src.db place-resolve            # stage 2 — all unresolved strings
python -m src.db household --source 4    # stage 3 — one source at a time

# 5. Cross-census linkage (run once all sources are reconstructed)
python -m src.db link

# 6. Inspect
python -m src.db summary
```

---

## 3. Release Plan

### Release 1 — Full census pipeline (1901, 1911, 1926)

| # | Milestone | Status |
|---|---|---|
| R1-0 | Place authority seeding (logainm API + CSV) | ✅ Complete |
| R1-1 | Place resolution + household inference | ✅ Complete |
| R1-2 | Cross-census Splink person linkage (1901↔1911↔1926) | ✅ Complete — linkage correctness pass done this session |
| R1-3 | Validator (R40–R46 genealogical constraint rules) | ✅ Complete |
| R1-4 | Person Browser basics (source coverage, merge error flags) | 🔜 Next — depends on service layer |

### Release 2 — Civil registration and parish registers

Civil registration sources (birth, marriage, death) and Catholic parish registers. Planned modules:
- `src/reconstruction/core.py` — shared Person/Relationship/Event commit logic extracted from `household_inference.py`
- `src/reconstruction/registration_inference.py`
- `src/reconstruction/parish_inference.py`

### Release 3 and beyond

Land records, military sources, folklore, service layer, consumer front ends.

---

## 4. Work Queue

### Tier 3 — Reconstruction pipeline ← current

**Linkage: clean re-run needed** 🔜 — wipe DB and rerun full pipeline with all linkage fixes applied. Expected: intra-census merges eliminated; revised delta-violation count; TF adjustment active. Then:
- Review near-commit band (0.80–0.85) with fresh eyes — composition will change materially
- Investigate 60% null `place_id` — run `place-resolve` verbosely to identify unresolved Clogher townland strings
- After clean run: consider lowering `AUTO_COMMIT_THRESHOLD` to 0.82 if near-commit band quality justifies it

**`review.py` update needed** 🔜 — proposal query must read from `training_labels WHERE decision = 'proposed'` rather than `person_record WHERE verified = 0 AND score < threshold`. This is a breaking change from the proposal write correction.

**flag and lead tables** 🔜 — needed before service layer. DDL specified in `service_api.md` §10.3.

### Tier 4 — Service layer

`src/service.py` — ResearchService class. Depends on flag/lead tables being added to schema.

### Tier 5 — Consumers

Claude consumer, Lovable UI, MCP server.

---

## 5. Open Decisions

### OD-02 — Derived confidence function

Provisional placeholder (record count → low/medium/high) in place. Real multi-source scored linkages available after R1-2. Revisit after clean re-run with linkage fixes.

---

## 6. Version History

| Version | Date | Change |
|---|---|---|
| 1.0 | May 2026 | Initial ROADMAP |
| 1.1 | May 2026 | Tier 1 and 2 complete; Tullynaught 1911 tested |
| 1.2 | May 2026 | R1-1 complete; Release Plan added; R1-2 as next milestone |
| 1.3 | May 2026 | Schema v2.6 (OD-01 resolved); census date fixes; 1926 normaliser corrected; migration added |
| 1.4 | May 2026 | Place authority redesign complete. PlaceAuthority added to foundational layer (flat schema, logainm.ie source). `src/fetch_places.py` and updated `src/seed_places.py` implemented. `src/reconstruction/place_resolution.py` v2.0. Schema v2.7. 33 tests passing. |
| 1.5 | June 2026 | Schema v2.8: RecordedEvent merged into Record; junction tables reduced from 9 to 5. R1-2 and R1-3 complete. Linkage first test run completed (3881 persons, 264 merged). Relationship features added to census feature extractor. Explicit `place-resolve`, `household`, `link` CLI commands added to `db.py`; `reconstruct` retained as convenience. OD-04 resolved (DuckDBAPI). |
| 1.7 | June 2026 | Household robustness pass. Role-independent HH features (modal surname, adult forename set). Szymkiewicz–Simpson replaces Jaccard for all name-set comparisons. Child departure prior: age-split child columns (young ≤20 / older >20). Age coherence gate in Pass 2 person resolution. reconstruction_algorithms.md → v1.4. |
| 1.6 | June 2026 | Linkage correctness pass. Full e2e log analysed. `link_type` → `link_only`. `_UnionFind` replaces `merged_set`. `_persons_for_record` positional pairing. Proposal write corrected. Safe ID generation. TF adjustment via `.configure()`. Per-merge commits. `CENSUS_SOURCE_IDS` constant. |
