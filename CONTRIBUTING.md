# Contributing to GRA

Thanks for getting involved. GRA has two kinds of contributors — code and
research/QA — and this doc covers both. If you're not sure which track
applies to you, ask.

## Project shape (read this first)

GRA keeps a strict separation between **evidence** (Record, RecordedPerson,
RecordedRelationship — faithful transcription, no interpretation) and
**conclusions** (Person, Relationship, Event — researcher/algorithm
assertions built on top of evidence). Nothing in the evidence layer should
ever "know about" a conclusion. If a change blurs that line, it needs a
design discussion before code.

Start here:
- [`README.md`](README.md) — architecture, CLI usage, running tests
- [`ROADMAP.md`](ROADMAP.md) — current work queue and version history
- [`docs/conceptual_model.md`](docs/conceptual_model.md) — the data model
- [`docs/genealogical_constraints.md`](docs/genealogical_constraints.md) — the
  domain rules (GC-coded constraints) that the conclusion layer enforces

## For developers

**Setup**
1. Clone the repo, `pip install -r requirements.txt`.
2. Copy `.env.example` → `.env` (ask the maintainer if this doesn't exist
   yet) and set `DATABASE_URL` for a local PostgreSQL instance.
3. `python -m src.cli init` to build the schema.
4. `pytest tests/test_pipeline.py -v` — should be all green before you start.

**Workflow**
- Design-first: for anything touching schema, the evidence/conclusion
  boundary, or linkage scoring, open an issue or discussion before writing
  code. Small bug fixes and doc corrections don't need this.
- One logical change per PR. Include the test(s) that cover it.
- `src/dal/` is the only place that writes raw SQL — repo-per-table pattern.
  Don't reach around it from `src/evidence/`, `src/conclusion/`, etc.
- `src/genealogy/` encodes Irish domain rules (name variants, age tolerances,
  GC-coded constraints). If your change affects matching or validation
  behavior, check whether it belongs here rather than inline in a pipeline
  step.
- Run the full test suite before opening a PR. If you're changing linkage
  thresholds or scoring, also run `python -m src.cli timing-report` and note
  any material shift in match rates in the PR description.

**Never commit:**
- `.env` or any credentials
- Anything under a non-redistributable source license (see **Data
  licensing** below)
- Generated DB files (`*.db`), `.DS_Store`, or other local cruft — check
  `.gitignore` covers it before adding a new generated file type

## For researchers / QA

You don't need to write Python to contribute meaningfully here — a lot of
the most valuable work is reviewing what the pipeline concludes against
what you know as a genealogist.

**What this looks like in practice:**
- Run `python -m src.cli review` to generate a prioritised findings report
  (`reports/*.md`) — flagged merge conflicts, age anomalies, household
  inconsistencies.
- Use the web UI (`python -m src.cli web`, then `http://localhost:5000`) to
  browse individual Person records, see the evidence behind a conclusion,
  and check the audit trail (`/audit`).
- When something looks wrong, the useful report is: which Person/Record IDs,
  what you'd expect instead, and why (source citation if you have one).
  That maps directly to `docs/genealogical_constraints.md` — if you're
  finding a pattern that isn't covered by an existing GC-coded rule, that's
  a strong signal a new constraint is needed.
- `export-validation` (`python -m src.cli export-validation`) produces a CSV
  of linkage pairs for manual review outside the web UI, if that's easier
  for a working session.

Findings and constraint proposals go in `analysis/` or as an issue —
check with the maintainer which the project is using day-to-day, since
both exist right now.

## Data licensing — read before adding any data file

This repo's code is under the [PolyForm Noncommercial License](LICENSE).
**Data files are a separate matter** — each source has its own terms:

- **Census CSVs (NAI, 1901/1911/1926):** already tracked in `data/`.
- **Historic Graves / headstone data (CC BY-NC-ND 4.0):** **do not commit
  this to the repository.** The license does not clear it for
  redistribution. Keep any headstone extraction CSVs local and untracked.
- Any new source: confirm its redistribution terms before adding files to
  `data/`, and note the terms in `docs/repositories.md`.

If you're unsure whether a file is safe to commit, ask before pushing.
