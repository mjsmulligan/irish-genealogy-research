# Start Here

One page to get oriented, then send you to the right doc. Pick your track.

## If you're writing code

1. Read [`README.md`](README.md) — architecture, CLI, how to run tests.
2. Read [`docs/conceptual_model.md`](docs/conceptual_model.md) — the
   evidence/conclusion split. Everything else assumes you understand this.
3. Set up per [`CONTRIBUTING.md`](CONTRIBUTING.md#for-developers), get
   `pytest tests/test_pipeline.py -v` green, then look at
   [`ROADMAP.md`](ROADMAP.md) §"Open work queue" for something to pick up.

## If you're doing genealogy research / QA

1. Read [`docs/conceptual_model.md`](docs/conceptual_model.md) — same
   starting point as developers; it's written for all roles and has no
   implementation detail.
2. Read [`docs/RESEARCHER_VALIDATION.md`](docs/RESEARCHER_VALIDATION.md) —
   how to review computer-generated linkages against what you know.
3. Follow [`CONTRIBUTING.md`](CONTRIBUTING.md#for-researchers--qa) — run the
   web UI and the `review` command, and how to report what you find.

## The doc suite

Every doc under `docs/` states its own audience and reading order at the
top. Rough map:

| Doc | For | What it's for |
|---|---|---|
| [`conceptual_model.md`](docs/conceptual_model.md) | Everyone | The data model, in plain terms. No implementation detail. Read this first regardless of track. |
| [`data_dictionary.md`](docs/data_dictionary.md) | Developers | Every field on every object. The reference you'll actually keep open while coding. |
| [`database_schema.md`](docs/database_schema.md) | Developers | DDL. **Caveat:** its own header still describes this as a SQLite spec — the live stack is PostgreSQL/Supabase (`src/db/schema.sql` is the source of truth if the two ever disagree). Worth a fix, tracked as a known doc-drift item. |
| [`genealogical_constraints.md`](docs/genealogical_constraints.md) | Developers, domain reasoning | The GC-coded Irish genealogical rules (name variants, age tolerances, household patterns) that gate linkage and validation. |
| [`reconstruction_algorithms.md`](docs/reconstruction_algorithms.md) | Developers | How the conclusion layer is built from evidence — the linkage/scoring algorithms themselves. |
| [`repositories.md`](docs/repositories.md) | Everyone | Reference for every data source (census, parish registers, headstones) and their repository/source IDs — check here before ingesting anything new, including licensing terms. |
| [`review_layer.md`](docs/review_layer.md) | Developers, researchers | Spec for `src/review/` — how findings get generated and prioritised. |
| [`RESEARCHER_VALIDATION.md`](docs/RESEARCHER_VALIDATION.md) | Researchers | How to manually validate pipeline output against ground truth. |
| [`performance.md`](docs/performance.md) | Developers | Scaling notes — relevant once you're working with a multi-DED dataset rather than a single townland. |
| [`bmd_exploratory_design.md`](docs/bmd_exploratory_design.md) | Developers | Exploratory design for civil registration (birth/marriage/death) integration — not yet implemented, useful context if you pick up that roadmap item. |

## Everything else

- [`AGENTS.md`](AGENTS.md) — guardrails for AI coding agents. If you're
  pairing with one on this repo, point it here explicitly even if it
  claims to have already read it.
- [`ROADMAP.md`](ROADMAP.md) — current priorities, open work queue, version
  history. Check this before starting anything so you're not duplicating
  in-flight work.
- [`changelog/`](changelog/) — session-by-session history. Useful for
  "why does this code look like this" archaeology; not required reading.
- [`analysis/`](analysis/) — investigative deep-dives. Reference material,
  not a reading list — search it when you hit a specific question.
- [`archive/`](archive/) — superseded working documents kept only for
  traceability. Each subfolder has its own README explaining what happened
  to the ideas in it and where the durable outcome actually lives. You
  should essentially never need to open this.

If you're unsure where something belongs, ask rather than guessing —
the evidence/conclusion boundary in particular has bitten people before.
