# Test Metrics Definitions

**Purpose**: Define how linkage percentages are calculated across all test runs to ensure consistency and eliminate confusion about numerator/denominator.

---

## Tullynaught Golden Dataset (Fixed)

All tests use the complete Tullynaught 3-census fixture set with **known, fixed record and person counts**:

| Census | CSV File | Records | Persons |
|--------|----------|---------|---------|
| 1901 | tullynaught_1901.csv | 263 | 1,193 |
| 1911 | tullynaught_1911.csv | 240 | 1,080 |
| 1926 | tullynaught_1926.csv | 212 | 894 |
| **TOTAL** | - | **715** | **3,167** |

These counts are:
- **Derived from**: CSV row counts (header + data rows)
- **Fixed**: Do not change unless fixture CSVs are modified
- **Source of truth**: Used as the denominator for all linkage calculations

---

## Linkage Percentage Definitions

### 1. Three-Census Linkage Percentage

**Definition**: Proportion of recorded persons that are linked into unified persons across all three censuses.

**Formula**:
```
3-Census Linkage % = 100 × (Linked Recorded Persons) / (Total Recorded Persons)
                   = 100 × (rows in person_recorded_person) / 3,167
```

**Numerator**: `COUNT(DISTINCT recorded_person_id) FROM person_recorded_person`
- Recorded persons that have been linked to at least one unified person
- May include NULL links (depends on clustering threshold)

**Denominator**: `3,167` (fixed)
- All 3,167 recorded persons across the three censuses
- Includes persons who remain unlinked (no person_recorded_person row for them)

**Interpretation**:
- 0%: No persons linked (each census person is isolated)
- 50%: Half of all census persons merged into unified persons
- 100%: All census persons merged into unified persons (complete clustering)

**Expected Range**: 20–30% in production (some unlinked due to missing records, data quality, threshold)

---

### 2. Pairwise Person Similarity Metric

**Definition**: Distribution and average quality of similarity scores across all recorded_person pairs evaluated by Splink.

**Formula**:
```
Pairwise Metrics:
  - Total pairs evaluated: COUNT(*) FROM recorded_relationship WHERE type='similarity'
  - Average score: AVG(score) FROM recorded_relationship WHERE type='similarity'
  - Pairs ≥0.65 (high confidence): COUNT(*) / total_pairs %
  - Pairs 0.50-0.65 (medium confidence): COUNT(*) / total_pairs %
  - Pairs 0.45-0.50 (marginal): COUNT(*) / total_pairs %
  - Pairs <0.45 (weak): COUNT(*) / total_pairs %
```

**Numerator** (each tier): Count of similarity pairs in score range
**Denominator**: Total similarity pairs evaluated

**Interpretation**:
- **High avg score (≥0.50)**: Splink features are well-calibrated; true matches score reliably above noise
- **Majority at ≥0.50**: Threshold of 0.50 leaves weak matches below, strong matches above
- **Skewed to <0.45**: Too many weak pairs; suggests features are not discriminating
- **Tight clustering**: Distribution clusters around threshold indicate good signal

**Expected Pattern** (v1.1 baseline):
- Average score: 0.50+
- 40–45% of pairs ≥0.50 (merge candidates)
- 55–60% of pairs <0.45 (likely non-matches)
- Mode in 0.45–0.50 range (marginal pairs)

---

## Test Execution Lifecycle

### Phase 1: Database Setup
1. **Clear evidence + conclusion layers** (place_authority preserved)
   ```
   DELETE FROM: training_labels, relationship_recorded_relationship, person_recorded_person,
               place_record, event_record, person_event, record_similarity, recorded_relationship,
               event, relationship, person, person_name, recorded_person, record
   ```
2. **Ingest all three CSVs** (sources 3, 4, 5)
   - Verify: 263 + 240 + 212 = 715 records ingested
   - Verify: 1,193 + 1,080 + 894 = 3,167 persons ingested

### Phase 2: Evidence Pipeline
3. **Run place resolution** → All 715 households matched to place_authority
4. **Run record similarity** → Splink household-level clustering
5. **Run person similarity** → Splink person-level clustering (uses role consistency v1.2)
6. **Run person resolution** → Threshold-based person clustering (threshold=0.50)

### Phase 3: Conclusion Pipeline
7. **Run relationship resolution** → Resolve relationships from clustered persons
8. **Run event resolution** → Resolve events and birth dates

### Phase 4: Metrics Capture
9. **Capture linkage metrics**:
   - Total persons: `COUNT(DISTINCT person_id) FROM person`
   - Linked persons: `COUNT(DISTINCT recorded_person_id) FROM person_recorded_person`
   - Linkage %: `(linked / 3,167) × 100`

10. **Capture pairwise metrics**:
    - Total similarity pairs: `COUNT(*) FROM recorded_relationship WHERE type='similarity'`
    - Score distribution by tier
    - Average score

---

## Consistency Rules for Test Runs

1. **Always start with clean database**: `python -m src.cli clear-evidence` before each test run
2. **Always ingest complete fixture set**: All three CSVs (1901, 1911, 1926)
3. **No selective ingestion or filtering**: All 3,167 persons enter the pipeline
4. **Fixed denominator**: Linkage % always uses 3,167 as denominator
5. **Record metrics at conclusion**: Capture after all pipeline phases complete
6. **Report with confidence**: Include avg score, percentile distribution, threshold

---

## Regression Detection

**If linkage % drops >2pp between runs**:
- Verify database was cleared: `SELECT COUNT(*) FROM person` should be 0 before setup
- Verify all three fixtures ingested: Check record source_id distribution (263, 240, 212)
- Check similarity pair count: If it dropped, Splink comparison levels changed
- Check role consistency feature: Verify v1.2 comparison is enabled and correct
- Check EM weights: Query `recorded_relationship` score distribution for shifts

**Baseline for v1.2 (post-fix)**:
- Expected linkage: ≥26% (restored from regression)
- Expected avg score: 0.50+
- Expected pairs ≥0.50: ≥40%

---

## Updating Metrics After Code Changes

When changing Splink comparison levels, EM parameters, or clustering logic:

1. **Understand the expected direction**: Will change boost or penalize linkage?
2. **Run full test suite**: Capture all metrics
3. **Compare to baseline**: Document what changed and why
4. **Update documentation**: If new baseline is intentional, comment with reasoning
5. **Never silently swap numerators/denominators**: If a metric definition changes, document it

