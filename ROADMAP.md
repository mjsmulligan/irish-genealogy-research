# Genealogy Research Assistant (GRA) — Project Roadmap

*17 June 2026*

---

## 1. Current State

### Documentation

| Document | Status | Notes |
|---|---|---|
| `docs/conceptual_model.md` | ✅ Complete | RecordedEvent merged into Record |
| `docs/data_dictionary.md` | ✅ Complete | RecordedEvent removed; event fields inline on Record |
| `docs/repositories.md` | ✅ Complete | Repository 8 (logainm.ie) and Source 13 (place_authority) added |
| `docs/validation_rules.md` | ✅ Complete | R40–R46 implemented; retired rules updated |
| `docs/database_schema.md` | ✅ Complete | v3.0 DDL; `training_labels` + `event.is_primary` added |
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

---

## 3. Release Plan

* **v1.x (Current):** Stabilize schema (v3.0), complete documentation drift remediation, and verify pipeline against Tullynaught DED test data.
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

---

## 5. Open Decisions

* **Pipeline Reset:** Decide if `reset_pipeline.py` should be exposed via `src.cli` or kept as a standalone utility.
* **Source Expansion:** Prioritize Griffith’s Valuation vs. Tithe Applotment for the next ingest module.

---

## 6. Version History

| Date | Milestone / Change |
|---|---|
| 17 June 2026 | **Consolidation:** Resolved path drift, implemented migration scripts (v2.8→v3.0), restored roadmap structure, archived inactive documentation, and sync'd constraint versioning to v1.2. |
| 16 June 2026 | **Schema v3.0:** Finalized (`event.is_primary`, nullable roles). Linkage correctness pass: `link_only`, `_UnionFind`, Positional pairing, Per-merge transactions. |
| Early June 2026 | **Schema v2.8:** RecordedEvent merged into Record; junction tables 9→5. First full linkage test (3881 persons, 264 merged). Relationship features added. |
| 24 May 2026 | **Foundation & R1-1:** Initial GRA roadmap/rename established. Tier 1/2 complete; Tullynaught 1911 verified. Implemented place resolution and household inference (R1-1); established Release Plan (R1–R3). |