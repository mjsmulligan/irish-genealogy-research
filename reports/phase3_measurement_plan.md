# Phase 3 Measurement Plan

**Date**: 2026-06-27  
**Status**: Ready for full pipeline testing

---

## Objective

Measure the actual linkage impact of role consistency weighting (Phase 3) compared to v1.1 baseline.

---

## Baseline (v1.1)

**Configuration**: 0.50 person resolution threshold + household context + Soundex

**Test Data**: Tullynaught 1901/1911/1926 fixtures (3,167 total persons)

| Metric | v1.1 Value |
|--------|-----------|
| Linkage | 26.0% |
| Linked persons | 824 |
| Unlinked persons | 2,343 |
| Merge errors | 1 |
| False positive rate | 0.12% |

---

## Phase 3 Implementation

**New Feature**: Role consistency Splink comparison

**What it does**:
- Compares recorded_person.role across census years
- Three comparison levels: exact match, plausible transitions, else
- Allows Splink EM to learn appropriate weights for role signals

**Architecture**:
```
Person Similarity (v1.2) includes:
  1. surname
  2. forename
  3. birth_year_est
  4. sex_as_recorded
  5. place_id
  6. household_match_score
  7. role_consistency ← NEW
```

---

## Expected Impact

| Metric | v1.1 | v1.2 Target | Expected Gain |
|--------|------|------------|---------------|
| Linkage | 26.0% | 27-28% | +1-2pp |
| Linked persons | 824 | 855-887 | +31-63 |
| Merge errors | 1 | ≤2 | 0-1 |
| FP rate | 0.12% | ≤0.20% | Maintained |

**Rationale for +1-2pp gain**:
- Role consistency particularly valuable for ambiguous names
- Son→head transitions common in rural Ireland (adult children becoming household heads)
- Exact role matches provide strongest signal of same person
- Plausible transitions support without over-matching

---

## Measurement Strategy

### What to Compare

1. **Linkage Rate** (primary metric)
   - Count persons with person_recorded_person link
   - Compare: (linked) / (total) %
   - Expected: 26.0% → 27-28%

2. **Linked Persons Count** (secondary metric)
   - Total persons with cross-census clustering
   - Expected: 824 → 855-887

3. **Quality: False Positives** (critical)
   - Count merge_errors in person_similarity table
   - Calculate FP rate: (errors) / (linked) %
   - Threshold: ≤0.20% (currently 0.12%)

4. **Score Distribution** (diagnostic)
   - Distribution across thresholds (0.65+, 0.50-0.65, 0.45-0.50, <0.45)
   - Shift should be rightward (higher scores)
   - Verify exact role matches score higher than plausible transitions

5. **Role Match Percentages** (diagnostic)
   - % pairs with exact role match
   - % pairs with plausible transition
   - % pairs with no role data
   - Verify role data is present across census pairs

### How to Measure

1. **Run test suite**:
   ```bash
   pytest tests/test_pipeline.py -v
   ```
   All 59 tests should pass.

2. **Extract metrics from test database**:
   ```python
   # After tests complete:
   c.execute("SELECT COUNT(*) FROM person WHERE id IN (...)")  # linked
   c.execute("SELECT COUNT(*) FROM person_similarity WHERE label='merge_error'")
   c.execute("SELECT match_probability, COUNT(*) FROM person_similarity GROUP BY round(match_probability, 2)")
   c.execute("SELECT role_consistency, COUNT(*) FROM person_similarity GROUP BY role_consistency")
   ```

3. **Compare to v1.1 baseline**:
   - Linkage: 26.0% → ??? %
   - Gain: +{result - 26.0}pp
   - Quality: FP rate {result} vs 0.12%

---

## Success Criteria

### Phase 3 is Successful if:
- ✅ Linkage ≥ 27% (target: 27-28%, acceptable: ≥27%)
- ✅ False positive rate ≤ 0.20% (maintain quality)
- ✅ All 59 tests pass (no regressions)
- ✅ Role consistency signals present (verify role_consistency column populated)

