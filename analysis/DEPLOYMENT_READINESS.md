# Deployment Readiness: v1.3 Soundex Implementation

**Status**: ✅ READY FOR TESTING  
**Date**: 2026-06-27

---

## What's Implemented

### v1.3 Changes (Soundex Phonetic Blocking)

**Files Modified:**

1. **`src/evidence/features/census.py`** (household-level features)
   - ✅ Added `_soundex(s: str | None) -> str` function
   - ✅ Implements standard Soundex algorithm with Irish surname handling
   - ✅ Example: O'Brien, Brien, O Brien → B650 (all equivalent)
   - ✅ Returns column `soundex_household_surname` in feature dataframe

2. **`src/evidence/features/census_person.py`** (person-level features)
   - ✅ Imports `_soundex` from census.py
   - ✅ Returns column `soundex_surname` in feature dataframe
   - ✅ Documented in docstring

3. **`src/evidence/similarity.py`** (Splink settings)
   - ✅ Household-level blocking adds secondary rule: `block_on("soundex_household_surname")`
   - ✅ Person-level blocking adds secondary rule: `block_on("soundex_surname")`
   - ✅ Maintains existing first-level blocking (place_id, substring)
   - ✅ Documented in `_build_settings()` and `_build_person_settings()` docstrings

### Validation Checklist

- ✅ Soundex function correctly handles None/empty strings
- ✅ Soundex produces 4-char codes (standard format)
- ✅ DuckDB doesn't compute Soundex; we pre-compute in Python ✅
- ✅ Columns added to both household and person feature dataframes
- ✅ Splink blocking rules reference these columns
- ✅ Code compiles; no syntax errors
- ✅ All 59 existing tests still pass (no regressions)

---

## Expected Impact

### Linkage Improvement

| Version | Threshold | Features | Expected Linkage | Notes |
|---|---|---|---|---|
| v1.0 | 0.65 | Basic names, age | 17.4% | Baseline |
| v1.1 | 0.60 | + Household context | 21.1% | ✅ Deployed, measured |
| v1.2 | 0.60 | + Separated names, no TF | 23-24% | Not yet tested |
| v1.3 | 0.60 | + Soundex phonetics | 25-28% | Ready for testing |

**v1.3 expected gain**: +2-4 percentage points

### Target Validation

**If linkage reaches 25%+**: We're on track toward the realistic ceiling (28-30%).

**If linkage <25% after v1.3**: Move to Phase 3 (manual diagnostic sampling) to understand why.

---

## Testing Plan

### Step 1: Run Full Pipeline with v1.3

```bash
cd /Users/mike.mulligan/Documents/Personal\ Learning\ Space/irish-genealogy-research
python3 -m pytest tests/ -v  # Verify no regressions
python3 run_pipeline.py      # Full GRA pipeline
```

**Expected outputs:**
- `person_similarity` scores reflect Soundex blocking
- `reports/report_YYYYMMDD_HHMMSS.json` with updated linkage metrics
- Review findings showing unlinked person count

### Step 2: Compare Metrics

**Current (v1.1)**: 21.1% linkage (2,617 linked persons, ~2,498 unlinked)

**After v1.3**: Compare against baseline:
- Linkage % (target: 25%+)
- Unlinked count (target: ~2,375 or fewer)
- Person_similarity score distribution (should shift higher with Soundex blocking)
- Link conflicts resolved (should remain stable)

### Step 3: False Positive Check

**Risk**: Lower blocking standards might cause false positive matches within same household.

**Check**:
1. Look for any NEW merge_error_candidates in review findings
2. Spot-check 10-20 high-confidence (>0.90) same-household pairs
3. Manually verify they represent distinct individuals

**Decision**:
- ✅ False positives <1%: Proceed with v1.3 as stable
- ⚠️ False positives 1-3%: Accept trade-off (benefit > cost)
- ❌ False positives >3%: Revert, investigate

### Step 4: Threshold Tuning (if time permits)

If v1.3 + 0.60 threshold hits 25%+, optionally test:

```
Lower threshold to 0.55 → measure linkage increment
If +1-2pp without false positives: Deploy 0.55 as new default
```

This is Phase 2b; do after confirming Soundex is stable.

---

## Success Criteria

| Metric | Pass | Fail |
|---|---|---|
| All 59 tests pass | ✅ (0 failures) | ❌ (any failure) |
| Linkage ≥ 25% | ✅ | ❌ <24% |
| New merge errors | < 1% | > 3% |
| Person similarities (mean) | Shift +0.05+ | Shift < 0.03 |
| Code compiles | ✅ | ❌ |

---

## Rollback Plan

If v1.3 causes regressions:

1. Git revert: `git revert 078850f` (Soundex commit)
2. Re-run pipeline with v1.2
3. Investigate: Which Soundex thresholds caused issues?
4. Optional: Adjust Soundex algorithm (e.g., stricter matching) and retry

---

## Files Checklist

- ✅ `src/evidence/features/census.py` — _soundex() function
- ✅ `src/evidence/features/census_person.py` — soundex_surname column
- ✅ `src/evidence/similarity.py` — Splink blocking rules
- ✅ `ROADMAP.md` — v1.3 documented
- ✅ Commits: 078850f "Add Soundex..." and a763593 "Update ROADMAP..."

---

## Next Actions

**Immediate (after Phase 1 analysis confirmation)**:
1. ✅ Create test analysis framework (DONE)
2. ✅ Document empirical findings (DONE — PHASE1_FINDINGS.md)
3. ⏳ Run full pipeline with v1.3 (ready, awaiting go-ahead)
4. ⏳ Measure linkage improvement
5. ⏳ If ≥25%, declare Phase 2 complete; begin Phase 3 (diagnostic sampling)

**Timeline**: Estimated 30-45 minutes for full pipeline run + analysis.
