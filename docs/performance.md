# Performance Optimization Guide

## Overview

This document describes the performance optimizations implemented in the GRA pipeline and provides guidance for scaling to larger datasets.

## Current Performance (June 2026)

### Tullynaught Test Dataset
- **Records:** 715 (across 3 census sources: 1901, 1911, 1926)
- **Persons:** 3,167
- **Pipeline time:** 138.95s (2 min 19 sec)
- **Test execution:** 0.65s
- **All 59 tests passing**

### Baseline vs Optimized

| Stage | Baseline | Optimized | Improvement |
|-------|----------|-----------|-------------|
| Census ingestion (3 sources) | 87.99s | 54.54s | **-33.45s (38%)** |
| Event resolution | 38.33s | 8.02s | **-30.31s (79%)** |
| Relationship resolution | 24.76s | 24.52s | -0.24s (1%) |
| Record similarity (Splink) | 11.33s | 25.47s | +14.14s† |
| Person similarity (Splink) | 8.48s | 13.49s | +5.01s† |
| **Total setup** | **184.28s** | **138.30s** | **-45.98s (25%)** |

† *Splink times increased due to batching overhead at small scale, but batching prevents memory issues at large scale*

## Optimization Strategies

### 1. Bulk Census Ingestion

**Implementation:** `src/evidence/census.py`, `src/dal/record_repo.py`

**Pattern:**
```python
# Before: Per-row inserts
for household in households:
    insert_record(conn, ...)  # 1 SQL per record
    for person in household:
        insert_recorded_person(conn, ...)  # 1 SQL per person

# After: Bulk inserts
records_to_insert = []
persons_to_insert = []
for household in households:
    records_to_insert.append({...})
    for person in household:
        persons_to_insert.append({...})

bulk_insert_records(conn, records_to_insert)  # 1 SQL for all records
bulk_insert_recorded_persons(conn, persons_to_insert)  # 1 SQL for all persons
```

**Impact:** 38% faster census ingestion (87.99s → 54.54s)

**Savings:**
- Tullynaught: 33.45s
- Donegal projection: 2.2 hours

### 2. Batch Event Creation

**Implementation:** `src/conclusion/event_resolution.py`

**Pattern:**
```python
# Before: Per-event inserts
for record in records:
    event_id = _create_event(conn, ...)
    _link_event_to_person(conn, event_id, person_id)
    _link_event_to_record(conn, event_id, record_id)

# After: Batch creation
events_to_create = []
for record in records:
    events_to_create.append({...})

event_ids = _bulk_create_events(conn, events_to_create)
_bulk_link_events_to_persons(conn, person_event_links)
_bulk_link_events_to_records(conn, event_record_links)
```

**Impact:** 79% faster event resolution (38.33s → 8.02s)

**Savings:**
- Tullynaught: 30.31s
- Donegal projection: 2.0 hours

### 3. Splink Batching

**Implementation:** `src/constants.py`

**Configuration:**
```python
# Before:
BATCH_SIZE_RECORD_SIMILARITY: int | None = None  # All pairs in one transaction

# After:
BATCH_SIZE_RECORD_SIMILARITY: int | None = 5000  # Batch commits every 5000 pairs
BATCH_SIZE_PERSON_SIMILARITY: int | None = 5000
```

**Impact:** 
- Small datasets: Slight overhead (+19.15s at Tullynaught scale)
- Large datasets: **Critical** - prevents memory exhaustion with 10K+ pairs

**Why batching is essential at scale:**
- Tullynaught: 3 source pairs, small overhead acceptable
- Donegal: Potentially 10K+ pairs per source-pair
- Unbatched: Single transaction could require GB of memory
- Batched: Predictable memory usage, stable performance

## Scaling Projections

### Donegal County (Target Scale)
- **Records:** ~168,000 (235× Tullynaught)
- **Persons:** ~800,000 (253× Tullynaught)

| Stage | Baseline | Optimized | Savings |
|-------|----------|-----------|---------|
| Census ingestion | 5.8 hours | 3.6 hours | 2.2 hours |
| Event resolution | 2.5 hours | 0.5 hours | 2.0 hours |
| Relationship resolution | 1.6 hours | 1.6 hours | - |
| Splink similarity | 1.3 hours | 1.1 hours | 0.2 hours |
| **Total** | **~11 hours** | **~7.2 hours** | **~3.8 hours (35%)** |

## Performance Best Practices

### For Production Use

1. **Enable Splink batching** before processing large datasets (>10K records)
2. **Monitor transaction sizes** during ingestion
3. **Use bulk operations** for any repetitive inserts
4. **Profile before optimizing** - use the test suite timing output

### For Development

1. **Run tests with timing** to catch performance regressions:
   ```bash
   python3 tests/test_pipeline.py
   ```

2. **Check setup timings** in test output:
   ```
   SETUP TIMINGS
   --------------------------------------------------
   ingest + role_rels source 3                 21.15s
   event resolution                             8.02s
   ...
   ```

3. **Compare against baseline:** `docs/performance.md` (this file)

### For Large Datasets

When processing datasets larger than Donegal (>200K records):

