# BMD (Birth/Marriage/Death) Integration — Exploratory Design Plan

*Created: July 2026 — Exploratory session on cross-townland person linking via civil registration records*

**Objective:** Design how civil registration (BMD) records can enhance person linkage across townlands when census data alone cannot bridge the gap. Test case: John McCadden + Mary Logue marriage 1909 → enables their cross-townland linking.

**Scope:** Three sequential areas of design:
1. Schema design: How to store BMD records and link to persons
2. Linkage logic: How to use marriage records to auto-link persons
3. Data ingestion: Format and workflow for adding BMD records

---

## 1. SCHEMA DESIGN

### Current State

**Evidence layer** (`record` + `recorded_person`):
- Already handles BMD sources: source types include 'marriage_registration', 'birth_registration', 'death_registration'
- Record table has event_type: 'marriage', 'birth', 'death' already in CHECK constraint
- Recorded person roles include: 'groom', 'bride', 'father_of_groom', 'father_of_bride', 'witness', 'informant', 'officiator', 'principal', 'deceased'

**Conclusion layer** (event + relationship):
- Event.type already supports: 'marriage', 'birth', 'death'
- Relationship.type includes 'couple' (marriage), 'parent_child' (birth)
- event_record junction: Event links to Record with score, score_version

**Design principle (already established):**
- Census shows couple together → marriage Event with date=NULL (calculated)
- BMD record with actual date → separate Event with date='YYYY-MM-DD', date_qualifier='exact'
- Both coexist; no overwriting. Multiple events per person/type allowed.

### What's Missing

**Evidence layer linkage for marriage BMD → persons:**

The current schema works for ingest but lacks explicit recorded_relationship capture for BMD couples. 

**Current role-pair logic** (in evidence/role_relationships.py):
- Reads recorded_person.role field from census records
- Pairs: head+spouse → couple, head+son → parent_child, etc.
- Creates recorded_relationship rows with type and score ~0.75–0.90

**For marriage BMD, we need:**
- Groom + Bride → recorded_relationship type='couple' 
- Same flow, different source (civil record vs. census)
- Score: very high (~0.95+) because civil record is definitive

**Proposal: No schema changes required.**

The schema already supports this pattern. What's needed:
1. Extend role_relationships.py to handle BMD role pairs (groom+bride, father_of_groom+groom, etc.)
2. Ingest creates recorded_relationship entries with high confidence
3. Event resolution creates marriage Events from these relationships
4. Linkage logic (new) uses marriage BMD evidence to bridge cross-townland gaps

---

## 2. LINKAGE LOGIC: How BMD Evidence Enables Cross-Townland Linking

### Problem (Item 49 / John + Mary case)

Two separate persons in 1901 Census:
- Person 331863: RP 25110 (John McCadden, son, Aghlem place_id=2)
- Person 332148: RP 25657 (Mary Logue, daughter, Townlough place_id=16)

Census-only linking is blocked by:
1. place_id boundary (prevents false positives for cousins)
2. Surname change (Logue → McCadden) not in variants dictionary

Both move together to place_id=15 (Meenadreen) in 1911, but system never links them.

### Solution: Confidence-Scored BMD Person Linking

**Marriage record provides:**
- Definitive proof of surname change (Logue → McCadden)
- Definitive pairing (couple relationship)
- Bridge across place_id boundary (and surname change)

**New pipeline stage: `link_persons_via_bmd(repo)` with confidence scoring**

```
1. Find all couple Relationships with recorded_relationship_id pointing to:
   - BMD-sourced recorded_relationships (detect via source_id from record)
   - Non-BMD recorded_relationships with score >= 0.95 (high confidence)

2. For each such couple relationship:
   a. Get the two Persons (person_id_1, person_id_2)
   b. Score merge confidence:
      - Base: 0.95 (BMD couples are authoritative)
      - Check: Census birth-year compatibility across linked recorded_persons
        - If years differ by ≤2 years: confidence *= 1.0 (acceptable)
        - If years differ by >2 years: confidence *= 0.5 (flag as conflict)
      - Check: Multiple censuses show them together (1911, 1926?)
        - If yes: confidence *= 1.05 (strengthens case)
        - If no: confidence stays at base or conflict level

   c. If confidence > 0.85:
      → Merge the persons (keep primary, move all recorded_person linkages)
      → Log: "BMD marriage (date X, source Y) bridges persons P1 and P2; confidence: Z%"
   
   d. If confidence <= 0.85:
      → Flag for researcher review: "Potential merge (BMD): P1 + P2, confidence Z%"
      → Create audit_log entry with action='flag'

3. Continue pipeline — household continuity now sees consolidated person(s)
```

**Design choice: When to run?**

**Recommended: As new BMD-specific pass in pipeline (Option B)**
- New CLI command: `add-bmd-evidence` (parallel to `add-evidence`)
- Ingests marriage/birth/death records
- Creates recorded_person + recorded_relationship + place_record
- Runs `link_persons_via_bmd()` at end of add-bmd-evidence, before conclude begins

**Rationale:**
- All BMD evidence loaded before any conclusions
- Exploratory: lets us see linkage confidence scores and flags
- Follows additive principle: BMD doesn't overwrite census conclusions, enhances them

---

## 3. DATA INGESTION: Workflow for Adding BMD Records

### CSV Schema: Single Record per Marriage + Multiple RecordedPersons

**Pattern:** Follow census model — one Record captures the event, RecordedPersons capture all named individuals.

**For marriage, that's:** Groom, Bride, Father of Groom, Father of Bride (+ optional witnesses as structured rows if present).

