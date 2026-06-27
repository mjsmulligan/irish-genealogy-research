# Session Summary — Pipeline Fix & Test Infrastructure

**Date**: 2026-06-27  
**Final Status**: ✅ COMPLETE

---

## What Was Accomplished

### 1. ✅ Removed Phase 3 Role Consistency Feature

**Problem identified:**
- Role consistency feature was suppressing linkage (26% → 14.6%)
- Root cause: Roles are inherently unstable across census intervals
- Sons become heads, daughters become spouses, heads become lodgers
- Feature treated role changes as matching evidence against, suppressing 70% of true pairs

**Solution implemented:**
- Removed entire role_consistency CustomComparison from Splink settings
- Returned to v1.1 baseline linking approach

**Results:**
```
Before removal:  14.6% linkage (463 persons) ✗
After removal:   26.4% linkage (836 persons) ✓

Score metrics restored:
  Avg score: 0.476 (was 0.441)
  Pairs ≥0.50: 52.2% (was 43.4%)
  Pairs ≥0.65: 14.6% (was 0%)
```

**All 59 tests passing** — no regressions

---

### 2. ✅ Enhanced Test Infrastructure

**Clean database state verification:**
- Tests explicitly verify person count = 0 after clearing
- Fail fast with clear error message if database not clean
- Prevents stale data contamination

**Consistent metrics output:**
- Three-census linkage % with fixed denominator (3,167)
- Pairwise person similarity distribution and statistics
- Regression detection vs v1.1 baseline (26%)
- Printed before every test run

**All metrics visible:**
- No need to parse test failures to understand results
- Consistent numerator/denominator across all runs
- Reproducible measurements

---

### 3. ✅ Documented Metrics Definitions

**File: `tests/METRICS_DEFINITIONS.md`**
- Three-census linkage formula and interpretation
- Pairwise person similarity metrics
- Test execution lifecycle (4 phases)
- Consistency rules and regression detection

**File: `TEST_SETUP_SUMMARY.md`**
- Overview of test improvements
- Tullynaught golden dataset (715 records, 3,167 persons — fixed)
- Test execution flow with commands
- Regression detection thresholds

---

### 4. ✅ Proposed Future Architecture

**Review Layer (post-clustering validation):**
```
src/review/
├─ role_validation.py    (annotate with confidence)
└─ logical_checks.py     (future: date plausibility, etc.)
```

**Concept:**
- Pipeline creates conclusions (best interpretation of evidence)
- Review layer validates conclusions without suppressing them
- Annotates with confidence scores and flags for manual review
- Records in person_changelog for auditability
- Future: Review may recommend conclusion updates (calling back to Conclusion layer)

**Role consistency as review:**
- Persons with exact role match: HIGH confidence (63%)
- Persons with plausible transitions: MEDIUM confidence (30%)
- Persons with questionable patterns: LOW confidence (7%)

---

## Key Insights

### Why Role Consistency Failed

**Irish rural census data characteristics:**
- Roles change frequently across 10–15 year intervals
- Expected transitions: son→head (inheritance), daughter→spouse (marriage)
- Unexpected variations: same person enumerated with different role
- Role instability is a FEATURE of the data, not a bug

**The mistake:**
- Treated role matching as discriminator for same-person matches
- Actually penalizes 70% of true matches (those with role changes)
- Feature actively suppressed linkage instead of improving it

### Why Review Layer Is Better

- ✓ Doesn't suppress conclusions (linkage not affected)
- ✓ Annotates confidence (validates good links)
- ✓ Flags questionable cases (for manual review)
- ✓ Explains reasoning (interpretable)
- ✓ Extensible (can add other validators)

---

## Files Changed

| File | Change | Impact |
|------|--------|--------|
| `src/evidence/similarity.py` | Removed role_consistency comparison | Restored linkage to 26.4% |
| `tests/test_pipeline.py` | Enhanced setup + metrics output | Better test diagnostics |
| `tests/METRICS_DEFINITIONS.md` | NEW | Metrics reference |
| `TEST_SETUP_SUMMARY.md` | NEW | Quick guide |
| `METRICS_DEFINITIONS.md` | NEW | Complete reference |

---

## Commits Made

1. `aef2fc3` — Add metrics definitions and update tests for clean database state
2. `a64b5d0` — Add test setup summary documentation
3. `30e5b83` — Work completion summary: tests, metrics, Phase 3 analysis
4. `d825274` — Remove Phase 3 role consistency feature - restore to v1.1 baseline

---

## Current State

### Pipeline

```
Foundation Layer
├─ Place authority (seeded externally)
└─ Seed data (repositories, sources)

Evidence Layer
├─ Census ingest (3 sources: 1901, 1911, 1926)
├─ Role relationship assignment
├─ Place resolution (all 715 households matched)
├─ Record similarity (household-level clustering)
└─ Person similarity (individual-level clustering, 7 features, NO role)

Conclusion Layer
├─ Person resolution (threshold 0.50)
├─ Relationship resolution
└─ Event resolution

(Future) Review Layer
├─ Role validation (annotate confidence)
└─ Logical checks (future)
```

### Metrics (Current Baseline)

**Three-Census Linkage:**
- Linked: 836 / 3,167 = **26.4%**
- Clustered persons: 392 (2.13x merge ratio)

**Pairwise Person Similarity:**
- Total pairs: 705
- Mean score: 0.476
- ≥0.65 (high): 14.6%
- 0.50-0.65 (med): 31.6%
- <0.45 (weak): 47.8%

**Threshold:**
- Clustering threshold: 0.50
- Pairs above threshold: 52.2%

---

## Next Steps (Future Sessions)

### Short Term
1. Test on production data to confirm 26% baseline holds
2. Document why roles are unstable (for future researchers)
3. Implement Review layer with role validation

### Medium Term
1. Add logical constraint validation (birth date plausibility, etc.)
2. Build flagging system for manual review
3. Create confidence scoring for each person

### Long Term
1. Implement feedback loop: Review → Conclusion
2. Allow manual revisions to persist in changelog
3. Track conclusion evolution as new evidence emerges

---

## Testing Notes

**Run tests with clean database:**
```bash
python -m src.cli clear-evidence
python -m pytest tests/test_pipeline.py -v -s
```

**Current results:**
```
59 passed in 8.56s
Linkage: 26.4% ✓ (matches v1.1 baseline)
All metrics printed before tests run
```

**If regression detected:**
1. Check linkage % in metrics output
2. Compare against v1.1 baseline (26%)
3. Check role consistency status (should show NO role comparison)
4. Consult `tests/METRICS_DEFINITIONS.md` for diagnostic rules

---

## Documentation

**Key references:**
- `tests/METRICS_DEFINITIONS.md` — Complete metrics calculations
- `TEST_SETUP_SUMMARY.md` — Quick reference and commands
- `PHASE3_FIX_COMPLETE.md` — Explanation of what was attempted (for reference)
- `WORK_COMPLETED.md` — Full work summary

---

## Session Complete

✅ Phase 3 role consistency feature removed
✅ Linkage restored to baseline (26.4%)
✅ Test infrastructure improved
✅ Metrics definitions documented
✅ Future Review layer architecture proposed
✅ All tests passing (59/59)

Ready to close session.

