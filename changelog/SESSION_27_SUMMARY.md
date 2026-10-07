# Session 27 Changelog — 27 June 2026

## Topic
Phase 3 regression analysis, test infrastructure improvements, and pipeline restoration to baseline

---

## Decisions Made

### 1. Removed Phase 3 Role Consistency Feature
**Decision**: Remove role_consistency CustomComparison from Splink person similarity pipeline entirely.

**Rationale**: 
- Role consistency feature was suppressing linkage from 26% (v1.1 baseline) to 14.6% (regression)
- Root cause analysis revealed roles are inherently unstable across 10-15 year census intervals
- Sons become heads (inheritance), daughters become spouses (marriage), heads become lodgers (migration)
- Feature treated role changes as matching evidence against (penalty), when they should be expected in true same-person matches
- Penalizing 70% of true matches for role changes
- Original hypothesis (role matching provides linking power) was **incorrect**

**Implementation**:
- Deleted entire role_consistency comparison block (23 lines) from `src/evidence/similarity.py`
- No other changes to Splink settings or pipeline logic
- Linkage restored to 26.4% (essentially matching v1.1 baseline of 26.0%)

**Evidence**:
```
After removal:
  Linkage: 26.4% (836 persons) vs 14.6% before removal
  Avg score: 0.476 vs 0.441
  Pairs ≥0.50: 52.2% vs 43.4%
  Pairs ≥0.65: 14.6% vs 0%
```

**All 59 tests passing** — no regressions introduced by removal

---

### 2. Enhanced Test Infrastructure
**Decision**: Improve test setup and metrics output to prevent future measurement confusion.

**What was implemented**:

#### Clean Database State Verification
- After clearing evidence + conclusion layers, verify person count = 0
- Fail fast with clear error message if database not clean
- Prevents stale data from contaminating measurements

#### Consistent Metrics Output
- Every test run prints comprehensive metrics before running tests
- Three-census linkage percentage: `(linked recorded persons) / 3,167 × 100`
- Pairwise person similarity: score distribution by tier (≥0.65, 0.50-0.65, 0.45-0.50, <0.45)
- Regression detection: comparison to v1.1 baseline (26%)

**Why this matters**:
- Fixed denominator (3,167 persons) for all linkage calculations
- Consistent numerator definition across all test runs
- Visible metrics prevent silent regressions
- Automatic regression detection

---

### 3. Established Metrics Definitions
**Decision**: Document exact calculation methods for all metrics to eliminate ambiguity.

**Three-Census Linkage Percentage**:
```
Formula: 100 × (Linked Recorded Persons) / 3,167

Numerator: COUNT(DISTINCT recorded_person_id FROM person_recorded_person)
Denominator: 3,167 (FIXED — all persons from 1901+1911+1926 fixtures)

Interpretation: % of all census persons that were merged via Splink + clustering
```

**Pairwise Person Similarity**:
- Total pairs evaluated by Splink person_similarity
- Average score across all pairs
- Distribution by confidence tier
- Standard deviation and range
- Interpretation: concentration near threshold indicates good feature discrimination

**Tullynaught Golden Dataset**:
- 1901: 263 records, 1,193 persons
- 1911: 240 records, 1,080 persons
- 1926: 212 records, 894 persons
- **Total**: 715 records, 3,167 persons (FIXED)

---

### 4. Proposed Future Architecture: Review Layer
**Decision**: Implement role consistency as post-clustering validation (not as linking feature).

**Concept**:
```
Pipeline (creates conclusions):
  Evidence → Splink + clustering → Linked persons

Review (validates conclusions):
  Linked persons → Role consistency check → Confidence annotations
```

**How it would work**:
- After person_resolution completes, check role consistency for each linked person
- Classify by validation status:
  - EXACT_MATCH: Role unchanged across all censuses (63%) → High confidence
  - PLAUSIBLE_TRANSITION: Son→head, daughter→spouse, etc. (30%) → Medium confidence
  - QUESTIONABLE: Unexpected patterns (7%) → Low confidence, flag for review

