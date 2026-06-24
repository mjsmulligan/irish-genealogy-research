# Session 18: Review Layer Design

**Date:** 24 June 2026
**Status:** ✅ Design complete — implementation next session

---

## Objective

Design the review layer: the researcher-facing report module that replaces `src/review/validator.py`. The goal is a prioritised list of findings that tells a researcher what is most worth their attention in the current conclusion layer.

---

## Key Decisions

### 1. Clean break — not a port

`src/review/validator.py` is retired in full. The old rule codes (R40–R46), entry points (`validate`, `validate_object`, `validate_genealogical`), and flat error-string output format are all superseded. The new design is derived from `genealogical_constraints.md` and conceptual model §7.4, not from the old validator. Some domain logic reappears in the new findings functions, but this is incidental.

### 2. Primary interaction

```
python -m src.cli review
```

Returns a prioritised list of findings across the full database. No scoping arguments in v1.0. The researcher gets: *here are the things most worth your attention right now, in order.*

### 3. Heterogeneous priority list

Health findings (constraint violations, merge error candidates) and research prompts (gaps, leads) are interleaved by priority score — not separated into sections. The distinction is somewhat arbitrary in practice and the researcher's question is "what do I do next," not "what category of thing should I think about."

### 4. Read-only

The report module queries the conclusion layer. It does not write to it or to `conclusion_log`. Write semantics (marking findings as reviewed, acting on research prompts) are deferred to a later design iteration after real usage establishes what's needed.

### 5. Training session workflow

After the first implementation, run the report against real Supabase data in a focused session with Claude. Review the top findings: is this real or noise? Is the detail sufficient to make a judgment? What would the researcher want to do next? That feedback drives iteration on taxonomy, thresholds, and priority scoring. The design is intentionally held loosely — we expect to tune it.

### 6. `validate_object` disposition

Pre-write structural validation is DAL-adjacent, not a researcher-facing concern. It is not carried forward into the new design. If pre-write checks are needed they live in the repo layer. No immediate action required — the old function is simply not replaced.

---

## Data Structures

### `ReportItem`

```python
@dataclass
class ReportItem:
    finding_type:       str
    priority:           int           # 1 = highest; computed at assembly time
    person_id:          int | None
    relationship_id:    int | None
    event_id:           int | None
    record_ids:         list[int]     # evidence records underpinning the finding
    title:              str           # one-line summary
    detail:             str           # full explanation with specific DB values
    recommended_action: str | None
```

Key choices:
- No `category` field — health vs. research prompt is encoded implicitly in `finding_type` naming
- No `evidence` list — detail string carries what the researcher needs for now; structured evidence deferred until write semantics arrive
- No `severity` field — priority already encodes urgency; two fields saying the same thing is noise
- `record_ids` is a list — a finding may reference multiple Records (e.g. merge error candidate cites both Records)

### `Report`

```python
@dataclass
class Report:
    generated_at:   datetime
    items:          list[ReportItem]   # sorted by priority ascending
    summary:        dict               # counts by finding_type
```

Deliberately thin. No `reviewer_id` — becomes relevant when reports are persisted or write semantics arrive.

---

## Finding Taxonomy

### V1.0 scope (implement first)

| finding_type | Domain source | Notes |
|---|---|---|
| `merge_error_candidate` | GC07 | Person with 2+ active Records from same census source |
| `birth_singularity_violation` | GC04 | Multiple `is_primary=true` birth Events on one Person |
| `death_singularity_violation` | GC05 | Same for death |
| `life_event_sequence_violation` | GC02 | Chronological order broken — detail must show actual values so researcher can distinguish signal from measurement noise |
| `parent_age_implausible` | GC12 | Gap outside plausible range (< 15 yrs or > 50/70 maternal/paternal) |
| `marriage_age_implausible` | GC13 | Person under 15 at marriage date |
| `lifespan_boundary_violated` | GC01 | Record date outside concluded lifespan — detail must show actual delta |
| `unlinked_recorded_person` | — | RecordedPerson with no Person conclusion |
| `single_census_appearance` | — | Person in only one census, no concluded death Event |

Note on sequence/lifespan findings: thresholds should be conservative. The `detail` field must show actual recorded values (age in each census, year delta, expected range) so that precision issues (age 1 in 1901, age 10 in 1911 — delta 9, expected 10 ± 3) are immediately recognisable as noise rather than errors.

### Deferred (post-training-session)

| finding_type | Reason for deferral |
|---|---|
| `source_coverage_gap` | Requires full §4 eligibility logic from `genealogical_constraints.md` |
| `household_placement_unresolved` | Requires reasonably populated relationship graph (GC15 Case 3) |
| `female_occupier_inference` | Same dependency (GC16) |
| `sibling_birth_spacing` | < 9 months gap — low volume expected at Tullynaught scale |
| `naming_pattern_lead` | Experience-dependent; low confidence until relationship graph is verified |

---

## Priority Scoring

Three inputs collapse to a single integer priority score (1 = highest):

1. **Certainty** — schema-state findings (singularity violations, merge error candidates) score highest; inferred findings (source gaps, naming leads) score lower
2. **Severity** — findings that contaminate many downstream conclusions score higher than local findings
3. **Scope of impact** — Persons with more linked RecordedPersons across multiple censuses score higher than thinly-evidenced Persons

Exact weights are held loosely pending first training session.

---

## Output

Two files written per run, same timestamp in both filenames:

- `reports/report_YYYYMMDD_HHMMSS.json` — machine-readable; for training sessions and future MCP consumption
- `reports/report_YYYYMMDD_HHMMSS.md` — human-readable Markdown; for researcher review

Files are sortable by name to see history. No symlink or `latest` convention — `ls -t reports/` is sufficient.

Markdown structure:
```
# GRA Research Report — 24 June 2026 14:32

## Summary
- 3 merge error candidates
- 7 constraint violations
- 12 research prompts
- 22 total findings

## Findings

### 1. [MERGE_ERROR_CANDIDATE] Person 42 — Séamus Ó Gallchóir
...
```

---

## Module Structure

```
src/review/
    __init__.py
    report.py      # ReportItem and Report dataclasses
    findings.py    # one function per finding_type
    priority.py    # priority scoring
    runner.py      # assembles Report from findings, writes output files
```

---

## Documentation Updated

- `ROADMAP.md` — item 13 updated; §5.9 added with full design spec; session 18 added to version history
- `docs/validation_rules.md` — v2.9: supersession notice added at top; v2.9 changelog entry added

---

## Next Session

Implementation of the review layer:

1. Delete `src/review/validator.py`
2. Create `src/review/report.py` — dataclasses
3. Create `src/review/findings.py` — v1.0 finding functions (9 types)
4. Create `src/review/priority.py` — priority scoring
5. Create `src/review/runner.py` — assembly + file output
6. Add `review` subcommand to `src/cli.py`
7. Create `reports/` directory (add to `.gitignore` or commit empty with `.gitkeep`)
8. First run against Supabase to validate output
