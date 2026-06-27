# Irish Genealogy Research — Review Layer

*Version 1.0 — 24 June 2026*
*Audience: Developers and researchers. This document is the authoritative specification for the review layer (`src/review/`). It is the companion to `conceptual_model.md` §7.4, `genealogical_constraints.md`, and `validation_rules.md`.*

______________________________________________________________________

## 1. Overview

The review layer surfaces areas of the conclusion database that warrant researcher attention. It is distinct from the audit trail (`conclusion_log`) — it is prospective rather than retrospective.

**Design principles:**
- Read-only — the report module queries the conclusion layer; it never writes to it or to `conclusion_log`
- Structured data first — output is a typed `Report` containing `ReportItem` entries, rendered to JSON and Markdown
- Iterative — first implementation covers confident findings only; thresholds and taxonomy are tuned after training sessions against real data

**CLI:** `python -m src.cli review`

No scoping arguments in v1.0. Full-database report only. Scoped review (per-person, per-finding-type) deferred until training sessions establish what is useful.

______________________________________________________________________

## 2. Module Structure

```
src/review/
    __init__.py
    report.py      # ReportItem and Report dataclasses
    findings.py    # one function per finding_type
    priority.py    # priority scoring
    runner.py      # assembles Report from findings, writes output files
```

`validate_object` disposition: pre-write structural validation is DAL-adjacent, not a researcher-facing function. It is not carried forward from the retired `validator.py`. If pre-write checks are needed they live in the repo layer directly.

______________________________________________________________________

## 3. Data Structures

### ReportItem

| Field | Type | Notes |
|---|---|---|
| `finding_type` | `str` | Controlled vocabulary — see §4 |
| `priority` | `int` | 1 = highest; computed at assembly time by `priority.py` |
| `person_id` | `int \| None` | |
| `relationship_id` | `int \| None` | |
| `event_id` | `int \| None` | |
| `record_ids` | `list[int]` | Evidence records underpinning the finding |
| `title` | `str` | One-line summary |
| `detail` | `str` | Full explanation with specific values from the DB |
| `recommended_action` | `str \| None` | |

### Report

| Field | Type | Notes |
|---|---|---|
| `generated_at` | `datetime` | |
| `items` | `list[ReportItem]` | Sorted by priority ascending |
| `summary` | `dict` | Counts by `finding_type` |

______________________________________________________________________

## 4. Finding Taxonomy

### v1.0 — Implemented

| `finding_type` | Domain source | Notes |
|---|---|---|
| `merge_error_candidate` | GC07 | Person with 2+ active Records from the same census source |
| `birth_singularity_violation` | GC04 | Multiple `is_primary=true` birth Events on one Person |
| `death_singularity_violation` | GC05 | Same for death |
| `life_event_sequence_violation` | GC02 | Chronological order broken — detail must show actual values so researcher can distinguish signal from measurement noise |
| `parent_age_implausible` | GC12 | Gap outside plausible range (< 15 yrs or > 50/70 maternal/paternal) |
| `marriage_age_implausible` | GC13 | Person under 15 at marriage date |
| `lifespan_boundary_violated` | GC01 | Record date outside concluded lifespan — detail must show actual delta |
| `unlinked_recorded_person` | — | RecordedPerson with no Person conclusion |
| `single_census_appearance` | — | Person in only one census, no concluded death Event |
| `link_conflict_resolved` | — | Step 2 attempted to re-link a RecordedPerson already assigned by Step 1; Step 1 assignment preserved |

### Deferred — after first training session

| `finding_type` | Notes |
|---|---|
| `source_coverage_gap` | Requires full §4 eligibility logic from `genealogical_constraints.md` |
| `household_placement_unresolved` | Requires populated relationship graph (GC15 Case 3) |
| `female_occupier_inference` | Same dependency (GC16) |
| `sibling_birth_spacing` | < 9 months gap between concluded siblings |
| `naming_pattern_lead` | Experience-dependent; low confidence (GC18) |

______________________________________________________________________

## 5. Priority Scoring

Three inputs collapse to a single integer rank (1 = highest priority):

1. **Certainty** — schema-state findings (singularity violations, constraint violations) score highest; inferred findings (source gaps, naming patterns) score lower
2. **Severity** — merge error candidates score higher than local findings
3. **Scope** — Persons with more linked RecordedPersons score higher (more evidence at stake)

Exact weights are tuned after the first training session against Supabase data.

______________________________________________________________________

## 6. Output

- `reports/report_YYYYMMDD_HHMMSS.json` — machine-readable; for training sessions and future MCP consumption
- `reports/report_YYYYMMDD_HHMMSS.md` — human-readable Markdown; for researcher review

Both written on each run. Files are sortable by filename to see history.

______________________________________________________________________

## Changelog

| Version | Date | Change |
|---|---|---|
| 1.0 | 24 June 2026 | Initial specification. Derived from ROADMAP.md §5.9 (session 18 design) and session 19 implementation. Finding taxonomy v1.0: nine implemented types, five deferred. `link_conflict_resolved` added (27 June 2026, double-link prevention work). |