**Benefits**:
- ✓ Doesn't suppress conclusions (linkage not affected)
- ✓ Annotates confidence (validates good links)
- ✓ Flags questionable cases (for manual review)
- ✓ Records in person_changelog (auditability)
- ✓ Extensible (can add other validators)

**Future enhancement**:
- Review may recommend conclusion updates (calling back to Conclusion layer for revisions)
- But Conclusion layer handles actual revisions (clean separation of concerns)

---

## Architecture Insights

### Pipeline vs Review Layers
**Conclusion Layer** (existing):
- Takes fragmented evidence (similarity scores, household memberships, etc.)
- Synthesizes into first organized conclusions (linked persons, relationships, events)
- Ephemeral in a sense — initial gathering into structure

**Review Layer** (proposed):
- Takes existing conclusions
- Validates them against other evidence patterns (role consistency, logical checks, etc.)
- Annotates with confidence, flags, notes — but doesn't fundamentally change them yet
- Keeps conclusions as "best interpretation of evidence"

This separation preserves the important principle: conclusions are working interpretations that can be revised when better evidence emerges.

---

## Results

### Linkage Metrics
```
Before fix:     14.6% (463 persons) ✗ REGRESSION
After fix:      26.4% (836 persons) ✓ RESTORED

Similarity scores:
  Avg:          0.441 → 0.476
  ≥0.50 pairs:  43.4% → 52.2%
  ≥0.65 pairs:  0% → 14.6%
```

### Test Status
- All 59 tests passing
- No regressions introduced
- Enhanced metrics output
- Clean database state verification working

### Documentation
- `METRICS_DEFINITIONS.md` — Complete reference with formulas and examples
- `TEST_SETUP_SUMMARY.md` — Quick guide for researchers
- `SESSION_SUMMARY.md` — Full work summary
- This changelog entry

---

## Files Changed

| File | Change | Why |
|------|--------|-----|
| `src/evidence/similarity.py` | Removed role_consistency comparison | Restore linkage |
| `tests/test_pipeline.py` | Enhanced setup + metrics output | Better diagnostics |
| `tests/METRICS_DEFINITIONS.md` | NEW | Metrics reference |
| `TEST_SETUP_SUMMARY.md` | NEW | Quick guide |
| `SESSION_SUMMARY.md` | NEW | Full summary |

---

## Commits

1. `aef2fc3` — Add metrics definitions and update tests for clean database state
2. `a64b5d0` — Add test setup summary documentation
3. `30e5b83` — Work completion summary: tests, metrics, Phase 3 analysis
4. `d825274` — Remove Phase 3 role consistency feature - restore to v1.1 baseline
5. `428932a` — Add session summary - Phase 3 removed, test infrastructure improved

---

## Lessons Learned

### 1. Role Instability is a Feature, Not a Bug
In Irish rural census data, role changes are **expected**, not evidence against a match:
- Population mobility (migration, marriage, inheritance)
- Census variations (different enumerators, annotation styles)
- Household dynamics (aging, death, remarriage)

Treating role consistency as a linking discriminator was fundamentally misaligned with the data characteristics.

### 2. Data-Driven Validation Better Than Linking Feature
Instead of using role consistency to suppress weak matches during linking:
- Let strong name/age/household evidence drive linking (26% baseline)
- Use role consistency to **validate** and **annotate** conclusions post-hoc
- Provides transparency without suppression

### 3. Metrics Clarity Prevents Silent Regressions
The old approach (metrics not visible unless test failed) masked the regression for multiple commits:
- Fixed denominator (3,167)
- Consistent numerator definition
- Automatic regression detection
- Visible output every run

Made it obvious what was happening instead of hidden in database state.

---

## Next Steps (Future Sessions)

1. **Implement Review Layer** with role validation
2. **Test on production data** to confirm 26% baseline holds at scale
3. **Document role instability patterns** for future researchers
4. **Add logical constraint validation** (birth date plausibility, etc.)
5. **Build manual review flagging system** for questionable conclusions

---

## Current State

✅ Pipeline restored to v1.1 baseline (26.4% linkage)
✅ Test infrastructure improved with clean state verification
✅ Metrics definitions documented and visible
✅ All 59 tests passing
✅ Future Review layer architecture documented
✅ Ready for deployment or further optimization