1. **Consider incremental processing:**
   - Process one source at a time
   - Use `clear-conclusions` to re-run conclusion layer only
   - Avoid re-ingesting evidence if possible

2. **Monitor memory usage:**
   ```bash
   time python3 -m src.cli ingest --source 3 --file data.csv
   ```

3. **Adjust batch sizes if needed:**
   - Increase for very large datasets (e.g., 10000)
   - Decrease if memory constrained (e.g., 1000)

4. **Use connection pooling** for concurrent operations (future optimization)

## Implementation Details

### Bulk Insert Functions

**Location:** `src/dal/record_repo.py`

```python
def bulk_insert_records(conn, records: list[dict]) -> None:
    """Bulk insert multiple Records in one statement."""
    
def bulk_insert_recorded_persons(conn, persons: list[dict]) -> None:
    """Bulk insert multiple RecordedPersons in one statement."""
```

**SQL Pattern:**
```sql
INSERT INTO record (record_id, source_id, ...)
VALUES (%s, %s, ...), (%s, %s, ...), ...
```

**Advantages:**
- Single round-trip to database
- PostgreSQL query planner optimizes bulk operations
- Transaction overhead paid once, not per row
- Maintains ACID properties

### Batch Event Creation Functions

**Location:** `src/conclusion/event_resolution.py`

```python
def _bulk_create_events(conn, events: list[dict]) -> list[int]:
    """Bulk create Events and return list of generated event_ids."""
    
def _bulk_link_events_to_persons(conn, links: list[tuple[int, int]]) -> None:
    """Bulk insert person_event links. Expects (person_id, event_id) tuples."""
    
def _bulk_link_events_to_records(conn, links: list[tuple[int, int]]) -> None:
    """Bulk insert event_record links. Expects (event_id, record_id) tuples."""
```

**Algorithm:**
1. Collect all event specifications during processing
2. Bulk create events with RETURNING clause to get generated IDs
3. Build link tuples using returned IDs
4. Bulk insert all links

**Transaction Handling:**
- All bulk operations within `with conn:` blocks
- Rollback on error preserves consistency
- No partial commits within a batch

## Performance Testing

### Running the Test Suite

```bash
# Full pipeline test with timing
python3 tests/test_pipeline.py

# Check log file for detailed timings
cat tests/logs/test_run_*.log | tail -20
```

### Interpreting Results

**Setup timings:**
- **< 150s total:** Optimizations working correctly
- **> 200s total:** Performance regression, investigate

**Per-stage targets (Tullynaught scale):**
- Census ingestion (3 sources): ~55s
- Event resolution: ~8s
- Relationship resolution: ~25s
- Record similarity: ~25s (batched) or ~11s (unbatched)
- Person similarity: ~13s (batched) or ~8s (unbatched)

**Test execution:**
- Should remain < 1s
- Tests verify data correctness, not performance

## Future Optimizations

### Not Yet Implemented

1. **Relationship resolution batching** (14.6% of setup time)
   - Complex due to conditional logic and state dependencies
   - Potential savings: 5-10s

2. **Connection pooling** for concurrent operations
   - Would enable parallel source ingestion
   - Test suite only, not production (sources ingested separately)

3. **COPY command** for largest bulk loads
   - PostgreSQL COPY faster than INSERT VALUES for 100K+ rows
   - Requires CSV/binary format generation

4. **Incremental processing**
   - Process only new/changed records
   - Requires change detection mechanism

5. **Caching**
   - Cache Splink models between runs
   - Cache place authority lookups

## Troubleshooting

### Slow Ingestion

**Symptoms:** Census ingestion > 30s per source

**Causes:**
- Using old per-row insert code
- Network latency (remote database)
- Database locks or contention

**Solutions:**
- Verify bulk insert functions are being used
- Check database connection parameters
- Ensure no concurrent writes to same tables

### Memory Issues

**Symptoms:** Process killed, out of memory errors

**Causes:**
- Splink unbatched with large datasets
- Loading entire CSV into memory
- Too many in-flight bulk operations

**Solutions:**
- Enable Splink batching: `BATCH_SIZE_*_SIMILARITY = 5000`
- Reduce batch sizes for constrained environments
- Process sources one at a time

### Slow Event Resolution

**Symptoms:** Event resolution > 15s

**Causes:**
- Using old per-event insert code
- Foreign key violations (data corruption)
- Missing indexes

**Solutions:**
- Verify bulk event creation is being used
- Check for data integrity issues
- Ensure database schema is up to date

## Version History

### v3.2 (June 2026) - Performance Optimizations
- Implemented bulk census ingestion (38% faster)
- Implemented batch event creation (79% faster)
- Enabled Splink batching for large-scale processing
- Overall pipeline: 25% faster (184.88s → 138.95s)

### v3.1 (June 2026) - Baseline
- Initial performance measurements
- Identified optimization opportunities
- No bulk operations

## References

- Test results: `tests/logs/test_run_*.log`
- Performance analysis: `PERFORMANCE_ANALYSIS.md`
- Reconstruction algorithms: `docs/reconstruction_algorithms.md`
- Database schema: `docs/database_schema.md`
