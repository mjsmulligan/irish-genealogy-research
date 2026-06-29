# v1.3 Test Results - 2026-06-27

**Test Status**: REGRESSION DETECTED

## Metrics

| Metric | v1.1 Baseline | v1.3 Current | Change |
|--------|---------------|--------------|---------|
| Linked Persons | 670 (21.1%) | 552 (17.4%) | -118 (-3.7pp) |
| Record Pairs | 290 | 290 | 0 |
| Threshold (0.85+) | ? | 58 | ? |

## Findings

### 1. Critical Soundex Bug Fix ✅
- **Issue**: `_soundex("O'Brien")` returned "O165" instead of "B650"
- **Cause**: Function kept first CHARACTER instead of first LETTER after removing prefix
- **Fix**: Modified [src/evidence/features/census.py:46-87](src/evidence/features/census.py:46-87)
- **Status**: Fixed in commit 4cb474e

### 2. Linkage Regression ❌
After fixing Soundex bug, linkage remains **17.4%** vs **21.1%** baseline (-3.7pp).

**Investigation Results:**
- Soundex bug fix alone does not restore linkage (suggests not root cause)
- Removed Soundex blocking rule → linkage still 17.4% (blocking not the culprit)
- Reverted to v1.1 name_norm with TF=True → linkage still 17.4%

**Conclusion:** The regression appears to be structural, not due to any single recent change. Possible causes:
1. Fixture CSV data differs from original baseline run
2. Database schema changes affect feature computation
3. EM training parameters have shifted (Splink EM is non-deterministic)

### 3. Record Similarity (Household Level)
- Total pairs: 290 (split 137 + 60 + 93 across source pairs)
- 58 pairs above 0.85 threshold
- 183 pairs above 0.50 threshold
- **Status**: ✅ Matches expected household blocking behavior

## Recommendation

**Do NOT deploy v1.3 in current state.**

The v1.2 changes (split surname/forename, disable TF) introduced a 3.7pp regression. Root cause analysis suggests it's not a simple tuning issue but relates to how the feature separation and TF disabling interact with EM training.

### Next Steps

1. **Investigate fixture data**: Compare current CSV files against the version that produced 21.1%
2. **Test v1.1 commit directly**: Check out commit 54c0c42 and run full pipeline to verify baseline
3. **Isolate regression point**: Methodically test commits between v1.1 and v1.3
4. **Consider EM training**: Splink EM is stochastic; re-running might produce different results (unlikely to recover 3.7pp, but worth checking)

## Files Modified

- `src/evidence/features/census.py`: Fixed Soundex bug
- `src/evidence/similarity.py`: Reverted to v1.1 person comparison settings

## Conclusion

v1.3 Soundex blocking is ready in isolation, but the platform has regressed 3.7pp. This must be resolved before deployment. The bug fix is solid, but larger architectural changes (v1.2) have created a problem that needs root cause analysis.

**Mark as**: BLOCKED - pending regression investigation
