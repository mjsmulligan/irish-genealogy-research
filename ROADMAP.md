# Genealogy Research Assistant (GRA) — Project Roadmap

*17 June 2026 — v1.7*

---

## 1. Current State

### Documentation

| Document | Version | Status | Notes |
|---|---|---|---|
| `docs/conceptual_model.md` | v2.4 | ✅ Complete | RecordedEvent merged into Record |
| `docs/data_dictionary.md` | v2.6 | ✅ Complete | RecordedEvent removed; event fields inline on Record |
| `docs/repositories.md` | v1.5 | ✅ Complete | Repository 8 (logainm.ie) and Source 13 (place_authority) added |
| `docs/validation_rules.md` | v2.6 | ✅ Complete | R40–R46 implemented; retired rules updated for schema v2.8 |
| `docs/database_schema.md` | v3.0 | ✅ Complete | `training_labels` + `event.is_primary` added; `recorded_person.role` nullable |
| `docs/reconstruction_algorithms.md` | v1.2 | ✅ Complete | Updated for schema v2.8; event linkage simplified |
| `docs/genealogical_constraints.md` | v1.2 | ✅ Complete | 22 GC-coded constraints |
| `docs/service_api.md` | v1.0 | ✅ Complete | Service layer API; flag/lead tables still needed |
| `docs/session_bootstrap.md` | v1.0 | ✅ Complete | Ingest and update knowledge session protocols |
| `ROADMAP.md` | v1.7 | ✅ Complete | Updated structure and remediation queue |

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
* **v2.0 (Target):** Implementation of full-scale Irish Census (1901–1926) ingestion and analysis. Introduce `future_ideas.md` features (e.g., flag/lead schema additions, pending v3.1 schema).
* **v3.0 (Long-term):** Analysis layer: community queries, graph traversal, and automated GEDCOM export.

---

## 4. Work Queue

| # | Item | Status |
|---|---|---|
| 2 | Migration scripts: `migrate_28_to_29.sql` / `migrate_29_to_30.sql` created. | ✅ Resolved (17 Jun) |
| 3 | `service_api.md` deprecation: Move to `/archive` or add "Deprecated" banner. | 🔜 |
| 4 | `future_ideas.md` update: Reset target schema version from v2.10 to v3.1. | 🔜 |
| 5 | Path drift: `fetch_places.py` / `seed_places.py` / `reset_pipeline.py` location corrected to `src/db/`. | ✅ Resolved (17 Jun) |
| 6 | Update `genealogical_constraints.md` metadata: Correct version to v1.2. | 🔜 |
| 7 | Update stale schema footers: Audit all `docs/` files to reflect v3.0. | 🔜 |

---

## 5. Open Decisions

* **Pipeline Reset:** Decide if `reset_pipeline.py` should be exposed via `src.cli` or kept as a standalone utility.
* **Source Expansion:** Prioritize Griffith’s Valuation vs. Tithe Applotment for the next ingest module.

---

## 6. Version History

* **1.7 (17 June 2026):** Resolved path drift (`src/db/` corrections), implemented migration scripts (v2.8→v3.0), and restored roadmap structure.
* **1.6 (16 June 2026):** Schema v3.0 finalized (`event.is_primary`, nullable roles).
* **1.5 (Early June 2026):** Integration of `logainm.ie` place authority.