# Age Regression Issue Analysis

**Date:** 2026-06-28
**Status:** OPEN - Design decision needed

## Problem

The validation report flags **8 age regressions** where a Person is linked to census records showing impossible age progression:
- Example: Person linked to age 20 in 1901 but also age 35 in 1911 (suggests born ~1881 vs ~1876)

## Root Cause

**Birth year derivation uses the earliest census age** to back-calculate:
- Code: `src/review/findings.py::_derive_birth_year()`
- Logic: Takes minimum age from all linked censuses, calculates as: `birth_year = census_year - age`
- Problem: If Person cluster contains ages [20, 35], uses 20 → birth ~1881
  - But age 35 in 1911 suggests birth ~1876
  - This creates logical inconsistency in parent-child relationships

## Why It Happens

1. Person Resolution clusters similar recorded persons by Splink score ≥ 0.45
2. Relationship Resolution adds linkages without age validation (as of this session)
3. A Person can end up with conflicting ages from different censuses
4. When deriving birth year for the Person, using the minimum age doesn't reflect all evidence

## Current Findings (Latest Report 2026-06-28)

- **Age regressions flagged:** 8
- **Parent age implausible:** 18
- **Total:** 26 findings related to age issues

## Options for Resolution

### Option 1: Use Age Range
- Calculate birth year range from all linked censuses
- Allow for aging/estimation error (±2 years)
- More robust but changes how we reason about age certainty
- **Pro:** Captures all evidence; **Con:** More complex state representation

### Option 2: Reject Conflicting Ages
- Add hard constraint during conclusion: reject linkage if ages conflict beyond tolerance
- Similar to same-census linking constraint
- **Pro:** Simple, deterministic; **Con:** May lose valid linkages with genuine estimation error

### Option 3: Use Median/Average Birth Year
- Back-calculate birth year from each census age, use median
- Simpler than ranges, more robust than minimum
- **Pro:** Balances outliers; **Con:** Less transparent

### Option 4: Flag for Manual Review
- Keep as findings in report
- Reviewer decides whether to split Person or accept conflict
- **Pro:** Conservative, preserves data; **Con:** Adds manual work

## Recommended Next Steps

1. **Quantify the issue:** How many Persons have conflicting ages? What's the range?
2. **Examine actual cases:** Are these legitimate (estimation error) or genuine merge errors?
3. **Design decision:** Choose resolution approach (1-4 above)
4. **Implement:** Add logic to person_resolution or relationship_resolution to prevent creating conflicting-age Persons
5. **Validate:** Re-run conclude and verify age regressions drop to near-zero

## Related Code

- **Linkage validation:** `src/validation/linkage_validation.py::validate_age_progression()`
  - Rejects progression outside ±2 years tolerance
  - Already rejects backward age (but this isn't catching it)
  
- **Birth year derivation:** `src/review/findings.py::_derive_birth_year()`
  - Priority: birth Event > baptism Event > census age (minimum)
  
- **Person resolution:** `src/conclusion/person_resolution.py::_filter_valid_pairs()`
  - Runs age validation on pair level but not cluster level
  
- **Relationship resolution:** `src/conclusion/relationship_resolution.py`
  - Recently added same-census check; age regression check also added (this session)

## Notes

- This is distinct from the same-census linking constraint (now enforced)
- Age regressions only appear in validation report, not during conclusion (so aren't being rejected upstream)
- Likely some linkages with ages [20, 35] are being accepted by Splink despite age conflict
