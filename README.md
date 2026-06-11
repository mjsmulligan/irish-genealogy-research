# Genealogy Research Assistant (GRA)

*grá — Irish for love*

A probabilistic genealogy research platform combining a SQLite knowledge base, authoritative place data from logainm.ie, record linkage scoring, genealogical domain reasoning, and comprehensive validation. Evidence and conclusion layers strictly separated. Designed for Irish genealogy research at townland scale.

Schema version: **2.9** (June 2026)

---

## Project Status

> **→ See [`ROADMAP.md`](ROADMAP.md) for current work queue, open decisions, and what to focus on next.**

---

## Documentation

| File | Status | Description |
|---|---|---|
| `docs/conceptual_model.md` | ✅ v2.4 | Three-layer architecture; event fields inline on Record |
| `docs/data_dictionary.md` | ✅ v2.6 | Field-level definitions; flat PlaceAuthority schema; full NAI census role mapping |
| `docs/repositories.md` | ✅ v1.5 | 13 sources across 8 repositories; logainm.ie added |
| `docs/validation_rules.md` | ✅ v2.6 | 46 rules (R01–R46) |
| `docs/database_schema.md` | ✅ v2.9 | SQLite DDL; RecordedEvent merged into Record; 5 junction tables; event.is_primary added |
| `docs/reconstruction_algorithms.md` | ✅ v1.5 | Linkage pipeline: household pass, person pass, Splink config, gates, merge contract |
| `docs/genealogical_constraints.md` | ✅ v1.2 | 22 domain constraints (GC01–GC22) |
| `docs/service_api.md` | 🔜 v1.0 | Service layer API — designed, not yet implemented |
| `docs/session_bootstrap.md` | ✅ v1.0 | Ingest session protocols |
| `docs/future_ideas.md` | ✅ v1.0 | Deferred features: service layer, GEDCOM, event linkage, incremental mode |
| `ROADMAP.md` | ✅ v1.8 | Work queue, open decisions, project roadmap |

---

## Repository Structure

```
irish-genealogy-research/
│
├── docs/                              # Schema and system documentation
│
├── src/                               # Implementation
│   ├── db/
│   │   ├── schema.sql                 # Complete DDL (v2.9)
│   │   ├── seed.sql                   # Repository and source seed data
│   │   └── migrations/
│   │       ├── migrate_25_to_26.sql
│   │       ├── migrate_26_to_27.sql   # place → place_authority
│   │       └── migrate_27_to_28.sql   # recorded_event merged into record
│   ├── reconstruction/
│   │   ├── __init__.py
│   │   ├── place_resolution.py        # Stage 2: authority-based place matching
│   │   ├── household_inference.py     # Stage 3: household structure → conclusions
│   │   ├── linkage.py                 # Stage 4: cross-census Splink person linkage
│   │   ├── scoring.py                 # Stage 5: rebuild-consensus (event is_primary arbitration)
│   │   ├── debug.py                   # Debug log writer; shared threshold constants
│   │   └── features/
│   │       └── census.py              # Splink feature extractor (name, age, place, relationships)
│   ├── db.py                          # Database layer and CLI
│   ├── fetch_places.py                # logainm API fetcher → DB or CSV
│   ├── seed_places.py                 # CSV → place_authority loader
│   └── validator.py                   # Genealogical constraint rules R40–R46
│
└── tests/
    └── test_place_authority.py        # 33 tests: schema, CSV, resolution, hierarchy
```

---

## System Architecture

### Three-Layer Data Model

**Foundational Layer** — Repository, Source, PlaceAuthority
Institutional, bibliographic, and geographical reference data. PlaceAuthority entries are seeded from logainm.ie before research begins — they are facts, not conclusions.

**Evidence Layer** — Record, RecordedPerson
Verbatim assertions from historical sources. Each Record carries its event fields inline (`event_type`, `date`, `place_as_recorded`). Never points to conclusions.

**Conclusion Layer** — Person, Relationship, Event
Researcher assertions, mutable and supported by evidence.

### Reconstruction Pipeline

```
0. Place seeding      → place_authority populated from logainm.ie        ✅ implemented
1. Ingest             → Evidence layer populated                          ✅ implemented
2. Place resolution   → Evidence strings matched to place_authority       ✅ implemented
3. Household          → Census structure → Person/Relationship/Event      ✅ implemented
4. Linkage            → Cross-census Splink person linkage                ✅ implemented
5. Rebuild-consensus  → Event is_primary arbitration by record votes      ✅ implemented
6. Analysis           → Community queries, graph traversal, GEDCOM        🔜 future
```