**Header row:**

```
record_id,source_type,event_type,date,date_qualifier,place_as_recorded,
recorded_person_id,name_as_recorded,role,age_as_recorded,occupation_as_recorded,address_as_recorded,
civil_status_as_recorded,notes
```

**Example: John + Mary 1909 marriage**

```
,marriage_registration,marriage,1909-12-30,exact,Donegal,
,John Mccadden,groom,full,Farmer,Aughlin,
,Mary Logue,bride,full,,Townlough,
,Patrick Mccadden,father_of_groom,,Farmer,,
,Thomas Logue,father_of_bride,,Farmer,,
,James Mcshane,officiator,,,Donegal,
,Andrew Mccadden,witness,,,Aughlin,
,Ellie Jos. Gallagher,witness,,,Donegal,
```

**Key design choices:**

1. **One Record per marriage** (not one per person)
   - Matches census model (one Record per household/enumeration)
   - Role field distinguishes groom, bride, witness, etc.
   - All recorded_persons link back to same Record

2. **Witnesses as separate rows**
   - Follows census model (all household members are rows)
   - Enables searching/linking on witness names
   - Natural for future genealogical work (witness as relative indicator)

3. **CSV ingest workflow**
   - CLI: `python -m src.cli add-bmd-evidence --source civil-marriage-registrations --file marriages.csv`
   - Parser: `src/evidence/bmd.py` (new module)
   - Flow mirrors census ingest: validate → record + recorded_person rows → role-pair recorded_relationships → place resolution

---

## Implementation Phases (Ordering)

### Phase 1: Schema Verification (read-only)
- ✅ Confirm record/recorded_person already support BMD event types
- ✅ Confirm recorded_relationship vocabulary includes 'couple', 'parent_child'
- ✅ Understand current event_resolution.py marriage event creation (lines 373–428)

**Deliverable:** Documented confirmation that schema needs no changes

### Phase 2: CSV Ingestion Template + Parser
- Create CSV schema specification document
- Build bmd.py parser (leverage existing record/recorded_person creation patterns)
- Integrate with role_relationships.py for BMD role pairs (groom+bride, father_of_groom+groom, etc.)
- New CLI command: `add-bmd-evidence`

**Deliverable:** Working `add-bmd-evidence` command that ingests marriage records

### Phase 3: Confidence-Scored BMD → Person Linkage Logic
- Implement `link_persons_via_bmd(repo)` with confidence scoring
- Score merge candidates based on: BMD authoritativeness, birth-year compatibility, co-appearance in other censuses
- Wire into conclude pipeline (call after relationship_resolution, before household_continuity)
- Log merge decisions and flags to audit_log

**Deliverable:** Person merging triggered by BMD evidence with confidence scoring

### Phase 4: Validation & Iteration (John + Mary test case)
- Run full pipeline: ingest 1901 census → 1911 census → marriage BMD record
- Verify John (331863) + Mary (332148) merge to single Person with confidence > 0.85
- Verify merged Person appears in 1901 (Aghlem + Townlough) + 1911 (Meenadreen) + 1926
- Check audit log and confidence scores
- Document in roadmap

**Deliverable:** Test case passes; roadmap updated

### Phase 5: Birth Registration Support (next focus)
- Extend BMD parser to handle birth records
- Schema: Infant, Father, Mother roles (parallels parent_child logic)
- Test: Link John + Mary's children to parents via birth records
- Validates parent_child linkage across different record types

**Deliverable:** Birth records working; pipeline tested with family unit

---

## Key Implementation Files

| File | Task |
|------|------|
| `src/evidence/bmd.py` (new) | CSV parser, place resolution, recorded_person/relationship creation for BMD |
| `src/cli.py` | New `add-bmd-evidence` command; integrate link_persons_via_bmd into conclude pipeline |
| `src/evidence/role_relationships.py` | Extend to create BMD couple/parent_child pairs from groom/bride/father roles |
| `src/conclusion/relationship_resolution.py` | Add `link_persons_via_bmd()` function with confidence scoring |
| `src/dal/person_repo.py` | Leverage existing merge_persons() function; ensure audit logging |
| `docs/data_dictionary.md` (update) | Document CSV schema and ingestion process |

---

## Testing Strategy

1. **Unit tests:** CSV parser, place resolution, confidence scoring
2. **Integration test:** Full pipeline with John + Mary marriage record
3. **Validation:** After conclude, verify:
   - One Person linked to RPs from 1901 (Aghlem + Townlough) and 1911/1926 (Meenadreen)
   - Household continuity sees single head across all censuses
   - Age progression coherent (18 in 1901 → 30 in 1911 → 46 in 1926)
   - Marriage relationship exists with spouse names normalized
   - Audit log shows: person merge with confidence score, source trace to BMD record

---

## Out of Scope (Phase 2+)

- Web UI for manual BMD entry (future)
- Automated OCR/transcription from images
- Cross-referencing BMD with existing persons (probabilistic matching for pre-merge disambiguation)
- Death event creation (marriages + births first)
- Complex family structures (remarriages, multiple witnesses with genealogical significance)

---

## Key Design Principles Applied

1. **Additive design:** BMD doesn't overwrite census conclusions; adds new evidence chains
2. **High-confidence sources:** Civil registration is authoritative; use confidence scoring to flag uncertain merges
3. **Pattern reuse:** Mirror census ingest workflow (record + recorded_persons + role pairs)
4. **Audit trail:** All merges logged with confidence scores and source traces
5. **No schema changes:** Existing BMD support in record/recorded_person/event already present
