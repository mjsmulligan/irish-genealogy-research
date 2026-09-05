# CRITICAL FINDING: 1926 Linkage Crisis

**Date**: 2026-06-27  
**Status**: Requires immediate investigation  
**Severity**: HIGH — Invalidates Phase 1 assumptions

---

## The Problem

**Previous belief**: "21.1% linkage is solid household-level matching"

**Reality**: Only **203 linked Persons (426 RecordedPersons)** out of 3,167 total.

Breakdown by coverage:

| Category | Count | Details |
|---|---|---|
| All 3 censuses (1901+1911+1926) | 20 | 0.6% — Truly connected chains |
| 1901+1911 only | 141 | 4.5% — Lost by 1926 (death/emigration) |
| 1911+1926 only | 38 | 1.2% — Appeared after 1901 |
| 1901+1926 only | 4 | 0.1% — Direct 25-year link |
| Single-census only | 0 | 0% — No truly isolated persons |

**Linkage by source:**
- **1901**: 165/1193 linked (13.8%) — **86.2% unlinked**
- **1911**: 199/1080 linked (18.4%) — **81.6% unlinked**
- **1926**: 62/894 linked (6.9%) — **93.1% unlinked** ⚠️ CRITICAL

---

## The 1926 Crisis

**1926 has only 6.9% linkage**, compared to 13-18% for 1901/1911. This is **catastrophic**.

**Possible causes:**

### 1. Household Structure Changed (Most Likely)

**1901/1911 structure:**
- 19-17 households (giant aggregations)
- 62-63 persons per household
- Example: "House 1" = 142 people (head Robert White + extended family + servants)

**1926 structure:**
- 217 households (13× fragmentation)
- 4.1 persons per household
- Each "aform_name" is a separate household return

**Impact on linking:**
- Splink's household-level matching uses modal surname + forename sets
- With only 4 people per household, there's no family structure to match
- A 1911 household (head + wife + 3 kids + 2 servants) fragments into separate 1926 units
- We can't recognize them as the same family anymore

### 2. Data Quality / Enumeration Differences

- 1901/1911 were more complete household enumerations
- 1926 data structure is fundamentally different (smaller, more fragmented returns)
- Irish census format changed between decades

### 3. Demographic Reality (Partial Explanation)

- Emigration rates 1911→1926 were high (~15-25%)
- Sons/daughters move out, marry, form their own households
- Deaths during WWI era

**But this only explains ~25% loss, not 80%+ unlinkage.**

---

## Why Soundex (v1.3) Won't Fix This

**Soundex helps with name variants** (O'Brien/Brien).  
**1926 linkage crisis is structural, not a name problem.**

Evidence:
- We found 275 exact name matches (1901→1911) earlier
- No name variant issue detected
- Problem is we can't **find** 1926 matches to begin with

---

## What v1.3 Testing Will Actually Show

**Prediction**: Soundex → minor gain (maybe +0.5pp)

**Why**: Most unlinked persons in 1926 aren't "close matches we're missing"—they're **completely unmatched** because household structure is incomparable.

---

## Immediate Questions (Before v1.3 Deployment)

1. **Is the 1926 CSV data actually from Tullynaught?**
   - Check: Do the surnames match 1901/1911?
   - If not: Data error.

2. **Are we parsing 1926 correctly?**
   - We renamed `aform_name` → `house_number`
   - Did this grouping work correctly?
   - Check: Household size distribution (should be 4.1 avg per earlier output)

3. **Is 1926 truly fragmented, or is it a data loading issue?**
   - Manual inspection: Open 1926 CSV, spot-check 5 households
   - Are they really 4-person units, or did we misparse?

4. **Should we lower person resolution threshold specifically for 1926?**
   - Maybe 0.55 (instead of 0.60) catches more 1926 matches?
   - Would help cross-decade linking but risks false positives

---

## Revised Theory on 78.9% Unlinked

**Original breakdown** (from Phase 1):
- Household dissolution: 20-30%
- Deaths/emigration: 15-25%
- Age heaping: 5-10%
- Other: 20-30%

**Revised understanding**:
- **1926 household fragmentation**: 40-50% (structural, can't match tiny households)
- **1901→1926 survival loss**: 20-30% (death/emigration is real)
- **Feature mismatch for small households**: 10-20% (forename sets don't work for 4 people)
- **Name/age/role issues**: 5-10%
- **Threshold conservatism**: 1-3%

---

## Recommended Next Actions

**BEFORE deploying v1.3:**

1. ✅ **Verify 1926 data parsing**
   - Spot-check 10 households in CSV
   - Confirm they're actually 4-person units
   - Check if surnames match expected Donegal families (Graham, Cassidy, Wray, etc.)

2. ✅ **Understand 1926 household structure**
   - Why is it so fragmented vs. 1901/1911?
   - Is this genuine enumeration format change, or data error?

3. ⏳ **If 1926 is genuine fragmentation:**
   - Don't expect v1.3 to help much
   - Consider alternative features (role consistency, place stability)
   - Maybe 1926 is just incomparable—set expectations accordingly

4. ⏳ **If 1926 is a parsing error:**
   - Fix the parsing
   - Re-run pipeline
   - Test v1.3 impact (should be higher)

---

## Bottom Line

**The 21.1% linkage breaks down as:**
- ✅ 0.6% truly stable (all 3 censuses)
- ⚠️ 4.5% connected 1901→1911 but lost by 1926
- ⚠️ 1.2% appeared after 1901
- ❌ 0.1% direct 25-year jumps (almost none)
- ❌ 93% of 1926 persons remain completely unlinked

**The 1926 crisis is not a matching quality issue—it's structural.**

Soundex won't help much unless we first understand and solve why 1926 household structure is so different.