### Linkage Design

The Splink linkage model uses `link_only` mode — candidate pairs are generated exclusively across census years (1901↔1911, 1901↔1926, 1911↔1926). Within-source pairs are never generated, eliminating spurious intra-census merges.

**Two-pass pipeline:**
- **Pass 1 (household):** Matches whole census households across years using role-independent household features (modal surname, adult forename set, child forename sets split by age). Confirmed household pairs then resolve individual identities within each pair.
- **Pass 2 (person):** Matches individual Persons not resolved in Pass 1, using person-level features drawn from both the evidence layer and the conclusion layer.

**Comparisons** (person pass):
- Surname (Jaro-Winkler + TF adjustment) — high-frequency surnames downweighted automatically
- Forename (Jaro-Winkler + TF adjustment) — common forenames downweighted automatically
- Estimated birth year (absolute difference, GC03 tolerances: ±3 yr for 10/15-year gaps, ±4 yr for 25-year gap)
- Resolved townland (`place_id` exact match)
- Concluded spouse name (Jaro-Winkler)
- Concluded child name set (Szymkiewicz–Simpson — correct for cross-census where child departure is expected)
- Concluded sibling name set (Szymkiewicz–Simpson)

**Per-pair gates:** Forename gate (demotes pairs where forenames are maximally dissimilar) and birth year coherence gate (demotes pairs outside GC03 tolerance) run after Splink scoring.

**Identity resolution** uses a path-compressed union-find structure (`_UnionFind`) with transitive closure. A 1:1 bipartite constraint (`committed_this_run`) ensures no person appears in more than one auto-committed merge per run.

**Proposals** (score 0.30–0.85) are written to `training_labels (decision='proposed')` only.

### Consensus Building

After linkage, `rebuild-consensus` (stage 5) arbitrates `Event.is_primary` for each merged person. For each person + event type, record votes are counted via the `event_record` junction; the highest-vote event is marked `is_primary=true` and all alternatives `is_primary=false`. Ties are broken deterministically by lower `event_id`. The stage is idempotent and safe to rerun.

---

## Getting Started

```bash
pip install -r requirements.txt

# First-time setup: initialise database and seed place authority
python -m src.db init
python -m src.fetch_places --logainm-id 111482 --db genealogy.db
# Or seed from a pre-fetched CSV:
python -m src.db seed-places --file tullynaught_places.csv

# Ingest census records
python -m src.db ingest --source 3 --file tests/1901_Tullynaught.csv
python -m src.db ingest --source 4 --file tests/1911_Tullynaught.csv
python -m src.db ingest --source 5 --file tests/1926_Tullynaught.csv

# Run full reconstruction pipeline (stages 2–5)
python -m src.db reconstruct

# Inspect
python -m src.db summary
```

### Re-running the Pipeline

To wipe evidence and conclusions and re-run (place_authority is preserved by default):

```bash
python -m src.db reset          # preserves place_authority
python -m src.db ingest --source 3 --file tests/1901_Tullynaught.csv
python -m src.db ingest --source 4 --file tests/1911_Tullynaught.csv
python -m src.db ingest --source 5 --file tests/1926_Tullynaught.csv
python -m src.db reconstruct
python -m src.db summary
```

To reseed places from scratch:

```bash
python -m src.db reset --all    # wipes everything including place_authority
# delete and reinitialise: rm genealogy.db && python -m src.db init
python -m src.db seed-places --file tullynaught_places.csv
# then ingest and reconstruct as above
```

### Explicit Pipeline Stages

For finer control, each stage can be run independently:

```bash
python -m src.db place-resolve      # stage 2: resolve all unresolved place strings
python -m src.db household          # stage 3: household inference across all sources
python -m src.db link               # stage 4: cross-census Splink person linkage
python -m src.db rebuild-consensus  # stage 5: arbitrate event is_primary by record votes
```

**Supported ingest sources:** Census 1901 (source 3), Census 1911 (source 4), Census 1926 (source 5). Additional sources planned for Release 2.

**Logainm API key:** Required for `fetch_places`. Set via `LOGAINM_API_KEY` environment variable or `--api-key` argument.

---

## requirements.txt

```
splink>=4.0
jellyfish>=1.0
pandas>=2.0
jsonschema>=4.0
pytest>=8.0
requests>=2.31
black
```

---

*Designed for Irish genealogy research at townland scale. Evidence from civil registrations (1864+), census returns (1901, 1911, 1926), land records (Griffith's Valuation, Tithe Applotment), parish registers, and military/folklore sources. Place authority from logainm.ie.*
