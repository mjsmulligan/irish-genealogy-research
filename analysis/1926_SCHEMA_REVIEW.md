# 1926 Census Schema Review & Normalization Issues

**Date**: 2026-06-27  
**File**: `src/evidence/census.py` (_SOURCE_CONFIG lines 47-102)  
**Status**: Identified normalization gaps and potential bugs

---

## Schema Comparison

### Column Mappings

| Aspect | 1901/1911 | 1926 | Ingest Handler | Issue? |
|---|---|---|---|---|
| **Forename** | `firstname` | `first_name` | ✅ Mapped | ✓ OK |
| **Surname** | `surname` | `surname` | ✅ Same | ✓ OK |
| **Age** | `age` | `updated_age` | ✅ Mapped | ✓ OK |
| **Sex** | `sex` | `updated_sex` | ✅ Mapped | ✓ OK |
| **Relation/Role** | `relation_to_head_updated` | `updated_relationship_to_head` | ✅ Mapped | ⚠️ Different terminology |
| **Townland** | `townland_clean` | `townland` | ✅ Mapped | ✓ OK |
| **Household ID** | `image_group` | `image_group` | ✅ Same | ✓ OK |
| **Occupation** | `occupation_updated` | **NULL** | ✅ None | ✓ OK (1926 has no occupation) |
| **Birthplace** | `birthplace` | `birthplace_county` | ✅ Mapped | ✓ OK (county-level instead of full) |
| **Document ID** | `images` (JSON list) | `aform_name` | ✅ Uses aform_name | ✓ OK |

✅ **Conclusion on column mapping**: The ingest function appears to handle schema differences correctly.

---

## Critical Issue: Role Terminology Normalization

The ingest function maps relation strings using `_normalise_relation()` and `_map_role()` (lines 157-190).

**Normalization process:**
```python
def _normalise_relation(raw: str) -> str:
    s = raw.strip().lower().replace("'", "")
    return " ".join(s.split())
```

Then looks up in `_ROLE_MAP` (lines 110-154).

### 1901/1911 Relation Values (Observed)

From our CSV data:
- "Head of Family"
- "Wife"
- "Son"
- "Daughter"
- "Sister"
- "Grand Daughter"
- "Grand Son"
- etc.

**After normalization** (lowercase, strip apostrophes, collapse spaces):
- "head of family" → ✅ Maps to "head"
- "wife" → ✅ Maps to "spouse"
- "son" → ✅ Maps to "son"
- etc.

### 1926 Relation Values (Observed from sample)

From our 1926 CSV:
- "Head" (not "Head of Family")
- "Grandson" (not "Grand Son")
- (Need to see more data)

**After normalization**:
- "head" → ✅ In _ROLE_MAP, maps to "head"
- "grandson" → ✅ In _ROLE_MAP, maps to "grandchild"

### ✅ Role Mapping Appears OK

The role map includes both variants:
```python
_ROLE_MAP = {
    "head of family": "head",
    "head": "head",              # ← 1926 variant
    "grand son": "grandchild",
    "grandson": "grandchild",   # ← 1926 variant
    # ...
}
```

**But let me check if there are ANY 1926-specific role values missing:**

Let me extract unique 1926 role values from the CSV:

<function_calls>
<invoke name="Bash">
<parameter name="command">cd /Users/mike.mulligan/Documents/Personal\ Learning\ Space/irish-genealogy-research && python3 << 'EOF'
import pandas as pd
from collections import Counter

df_1926 = pd.read_csv("tests/tullynaught_1926.csv")

# Get unique values from both raw and updated relation columns
raw_roles = df_1926['relationship_to_head'].dropna().str.strip().unique()
updated_roles = df_1926['updated_relationship_to_head'].dropna().str.strip().unique()

print("1926 RELATIONSHIP_TO_HEAD (raw):")
for role in sorted(set(raw_roles)):
    count = (df_1926['relationship_to_head'].str.strip() == role).sum()
    print(f"  {role:30} ({count:3d})")

print("\n1926 UPDATED_RELATIONSHIP_TO_HEAD (normalized):")
for role in sorted(set(updated_roles)):
    count = (df_1926['updated_relationship_to_head'].str.strip() == role).sum()
    print(f"  {role:30} ({count:3d})")

# Check differences
print("\nValues in UPDATED but not in RAW:")
for role in sorted(set(updated_roles) - set(raw_roles)):
    print(f"  + {role}")

print("\nValues in RAW but not in UPDATED:")
for role in sorted(set(raw_roles) - set(updated_roles)):
    print(f"  - {role}")
EOF
