# Parent Age Implausibility Analysis: 8 Findings

**Report Section**: Priority 2-9 findings  
**Total Cases**: 8 parent-child relationships  
**Status**: 5 likely errors, 3 edge cases

---

## Summary Table

| # | Parent | Child | Gap | Gender | Issue | Type | Confidence |
|---|--------|-------|-----|--------|-------|------|-----------|
| 1 | Patrick Kelly (~1859) | Mary Kelly (~1864) | 5yr | M→F | Below 15yr min | **TOO YOUNG** | HIGH |
| 2 | Jane Graham (~1857) | John Graham (~1868) | 11yr | F→M | Below 15yr min | **TOO YOUNG** | HIGH |
| 3 | Patrick Ward (~1863) | James Ward (~1865) | 2yr | M→M | Below 15yr min | **MERGE ERROR** | VERY HIGH |
| 4 | James McMenamin (~1858) | James McMenamin (~1866) | 8yr | M→M | Below 15yr min | **MERGE ERROR** | VERY HIGH |
| 5 | Anne Slevin (~1839) | Patrick (~1893) | 54yr | F→M | Exceeds 50yr max | **SPLIT ERROR** | VERY HIGH |
| 6 | Anne Slevin (~1839) | Charles (~1895) | 56yr | F→M | Exceeds 50yr max | **SPLIT ERROR** | VERY HIGH |
| 7 | Anne Slevin (~1839) | Mary Margaret (~1900) | 61yr | F→M | Exceeds 50yr max | **SPLIT ERROR** | VERY HIGH |
| 8 | Catherine McM (~1874) | James McM (~1866) | -8yr | F→M | **AGE REGRESSION** | **CATASTROPHIC** | CRITICAL |

---

## Detailed Analysis

### CRITICAL: Case 8 (Catherine McMenamin / James McMenamin)

**Relationship 22767**: Parent 29167 (Catherine, b. ~1874) / Child 29166 (James, b. ~1866)  
**Gap**: -8 years (parent YOUNGER than child) 

**Status**: ✗ **CATASTROPHIC MERGE ERROR**

**Analysis**:
- Parent born 1874, child born 1866 = child is 8 years older
- This is **impossible** — parent cannot be younger than child
- Indicates **wrong person merged** or **relationship assignment error**

**Action**: **MUST SPLIT** — This is a clear merge error, not an age estimation issue.

---

### VERY HIGH: Cases 5-7 (Anne Slevin & Children)

**Person 29146 (Anne Slevin, b. ~1839)** linked as parent to THREE children with impossible age gaps:

| Child | Birth | Gap | Issue |
|-------|-------|-----|-------|
| Patrick (28234) | ~1893 | 54yr | Exceeds 50yr maternal max |
| Charles (28525) | ~1895 | 56yr | Exceeds 50yr maternal max |
| Mary Margaret (28236) | ~1900 | 61yr | Exceeds 50yr maternal max |

