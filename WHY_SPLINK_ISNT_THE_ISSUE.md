# Why Splink Isn't The Issue: The Real Problem is Clustering

**Question**: Why does Splink generate scores for records within the same census?

**Answer**: It doesn't. Splink is correctly configured and working as intended.

---

## The Real Problem: Transitive Clustering Through False Bridge Links

The Connell Harvey merge error wasn't caused by Splink generating within-census pairs. It was caused by **person resolution clustering creating a transitive merge** through an intermediate record.

### What Actually Happened

**Splink generated these cross-census links (all correct):**

```
RP 3691 (Connell, age 8, 1901)
    ↓ similarity=0.626
RP 4591 (Connell, age 18, 1911, James Harvey household)  ✓ Correct

RP 3691 (Connell, age 8, 1901)
    ↓ similarity=0.626
RP 4631 (Connell, age 18, 1911, McGinty household)  ✗ False positive
```

Both linkages scored 0.626 (above 0.45 threshold), so both were proposed.

**Person resolution clustering (union-find) then created the merge:**

```
RP 3691 → RP 4591 [link 1: 1901-1911, James Harvey]
RP 3691 → RP 4631 [link 2: 1901-1911, McGinty]
RP 4591 → RP 5369 [link 3: 1911-1926]
RP 4631 → RP 5369 [link 4: 1911-1926]

Union-find algorithm:
  find(RP 3691) = find(RP 4591) = find(RP 4631) = find(RP 5369)
  → All merged into single person

Result: Person 28708 contains all four
```

**The issue**: RP 3691 (8 years old) matched **both** RP 4591 (18, James household) AND RP 4631 (18, McGinty household). The union-find algorithm didn't know these two 1911 records were from different households in the same census — it just saw a transitive path.

---

## Why Splink Is Actually Correct

**Check the configuration**:

```python
# In _build_person_settings():
return SettingsCreator(
    link_type="link_only",  # Only cross-source pairs
    ...
)

# In run_person_similarity():
for source_id_l, source_id_r in itertools.combinations(active_sources, 2):
    df_l = df_by_source[source_id_l]  # All persons from source 1
    df_r = df_by_source[source_id_r]  # All persons from source 2
    linker = Linker([df_l, df_r], settings, db_api=db_api)
    # Splink only sees TWO DataFrames → can only create pairs between them
```

**Splink behavior**:
- Passes two separate DataFrames (one per census)
- `link_type="link_only"` tells Splink: "Only generate pairs from DataFrame 1 to DataFrame 2"
- Result: No within-census pairs, only cross-census pairs

**Verification**:
All recorded_relationship entries show correct cross-census pairs:
- RP 3691 (1901) → RP 4591 (1911) ✓
- RP 3691 (1901) → RP 4631 (1911) ✓
- RP 4591 (1911) → RP 5369 (1926) ✓
- RP 4631 (1911) → RP 5369 (1926) ✓

None of these are within-census.

---

## The Real Problem: False Positives During Bridge Linkage

The issue is **not that Splink generates bad pairs**, but that **transitive clustering creates bad merges when there are multiple plausible cross-census matches**.

### The Chain of Events

1. **RP 3691 (Connell, 8yo, 1901)** needs to be matched forward to 1911
2. Splink finds TWO plausible matches in 1911:
   - RP 4591 (Connell, 18yo, James Harvey household) — similarity 0.626
   - RP 4631 (Connell, 18yo, McGinty household) — similarity 0.626
3. Both score above 0.45 threshold → both are proposed
4. Person resolution clustering accepts both
5. Union-find merges them into single person (transitively through RP 3691)
6. Result: Impossible scenario (one person in two 1911 households)

### Why This Happened

The **false positive** is actually RP 3691 → RP 4631. The real Connell Harvey is:
- RP 3691 (age 8, 1901) → RP 4591 (age 18, 1911) → RP 5369 (age 33, 1926)

But Splink found RP 3691 could also match RP 4631 (also age 18, also named Connell, also 1911). This is a **reasonable but incorrect match** — just happens to be a different person with the same name.

---

## The Right Fix: Validation at Clustering Time

The solution isn't to blame Splink. The solution is to **add a constraint to the clustering stage** that prevents impossible merges:

**Before**: 
```
Person resolution accepts all cross-census links
→ Clusters them via union-find
→ Some clusters contain same-census duplicates
→ Review layer catches them as errors
```

**After** (with new validation):
```
Person resolution accepts all cross-census links
→ Clusters them via union-find
→ Validation cleanup checks for same-census within single person
→ If found: Remove the weaker link (RP 3691 → RP 4631)
→ No merge errors in final dataset
```

This is exactly what we implemented: the cross-household same-census check that removes RP 4631 from Person 28708 **during validation cleanup**, before it becomes a merge error.

---

## Key Insight

Splink isn't the problem. **Multi-hop transitive merging through bridge linkages is the problem.**

When you have:
```
A → B (weak signal, but above threshold)
A → C (weak signal, but above threshold)
B → D
C → D
```

Union-find will merge all four together, even if B and C are from the same census (impossible).

**Solution**: Add census-level constraints that catch and remove the weaker inter-census link when it would create an impossible same-census duplicate.

---

## Why Splink Isn't At Fault

If we changed Splink to generate within-census scores, we'd be solving the wrong problem:

1. **It wouldn't help**: Even if Splink explicitly rejected within-census pairs, transitive clustering would still create the same merge through the bridge link.
2. **It would break cross-source logic**: Splink needs to generate across-source pairs only, which it does correctly.
3. **The real issue is downstream**: The clustering algorithm (union-find) + the absence of same-census uniqueness constraints, not Splink's linking.

---

## Conclusion

**Your question: "Why does Splink even try to create scores within the same census?"**

**Answer**: It doesn't. Splink is correctly configured for cross-census linking only. The problem is that **transitive clustering through bridge linkages can create same-census duplicates downstream**, which we now catch with validation.

The new validation check (`household_same_census_errors`) prevents this by ensuring that **no person ever appears in two different households in the same census**, regardless of how the clustering algorithm got there.

