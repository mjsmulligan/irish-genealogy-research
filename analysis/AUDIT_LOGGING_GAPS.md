# Audit Logging Gaps in Conclusion Pipeline

## Executive Summary

Only **Step 1 (Person Resolution)** has audit logging implemented. Steps 2-5 create entities without logging, leaving a critical audit trail gap that explains why Person #128517 has no audit history despite existing in the database.

## Pipeline Coverage

| Step | Name | Entities Created | Logging Status | Impact |
|------|------|------------------|----------------|--------|
| 1 | Person Resolution | Person, person_recorded_person | ✓ **LOGGED** | High-threshold similarities only |
| 2 | Relationship Resolution | Person, Relationship, relationship_recorded_relationship | ✗ **MISSING** | **Person #128517 unlogged** |
| 3 | Household Resolution | Person, Relationship | ✗ **MISSING** | Anchor-extension persons unlogged |
| 4 | Event Resolution | Event, person_event, event_record | ✗ **MISSING** | All census/birth/marriage events unlogged |
| 5 | Validation Cleanup | (deletions) | ✗ **MISSING** | Constraint violations unlogged |

## Unlogged Entities

### Step 2: Relationship Resolution
- **Person** — Created via `_get_or_create_person_for_pair()` when household-based matching yields new pairings
  - File: `src/conclusion/relationship_resolution.py:242`
  - Missing reason: Relationship-based matching (household context)
  
- **Relationship** — Created via `ensure_relationship()` for couple/parent-child/sibling links
  - File: `src/conclusion/household_utils.py:103`
  - Missing reason: Derived from household role structure

- **relationship_recorded_relationship** — Linkage provenance for relationships

### Step 3: Household Resolution  
- **Person** — Created via `_create_person_for_recorded_person()` for unlinked household members
  - File: `src/conclusion/household_resolution.py:138`
  - Missing reason: Anchor-extension for household completeness
  
- **Relationship** — Created in `create_relationships_from_household()` for members of same household
  - File: `src/conclusion/household_utils.py:146`

### Step 4: Event Resolution
- **Event** — Created via `_create_event()` for census, birth, marriage events
  - Files: `src/conclusion/event_resolution.py:76, 133`
  - Missing reason: Evidence-derived census/birth/marriage conclusions

- **person_event** — Links Event to Person
- **event_record** — Links Event to source Record (provenance)

### Step 5: Validation Cleanup
- **Relationship** (deletions) — Removed linkages failing genealogical constraints
  - File: `src/conclusion/validation_cleanup.py`
  - Missing reason: Constraint violations (age conflicts, gender mismatches, etc.)

## Discovery Evidence

**Person #128517 (Eliza Farrell, raneany west):**
- Exists in `person` table
- Linked to recorded_person 20399 (1901 census)
- **Has 0 audit log entries**
- Audit logs go up to person_id 127757
- Person #128517 > 127757 → Created after initial person resolution batch
- Conclusion: Created in Relationship Resolution (Step 2) without logging

## Recommended Fix Priority

### Phase 1: Critical (restore audit trail)
1. Add logging to Relationship Resolution (`relationship_resolution.py`)
   - Log Person creation in `_get_or_create_person_for_pair()`
   - Log Relationship creation in `ensure_relationship()`
   
2. Add logging to Household Resolution (`household_resolution.py`)
   - Log Person creation in `_create_person_for_recorded_person()`
   - Log Relationship creation in `create_relationships_from_household()`

### Phase 2: Important (complete audit record)
3. Add logging to Event Resolution (`event_resolution.py`)
   - Log Event creation with source record reference
   - Log person_event linkages

4. Add logging to Validation Cleanup (`validation_cleanup.py`)
   - Log Relationship deletions with constraint violation reason

### Phase 3: Enhancement (audit infrastructure)
5. Standardize logging pattern across all steps
   - Use consistent change_group_id generation
   - Document "reason" strings for each entity type
   - Consider async logging if performance impacts

## Implementation Notes

- Each step should pass a `run_change_group_id` (or generate a new one per logical operation)
- Logging calls follow pattern: `AuditLog.log_create(repo, entity_type, entity_id, values, reason, change_group_id)`
- Deletions use: `AuditLog.log_delete(repo, entity_type, entity_id, reason, change_group_id)`
- Link entity "reason" should indicate linkage type: "Linked via ...", "Derived from ...", etc.

## Testing

- Re-run conclusion pipeline on test data
- Verify Person #128517 (or equivalent) now has audit entries
- Check all entity types appear in audit log with appropriate reasons
- Verify change_group_id grouping is logical

## Related Issues

- Orphaned audit entries when clearing conclusions (now fixed in cli.py)
- No deletion logging for removed entities
- No update logging for modified field values (only create events logged)
