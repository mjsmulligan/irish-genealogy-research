# Session 19: Review Layer Implementation

**Date:** 24 June 2026
**Status:** ✅ Complete — implementation delivered; first run against Supabase is next session

---

## Objective

Implement the review layer designed in session 18. Replace `src/review/validator.py` with the new researcher report module.

---

## Delivered

### New files

| File | Description |
|---|---|
| `src/review/__init__.py` | Package marker (new) |
| `src/review/report.py` | `ReportItem` and `Report` dataclasses; `to_dict()`, `to_json()`, `to_markdown()` serialisers |
| `src/review/findings.py` | Nine v1.0 finding functions + `run_all_findings()` aggregator |
| `src/review/priority.py` | Priority scoring: tier base scores × scope multiplier → integer rank |
| `src/review/runner.py` | `run_review()`, `write_report()`, `run_and_print()` |
| `reports/.gitkeep` | Tracks `reports/` directory in git; add `reports/` to `.gitignore` |

### Modified files

| File | Change |
|---|---|
| `src/cli.py` | `validate` subcommand → `review`; old `_cmd_validate` → `_cmd_review` |
| `src/review/validator.py` | **Delete** |

---

## Implementation notes

### findings.py — SQL placement

All SQL in `findings.py` lives directly in the finding functions rather than in `src/dal/`. These are ad-hoc multi-join analytical queries serving exactly one consumer (the report module). DAL repos cover the conclusion-layer write path; finding functions cover the read-only reporting path. Putting them in the DAL would add CRUD-adjacent plumbing for queries that aren't CRUD.

### findings.py — PostgreSQL, not SQLite port

`_derive_birth_year()` and all queries are rewritten fresh for PostgreSQL:
- `%s` placeholders (not `?`)
- `person_recorded_person → recorded_person → record` join path (current schema)
- `is_primary = 1` used to source birth/death years from the correct Event
- `ARRAY_AGG(... ORDER BY ...)` used for deterministic multi-value outputs

### Finding taxonomy — v1.0 scope implemented

| finding_type | Domain |
|---|---|
| `merge_error_candidate` | GC07 |
| `birth_singularity_violation` | GC04 |
| `death_singularity_violation` | GC05 |
| `life_event_sequence_violation` | GC02 |
| `parent_age_implausible` | GC12 |
| `marriage_age_implausible` | GC13 |
| `lifespan_boundary_violated` | GC01 |
| `unlinked_recorded_person` | — |
| `single_census_appearance` | — |

Five deferred finding types (from session 18 design) remain deferred pending the training session.

### Priority scoring

Three tiers in `priority.py`:
- `_TIER_SCHEMA_STATE` (100): merge error candidates, singularity violations — highest certainty, most downstream impact
- `_TIER_CONSTRAINT` (200): sequence violations, parent age, marriage age, lifespan boundary
- `_TIER_RESEARCH_PROMPT` (300): unlinked RecordedPersons, single census appearances

Scope weight: Persons evidenced across 3 census sources → ×0.80; 2 sources → ×0.90; 1 source → ×1.00. Raw float score → sorted → integer rank assigned 1..N. All weights are module-level constants in `priority.py`, tunable after first training session without touching logic.

### CLI

`python -m src.cli review`

Runs all findings, writes two timestamped files:
- `reports/report_YYYYMMDD_HHMMSS.json` — machine-readable
- `reports/report_YYYYMMDD_HHMMSS.md` — researcher-readable Markdown

Prints a summary to stdout including top-10 findings by priority.

---

## Next session

1. Add `reports/` to `.gitignore` (keep `.gitkeep`)
2. First run: `python -m src.cli review` against Supabase data
3. Training session: review top findings with Claude — is this real or noise? Is the detail sufficient? What would the researcher do next?
4. ROADMAP item 13 → complete after clean first run
5. ROADMAP item 34: test harness v4.0 updates still outstanding
6. ROADMAP item 15: pin exact similarity/conclusion counts after first clean run
