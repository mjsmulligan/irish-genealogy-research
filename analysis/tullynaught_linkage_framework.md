# Tullynaught Genealogy Data: Manual Linkage Analysis Framework

## Context
- **Data**: 3 census years (1901, 1911, 1926) for Tullynaught townland(s) in Ireland
- **Current linkage**: ~21.1% (with v1.1) / expecting ~25-28% (with v1.2-v1.3 tuning)
- **Remaining unlinked**: ~72-79%

## Population Statistics
- **1901**: 1,193 recorded persons (263 records/households)
- **1911**: 1,080 recorded persons (240 records/households)
- **1926**: 894 recorded persons (212 records/households)
- **Total**: 3,167 recorded persons

## Analysis Framework

To understand why 72-79% remain unlinked, we should investigate:

### 1. **Household Continuity** (Expected: 30-40% linkage ceiling)
- Do household heads re-appear across censuses with their families?
- Expected pattern: Head (age 35→45→60), Spouse (age 33→43→58), Children age progression
- **Success**: When entire household links, including role consistency
- **Failure**: When head links but children don't

### 2. **Household Dissolution** (Expected loss: 20-30%)
- Widows living alone or with children (no spouse in later census)
- Spinster/bachelor pattern (adult children not living with parents)
- Adult children striking out on their own → new households
- Servants/lodgers changing households
- **Cannot be recovered**: These are correct—different households, different Persons

### 3. **Name Variations** (Expected gain: 2-5pp with better phonetics)
- Gaelic-English variants: Séamus→James, Mairead→Margaret, Saoirse→Sarah
- Spelling drift: O'Brien→OBrien, Bustard→Busterd
- Nickname usage: William→Bill, Margaret→Maggie
- **Currently missed**: Gaelic-English variants require specialized encoding
- **Addressed by v1.3**: Soundex helps O'Brien/Brien variants

### 4. **Age Heaping & Errors** (Expected gap: 10-15%)
- Systematic rounding: 45→50, 38→40, 52→50
- Off-by-one due to enumerator error or confusion
- Birth year reconstruction limits (±5 years, maybe ±7 with our analysis)
- **Example**: Head aged 45 in 1901, 54 in 1911 (should be 55, 10yr gap)
- **Difficulty**: Hard to tell heaping from real births/deaths without external data

### 5. **Deaths & Emigration** (Expected: 15-25%)
- People in 1901 but not 1911 or 1926 (died or emigrated)
- Reverse: children in 1911/1926 but not 1901 (born between censuses)
- Single-year appearances (e.g., only in 1901 and 1926, skipping 1911)
- **Cannot be recovered**: These are data facts, not matching failures

### 6. **Role Information Not Used** (Expected gain: 1-3pp)
- Person similarity doesn't use household role (head/spouse/son/daughter)
- Role consistency is strong signal (head→head, child→child)
- **Could improve**: Adding role as soft constraint to Splink

### 7. **Threshold Still Conservative** (Expected gain: 1-2pp)
- Current threshold 0.60; lowering to 0.55 might catch marginal matches
- Risk: false positives from similar names in same household
- **Could improve**: Confidence calibration analysis

## Expected Breakdown of 72-79% Unlinked

| Category | % of Total | Recoverable? | Current Mechanism |
|----------|-----------|-------------|-----------------|
| Household dissolution | 20-30% | No | Expected—different households |
| Deaths/Emigration | 15-25% | No | Expected—different people |
| Age heaping/errors | 5-10% | Partial | Birth year ±7 band helps somewhat |
| Name variations (Gaelic-English) | 3-5% | Yes | Needs custom phonetic encoding |
| Name/age/role mismatch | 2-5% | Yes | Could optimize threshold/features |
| Other errors | 2-5% | Partial | Might need role usage |
| **Ceiling (theoretically recoverable)** | **7-15%** | **Yes** | Need deeper analysis |

## Recommended Next Steps

### Phase 1: Empirical Pattern Analysis
1. Sample 3-5 townlands (5-15 households each, all 3 censuses)
2. For each, manually classify unlinked persons:
   - Which *should* link but don't? (recoverable)
   - Which correctly don't link? (not recoverable)
3. Measure breakdown by category

### Phase 2: Targeted Improvements
Based on Phase 1 findings:
- **If Gaelic-English variants dominate**: Custom phonetic encoding (high effort, 2-5pp gain)
- **If age heaping dominates**: Expand birth year bands or better age reconciliation (1-2pp gain)
- **If role info missing**: Add role to person similarity (1-3pp gain)
- **If threshold conservative**: Lower to 0.55 with verification (1-2pp gain)

### Phase 3: Diminishing Returns
Beyond 28-30% linkage, remaining gains require:
- Manual review and linking (not scalable)
- External data (baptism records, ship manifests, land deeds)
- Complex probabilistic inference (beyond Splink scope)

## Key Insight

**The real question isn't "why is linkage low?" but "what is theoretically recoverable?"**

- 70%+ is likely correct (household dissolution, deaths, emigration)
- 10-15% might be recoverable with better phonetics or features
- 2-5% is noise/errors

Once we categorize Phase 1 findings, we can set realistic targets and focus on highest-ROI improvements.
