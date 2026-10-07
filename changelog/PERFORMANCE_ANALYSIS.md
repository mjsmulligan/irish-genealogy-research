# Performance Analysis & Optimization Results
*23 June 2026*

**Status: COMPLETE ✅**

All Phase 1 and Phase 2 optimizations have been implemented and tested. See [docs/performance.md](docs/performance.md) for detailed performance guide.

## Quick Summary

- **Total improvement:** 25% faster (184.88s → 138.95s)
- **Census ingestion:** 38% faster (87.99s → 54.54s)
- **Event resolution:** 79% faster (38.33s → 8.02s)
- **All 59 tests passing**
- **Projected Donegal savings:** 3.8 hours (35% faster)

---

# Original Analysis (Pre-Optimization)
*23 June 2026*

## Current Performance Baseline

**Test Run Timings (Tullynaught dataset - 715 records, 3,167 persons):**

```
Total runtime:           169.30s
  Setup:                 168.68s (99.6%)
  Tests:                   0.61s (0.4%)
```

### Breakdown by Stage

| Stage | Time (s) | % of Setup | Operations |
|-------|----------|-----------|------------|
| Census ingestion (3 sources) | 85.60 | 50.7% | Ingest + role_rels |
| - Source 3 (1901): 263 records | 32.83 | 19.5% | 1,193 persons |
| - Source 4 (1911): 240 records | 28.93 | 17.2% | 1,080 persons |
| - Source 5 (1926): 212 records | 23.84 | 14.1% | 894 persons |
| Event resolution | 28.29 | 16.8% | Census + birth + marriage events |
| Relationship resolution | 24.58 | 14.6% | Household matching + relationships |
| Record similarity (Splink) | 11.68 | 6.9% | Cross-census household pairs |
| Person similarity (Splink) | 8.79 | 5.2% | Cross-census person pairs |
| Place resolution | 5.84 | 3.5% | 715 place linkages |
| Person resolution | 3.63 | 2.2% | Union-Find clustering |
| Clear tables | 0.26 | 0.2% | Truncate evidence + conclusion |

---

## Performance Bottlenecks

### 1. Census Ingestion (85.60s - 50.7%)

**Current Behavior:**
- Sequential processing: 1901 → 1911 → 1926
- Each source: CSV parse → insert records → insert persons → assign role relationships
- All done within single transactions per source

**Issues:**
- **No parallelization** - Sources processed one at a time
- **Per-row inserts** - Each record/person likely inserted individually
- Time scales linearly: ~0.125s per record, ~0.027s per person

**Optimization Opportunities:**

#### A. Parallel Source Ingestion (High Impact)
Currently sequential. Three census sources are independent and could run in parallel.

**Estimated Impact:** 50-60% reduction in ingestion time
- Current: 32.83s + 28.93s + 23.84s = 85.60s
- Parallel: ~max(32.83s, 28.93s, 23.84s) = 32.83s
- **Savings: ~52.77s (31% of total runtime)**

**Implementation:**
```python
import concurrent.futures

with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
    futures = {
        executor.submit(ingest_census_source, conn, source_id): source_id
        for source_id in [SOURCE_ID_1901, SOURCE_ID_1911, SOURCE_ID_1926]
    }
    for future in concurrent.futures.as_completed(futures):
        result = future.result()
```

**Consideration:** PostgreSQL handles concurrent connections well. Would need separate connections per thread.

#### B. Bulk Inserts (Medium-High Impact)
Currently likely using individual INSERT statements per record/person.

**Current pattern:**
```python
for person in persons:
    insert_recorded_person(conn, record_id, person)  # One INSERT per person
```

**Optimized pattern:**
```python
# Batch INSERT with VALUES clause
cur.execute("""
    INSERT INTO recorded_person (record_id, name_as_recorded, role, age, ...)
    VALUES (%s, %s, %s, %s, ...),
           (%s, %s, %s, %s, ...),
           ...
""", flattened_values)
```

**Estimated Impact:** 20-30% reduction in ingestion time
- **Savings: ~17-26s**

**Implementation complexity:** Medium - requires refactoring `census.py` ingest loop

---

