# GRA — Session Changelog: 28 June 2026 (Genealogy Layer)

*Schema: v4.3 (unchanged) | Session focus: validation audit → genealogy layer refactor*

---

## Context

Two review passes were conducted this session before implementation:

1. **Pipeline validation review** — systematic audit of all places where validation logic
   runs across the pipeline, checking for drift from `genealogical_constraints.md` and
   structural issues.

2. **Architectural framing** — concluded that the problem was not individual bugs but a
   missing architectural home for genealogical domain knowledge. `src/validation/` existed
   but was being bypassed, duplicated, and called with inconsistent tolerances. The correct
   framing: genealogical constraints and domain knowledge should live in one layer, callable
   by evidence, conclusion, and review.

**Decision:** Rename `src/validation/` → `src/genealogy/`. The new module is the
materialisation of `docs/genealogical_constraints.md` — the single authoritative expression
of Irish genealogical domain expertise available to all pipeline layers.

---

## Bugs Fixed

### B1 — Age tolerance wrong for all census pairs (GC §2.3)

`validate_age_progression()` applied ±2 years unconditionally. Spec requires:
- 1901↔1911 (10-year span): ±3 years
- 1911↔1926 (15-year span): ±3 years
- 1901↔1926 (25-year span): ±4 years

This was a material contributor to false negatives — valid cross-census matches being
rejected by `_filter_invalid_pairs` before clustering, which in turn contributed to
`PERSON_RESOLUTION_THRESHOLD` being lowered to 0.45.

**Fix:** New `CENSUS_AGE_TOLERANCE` dict in `src/genealogy/ages.py`. `evaluate_age_progression()`
takes `source_id` arguments and derives both year and tolerance internally. No caller sets
a tolerance value manually.

### B2 — `remove_flagged_linkages()` deleted only one side of each pair

`validate_all_linkages()` stored both `recorded_person_id_1` and `recorded_person_id_2` in
the flagged pair dict but assigned both keys from the same column (`prp.recorded_person_id`).
`prp2.recorded_person_id` was never extracted. The deletion then only removed one of the two
linkages per violation, leaving the other intact.

**Fix:** `apply_constraints_to_linkages()` selects both `prp.recorded_person_id` and
`prp2.recorded_person_id` as distinct columns. `remove_flagged_linkages()` deletes both.

### B3 — `_classify_first_name_variant()` never returned `'exact'`

Documented as returning `'exact' | 'approved' | 'suspicious'` but only ever returned
`'approved'` or `'suspicious'`. The Splink highest-confidence comparison level
(`name_first_name_variant_l = 'exact' OR name_first_name_variant_r = 'exact'`) was
permanently dead — no pair ever reached it.

**Fix:** `classify_forename()` in `src/genealogy/names.py` returns `'exact'` for names
that are keys in `APPROVED_NAME_VARIANTS` (canonical forms with known aliases), `'approved'`
for names that appear as values (known aliases), and `'suspicious'` for all others.
The Splink comparison tier is now live.

### B4 — `household_same_census_errors` field always zero

`ValidationReport.household_same_census_errors` was declared but never assigned.
`validate_household_coherence()` returned a combined count that all went to
`household_errors`. The field was meaningless.

**Fix:** `check_household_coherence()` in `src/genealogy/constraints.py` returns
`(within_household_errors, same_census_errors, descriptions)` as distinct counts.
`ConstraintReport` tracks `household_errors` as the combined total (sufficient for
cleanup purposes). The stale `household_same_census_violations_removed` field removed
from `ValidationCleanupResult`.

### B5 — Inline `{3: 1901, 4: 1911, 5: 1926}` dict duplicated in three modules

The same bare dict literal appeared independently in:
- `src/conclusion/person_resolution.py`
- `src/conclusion/relationship_resolution.py`
- `src/validation/linkage_validation.py`
- `src/evidence/similarity.py` (as `_CENSUS_YEAR`)
- `src/evidence/features/census_person.py` (as `_SOURCE_YEAR`)

**Fix:** All five replaced by `CENSUS_YEAR` from `src/genealogy/ages.py`.

### B6 — Deferred `from src.validation import validate_age_progression` in `relationship_resolution.py`

Import placed inside a function body rather than at module top level. Also bypassed
the module's public interface.

**Fix:** Top-level import from `src.genealogy`.

### B7 — `APPROVED_NAME_VARIANTS` had duplicate `william` key

Two separate `'william'` entries in the dict — the second silently overwrote the first,
losing `'liam'`, `'will'`, and `'willie'` from its variant set.

**Fix:** Merged into a single canonical entry in `src/genealogy/names.py`.
`'wm'` given its own reverse entry.

---

## New Module: `src/genealogy/`

**`src/genealogy/names.py`**

Authoritative Irish name knowledge:
- `APPROVED_NAME_VARIANTS` — cleaned dict of known first-name aliases
- `IRISH_MALE_NAMES` / `IRISH_FEMALE_NAMES` — deduplicated frozensets
- `_ALL_APPROVED` — pre-computed frozenset of all names in variant graph (O(1) lookup)
- `classify_forename(forename) -> 'exact' | 'approved' | 'suspicious'`
- `infer_gender(name) -> 'M' | 'F' | None`

**`src/genealogy/ages.py`**

