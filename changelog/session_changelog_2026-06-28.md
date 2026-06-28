# GRA — Session Changelog: 28 June 2026

## Household Resolution — New Conclusion Pipeline Step

### Context

Running the conclusion pipeline against Tullynaught data and reviewing the output reports revealed a systematic gap: Persons were only created when a RecordedPerson could be matched across two or more census years. RecordedPersons appearing in a single census, or whose households did not achieve the similarity threshold for relationship_resolution, were never promoted to conclusions. This left valid family structures — particularly households where some members linked cross-census and others did not — partially resolved, with siblings, spouses, and children treated as isolated records.

The validation reports surfaced this concretely: households with a resolved head or parent but unlinked children, and households where one child linked but siblings did not.

---

### Design Decisions

**Anchor principle.** If at least one RecordedPerson in a household has been promoted to a Person (by either person_resolution or relationship_resolution), that Person acts as an anchor. Any unlinked RecordedPerson connected to the anchor via a RecordedRelationship is eligible for Person creation.

**RecordedRelationship required.** Co-presence in a household alone is not sufficient justification. A RecordedRelationship path to the anchor — created at ingest time by `role_relationships.py` — is required. This excludes visitors, boarders, and other non-family roles that `role_relationships.py` does not produce RecordedRelationship rows for. This is the correct line.

**Single-census only.** The new step operates within a single census. Cross-census anchoring is already handled by relationship_resolution.

**Score inheritance.** The person_recorded_person linkage score is inherited from the RecordedRelationship's prior score (0.75–0.90 depending on role pair), reflecting the strength of the ingest-time evidence. Falls back to 0.75 if score is null.

**Cases enumerated:**
- Case A: Anchor is head — creates Persons for unlinked spouse and children.
- Case B: Anchor is a child — creates Person for unlinked head (and spouse if connected).
- Case C: Anchor is spouse — creates Person for unlinked head.
- Case D: Multiple anchors — each unlinked member created once; newly created Persons are added to the anchor set within the same record loop, enabling sibling-to-sibling extension.

**Naming.** `household_resolution` chosen over `household_extension` for consistency with the pipeline naming convention (person_resolution, relationship_resolution, event_resolution).

---

### Files Changed

#### New: `src/conclusion/household_utils.py`

Shared household helpers extracted from `relationship_resolution.py` and moved here to avoid duplication between the two modules that need them.

Functions:
- `get_household_members(conn, record_id)` — fetches RecordedPersons with Person linkage for a Record, ordered by role then age desc.
- `ensure_relationship(conn, person_id_1, person_id_2, rel_type)` — idempotently creates a Relationship conclusion and populates `relationship_recorded_relationship` provenance from ingest-time RecordedRelationship rows. Returns relationship_id if newly created, None if already existed.
- `create_relationships_from_household(conn, household_members)` — derives couple, parent_child, and sibling Relationship conclusions from the roles of members who have Persons. Returns count created.

#### New: `src/conclusion/household_resolution.py`

New conclusion pipeline step [3/5].

Entry point: `run_household_resolution(conn) -> HouseholdResolutionResult`

Algorithm:
1. Query for Records that have at least one anchored RecordedPerson and at least one unlinked RecordedPerson (two EXISTS subqueries).
2. For each candidate Record, find unlinked members and check for a RecordedRelationship connecting them to any anchor.
3. Create a Person for each eligible unlinked member; inherit the RecordedRelationship prior score; add new Person to the anchor set for the current record (enables Case D sibling extension).
4. After all Person creation for a Record, re-fetch household members and call `create_relationships_from_household`.

`HouseholdResolutionResult` dataclass tracks: records_examined, persons_created, linkages_created, relationships_created, skipped_no_anchor, skipped_no_rr.

Score version: `SCORE_VERSION_HOUSEHOLD_EXTENSION = "household_extension_v1.0"`.

#### Modified: `src/conclusion/relationship_resolution.py`

- Module docstring updated to reference `household_utils.py` as the new home for shared helpers.
- `_get_household_members`, `_ensure_relationship`, `_create_relationships_from_household` removed.
- All three now imported from `src.conclusion.household_utils` (public names, no leading underscore).
- All internal call sites updated to use the public names.
- Unused imports `Optional` and `defaultdict` removed.

#### Modified: `src/constants.py`

Added:
```python
SCORE_VERSION_HOUSEHOLD_EXTENSION: str = "household_extension_v1.0"
```

#### Modified: `src/cli.py`

- Conclude pipeline docstring updated: 4 steps → 5 steps, step labels updated.
- Top-level usage docstring updated: "3 steps" → "5 steps".
- `household_resolution` imported and called as new step [3/5].
- Step counters updated throughout: `[1/4]`–`[4/4]` → `[1/5]`–`[5/5]`.
- Help text for `conclude` subcommand updated from `[1/3–3/3]` to `[1/5–5/5]`.
- `pipeline_run` logging added for `run_household_resolution`.

---

### Work Queue

- **Item 40** added: Test harness coverage for `household_resolution.py` and `household_utils.py`. Five test cases specified. Step-counter assertions to be updated from [4/4] to [5/5].
- **Item 41** added: Household contradiction validation (review layer finding). Flag Relationship conclusions contradicted by intra-census household evidence. Warning-level at v1; auto-action deferred. Blocked on item 40.

---

### Not Changed

- Schema: no migration required. No new tables or columns. The new step writes to existing `person`, `person_recorded_person`, `relationship`, and `relationship_recorded_relationship` tables.
- DAL: no new repo functions required. `create_person` and `link_person_to_recorded_person` from `person_repo.py` reused as-is.
- `ROADMAP.md`: items 40 and 41 added. No items closed this session (memory update + changelog admin only, no pre-existing items completed).