### 2. Event Resolution (28.29s - 16.8%)

**Current Behavior:**
- Pass 1: Census events (one per record)
- Pass 2: Birth events (calculated from ages)
- Pass 3: Marriage events (from couple relationships)

**Issues:**
- Likely creating events one at a time
- Multiple passes over the same data

**Optimization Opportunities:**

#### A. Batch Event Creation (Medium Impact)
Collect all events for a pass, then bulk insert.

**Estimated Impact:** 25-30% reduction
- **Savings: ~7-8.5s**

#### B. Single-Pass Event Generation (Low-Medium Impact)
Create census + birth event candidates in one pass per record.

**Estimated Impact:** 10-15% reduction
- **Savings: ~3-4s**

---

### 3. Relationship Resolution (24.58s - 14.6%)

**Current Behavior:**
- Match households across census pairs
- Create Person conclusions for matched pairs
- Create Relationship conclusions from household roles

**Issues:**
- Complex nested loops over households
- Many small database queries per match
- No batching apparent

**Optimization Opportunities:**

#### A. Prefetch Household Data (Medium Impact)
Load all household members for all candidate matches upfront instead of querying per match.

**Estimated Impact:** 20-25% reduction
- **Savings: ~5-6s**

#### B. Batch Relationship Creation (Medium Impact)
Accumulate all relationships, insert in batches.

**Estimated Impact:** 15-20% reduction
- **Savings: ~3.7-5s**

---

### 4. Splink Similarity (20.47s combined - 12.1%)

**Current Behavior:**
- Record similarity: 11.68s
- Person similarity: 8.79s
- Batch constants set to `None` (unbatched)

**From constants.py:**
```python
BATCH_SIZE_RECORD_SIMILARITY: int | None = None  # Unbatched
BATCH_SIZE_PERSON_SIMILARITY: int | None = None  # Unbatched
```

**Documentation:**
> "Maximum pairs to commit per transaction within a source-pair run.  
> None = unbatched (commit all pairs for a source-pair in one transaction).  
> Set to an integer (e.g. 5000) for large datasets to reduce transaction size."

**Optimization Opportunities:**

#### A. Enable Batching (Medium Impact)
Current: All pairs inserted in single transaction per source-pair (could be 10K+ pairs).

**Recommended:**
```python
BATCH_SIZE_RECORD_SIMILARITY: int | None = 5000
BATCH_SIZE_PERSON_SIMILARITY: int | None = 5000
```

**Estimated Impact:** 10-15% reduction in Splink time
- **Savings: ~2-3s**

**Trade-off:** Smaller transactions = less memory but slightly more overhead. At Tullynaught scale (small), benefit is marginal. At Donegal scale (168K records), this becomes critical.

#### B. Splink Configuration Tuning (Low Impact)
Review Splink `estimate_u` and EM iteration settings - may be over-training for small dataset.

**Estimated Impact:** 5-10% reduction
- **Savings: ~1-2s**

---

## Recommended Optimization Priority

### Phase 1: Quick Wins (Low effort, high impact)

1. **Enable batch constants** (5 minutes)
   ```python
   BATCH_SIZE_RECORD_SIMILARITY = 5000
   BATCH_SIZE_PERSON_SIMILARITY = 5000
   ```
   - **Effort:** Trivial (change 2 constants)
   - **Impact:** 2-3s savings now, critical at scale
   - **Risk:** None

2. **Add parallel census ingestion** (2-4 hours)
   - **Effort:** Medium (need connection pool, error handling)
   - **Impact:** ~52s savings (31% total runtime)
   - **Risk:** Low (sources are independent)

### Phase 2: Batching Improvements (Medium effort, medium-high impact)

3. **Bulk insert for records/persons** (4-8 hours)
   - **Effort:** Medium-High (refactor `census.py` ingestion)
   - **Impact:** 17-26s savings
   - **Risk:** Medium (need careful transaction handling)

4. **Batch event creation** (2-4 hours)
   - **Effort:** Medium
   - **Impact:** 7-8.5s savings
   - **Risk:** Low

5. **Batch relationship creation** (2-3 hours)
   - **Effort:** Medium
   - **Impact:** 3.7-5s savings
   - **Risk:** Low

