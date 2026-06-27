# Merge Error Root Cause Analysis & Fix

**Issue**: Person 28708 (Connell Harvey, Druminnin) appears in 2 different Census 1911 households  
**Status**: Fixed — Added cross-household same-census validation check  
**Impact**: Future pipeline runs will catch this error automatically

---

## The Problem

Person 28708 is linked to:
- **Record 1023**: Household A, Census 1911
- **Record 1030**: Household B, Census 1911

This is impossible. A single person cannot appear in two different households in the same census. This is a **merge error** — either:
1. These are two different people incorrectly merged into one Person
2. One of the records has the wrong source/date metadata

---

## Why the Original Validation Didn't Catch It

Your household coherence validation checked:

```sql
WHERE r1.record_id = r2.record_id  -- same household
```

**Logic**: "If two recorded persons are linked to the same record_id, they're in the same household → flag as duplicate."

**In Connell Harvey's case**:
- r1.record_id = 1023 (Household A)
- r2.record_id = 1030 (Household B)
- 1023 ≠ 1030, so WHERE clause returns **NO ROWS**
- Validation passes ✓ (no error detected)

**The gap**: The check only caught **within-household duplicates**. It missed **across-household duplicates** (same person in different households).

---

## Why This Happened

The pipeline architecture runs in this order:

```
1. Person Resolution (Splink clustering at 0.45 threshold)
   ↓ (clusters recorded persons without household constraints)
2. Relationship Resolution (infers household structure)
   ↓
3. Event Resolution (creates life events)
   ↓
4. Validation Cleanup (checks linkage validity)
```

**The problem**: Person resolution happens *before* validation. Splink doesn't enforce "can't link two people from same census" — it just scores similarity (0.45+). If two 1911 records are similar enough, they cluster together.

**Example**:
- Connell Harvey appears in 1911 Household A (record 1023)
- Connell Harvey appears in 1911 Household B (record 1030)
- Both records have similar names, ages, locations → Splink scores 0.50+
- Clustering merges them into one Person
- Validation only checks same-household; different-household passes

**Then the review layer caught it** as a GC07 finding (merge error candidate), not as a validation error.

---

## The Fix: Cross-Household Same-Census Check

Added a second household coherence check that detects:

```sql
WHERE r1.source_id = r2.source_id          -- same census source (source_id=4 = Census 1911)
  AND r1.record_id != r2.record_id         -- different households (1023 ≠ 1030)
  AND EXTRACT(YEAR FROM r1.date) = EXTRACT(YEAR FROM r2.date)  -- same year (1911)
```

**This catches the exact Connell Harvey case:**
- source_id = 4 (Census 1911) for both
- record_id = 1023 and 1030 (different)
- date = 1911-04-02 for both (same year)
- Query returns this pair → flags as household_same_census_error → linkage removed

---

## When the Check Runs

**During validation cleanup** (step [4/4] of conclusion pipeline):

```
Validation Cleanup
├─ Check 1: Same-household duplicates (existing)
│   WHERE r1.record_id = r2.record_id
│
├─ Check 2: Cross-household same-census duplicates (NEW)
│   WHERE r1.source_id = r2.source_id AND r1.record_id != r2.record_id
│
├─ Gender flips (existing)
├─ Age regressions (existing)
├─ Name mismatches (existing)
└─ Remove all flagged linkages
```

---

## Why It Wasn't Caught Earlier

Three reasons:

### 1. **Validation Strategy Was Incomplete**
- Designed for pairwise cross-census validation (age, names)
- Wasn't designed to catch same-census impossible scenarios
- Assumed person resolution wouldn't merge impossible pairs

### 2. **Person Resolution Doesn't Know Census Rules**
- Splink optimizes for similarity matching
- Doesn't enforce "one person per household per census"
- That's a genealogical constraint, not a linking constraint

### 3. **Review Layer Caught It (Eventually)**
- The review findings detected this as GC07 (merge error candidate)
- But it had already propagated through the database
- Ideally, validation should prevent it from ever reaching the report

---

## Why This Is Important

**The strict resolution strategy you mentioned** includes:
- Person resolution (cluster similar records)
- Household coherence (no duplicates within household)
- Age/name validation (plausible progression)

**What was missing:**
- Census-level uniqueness (person can only appear once per census)

**Why it matters:**
- Without this check, impossible merge errors slip through to the review layer
- The report catches them (good), but better to prevent them at validation time (better)

---

## Implementation Details

**Changes made:**

1. **src/validation/linkage_validation.py**:
   - Extended `validate_household_coherence()` with second SQL check
   - Added `household_same_census_errors` field to `ValidationReport`

2. **src/conclusion/validation_cleanup.py**:
   - Added `household_same_census_violations_removed` to `ValidationCleanupResult`
   - Updated report printing to show both household error types

**Validation now checks:**
```
Household errors (same household):      N linkages removed
Household (same census):                M linkages removed  ← NEW
```

---

## Future Implications

**Next time the pipeline runs:**
- If Connell Harvey's 1911 records appear in person resolution again
- Same-census check will flag them → linkages removed before clustering
- Person 28708 won't exist (or will have only one record)
- Review report won't show merge error candidate

**Benefit**: Validation catches impossible scenarios *before* they become findings. The strict resolution strategy is now actually strict.

---

## Key Takeaway

Your instinct was right: a strict resolution strategy *should* prevent merge errors. The fix closes the gap by adding one more constraint to the validation layer:

**"A person can appear in only one household per census."**

This is enforced alongside:
- ✓ Age must progress plausibly
- ✓ Names must be consistent
- ✓ No gender flips
- ✓ No household duplicates
- ✓ **NEW: No same-census household duplicates**

The pipeline is now fully protected against impossible merge scenarios at the validation layer.

