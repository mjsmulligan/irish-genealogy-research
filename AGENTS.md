# Agent Instructions for GRA

This file is read by AI coding agents (Claude Code, Codex, Cursor, and
others that support the AGENTS.md convention). It's guardrails, not
explanation — for the reasoning behind any of these, see
[`ONBOARDING.md`](ONBOARDING.md), [`CONTRIBUTING.md`](CONTRIBUTING.md), and
[`docs/conceptual_model.md`](docs/conceptual_model.md).

## Non-negotiable rules

1. **Evidence layer never references conclusions.** `Record`,
   `RecordedPerson`, `RecordedRelationship`, `RecordSimilarity` (in
   `src/evidence/`) must have zero knowledge of `Person`, `Relationship`,
   `Event` (in `src/conclusion/`). Linkage flows exclusively
   conclusion → evidence, never the reverse. If a task seems to require
   evidence-layer code to check or reference a conclusion object, stop and
   flag it — don't route around the boundary.

2. **Never commit non-redistributable source data.** Historic Graves /
   headstone data is CC BY-NC-ND 4.0 and not cleared for redistribution —
   never write files derived from it into `data/` or anywhere else in this
   repo. Before adding any new data source, check its license in
   `docs/repositories.md`. If a source's redistribution terms aren't
   documented there, don't commit files from it — ask first. This exact
   mistake happened once already (see `ROADMAP.md` §8, September 2026); the
   fix required rewriting git history.

3. **`src/dal/` is the only place with raw SQL.** Repo-per-table pattern —
   one repository class per database table. Don't write a query inline in
   `src/evidence/`, `src/conclusion/`, `src/review/`, or anywhere else. If
   the DAL doesn't have the method you need, add it there first.

4. **Design-first for anything touching schema, the evidence/conclusion
   boundary, or linkage/matching scoring.** Don't start implementing. State
   the design, name the tradeoff, and wait for confirmation before writing
   code. Small, self-contained bug fixes don't need this — use judgment,
   and when unsure, ask.

5. **`src/genealogy/` encodes Irish domain rules** — name variants, age
   tolerances, the GC-coded constraints in
   `docs/genealogical_constraints.md`. If a change affects matching or
   validation behavior, check whether it belongs here before writing it
   inline in a pipeline step.

6. **Run the test suite before calling anything done.**
   `pytest tests/test_pipeline.py -v` should be fully green. If a change
   affects linkage thresholds or scoring, also run
   `python -m src.cli timing-report` and report any material shift in
   match rates.

## Before touching linkage, matching, or validation logic

Read [`docs/genealogical_constraints.md`](docs/genealogical_constraints.md)
first. It encodes real Irish genealogical domain knowledge (generational
name-recycling, co-residency patterns, source-priority rules) that looks
like arbitrary logic without that context — don't "simplify" or "fix" code
that implements a GC-coded rule without checking the rule first.

## Repo layout, one line each

- `src/cli.py` — sole entry point
- `src/db/` — schema lifecycle
- `src/ingest/` — external data acquisition (CSV in, DB/CSV out)
- `src/evidence/` — ingest + feature pipeline
- `src/conclusion/` — 4-step conclusion pipeline
- `src/review/` — report/findings/priority
- `src/genealogy/` — Irish domain rules (see rule 5 above)
- `src/dal/` — all SQL (see rule 3 above)

Full detail: [`README.md`](README.md).

## What "done" looks like

- Tests pass (rule 6)
- No evidence/conclusion boundary violation (rule 1)
- No raw SQL outside `src/dal/` (rule 3)
- No new data files without a checked license (rule 2)
- If you touched matching/validation logic, you read the relevant GC rule
  first, not after
