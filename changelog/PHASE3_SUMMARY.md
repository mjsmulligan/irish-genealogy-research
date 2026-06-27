# Phase 3 Implementation Summary

## ✅ Status: Complete

Phase 3 (Role Consistency Weighting) has been successfully implemented and is ready for testing.

---

## What Was Implemented

### 1. Feature Extraction
Role column added to person features pipeline:
- `src/evidence/features/census_person.py` modified to extract `recorded_person.role`
- Role normalized (lowercased) and included in Splink input DataFrames
- Null-safe handling (NULL for missing roles)

### 2. Splink Comparison
Role consistency comparison added to person_similarity:
- **Exact matches** (head→head, son→son, etc.): Strongest evidence
- **Plausible transitions** (son→head, daughter→head): Medium evidence
- **Everything else** (head→son, son→daughter, etc.): Weak/negative signal
- **NULL roles**: No penalty (graceful handling)

### 3. Score Versioning
- New constant: `SCORE_VERSION_PERSON_SIMILARITY_V1_2`
- All person_similarity scores now tagged as v1.2
- Enables tracking and A/B comparison with v1.1

---

## Testing Status

✅ **All 59 regression tests passing**
- No degradation in any pipeline layer
- Feature extraction working correctly
- Splink settings valid and parseable

---

## Architecture

```
Person Similarity Comparisons (v1.2):
  1. surname (Jaro-Winkler)
  2. forename (Jaro-Winkler)
  3. birth_year_est (bands: 0, ±2, ±5)
  4. sex_as_recorded (exact)
  5. place_id (exact)
  6. household_match_score (hierarchical)
  7. role_consistency (NEW, hierarchical)
```

Role consistency is a hierarchical feature that allows Splink EM training to:
- Learn different m/u parameters for exact role matches vs. plausible transitions
- Automatically weight role signals based on discriminative power
- Handle missing roles gracefully (no penalty for NULL)

---

## Expected Impact

**Target linkage:** 27-28% (currently 26.0%)  
**Expected gain:** +1-2pp  
**Quality baseline:** Maintain ≤ 0.20% false positive rate

Primary beneficiaries:
- Ambiguous names where role consistency breaks ties
- 1901→1911 consecutive matching (roles stable)
- Adult lifecycle transitions (son→head is common in rural Ireland)

---

## Rollback Plan

If role consistency reduces linkage or increases false positives:
1. Revert 4 files: `census_person.py`, `similarity.py`, `constants.py`, git history
2. Switch back to v1.1 in pipeline
3. Compare results with v1.1 baseline (26%)

Rollback is minimal and straightforward (all changes isolated).

---

## Next Steps

### Immediate
1. Run full pipeline test to measure linkage impact
2. Compare v1.1 vs v1.2 score distributions
3. Verify role match percentages across census pairs

### Analysis
- Identify which cases benefit most from role consistency
- Check if threshold (0.50) needs re-tuning
- Measure impact by census pair (1901→1911, etc.)

### If Successful
- Mark v1.2 as production-ready
- Update ROADMAP with Phase 3 completion
- Plan Phase 4 (BMD integration for validation)

---

## Code Summary

**Changes Made:**
- `src/evidence/features/census_person.py`: 5 lines added
- `src/evidence/similarity.py`: 25 lines added (CustomComparison)
- `src/constants.py`: 1 line added (new constant)
- `src/evidence/similarity.py`: 2 lines updated (imports and version reference)

**Total new code:** ~35 lines
**Total modified:** ~40 lines
**Risk level:** Very low (isolated, focused changes)

---

## Deployment Status

**Ready for:** Full pipeline testing  
**Required before production:** Linkage measurement (verify +1-2pp gain)  
**Risk assessment:** Low (minimal changes, all tests passing, easy rollback)

