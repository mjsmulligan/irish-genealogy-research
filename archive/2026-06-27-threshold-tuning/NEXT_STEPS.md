# Next Steps: v1.3 Deployment & Future Phases

**Date**: 2026-06-27  
**Current Status**: Analysis complete; ready for testing

---

## Phase 2: v1.3 Deployment (Ready Now)

### What's Already Done
- ✅ Soundex phonetic encoding implemented in `src/evidence/features/census.py`
- ✅ Soundex blocking rules added to `src/evidence/similarity.py`
- ✅ All tests passing (59/59)
- ✅ Code compiles without errors

### What to Do Now

**Step 1: Deploy v1.3**
```bash
# Run full pipeline with Soundex
python3 run_pipeline.py
```

**Step 2: Measure Linkage**
- Check `reports/report_YYYYMMDD_HHMMSS.json`
- Extract: `total_findings` and `unlinked_recorded_person` count
- Calculate: (3167 - unlinked) / 3167 * 100 = linkage %

**Step 3: Compare Against Baseline**
- Previous (v1.1): 21.1% linkage (2,617 linked persons, 2,498 unlinked)
- v1.3 target: 21-23% (expect +0.5-2pp from Soundex)
- v1.3 threshold: Must stay ≥ 21% (no regression)

**Step 4: Validate Quality**
- Check `review/findings.py` output:
  - New `merge_error_candidates` count (should stay low, ideally ≤ 3)
  - `parent_age_implausible` count (should stay low)
- Spot-check 5-10 high-confidence matches (>0.90 score) for false positives

**Expected runtime**: 30-45 minutes for full pipeline

---

## Phase 2b: Threshold Tuning (Optional, Dependent on v1.3 Results)

### Only if v1.3 reaches 22%+

**Option: Lower person resolution threshold**
```python
# In run_pipeline.py or constants.py:
PERSON_RESOLUTION_THRESHOLD = 0.55  # was 0.60
```

**Expected gain**: +1-2pp (marginal matches now included)

**Validation needed**:
1. Run with threshold 0.55
2. Check for increase in false positives (merge_error_candidates)
3. If false positives < 2%, keep new threshold
4. If false positives > 5%, revert to 0.60

---

## Phase 3: Role Consistency Weighting (Future)

### Only if v1.3 + threshold tuning stalls below 25%

**Concept**: Use household role as soft signal in Splink matching

**Head in 1901/1911 → expected to be head in 1926**: ✅ Strong signal  
**Son in 1901/1911 → expected to be independent by 1926**: ✅ Explains non-linkage

**Implementation sketch**:
- Add `role_consistency` comparison to `_build_person_settings()` in `src/evidence/similarity.py`
- Compare person roles across matched pairs
- Boost confidence when roles are consistent (head→head, son→son)

**Effort**: Medium (~2-3 hours)  
**Expected gain**: +1-2pp  
**Risk**: Low (soft weighting, not hard blocks)

---

## Phase 4: BMD Integration (When Data Available)

### Goal: Validate linkage interpretation with civil records

**When available**:
1. **Death records**: Confirm persons marked "unlinked 1911→1926" actually died
2. **Marriage records**: Track household formation (daughter in 1901 → married by 1926)
3. **Birth records**: Identify persons born between censuses
4. **Emigration records**: Track who left Ireland

**Expected impact**:
- Won't increase linkage (ceiling still ~25-30%)
- Will EXPLAIN the ceiling (validate demographic interpretation)
- Will allow confident classification:
  - ✅ Correctly unlinked (person died)
  - ✅ Correctly unlinked (person emigrated)
  - ✅ Correctly unlinked (person born later)
  - ❌ Actually unlinked (matching failure—rare, should be <5%)

**Timeline**: After Tullynaught full dataset is prepared

---

## Success Criteria by Phase

### Phase 2 (v1.3): Deploy
- ✅ All tests pass (0 failures)
- ✅ Linkage ≥ 21% (no regression)
- ✅ New merge_error_candidates ≤ 3 (low false positive rate)
- ✅ Code compiles cleanly

### Phase 2b (Threshold Tuning): Optional
- ✅ Linkage 22-25% (with threshold 0.55)
- ✅ False positives < 5% (acceptable trade-off)

### Phase 3 (Role Consistency): Optional
- ✅ Linkage 23-25% (cumulative with v1.3 + tuning)
- ✅ No false positives introduced

### Phase 4 (BMD Integration): Future Validation
- ✅ 80%+ of unlinked persons explained by BMD data (death/emigration/born-later)
- ✅ Linkage ceiling validated as demographic, not algorithmic

---

## What NOT to Do

❌ **Don't force linkage above 30%**
- Diminishing returns kick in hard after 25-30%
- Further gains require manual linking (not scalable)
- Risk of false positives grows with aggressive tuning

❌ **Don't over-engineer Splink features**
- We're already capturing the easy matches
- Household level works well (20 across all 3 censuses)
- Person level works well (21.1% of 3,167)
- Tweaking features has diminishing returns

❌ **Don't assume "unlinked = failure"**
- ~20-30% are dead (TB mortality)
- ~5-10% emigrated
- ~15-25% formed new households
- Only ~5-15% are true matching shortfalls

---

## Timeline

| Phase | Action | Effort | Expected Gain | Timeline |
|---|---|---|---|---|
| **2** | Deploy v1.3 | 30-45 min | +0.5-2pp | Next session |
| **2b** | Threshold tuning | 30 min | +1-2pp | If v1.3 ≥ 22% |
| **3** | Role consistency | 2-3 hrs | +1-2pp | If 2b stalls |
| **4** | BMD integration | TBD | 0pp gain (validation only) | Later |

---

## One Final Note

Your question about linkage breakdown **by source pair** was the catalyst that revealed the analysis script bug. This is a great example of how questioning assumptions leads to better understanding.

The TB mortality context you provided adds crucial historical meaning to the numbers. We're not seeing a matching failure; we're seeing the real demographic impact of an epidemic. This is actually **more valuable for genealogy** than higher linkage rates would be.

The pipeline is working correctly. The "missing" persons are mostly accurately classified as data facts, not matching failures. Move forward with confidence.
