# Test Setup Summary — Clean Database & Metrics Definitions

**Date**: 2026-06-27  
**Status**: ✅ Updated with clean state verification and consistent metrics

---

## Overview

Tests now ensure **clean database state** before every run and produce **consistent, well-defined metrics** that can be compared across all test passes. This eliminates confusion about numerator/denominator and prevents stale data from contaminating measurements.

---

## What Changed

### 1. Clean Database State Verification

**Before**: Tests assumed a clean database; if not clean, they would fail mysteriously or produce misleading metrics.

**After**: Tests explicitly verify clean state:
```python
# After clearing evidence + conclusion layers:
cur.execute("SELECT COUNT(*) as count FROM person")
person_count = cur.fetchone()["count"]
if person_count > 0:
    raise AssertionError(
        f"Database not clean: {person_count} persons exist after clear. "
        "Run 'python -m src.cli clear-evidence' before tests."
    )
```

**Result**: If database isn't clean, test fails immediately with clear error message rather than producing garbage metrics.

---

### 2. Metrics Definitions (METRICS_DEFINITIONS.md)

New file documents exactly how linkage percentages are calculated:

#### Three-Census Linkage Percentage
```
Formula: 100 × (Linked Recorded Persons) / (Total Recorded Persons)
       = 100 × COUNT(DISTINCT recorded_person_id FROM person_recorded_person) / 3,167

Numerator: Recorded persons that were linked to a clustered person
Denominator: 3,167 (FIXED — all persons across 1901, 1911, 1926 fixtures)

Example: 463 linked / 3,167 total = 14.6% linkage
```

#### Pairwise Person Similarity Metrics
```
Definition: Distribution of person-level Splink scores
Formula: Score tiers as % of total similarity pairs evaluated

Example distribution:
  ≥0.65 (high):      0 (  0.0%)
  0.50-0.65 (med):  91 ( 23.0%)
  0.45-0.50 (marg): 81 ( 20.5%)
  <0.45 (weak):    224 ( 56.6%)
  ─────────────────────────────
  Total:           396 (100.0%)
```

---

### 3. Enhanced Metrics Output

Each test run now produces:

```
Three-Census Linkage (denominator: 3167 total persons)
  Linked recorded persons: 463
  Linkage: 14.6%
  Clustered persons: 220 (unique persons after merging)
  Merge ratio: 2.10x (463 recorded → 220 clustered)

Pairwise Person Similarity (person-level Splink scores)
  Total pairs: 396
  Statistics:
    Mean: 0.441
    Range: 0.304 – 0.618
    Std Dev: 0.093
  Score distribution (tiers as % of total pairs):
    ≥0.65 (high):         0 (  0.0%)
    0.50-0.65 (med):     91 ( 23.0%)
    0.45-0.50 (marg):    81 ( 20.5%)
    <0.45 (weak):       224 ( 56.6%)
  Pairs ≥0.45 (above clustering threshold): 172 (43.4%)

Regression Detection vs v1.1 Baseline
  v1.1 linkage: 26.0% (824 persons)
  v1.2 linkage: 14.6% (463 persons)
  ✗ Regression: -11.4pp (-361 persons)
```

This allows immediate visual detection of:
- Whether database was clean
- What linkage was achieved
- Score distribution characteristics
- Direction of regression/improvement vs baseline

---

## Tullynaught Golden Dataset (Fixed)

All tests use the complete 3-census fixture set with **known, unchanging counts**:

| Source | Year | Records | Persons |
|--------|------|---------|---------|
| 1901 | tullynaught_1901.csv | 263 | 1,193 |
| 1911 | tullynaught_1911.csv | 240 | 1,080 |
| 1926 | tullynaught_1926.csv | 212 | 894 |
| **TOTAL** | — | **715** | **3,167** |

These counts are:
- **Fixed**: Do not change unless CSV files are modified
- **Source of truth**: Used as denominator for all calculations
- **Verified at ingest**: Test explicitly checks these counts match

---

## Test Execution Flow

1. **Clean Database**
   - Run `python -m src.cli clear-evidence` (clears evidence + conclusion layers)
   - Verify person table is empty

2. **Ingest All Three CSVs**
   - Verify: 263 + 240 + 212 = 715 records ingested
   - Verify: 1,193 + 1,080 + 894 = 3,167 persons ingested

3. **Run Full Pipeline**
   - Place resolution → Record similarity → Person similarity → Person resolution
   - Relationship resolution → Event resolution

4. **Capture Metrics**
   - Linked recorded persons: COUNT(DISTINCT recorded_person_id FROM person_recorded_person)
   - Linkage %: (linked / 3,167) × 100
   - Score distribution: Percentiles of recorded_relationship.score WHERE type='similarity'
   - Regression detection: Compare to v1.1 baseline (26.0%)

5. **Run All Tests**
   - All 59 tests query the resulting database state
   - No test modifies the database (read-only)

---

## Consistency Rules

1. **Always start clean**: `python -m src.cli clear-evidence` before test runs
2. **Always use complete fixtures**: All three CSVs (no selective ingestion)
3. **No changing denominators**: Linkage % always uses 3,167
4. **Record metrics at conclusion**: Capture after ALL pipeline phases complete
5. **Report with context**: Include timestamps, thresholds, baseline comparisons

---

## Regression Detection

**If linkage % drops >2pp between runs:**

1. Verify database was cleaned: `SELECT COUNT(*) FROM person` should be 0 before setup
2. Verify all fixtures ingested: Check record count is exactly 715
3. Check similarity pair count: If dropped, Splink comparisons changed
4. Check role consistency: Verify v1.2 feature is enabled and correct
5. Check threshold: If changed from 0.50, will affect linkage % directly

**Baseline for v1.2:**
- Expected linkage: ≥26% (v1.1 baseline)
- Expected avg score: 0.50+
- Expected pairs ≥0.50: ≥40%

**Recent measurements (Phase 3 with fix applied):**
- Current linkage: 14.6% (REGRESSION from 26%)
- Current avg score: 0.441 (BELOW 0.50 threshold)
- Current pairs ≥0.50: 23.0% (FAR BELOW 40%)

This indicates Phase 3 role consistency feature is TOO RESTRICTIVE and needs redesign.

---

## Files Modified

- **tests/test_pipeline.py**
  - Added clean state verification (check person count = 0 after clear)
  - Enhanced metrics output with definitions and regression detection
  - Updated fixture docstring with new test lifecycle

- **tests/METRICS_DEFINITIONS.md** (new)
  - Complete definitions for three-census and pairwise metrics
  - Test execution lifecycle with phases
  - Consistency rules and regression detection thresholds
  - Instructions for updating metrics after code changes

---

## Next Steps

1. **Monitor metric stability**: Run tests multiple times to confirm reproducible results
2. **Investigate Phase 3 regression**: Linkage dropped to 14.6% (below v1.1's 26%)
3. **Review role consistency feature**: Current implementation is suppressing linkage
4. **Consider redesign**: May need to remove or fundamentally rethink role consistency

---

## Commands

**Run tests with clean database**:
```bash
python -m src.cli clear-evidence
python -m pytest tests/test_pipeline.py -v -s 2>&1 | head -100  # See setup metrics
```

**Run single test**:
```bash
python -m pytest tests/test_pipeline.py::test_schema_version -v -s
```

**Run by pattern**:
```bash
python -m pytest tests/test_pipeline.py -k "evidence" -v
```

**After viewing metrics**, check `tests/METRICS_DEFINITIONS.md` for calculation details and regression detection rules.