### Phase 3: Algorithmic Improvements (Higher effort, medium impact)

6. **Prefetch household data in relationship resolution** (4-6 hours)
   - **Effort:** Medium-High
   - **Impact:** 5-6s savings
   - **Risk:** Medium (careful caching needed)

7. **Single-pass event generation** (6-8 hours)
   - **Effort:** High (redesign event resolution logic)
   - **Impact:** 3-4s savings
   - **Risk:** Medium

---

## Projected Performance After Optimizations

| Optimization | Current | After | Savings | Effort |
|--------------|---------|-------|---------|--------|
| **Baseline** | 169.30s | - | - | - |
| + Enable batching | 169.30s | 167s | 2.3s | 5 min |
| + Parallel ingestion | 167s | 114s | 53s | 4h |
| + Bulk inserts | 114s | 92s | 22s | 6h |
| + Batch events | 92s | 84s | 8s | 3h |
| + Batch relationships | 84s | 80s | 4s | 2.5h |
| + Prefetch households | 80s | 75s | 5s | 5h |
| **Total (all)** | 169.30s | **75s** | **94s (56%)** | **20.5h** |

---

## Scalability Considerations

**Tullynaught dataset:** 715 records, 3,167 persons (current test)  
**Donegal county (target):** ~168K records, ~800K persons (**235× scale**)

### Linear Scaling Projection (no optimizations)

| Stage | Tullynaught | Donegal (235×) |
|-------|-------------|----------------|
| Ingestion | 85.60s | **5.6 hours** |
| Event resolution | 28.29s | 1.8 hours |
| Relationship resolution | 24.58s | 1.6 hours |
| Splink | 20.47s | 1.3 hours |
| **Total** | 169s (2.8 min) | **~10.5 hours** |

### With Optimizations

| Stage | Optimized Tullynaught | Optimized Donegal |
|-------|----------------------|-------------------|
| Ingestion (parallel + bulk) | 31s | **2.0 hours** |
| Event resolution (batched) | 20s | 1.3 hours |
| Relationship resolution (batched) | 16s | 1.0 hours |
| Splink (batched) | 17s | 1.1 hours |
| **Total** | 84s (1.4 min) | **~5.4 hours** |

**Scalability verdict:**
- Current implementation: Donegal would take 10-11 hours
- With optimizations: Donegal would take 5-6 hours
- Batching becomes **critical** at scale (prevents transaction size issues)

---

## Additional Optimization Ideas

### Database-Level

1. **Connection pooling** - Reuse connections instead of creating per operation
2. **COPY command for bulk loads** - PostgreSQL COPY is faster than INSERT VALUES
3. **Deferred constraints** - Defer FK checks until COMMIT for bulk operations
4. **Index optimization** - Ensure proper indexes for JOIN-heavy operations

### Application-Level

5. **Streaming CSV parsing** - Don't load entire CSV into memory
6. **Generator patterns** - Yield records instead of building full lists
7. **Profiling** - Use `cProfile` to identify unexpected hotspots

### Architecture

8. **Split evidence/conclusion** - Run evidence layer once, iterate on conclusion without re-ingesting
9. **Incremental updates** - Process only new records, not full re-run
10. **Caching** - Cache Splink models, place authority lookups

---

## Immediate Action Items

**For next session:**

1. ✅ Set batch constants to 5000 (trivial, safe)
2. 📋 Profile current run with `cProfile` to confirm assumptions
3. 📋 Implement parallel census ingestion (highest ROI)
4. 📋 Refactor to bulk inserts for records/persons

**For Donegal scale-up:**

1. 📋 All Phase 1 & 2 optimizations completed
2. 📋 Load testing with 10K-record subset
3. 📋 Monitor transaction sizes and memory usage
4. 📋 Consider incremental processing strategy

---

## References

- Test run log: `tests/logs/test_run_20260623_000513.log`
- Constants file: `src/constants.py` lines 98, 107
- Similarity code: `src/evidence/similarity.py`
- Census ingestion: `src/evidence/census.py`
- Reconstruction algorithms: `docs/reconstruction_algorithms.md`
