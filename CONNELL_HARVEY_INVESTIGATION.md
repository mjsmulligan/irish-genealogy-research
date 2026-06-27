# Connell Harvey Merge Error: Investigation & Resolution

**Person ID**: 28708  
**Name**: Connell Harvey (Druminnin)  
**Issue**: Appears in 2 different Census 1911 households  
**Status**: Under investigation & resolution

---

## Current State: Person 28708 Linkages

Person 28708 is currently linked to 4 recorded persons:

| # | RP ID | Name | Age | Record | Date | Source | Household |
|---|-------|------|-----|--------|------|--------|-----------|
| 1 | 3691 | Connell Harvey | 8 | 828 | 1901-03-31 | Census 1901 | James Harvey household |
| 2 | 4591 | Connell Harvey | 18 | **1023** | 1911-04-02 | Census 1911 | James Harvey household |
| 3 | 4631 | Connell Harvey | 18 | **1030** | 1911-04-02 | Census 1911 | Mary McGinty household |
| 4 | 5369 | Connell Harvey | 33 | 1197 | 1926-04-18 | Census 1926 | ??? |

---

## The Problem: Two 1911 Records

**Record 1023 (Census 1911)** - James Harvey Household:
```
RP 4589 | James Harvey (69)                    ← Head
RP 4590 | Anne Harvey (57)                     ← Spouse
RP 4591 | Connell Harvey (18)   ← PERSON 28708 (son)
RP 4592 | James Harvey (17)                    ← Son
RP 4593 | Mary Anne Harvey (14)                ← Daughter
RP 4594 | Margaret Harvey (63)                 ← Mother
```

**Record 1030 (Census 1911)** - Mary McGinty Household:
```
RP 4629 | Mary McGinty (52)                    ← Head
RP 4630 | Margaret McGinty (50)                ← Spouse (or relative?)
RP 4631 | Connell Harvey (18)   ← PERSON 28708 (???)
```

---

## Analysis: What Likely Happened?

**Option A: Two Different People (Most Likely)**
- RP 4591 (Connell Harvey, age 18, in James Harvey household) = son of James Harvey
- RP 4631 (Connell Harvey, age 18, in Mary McGinty household) = different person, possibly related to McGintys
- Both happen to be named "Connell Harvey" and age 18
- Splink similarity scorer at 0.45+ clustered them as same person (merge error)

**Option B: Same Person, Census Enumeration Error (Unlikely)**
- Connell Harvey was enumerated in two households on same date (impossible without transcription error)
- Very unlikely in systematic census enumeration

**Option C: Naming/Relationship Confusion (Possible)**
- Connell Harvey might be servant/lodger in McGinty household while living with Harveys
- 1911 census sometimes listed all people in building on census date
- But records show different addresses/townlands → unlikely

---

## Evidence for Two Different People

**Age progression analysis**:
- RP 3691 (Connell, age 8, 1901) → RP 4591 (Connell, age 18, 1911): **+10 years, 10-year gap ✓ plausible**
- RP 3691 (Connell, age 8, 1901) → RP 4631 (Connell, age 18, 1911): **+10 years, 10-year gap ✓ plausible**

Both pass age validation! So we can't distinguish on age alone.

**Household context**:
- RP 4591 is clearly son of James Harvey (1901 household context supports)
- RP 4631 appears in McGinty household (no obvious relationship)
- **Conclusion**: Most likely two different "Connell Harvey" individuals

**Best guess**: 
- RP 4591 is the legitimate Connell Harvey (son of James Harvey)
- RP 4631 is a different Connell Harvey (possibly nephew, relative of McGintys, or unrelated person with same name)

---

## Resolution Strategy

Since we can't determine with 100% certainty which is correct, the safest approach is:

**Option 1: Split Person 28708 into Two Persons (RECOMMENDED)**
- Person 28708 keeps RP 3691, RP 4591, RP 5369 (James Harvey lineage)
- Create new Person with RP 4631 (McGinty context)
- Rationale: Preserves genealogically coherent family lines

**Option 2: Keep Person 28708 as-is, flag in review**
- Report already flags it as GC07 merge error candidate
- Let genealogist decide
- Not recommended for production database

**I recommend Option 1**: Split into two persons. The James Harvey lineage (RP 3691 → RP 4591 → RP 5369) is more internally consistent than mixing with McGinty household.

---

## How the New Validation Would Have Resolved This Automatically

**If the cross-household same-census check was in place BEFORE person resolution**:

Person resolution (0.45 threshold) would have clustered RP 4591 and RP 4631:
```
Splink similarity: 0.48+ (both Connell Harvey, age 18, 1911)
→ Clusters into single Person
→ During validation cleanup:
   CHECK: Same census (source_id=4)? YES
   CHECK: Different households (record_id 1023 ≠ 1030)? YES
   CHECK: Same year (1911 = 1911)? YES
   RESULT: VIOLATION FLAGGED
   ACTION: Remove linkage
```

**Result**:
- RP 4591 stays as Person 28708 (linked to RP 3691, RP 5369)
- RP 4631 becomes separate person/orphan
- No merge error in final dataset
- Report might flag RP 4631 as unlinked in household, but NOT as merge error

---

## Manual Fix Steps

1. **Create new person for RP 4631**
   - Insert new row in `person` table
   - Link RP 4631 via new person_recorded_person entry

2. **Remove erroneous linkage**
   - Delete `person_recorded_person` row where person_id=28708 AND recorded_person_id=4631

3. **Verify**
   - Person 28708 should have 3 linked persons (RP 3691, 4591, 5369)
   - New person should have 1 linked person (RP 4631)
   - Report should show Person 28708 in James Harvey lineage only

---

## Summary

**The merge error**: Connell Harvey appears in two 1911 households
**The likely cause**: Two different people with same name got clustered by Splink
**The fix**: Split into two persons
**How automation prevents it**: Cross-household same-census validation detects and removes the bad linkage during validation cleanup

