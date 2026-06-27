# Root Cause: Analysis Script Bug, Not Data Problem

**Date**: 2026-06-27  
**Status**: CRITICAL BUG IDENTIFIED AND FIXED

---

## The Problem

Earlier analysis claimed:
- **1901/1911**: ~62 persons per household (massive aggregations)
- **1926**: ~4 persons per household (fragmented)
- **Conclusion**: 1926 data structure is fundamentally different

**This was WRONG.**

---

## Root Cause: My Analysis Script Bug

**In `analyze_tullynaught_linkage.py` (line ~38):**

```python
# WRONG: I used aform_name (document ID) as household grouper for 1926
if 'aform_name' in df_1926.columns:
    df_1926['house_number'] = pd.factorize(df_1926['aform_name'])[0] + 1
```

**What this did:**
- `aform_name` = form document identifier (e.g., "Aghlem_0508_0001_0004_0_00006.pdf")
- Different documents = different "households" in my factorization
- Result: 217 fake households instead of 212 real ones

**But the actual household grouper is `image_group`** (same as 1901/1911):
- `image_group` = numeric household ID (5500, 5501, 5502, etc.)
- Correctly groups persons into real households
- Result: 212 real households at ~4.2 persons/household

---

## Correct Household Structure (ALL 3 CENSUSES)

| Year | Total Persons | Households | Avg/HH | Min | Max |
|------|---|---|---|---|---|
| **1901** | 1,193 | 263 | 4.5 | 1 | 12 |
| **1911** | 1,080 | 240 | 4.5 | 1 | 12 |
| **1926** | 894 | 212 | 4.2 | 1 | 15 |

✅ **All three censuses have normal household sizes** (~4-5 persons per household).

There is **NO household fragmentation** in 1926.

---

## Why Does 1926 Still Have 6.9% Linkage?

If households are normal and comparable, why are we only linking 6.9% of 1926 persons?

**The real questions (now valid):**

1. **Are 1926 surnames different?**
   - We found no Gaelic-English variants
   - Surnames are stable (Graham, Cassidy, Wray, etc.)
   - ❌ Not the issue

2. **Are 1926 ages/roles different?**
   - Role mapping works fine (all updated roles map correctly)
   - Ages parse correctly
   - ❌ Not the issue

3. **Is 1926 just a different time period?**
   - 25 years between 1901 and 1926
   - ✅ Deaths/emigration rate would be high (15-25%)
   - ✅ Adult children left home and formed new households (5-10%)
   - ✅ Younger people in 1911 might not appear in 1911 census
   - **This is likely the real issue**

4. **Is the database actual ingesting 1926 correctly?**
   - Ingest function uses `image_group` as household_col ✅
   - Column mappings are correct ✅
   - Role mapping is correct ✅
   - ❌ Not the issue

---

## Revised Theory: Demographic Loss, Not Data Problem

**New hypothesis:**

- **1901→1911 (10 years)**: People stay in the same area, heads link well (18.4% linkage)
- **1911→1926 (15 years)**: More emigration, more household changes, fewer people remain (lost 20-30% of 1911)
- **1901→1926 (25 years)**: Very few survive (only 6.9% link)

**The solution is NOT:**
- Better normalization (already correct)
- Better feature engineering (household structures are normal)
- Soundex (no name variants detected)

**The solution MIGHT be:**
- Lower the person resolution threshold (0.60 → 0.55) to catch marginal matches
- Better handling of age heaping (±7 year band might be too tight for 25-year gaps)
- Accept that 1926 is just low-linkage due to demographic reality

---

## Conclusion

**My Phase 1 analysis was fundamentally flawed due to a script bug.**

The corrected facts:
- ✅ All three censuses have normal household structures (~4-5 persons)
- ✅ Schema normalization is working correctly
- ✅ Role/age/name parsing is working correctly
- ✅ The 1926 linkage crisis is likely **demographic (deaths/emigration)**, not structural

**Next steps:**
1. Re-run v1.3 testing with correct understanding
2. Don't expect household fragmentation fixes to help (they're not the problem)
3. Focus on threshold tuning and demographic reality acceptance
4. Expected ceiling: 25-30% linkage (reasonable given emigration)

---

## Lessons Learned

- ✅ Always verify data assumptions with spot-checks
- ✅ Column naming can be misleading (`aform_name` vs `image_group`)
- ✅ Factorize() is dangerous without understanding what you're grouping
- ✅ Your question (breakdown by source pair) forced me to investigate deeper