Census age progression rules:
- `CENSUS_AGE_TOLERANCE: dict[tuple[int,int], float]` — per source-pair tolerances
- `CENSUS_YEAR: dict[int, int]` — canonical source_id → year mapping
- `AgeProgressionResult` dataclass
- `evaluate_age_progression(age1, source_id_1, age2, source_id_2) -> AgeProgressionResult`

**`src/genealogy/constraints.py`**

Pairwise evaluation and DB-level structural checks:
- `GenderConsistencyResult`, `NameVariantResult`, `PairViolation`, `PairEvaluation`, `ConstraintReport`
- `evaluate_gender_consistency(name1, name2) -> GenderConsistencyResult`
- `evaluate_name_variant(name1, name2) -> NameVariantResult`
- `evaluate_pair(name1, age1, source_id_1, name2, age2, source_id_2) -> PairEvaluation` — unified gate
- `check_household_coherence(conn) -> (within_errors, census_errors, descriptions)`
- `apply_constraints_to_linkages(conn) -> ConstraintReport` — full linkage sweep
- `remove_flagged_linkages(conn, report, dry_run) -> (count, message)` — both sides deleted

**`src/genealogy/__init__.py`**

Full public interface exported; docstring describes the layer's role and lists all public names.

---

## Files Modified

| File | Change |
|---|---|
| `src/genealogy/__init__.py` | **New** — public interface |
| `src/genealogy/names.py` | **New** — Irish name knowledge |
| `src/genealogy/ages.py` | **New** — age progression rules |
| `src/genealogy/constraints.py` | **New** — pairwise evaluation + DB sweeps |
| `src/evidence/features/census_person.py` | Imports `classify_forename`, `CENSUS_YEAR` from genealogy; `_classify_first_name_variant` delegates to `classify_forename`; `_SOURCE_YEAR` removed |
| `src/evidence/similarity.py` | `_CENSUS_YEAR` imported from genealogy |
| `src/conclusion/person_resolution.py` | Imports `evaluate_pair`, `CENSUS_YEAR`; `_filter_invalid_pairs` rewrites to call `evaluate_pair`; inline dict removed |
| `src/conclusion/relationship_resolution.py` | Top-level import of `evaluate_age_progression`, `CENSUS_YEAR`; deferred import and inline dict removed |
| `src/conclusion/validation_cleanup.py` | Calls `apply_constraints_to_linkages`; stale `household_same_census_violations_removed` field and print line removed |
| `src/cli.py` | `validate-linkages` calls `apply_constraints_to_linkages`; print heading updated to "GENEALOGICAL CONSTRAINT REPORT"; gender flips now shown in output |

## Files to Delete

| File | Reason |
|---|---|
| `src/validation/linkage_validation.py` | Superseded by `src/genealogy/` |
| `src/validation/__init__.py` | Superseded by `src/genealogy/__init__.py` |
| `src/validation/` (directory) | Empty after above deletions |

---

## Work Queue Changes

Items closed: B1–B7 (all resolved inline with the refactor).

New items added to ROADMAP §4:

| # | Item |
|---|---|
| 42 | **`validation_rules.md` → `genealogical_constraints.md` consolidation.** Two documents cover overlapping content with two numbering schemes (R-codes and GC-codes). `genealogical_constraints.md` is the de facto authority (code references GC codes only). Merge content from `validation_rules.md` into `genealogical_constraints.md`; retire `validation_rules.md` or reduce it to a pointer. Update `review_layer.md` §6.1 reference. |
| 43 | **`is_primary = 1` → `is_primary = TRUE` in `findings.py`.** PostgreSQL boolean idiom; correctness risk if column type tightened. Sweep all SQL in `findings.py`. |
| 44 | **Sequence check in `find_life_event_sequence_violations()` should prefer `is_primary` dates.** Currently uses `earliest_year()` across all events of a type — a non-primary event with a bad date can trigger a spurious violation. Use `_derive_birth_year()` / `_derive_death_year()` helpers (which already handle this) instead of the local helper. |
| 45 | **Marriage singularity (GC3.3) not in findings layer.** Birth (GC04) and death (GC05) have singularity findings; marriage does not. Add `find_marriage_singularity_violation()`. |
| 46 | **N+1 birth/death year queries in `findings.py`.** `_derive_birth_year()` and `_derive_death_year()` issue 2–3 queries per person, called in per-person loops. Pre-fetch all birth/death years for active persons in a single query at the start of `run_all_findings()`. |
| 47 | **`find_link_conflicts_resolved()` is a permanent placeholder.** Always returns `[]`. Either implement (requires conclusion_log to record opinion revisions) or remove from `run_all_findings()` and taxonomy until ready. |

---

## Notes

- `src/genealogy/` is stateless except for `constraints.py` which contains two DB-querying
  functions (`check_household_coherence`, `apply_constraints_to_linkages`). These are
  structurally distinct from the pure predicate functions but belong here because they
  enforce the same genealogical rules at DB scale.
- `age_progression_validity` Splink column remains hardcoded to 0.5 (neutral placeholder).
  Now that `classify_forename` is fixed and `evaluate_age_progression` uses correct tolerances,
  a future session should compute this value per-person from actual cross-source age data
  rather than leaving it as a constant. ROADMAP item to be added when Splink re-training
  is next scheduled.
- `docs/validation_rules.md` not yet retired — tracked as item 42 above.