**Status**: ✗ **LIKELY SPLIT ERROR** (multiple children incorrectly grouped as one person's children)

**Analysis**:
- Anne Slevin born ~1839 would be 54-61 years old in 1893-1900
- Possible if Anne lived very long, but:
  - Three children all with Anne with impossible gaps
  - **Pattern suggests TWO different people named "Anne Slevin"** merged into one
  - Older Anne (~1839) had children 1860-1880 (not in this data)
  - Younger Anne or different Anne (~1860-1870) had children 1893-1900

**Root cause**: Person resolution merged two different "Anne Slevin" records that shouldn't be together.

**Action**: **MUST SPLIT** into separate persons. This is likely two different Annes from different generations.

---

### VERY HIGH: Cases 3-4 (Sibling Misidentification)

**Case 3 - Patrick Ward & James Ward**  
Relationship 22665: Parent 29027 (Patrick, b. ~1863) / Child 29147 (James, b. ~1865)  
Gap: 2 years

**Case 4 - James McMenamin Family**  
Relationship 22766: Parent 28658 (James, b. ~1858) / Child 29166 (James, b. ~1866)  
Gap: 8 years

**Status**: ✗ **LIKELY SIBLING MISIDENTIFICATION**

**Analysis**:
- Both show men with 2-8 year age gaps assigned as parent-child
- Both have same surname and same townland (context suggests siblings)
- Pattern: Younger man named in 1901 census → linked to 1911
  - 1901 age: young (18-20s)
  - 1911 age: older (28-35)
  - Household role misread or brother confused with father

**Root cause**: Relationship resolution incorrectly assigned sibling-sibling linkages as parent-child.

**Action**: **MUST CORRECT** relationship type from `parent_child` to `sibling`. These are likely brothers, not father-son.

---

### HIGH: Cases 1-2 (Too-Young Parents)

**Case 1 - Patrick Kelly & Mary Kelly**  
Relationship 22429: Parent 28557 (Patrick, b. ~1859) / Child 28499 (Mary, b. ~1864)  
Gap: 5 years

**Case 2 - Jane Graham & John Graham**  
Relationship 22319: Parent 29081 (Jane, b. ~1857) / Child 29082 (John, b. ~1868)  
Gap: 11 years

**Status**: ✗ **LIKELY MERGE ERROR**

**Analysis**:
- Minimum parent-child gap is 15 years (biological constraint)
- Both cases have gaps of 5-11 years
- These could be:
  - **Misidentified siblings** (not parent-child)
  - **Wrong person merged** (e.g., brother of parent confused with parent)
  - **Census transcription error** (ages significantly off)

**Action**: Review household context and census records:
- If same-surname people in same household: likely siblings
- If one is clearly older generation: likely merge error

---

## Pattern Analysis

### Root Cause Breakdown

| Issue | Count | Likely Cause | Fix |
|-------|-------|--------------|-----|
| Age regression (-8 to -1 yrs) | 1 | Merge error | Split persons |
| Extreme maternal age (50+ yr gap) | 3 | Two different people merged | Split persons |
| Too-young parent (5-11 yr gap) | 2 | Sibling misidentification or merge | Review relationships |
| Young parent (8 yr gap) | 1 | Sibling misidentification | Change to sibling |
| **TOTAL** | **8** | | |

### Confidence Levels

**CRITICAL (Fix immediately):**
- Case 8: Age regression (-8yr) = 1 finding

**VERY HIGH (Fix after CRITICAL):**
- Cases 5-7: Extreme maternal age (54-61yr) = 3 findings
- Cases 3-4: Likely sibling misidentification = 2 findings

**HIGH (Review & correct):**
- Cases 1-2: Too-young parents (5-11yr) = 2 findings

---

## Recommended Improvements

### 1. **Immediate: Add Relationship Type Validation**

Currently, the validation layer checks **parent-child age gaps**. But it doesn't check if the relationship type itself is correct.

**Add**:
```python
def validate_relationship_type(person_1_birth_year, person_2_birth_year, assigned_type):
    """Check if relationship type matches age gap."""
    gap = abs(person_2_birth_year - person_1_birth_year)
    
    if assigned_type == 'parent_child':
        if gap < 15:  # Min parent-child gap
            return False, f"Gap {gap}yr < 15yr minimum → likely sibling"
        if gap > 60:  # Unusual but possible
            return True, f"Unusual but possible maternal age"
        return True
    
    elif assigned_type == 'sibling':
        if gap > 25:  # Unusual sibling gap (generational)
            return False, f"Gap {gap}yr > 25yr → likely parent-child"
        return True
```

**Impact**: Would catch Cases 3-4 as "suspicious sibling assignment" or "likely misidentified."

### 2. **Add Person Age Coherence Check**

For persons with 3+ census appearances, check that all recorded ages are coherent.

**Add**:
```python
def validate_person_age_coherence(person_census_records):
    """Check age progression across all censuses for one person."""
    records = sorted(by_year)
    
    for i in range(len(records) - 1):
        gap_years = records[i+1]['year'] - records[i]['year']
        age_delta = records[i+1]['age'] - records[i]['age']
        expected_delta = gap_years
        
        if age_delta < 0:  # Age regression
            return False, "Age decreased between censuses"
        if abs(age_delta - expected_delta) > 3:  # Allow ±3 for estimation error
            return False, f"Age gap {age_delta} != expected {expected_delta}"
    
    return True
```

**Impact**: Would catch Case 8 (age regression) automatically.

### 3. **Add Split-Person Detection**

When a person has multiple children with impossible age gaps (all from same household context), flag for splitting.

**Add**:
```python
def detect_split_person_pattern(person, children_list):
    """Check if person-children cluster suggests two people merged."""
    if not children_list:
        return False
    
    age_gaps = [person_birth - child_birth for child_birth in children]
    
    if len([g for g in age_gaps if g > 50]) >= 2:  # Multiple impossible gaps
        return True, f"Multiple children (n={len(children)}) with extreme age gaps"
    
    if max(gaps) - min(gaps) > 40:  # Wide spread suggests different parents
        return True, f"Age gap spread {max-min}yr suggests two people"
    
    return False
```

**Impact**: Would catch Case 5-7 (Anne Slevin) as split-person pattern.

### 4. **Enhance Relationship Resolution Logic**

The relationship resolution currently infers parent-child from household roles. But small age gaps should trigger sibling detection.

**Change**:
```python
# In relationship_resolution.py:
if head_age - child_age < 15:  # Too young to be parent
    # Re-classify as sibling, not parent_child
    relationship_type = 'sibling'
    confidence_score = 0.75  # Lower confidence for inferred sibling
```

**Impact**: Cases 3-4 would be correctly identified as siblings.

### 5. **Add Multi-Census Triangulation Check**

For relationships spanning 2+ censuses, verify consistency.

**Add**:
```python
def validate_relationship_across_censuses(person_1, person_2, relationship_type):
    """Verify relationship is consistent across all shared censuses."""
    shared_years = intersection(person_1.census_years, person_2.census_years)
    
    if len(shared_years) >= 2:
        # In each census, are they in same household? Same roles?
        for year in shared_years:
            record_1 = person_1.records[year]
            record_2 = person_2.records[year]
            
            if record_1.household_id != record_2.household_id:
                return False, f"Not in same household in {year}"
    
    return True
```

**Impact**: Would catch inconsistencies when same two people appear in different households across censuses.

---

## Implementation Priority

### Phase 1: Immediate (1-2 days)
1. Add age regression check (catch Case 8)
2. Add extreme age gap detection (catch Cases 5-7)
3. Manual review & split those persons

### Phase 2: Short-term (1-2 weeks)
4. Add relationship type validation (catch sibling misidentification)
5. Manual review & correct Cases 3-4 as siblings

### Phase 3: Medium-term (next iteration)
6. Enhance relationship resolution logic to catch too-young parents
7. Add multi-census triangulation check

---

## Genealogical Impact

### Before Fixes
- 8 incorrect parent-child relationships in conclusions
- Anne Slevin appears as single person with three impossible-age children
- Patrick & James Ward/McMenamin appear as father-son when they're brothers
- Age coherence is violated (parent younger than child)

### After Fixes
- All parent-child gaps 15+ years ✓
- All relationships consistent across censuses ✓
- Persons correctly split when evidence suggests two people ✓
- Sibling relationships properly identified ✓

---

## Recommendation

**Implement Phase 1 now** (age regression + extreme gap detection):
- Quick wins on Cases 5-8 (most severe)
- Requires only validation rule additions, no architectural changes
- Can fix persons immediately in follow-up manual review

**Plan Phase 2** for next sprint:
- Relationship type validation
- Sibling misidentification catches
- Estimate: 2-3 days work

These improvements will significantly reduce genealogically implausible relationships in future pipeline runs.

