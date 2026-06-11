# Genealogy Research Assistant (GRA) — Project Roadmap

*June 2026 — v1.8*

---

## 1. Current State

### Documentation

| Document | Version | Status | Notes |
|---|---|---|---|
| `docs/conceptual_model.md` | v2.4 | ✅ Complete | RecordedEvent merged into Record |
| `docs/data_dictionary.md` | v2.6 | ✅ Complete | RecordedEvent removed; event fields inline on Record |
| `docs/repositories.md` | v1.5 | ✅ Complete | Repository 8 (logainm.ie) and Source 13 (place_authority) added |
| `docs/validation_rules.md` | v2.6 | ✅ Complete | R40–R46 implemented; retired rules updated for schema v2.8 |
| `docs/database_schema.md` | v2.9 | ✅ Complete | event.is_primary added; training_labels added; RecordedEvent merged into Record |
| `docs/reconstruction_algorithms.md` | v1.5 | ✅ Complete | rebuild-consensus algorithm documented |
| `docs/genealogical_constraints.md` | v1.2 | ✅ Complete | 22 GC-coded constraints |
| `docs/service_api.md` | v1.0 | 🔜 Designed | Service layer API designed, not yet implemented; flag/lead tables still needed in schema |
| `docs/session_bootstrap.md` | v1.0 | ✅ Complete | Ingest and update knowledge session protocols |
| `docs/future_ideas.md` | v1.0 | ✅ Complete | Deferred features: service layer, GEDCOM, event linkage, incremental mode |
| `ROADMAP.md` | v1.8 | ✅ This document | — |

### Implementation

| Module | File(s) | Status | Notes |
|---|---|---|---|
| Database layer | `src/db.py` | ✅ Complete | Schema v2.9; `reset`, `rebuild-consensus` added; `reconstruct` now runs full pipeline (stages 2–5) |
| Schema DDL | `src/db/schema.sql` | ✅ Complete | v2.9 — event.is_primary added; training_labels added |
| Seed data | `src/db/seed.sql` | ✅ Complete | 12 sources, 8 repositories |
| Migration | `src/db/migrations/migrate_27_to_28.sql` | ✅ Complete | Merges recorded_event into record; drops redundant junction tables |
| Place fetcher | `src/fetch_places.py` | ✅ Complete | logainm API → DB direct write or CSV export |
| Place seeder | `src/seed_places.py` | ✅ Complete | CSV → place_authority; idempotent |
| Place resolution | `src/reconstruction/place_resolution.py` | ✅ Complete | v2.0 — authority-based Jaro-Winkler matching |
| Household inference | `src/reconstruction/household_inference.py` | ✅ Complete | Census role-pair rules → Person/Relationship/Event conclusions |
| Census feature extractor | `src/reconstruction/features/census.py` | ✅ Complete | Name, birth year, place_id, **spouse name, child names, sibling names** (relationship features added) |
| Cross-census linkage | `src/reconstruction/linkage.py` | ✅ Complete | Splink DuckDBAPI; merge contract; spouse/child/sibling comparisons; 1:1 bipartite gate |
| Linkage debug utilities | `src/reconstruction/debug.py` | ✅ Complete | Debug log writer; shared threshold constants |
| Rebuild-consensus | `src/reconstruction/scoring.py` | ✅ Complete | Post-linkage event arbitration; plurality voting; is_primary marked by record vote count |
| Validator | `src/validator.py` | ✅ Complete | R40–R46 genealogical constraint rules implemented |
| Service layer | `src/service.py` | 🔜 Pending | `service_api.md` v1.0 complete; flag/lead tables needed first |
| Test suite | `tests/test_place_authority.py` | ✅ 33/33 passing | Place authority: normalisation, CSV, DB, resolution, hierarchy |

**Verified against real data (Tullynaught DED):**
- Tullynaught DED: 1 DED + 33 townlands loaded; 17 townlands correctly store NULL barony/civil_parish
- Census 1901, 1911, and 1926 NAI downloads ingest correctly
- Place resolution matches "Straniss" → "Straness" via Jaro-Winkler
- Cross-census linkage first test run: 3881 persons across 3 sources; 264 auto-committed at mean score 0.918; 3291 proposals queued
- Full pipeline retest with relationship features and rebuild-consensus pending (next test run)

**Development environment:** VSCode with GitHub integration. Repository: https://github.com/mjsmulligan/irish-genealogy-research

**Housekeeping:** `genealogy.db` should be removed from git tracking — run `git rm --cached genealogy.db`.

---

## 2. Workflow

```bash
# First-time setup
python -m src.db init
python -m src.db seed-places --file tullynaught_places.csv   # or via fetch_places

# Ingest census records
python -m src.db ingest --source 3 --file 1901_Tullynaught.csv
python -m src.db ingest --source 4 --file 1911_Tullynaught.csv
python -m src.db ingest --source 5 --file 1926_Tullynaught.csv

# Full reconstruction pipeline (stages 2–5)
python -m src.db reconstruct

# Inspect
python -m src.db summary

# Re-run pipeline (place_authority preserved)
python -m src.db reset
# re-ingest and reconstruct as above

# Explicit stages (finer control)
python -m src.db place-resolve
python -m src.db household
python -m src.db link
python -m src.db rebuild-consensus
```