### Phase 3 is Inconclusive if:
- ⚠️ Linkage 26.0-26.9% (no measurable gain)
- ⚠️ Score distribution unchanged (role signals not contributing)
- Then: Investigate role data quality, transition heuristics

### Phase 3 Failed if:
- ❌ Linkage < 26.0% (regression)
- ❌ False positive rate > 0.20% (quality degradation)
- Then: Rollback to v1.1

---

## Potential Issues & Diagnostics

### Issue 1: No Linkage Gain
**Possible causes**:
- Role data sparsity (too many NULL roles)
- Plausible transitions overly permissive (false positives masked by other signals)
- Splink EM not assigning weight to role tier

**Diagnostic queries**:
```sql
-- Check role data coverage
SELECT role, COUNT(*) FROM recorded_person GROUP BY role;

-- Check role match distribution
SELECT 
  role_consistency,
  COUNT(*) as pairs
FROM person_similarity
WHERE type = 'similarity'
GROUP BY role_consistency;

-- Check if exact role matches score higher
SELECT 
  role_consistency,
  AVG(match_probability) as avg_score,
  MAX(match_probability) as max_score
FROM person_similarity
WHERE type = 'similarity' AND role_consistency IS NOT NULL
GROUP BY role_consistency;
```

### Issue 2: False Positive Rate Spike
**Possible causes**:
- Plausible transition heuristics too loose (son→head matching different people)
- Role consistency overwhelming other signals

**Diagnostic queries**:
```sql
-- Which roles generate merge errors?
SELECT 
  ps.role_consistency,
  COUNT(*) as errors
FROM person_similarity ps
WHERE ps.label = 'merge_error'
GROUP BY ps.role_consistency;
```

---

## Rollback Plan

If Phase 3 fails measurement criteria:

1. **Stop**: Do not deploy v1.2
2. **Investigate**: Run diagnostics above to understand cause
3. **Revert**: `git revert 4f64113 7723d57`
4. **Re-baseline**: Confirm v1.1 metrics restored (26.0% linkage)

**Time to rollback**: ~2 minutes (git revert + re-run tests)

---

## Post-Measurement Actions

### If Successful (Linkage ≥ 27%, FP ≤ 0.20%):
1. Document actual gain (e.g., "27.5% linkage, +1.5pp gain")
2. Create Phase 3 completion report
3. Update ROADMAP with Phase 3 ✅
4. Proceed with Phase 4 (BMD integration)

### If Inconclusive (26.0-26.9% linkage):
1. Analyze role data quality and distribution
2. Consider adjusting plausible transition heuristics
3. Test with different role transition combinations
4. Document findings for future optimization

### If Failed (Regression):
1. Revert to v1.1 immediately
2. Investigate root cause
3. Document learnings (e.g., "role data too noisy", "transition heuristics wrong")
4. Proceed to Phase 4 without role consistency

---

## Timeline

- **Measurement**: Now (5 min test run)
- **Analysis**: 15 min (extract and compare metrics)
- **Decision**: <5 min (pass/fail/investigate)
- **Total**: ~25 minutes to full results

---

## Appendix: Test Database State

The test suite runs against in-memory SQLite with Tullynaught fixtures.

**Fixtures** (fixed, do not change):
- `tests/tullynaught_1901.csv`: 1,193 persons, 263 households
- `tests/tullynaught_1911.csv`: 1,080 persons, 240 households
- `tests/tullynaught_1926.csv`: 894 persons, 212 households

**Pipeline layers**:
1. **Foundation**: Ingest records and persons
2. **Evidence**: Compute record_similarity, person_similarity, role relationships
3. **Conclusion**: Cluster persons, create relationships, events, birth estimates

**Key tables**:
- `person`: Clustered persons (conclusion layer output)
- `recorded_person`: Individual census records
- `person_similarity`: Splink scores (evidence layer output)
- `recorded_relationship`: Relationship conclusions