---

## 3. Release Plan

### Release 1 — Full census pipeline (1901, 1911, 1926)

| # | Milestone | Status |
|---|---|---|
| R1-0 | Place authority seeding (logainm API + CSV) | ✅ Complete |
| R1-1 | Place resolution + household inference | ✅ Complete |
| R1-2 | Cross-census Splink person linkage (1901↔1911↔1926) | ✅ Complete — relationship features added; 1:1 bipartite gate enforced |
| R1-3 | Rebuild-consensus: post-linkage event arbitration (is_primary by vote count) | ✅ Complete — pending full pipeline retest |
| R1-4 | Person Browser basics (source coverage, merge error flags) | 🔜 Next — depends on service layer and flag/lead tables |

### Release 2 — Civil registration and parish registers

Civil registration sources (birth, marriage, death) and Catholic parish registers. Planned modules:
- `src/reconstruction/core.py` — shared Person/Relationship/Event commit logic extracted from `household_inference.py`
- `src/reconstruction/registration_inference.py`
- `src/reconstruction/parish_inference.py`

### Release 3 and beyond

Land records, military sources, folklore, service layer, consumer front ends.

---

## 4. Work Queue

### Tier 3 — Reconstruction pipeline

**Full pipeline retest** 🔜 — first priority:
```bash
python -m src.db reset
python -m src.db ingest --source 3 --file tests/1901_Tullynaught.csv
python -m src.db ingest --source 4 --file tests/1911_Tullynaught.csv
python -m src.db ingest --source 5 --file tests/1926_Tullynaught.csv
python -m src.db reconstruct
python -m src.db summary
```
Verify: correct is_primary marking; no person has >1 is_primary=true event per type; birth year delta violations reduced from 16.

**Linkage quality review** 🔜 — following retest:
- Review near-commit proposals (score 0.80–0.85) — if ≥80% correct, consider lowering AUTO_COMMIT_THRESHOLD to 0.82
- Term-frequency adjustment for `surname_norm` — deferred until 3–4 DEDs ingested for representative frequency distribution

**fix `review.py` proposal query** 🔜 — must read `training_labels WHERE decision='proposed'` (not `person_record WHERE verified=0`)

### Tier 4 — Service layer

**flag and lead tables** — DDL specified in `service_api.md` §10.3; needed before service layer can be built. `score` column on `person_record` also needs to be nullable for manual researcher assertions.

`src/service.py` — ResearchService class. Depends on flag/lead tables in schema.

### Tier 5 — Consumers

Claude consumer, Lovable UI, MCP server.

---

## 5. Open Decisions

### OD-02 — Derived confidence function

Provisional placeholder (record count → low/medium/high) in place. Real multi-source scored linkages now available after R1-2. Revisit after reviewing linkage quality from full pipeline retest.

---

## 6. Version History

| Version | Date | Change |
|---|---|---|
| 1.0 | May 2026 | Initial ROADMAP |
| 1.1 | May 2026 | Tier 1 and 2 complete; Tullynaught 1911 tested |
| 1.2 | May 2026 | R1-1 complete; Release Plan added; R1-2 as next milestone |
| 1.3 | May 2026 | Schema v2.6 (OD-01 resolved); census date fixes; 1926 normaliser corrected; migration added |
| 1.4 | May 2026 | Place authority redesign complete. PlaceAuthority added to foundational layer (flat schema, logainm.ie source). `src/fetch_places.py` and updated `src/seed_places.py` implemented. `src/reconstruction/place_resolution.py` v2.0. Schema v2.7. 33 tests passing. |
| 1.5 | June 2026 | Schema v2.8: RecordedEvent merged into Record; junction tables reduced from 9 to 5. R1-2 and R1-3 (validator) complete. Linkage first test run completed (3881 persons, 264 merged). Relationship features added to census feature extractor. Explicit `place-resolve`, `household`, `link` CLI commands added; `reconstruct` retained as convenience. OD-04 resolved (DuckDBAPI). TF adjustment deferred to multi-DED scale. |
| 1.6 | June 2026 | Evidence scoring design locked. Event-based consensus model: persons = conclusion entities; events = alternatives; is_primary marks plurality winner. rebuild-consensus algorithm specified in `evidence_scoring_design.md` v1.0. |
| 1.7 | June 2026 | Schema v2.9: event.is_primary added; training_labels added. `src/reconstruction/scoring.py` implemented (rebuild_consensus). CLI refactored: `reset` added; `reconstruct` now runs full pipeline (stages 2–5 including rebuild-consensus); `place-resolve` and `household` retained as explicit stages. |
| 1.8 | June 2026 | README and ROADMAP updated to reflect v2.9 schema, refactored CLI, and R1-3 completion. Full pipeline retest pending. |
