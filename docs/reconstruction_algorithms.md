# Irish Genealogy Research — Reconstruction Algorithms

*Version 1.3 — 19 June 2026*
*Audience: Developers and data engineers. This document specifies the algorithms that construct and extend the conclusion layer from the evidence layer. Read `conceptual_model.md`, `data_dictionary.md`, `database_schema.md`, and `validation_rules.md` first.*

______________________________________________________________________

## 1. Foundations

### 1.1 The reconstruction problem

Reconstruction is the process of building conclusion-layer objects (Person, Event, Relationship) from evidence-layer objects (Record, RecordedPerson). It answers three related questions:

- **Record-to-Person:** Is this Record about an existing Person, or does it warrant a new Person conclusion?
- **Record-to-Event:** Does this Record document an existing Event conclusion, or does it warrant a new one?
- **Relationship inference:** Given that this Record involves Person A and Person B in specific roles, what Relationship assertion does that support?

Place is not a conclusion-layer object in this system. The place authority (`place_authority`) is a pre-seeded reference table populated from logainm.ie before reconstruction begins. Place resolution links Records to existing `place_authority` entries via the `place_record` junction table — it does not create new conclusion objects.

These questions are not independent. Place resolution must precede Person linkage because resolved `place_authority` entries are the primary blocking anchor for candidate generation. Relationship inference is downstream of Person linkage — it operates on concluded Persons, not on candidate pairs. Event linkage depends on both Place resolution and Person linkage being sufficiently complete to make event-level convergence meaningful.

The reconstruction pipeline therefore executes in the following order:

```
1. Ingest         → Evidence layer complete (Records with inline event fields, RecordedPersons)
2. Place          → Records linked to place_authority entries; unresolved strings flagged
3. Person         → Person conclusions constructed; Records linked to Persons
4. Relationship   → Relationship assertions derived from Person linkages and roles
5. Event          → Event conclusions constructed; Records linked to Events
6. Analysis       → Community-level queries, graph traversal, GEDCOM output
```

Each stage feeds the next. Stages 3–5 may iterate as new sources are ingested.

______________________________________________________________________

### 1.2 Two operational modes

The reconstruction pipeline operates in two distinct modes depending on whether a conclusion layer already exists for the target community.

**Initial construction** — no conclusion layer exists. All Records for a community are ingested first, then Place resolution runs across the full dataset, then Person construction runs from scratch. This is the mode used when beginning work on a new community or source set.

**Incremental linkage** — a conclusion layer already exists. New Records arrive (a new source is ingested) and the algorithm asks: do these Records extend existing conclusions, contradict them, or require new conclusions? Incremental linkage does not rerun the full pipeline — it proposes links between new Records and the existing conclusion layer, and flags where new evidence suggests a conclusion needs revision.

The distinction matters because incremental linkage can exploit the existing conclusion layer as prior knowledge. If a Person conclusion for "John Mulligan, Tullynaught, b. ~1852" already exists with three supporting Records, a new Record containing "John Mulligan, Tullynaught, age 49" from a 1901 census is evaluated against that prior — the algorithm is not starting from scratch.

______________________________________________________________________

### 1.3 Scoring and the verified flag

Every algorithmically-proposed linkage between a Record and a conclusion-layer object carries a **match probability score** in the range 0.0–1.0. This score is produced by the Splink probabilistic linkage engine (see §1.5) and stored on the junction table row connecting the Record to the conclusion object.

The score is the atomic unit of confidence in this system. Conclusion-level confidence (how confident are we in this Person or Event overall?) is **derived** from the scores of its supporting junction rows — it is not stored separately. The derivation function is described in §1.4.

Every junction row also carries a **verified flag** (`verified INTEGER`, 0 or 1, default 0). The verified flag records whether a human researcher has reviewed and confirmed this specific linkage. It is independent of the score — a high-scoring linkage may be unverified, and a low-scoring linkage may be verified if the researcher has examined and confirmed it.

This decoupling is the key design principle: **automation provides throughput; the verified flag provides auditability.** The system can auto-commit high-confidence linkages at scale (as required for batch ingestion of hundreds or thousands of records) while always making clear to the researcher what has and has not been human-reviewed.

**Threshold bands** govern automated behaviour:

| Band | Score range | Action |
|---|---|---|
| Auto-reject | Below floor (default 0.3) | Candidate suppressed; not surfaced to researcher |
| Propose | Floor to ceiling (0.3–0.85) | Candidate queued for researcher review |
| Auto-commit | At or above ceiling (default 0.85) | Linkage committed; `verified = 0` |

Thresholds are configurable per source type. A source with clean, structured data (civil registration) may warrant a higher auto-commit ceiling than a source with transcription noise (folklore collection). Default values are starting points, not fixed constants — they should be tuned as the Splink model is trained on real data.

The researcher sets `verified = 1` by reviewing and confirming a linkage in the application. Verification can be applied to any linkage regardless of how it was committed.

______________________________________________________________________

### 1.4 Derived confidence

Conclusion-level confidence for Person, Event, and Relationship objects is derived from the scores of their supporting junction rows rather than stored as a separate field. The derivation function takes three inputs:

- **Mean score** — the average Splink match probability across all supporting Record linkages
- **Record count** — the number of distinct Records supporting the conclusion
- **Source diversity** — the number of distinct source types represented among supporting Records

A conclusion supported by a single Record with a high score is a well-evidenced hypothesis. A conclusion supported by three Records from three different source types with consistently high scores is a finding. The derivation function rewards convergence across independent sources more than it rewards a single very high score.

The precise form of this function — how mean score, record count, and source diversity are weighted and combined — is a known open problem deliberately deferred from this version. The function will be specified and tuned once real data from the Tullynaught test case is available to calibrate against. The current implementation should expose the three inputs as computable values and return a placeholder confidence band (`high / medium / low`) based on record count alone as a temporary approximation:

| Record count | Provisional confidence |
|---|---|
| 1 | `low` |
| 2 | `medium` |
| 3+ | `high` |

This placeholder is explicitly labelled as provisional in the codebase and replaced once the derivation function is specified.

______________________________________________________________________

### 1.5 Library stack

The reconstruction pipeline is built on three components:

**Splink** — the probabilistic linkage engine. Splink implements the Fellegi-Sunter model of record linkage with an Expectation-Maximisation algorithm for unsupervised parameter estimation — no labelled training data is required. It operates directly on the SQLite backend, executing linkage workloads as SQL against `irish_genealogy.db` without an ETL step. Splink produces pairwise match probabilities for candidate record pairs and clusters predictions into entity groups. It supports term frequency adjustments, which is the mechanism used to handle high-frequency Irish surnames (see §4.4).

**rapidfuzz** — string similarity at the feature level. rapidfuzz provides Jaro-Winkler similarity via `rapidfuzz.distance.JaroWinkler.similarity`, which returns a value in the 0.0–1.0 range. It is called during feature extraction to produce numeric similarity scores for name pairs and place string pairs before those scores are passed to Splink as comparison features. rapidfuzz is preferred over jellyfish for its pure-Python installation path (no Rust compilation required) and consistent 0–1 return range.

**Irish-specific logic** — custom Python code implementing the domain knowledge that general-purpose libraries cannot provide: the name variant table, the townland normalisation pipeline, the source-specific feature extractors, the patronymic signal, and the role-pair relationship inference rules. This layer runs as pre-processing before Splink and as post-processing after it.

**Installation:**

```
pip install splink rapidfuzz
```

______________________________________________________________________

### 1.6 Schema changes driven by this document

This document introduces additions to the schema specified in `database_schema.md`. These changes are tracked as `database_schema.md` v2.4.

**Junction table additions** — `score` and `verified` columns are added to all evidence-to-conclusion junction tables:

```sql
-- Person.recorded_person_ids — extended
CREATE TABLE person_recorded_person (
    person_id             INTEGER NOT NULL REFERENCES person (person_id),
    recorded_person_id    INTEGER NOT NULL REFERENCES recorded_person (recorded_person_id),
    score                 REAL,       -- Splink match probability 0.0–1.0; null for manually-asserted linkages
    score_version         TEXT,       -- model run identifier; null for manually-asserted linkages
    verified              INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    PRIMARY KEY (person_id, recorded_person_id)
);
```

The same additions apply to `event_record` and `relationship_recorded_relationship`. The `person_event` structural junction is not modified — it expresses conclusion-to-conclusion participation and carries no score.

**Note on junction table naming:** The junction tables above reflect the v3.1 target design documented in `database_schema.md §1`. The renames from earlier schema versions (`person_record` → `person_recorded_person`, `relationship_record` → `relationship_recorded_relationship`) and the corresponding FK target changes (`record_id` → `recorded_person_id` / `recorded_relationship_id`) are tracked as Work Queue item 15 and are not yet reflected in the code. See `database_schema.md §1` for the full v3.1 target DDL.

**Conclusion table changes** — `confidence TEXT` is removed from the `relationship` and `event` tables. Confidence is now always derived, never stored. The `CHECK (confidence IN (...))` constraint is removed accordingly.

**New table: name_variant** — the Irish name variant table is a first-class schema object (see §4.2):

```sql
CREATE TABLE name_variant (
    name_variant_id INTEGER PRIMARY KEY,
    canonical       TEXT    NOT NULL CHECK (trim(canonical) != ''),
    variant         TEXT    NOT NULL CHECK (trim(variant) != ''),
    variant_type    TEXT    NOT NULL,
    notes           TEXT,

    CHECK (variant_type IN ('anglicisation', 'abbreviation', 'spelling', 'language_form', 'patronymic')),
    UNIQUE (canonical, variant)
);

CREATE INDEX idx_name_variant_variant ON name_variant (variant);
CREATE INDEX idx_name_variant_canonical ON name_variant (canonical);
```

______________________________________________________________________

## 2. Place Resolution

### 2.1 Role of Place resolution

Place resolution is the prerequisite stage for all subsequent reconstruction. Its output — Records linked to `place_authority` entries at townland-level granularity — provides the primary blocking anchor for Person linkage. Without resolved place references, Person candidate generation degenerates to a full cross-product of all Records, which is computationally expensive and produces low-quality results.

Place resolution does not create conclusion objects. The `place_authority` table is a pre-seeded reference populated from logainm.ie before any reconstruction begins (via `python -m src.cli seed-places` and `python -m src.cli fetch-places`). Resolution links a Record's place string to an existing `place_authority` entry by inserting a row into the `place_record` junction table. If no authority entry matches above threshold, the place string is flagged as unresolved and deferred for researcher attention — no new authority entry is created automatically.

Because `place_authority` is seeded at community scale before resolution runs, the evidence base for a given townland entry is typically the entire community dataset — many Records across multiple sources all containing variants of the same place string. Convergence at this scale makes resolution effectively certain and the linkage can be auto-committed with high confidence and low verification burden.

### 2.2 The townland as atomic unit

Place resolution always targets **townland granularity**. The townland is the common atomic unit of geographical reference across all twelve sources in the closed source set:

- Griffith's Valuation and Tithe Applotment Books are organised by townland
- Census records (1901, 1911, 1926) carry an explicit townland column
- Civil birth, marriage, and death registrations carry place of event at townland or near-townland precision
- Catholic Parish Registers typically carry parish name plus townland of residence for principals

Higher-level administrative units — DED, civil parish, barony, county — are derivable from the townland via the `place_authority` hierarchy columns and are not stored as separate entries. A Record that specifies only a higher-level unit (e.g. "Co. Donegal" or "Kilbarron parish") is treated as partial evidence; its place string is flagged as unresolved rather than linked at a coarser level.

**Important:** Administrative boundaries do not align across sources. The DEDs used by the census administration and the parishes used by church records cover overlapping but non-identical geographies. Tullynaught DED and Tawnawilly Catholic parish, for example, cover similar communities but with different boundary lines. Place resolution bridges these boundary mismatches by resolving to the townland, which is stable across all source types. The researcher's judgment — expressed via `place_record` linkages that connect Records from different administrative contexts to the same `place_authority` entry — is what resolves the boundary discrepancy. The algorithm supports this judgment; it does not make it automatically.

### 2.3 Townland normalisation pipeline

Before any string matching occurs, all `place_as_recorded` strings are passed through a normalisation pipeline:

1. **Lowercase** — case-fold the entire string
1. **Strip punctuation** — remove commas, full stops, hyphens used as separators
1. **Expand abbreviations** — "Co." → "county", "Par." → "parish", "Bal." → "bally"
1. **Strip administrative suffixes** — remove "townland", "td", "civil parish", "DED", "barony" and equivalents
1. **Normalise whitespace** — collapse multiple spaces to single space, strip leading/trailing

The result is a normalised place token suitable for fuzzy comparison. The original `place_as_recorded` string is always preserved verbatim in the `record.place_as_recorded` column — normalisation is a comparison artefact, never a data modification.

### 2.4 Place candidate scoring

For each distinct normalised place token in the dataset, the algorithm scores it against all `place_authority` entries using Jaro-Winkler similarity on the normalised `place_authority.name_en` value. A score at or above 0.88 is treated as a candidate match for auto-commit or researcher review.

The 0.88 threshold for place matching is set higher than the general auto-commit threshold (0.85) because place string matching is simpler than person matching — there are no confounding factors like age drift or name change — and false positive place merges (linking Records to the wrong townland authority) cause significant downstream damage to Person linkage.

### 2.5 Linking Records to place_authority

When a normalised place token matches a `place_authority` entry at or above the 0.88 threshold, a `place_record` row is inserted linking the Record to that authority entry with the match score.

When no `place_authority` entry matches above threshold, the place string is flagged as unresolved. The researcher resolves unresolved strings by:

1. Checking whether the missing townland should be fetched from logainm.ie (`python -m src.cli fetch-places`)
1. Manually adding an entry to `place_authority` if the townland is not in logainm (e.g. an anglicised variant not yet indexed)
1. Re-running place resolution after the authority table is extended

No `place_authority` entry is ever created automatically by the resolution algorithm. The authority table is a curated reference; resolution is a linking step only.

______________________________________________________________________

## 3. Feature Extraction by Source Type

### 3.1 The closed source set advantage

Because the source set is fixed and documented, the algorithm knows exactly which features are available in each source before any matching begins. Feature extractors are source-specific functions keyed on `source.type`. The following table summarises feature availability across the twelve sources:

| Feature | Griffith's | Tithe | Census | Civil Birth | Civil Marriage | Civil Death | Parish Register | Military | Folklore |
|---|---|---|---|---|---|---|---|---|---|
| Surname | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Forename | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Approximate birth year | — | — | ✓ (derived) | ✓ | ✓ | ✓ (derived) | ✓ (baptism) | Partial | — |
| Townland | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | Partial | ✓ |
| Household role | — | — | ✓ | — | ✓ | — | Partial | — | — |
| Occupation | ✓ | — | ✓ | ✓ | ✓ | ✓ | — | ✓ | — |
| Co-occurring persons | ✓ (lessor) | — | ✓ (household) | ✓ (parents) | ✓ (both families) | ✓ (informant) | ✓ (sponsors) | — | ✓ (informant) |
| Parentage | — | — | Partial | ✓ | ✓ | — | ✓ | — | — |

**Approximate birth year derivation** — where a birth year is not directly stated, it is derived from the event date and recorded age. Census 1901: `birth_year ≈ 1901 - age`. Civil death: `birth_year ≈ death_year - age_at_death`. Derived birth years carry an uncertainty of ±2 years to account for age rounding and transcription error.

### 3.2 Source-specific feature extractors

Each source type has a dedicated feature extractor that reads the RecordedPersons and the inline event fields on the Record and returns a standardised feature dictionary. The feature dictionary is the input to Splink's comparison functions.

**Standard feature dictionary fields:**

```python
{
    "record_id":        int,
    "surname_norm":     str,        # normalised surname (see §4.1)
    "forename_norm":    str,        # normalised forename (see §4.1)
    "birth_year_est":   int | None, # estimated birth year
    "birth_year_range": int | None, # ± uncertainty in years
    "place_id":         int | None, # place_authority_id of the resolved place_authority entry
    "place_raw":        str | None, # normalised place token (fallback if unresolved)
    "occupation_norm":  str | None, # normalised occupation string
    "co_persons":       list[str],  # normalised names of co-occurring persons
    "role":             str | None, # RecordedPerson role from controlled vocabulary
    "source_type":      str,        # source.type value
}
```

Co-occurring persons are the other RecordedPersons in the same Record — household members, parents, witnesses, sponsors. They are included as a list of normalised name strings. Their presence as a matching feature is described in §5.3.

______________________________________________________________________

## 4. Name Matching

### 4.1 Normalisation pipeline

All name strings are normalised before comparison. The pipeline applies in order:

1. **Lowercase** — case-fold
1. **Strip fada for comparison** — remove Irish language diacritics (á→a, é→e, í→i, ó→o, ú→u). The original spelling is always preserved in `name_as_recorded`
1. **Expand standard abbreviations** — Wm→william, Thos→thomas, Jas→james, Jno→john, Chas→charles, Mgt/Marg→margaret, Pat/Pk→patrick, Brid/Bgt→bridget, Michl→michael
1. **Strip particles** — remove "O'", "Mc", "Mac" as separate tokens for phonetic comparison (preserved in the full normalised string for Jaro-Winkler)
1. **Normalise whitespace**

Normalisation produces a `full_norm` string used for Jaro-Winkler comparison.

### 4.2 The name variant table

The name variant table (`name_variant`) is a researcher-curated asset that maps known Irish name equivalences. It is a first-class schema object (DDL in §1.6) and grows as the researcher works through the source set.

**Variant types:**

| Type | Example |
|---|---|
| `anglicisation` | Ó Murchadha → Murphy |
| `abbreviation` | Margaret → Mgt, Peggy |
| `spelling` | Mulligan → Mullagan, Mulligen |
| `language_form` | Máire → Mary, Maria, Marie |
| `patronymic` | (see §4.3) |

A name pair that resolves via the variant table receives a similarity score of **0.95** — treated as a near-certain match, below 1.0 only to allow the possibility of a coincidental variant collision.

The variant table is consulted before Jaro-Winkler is applied. If a variant table match is found, the Jaro-Winkler step is skipped for that pair. If no variant table match exists, Jaro-Winkler is applied to the normalised full string.

Variant table entries are community-specific and should be seeded for the target community before reconstruction begins. A base set of common Irish name equivalences is provided as a starter fixture (see Appendix A).

### 4.3 Patronymic naming pattern

In 19th-century Irish communities, generational naming conventions create predictable name recurrence: the first son named after the paternal grandfather, the first daughter after the maternal grandmother, the second son after the maternal grandfather, and so on. This means the same name — "Patrick Mulligan" — may appear in the same townland across three generations without referring to the same Person.

The patronymic signal is a **negative disambiguation feature** rather than a positive matching feature. When the algorithm encounters two Records with identical names in the same townland, it uses the estimated birth years and the existing relationship graph to determine whether generational arithmetic makes a same-Person conclusion plausible or implausible.

If Person conclusion P1 ("Patrick Mulligan, b. ~1820") already exists with a `parent_child` Relationship to Person P2 ("John Mulligan, b. ~1848"), and a new Record contains "Patrick Mulligan, age 8" in 1901, the algorithm should strongly prefer creating a new Person P3 (John's son, b. ~1893) over linking to P1. The name match is high but the birth year arithmetic makes P1 impossible.

This logic requires the existing relationship graph to be populated. It therefore only applies in incremental linkage mode, not in initial construction.

### 4.4 Surname frequency weighting

In a small closed community, certain surnames dominate — many Mulligans, Brennans, or Kellys in the same townland across generations. A surname match in a high-frequency community contributes less discriminating information than the same match in a low-frequency community.

Splink's term frequency adjustment mechanism handles this directly. For the surname comparison feature, Splink is configured to apply a term frequency adjustment that reduces the weight of a match on a surname that appears frequently in the dataset. The frequency table is computed from the ingested RecordedPerson data and passed to Splink during model configuration.

This means surname frequency weighting is automatic and self-calibrating — it reflects the actual surname distribution in the target community, not a static prior.

### 4.5 Forename gender signal

Forename is a weak but useful gender signal. "Mary", "Bridget", "Catherine" are reliably female; "Patrick", "Michael", "John" are reliably male. Where `Person.gender` is already concluded, a forename that contradicts the concluded gender is a strong negative signal against a proposed match. This check is applied as a hard filter before scoring — a male Person is never proposed as a candidate match for a Record whose principal RecordedPerson has a reliably female forename, regardless of surname similarity.

______________________________________________________________________

## 5. Person Linkage

### 5.1 Blocking

Blocking is the step that restricts the candidate pair space before scoring. Without blocking, every Record would be compared against every existing Person conclusion — a quadratic operation that is computationally infeasible even at community scale.

Two blocking rules are applied in order. A Record must pass at least one blocking rule to generate candidates.

**Blocking rule 1 — Place anchor (primary):**
Candidate pairs are generated between a new Record and existing Person conclusions where both share the same resolved `place_authority` entry (`place_id`). This is the primary blocking rule and covers the majority of cases in a One Place Study context.

**Blocking rule 2 — Surname fallback:**
For Records whose place string is unresolved or coarser than townland level, candidates are generated where the normalised surname matches above a Jaro-Winkler threshold (default 0.85). This catches cases where a Record mentions only a parish or county, or where a place string could not be resolved to an existing `place_authority` entry.

Records that pass neither blocking rule generate no candidates and are flagged for researcher attention.

### 5.2 Comparison features

Within each candidate pair, Splink computes the following comparison features:

| Feature | Comparison method | Weight |
|---|---|---|
| Surname | Variant table → Jaro-Winkler; term frequency adjusted | High |
| Forename | Variant table → Jaro-Winkler | High |
| Birth year | Absolute difference, with ±2 year tolerance for derived years | High |
| Place | Resolved `place_authority` entry match (exact on `place_id`) | High |
| Occupation | Jaro-Winkler on normalised occupation string | Medium |
| Co-occurring persons | Overlap score between co-person name lists | Medium |
| Source type | Compatibility score between source types (see §5.3) | Low |

Feature weights are initial estimates. Splink's EM algorithm will refine these weights during training on the Tullynaught dataset. The weights listed here should be treated as configuration starting points, not fixed constants.

### 5.3 Co-occurring person matching

Co-occurring persons — household members, parents, witnesses, sponsors — are a powerful disambiguating feature that generic record linkage systems typically ignore. In the Irish context, a Record containing "John Mulligan, head" with co-occurring persons "Mary Mulligan, spouse" and "Patrick Mulligan, child" can be matched against an existing Person conclusion for John Mulligan not just on John's own features, but on the presence of a Mary Mulligan and a Patrick Mulligan in the expected roles in the existing relationship graph.

The co-occurring person overlap score is computed as the Szymkiewicz–Simpson similarity between the set of normalised co-person name strings in the new Record and the set of names of Persons in the existing conclusion's relationship graph. Szymkiewicz–Simpson (`|A∩B| / min(|A|, |B|)`) is used rather than Jaccard because household composition is expected to change across census years — children leave, members die — so the smaller of the two sets is the correct denominator. A 1911 household that is a genuine subset of the 1901 household should score high, not be penalised for the departures.

This feature is only available in incremental linkage mode — in initial construction, no relationship graph exists yet. During initial construction, co-person names are stored in the feature dictionary but the overlap score is set to null and excluded from Splink's comparison.

### 5.4 Within-source deduplication (initial construction)

Before cross-source Person linkage, the algorithm runs within-source deduplication to identify Records within the same source that refer to the same Person. This is most relevant for census sources, where a household head may appear in multiple roles across related records, and for sources where the same individual appears more than once due to transcription practices.

Within-source deduplication uses the same Splink pipeline as cross-source linkage but with `link_type = "dedupe_only"` and tighter thresholds, since Records within the same source are expected to be more consistent in spelling and format.

### 5.5 Household structure inference (census sources)

For census sources (1901, 1911, 1926), the household Record provides strong structural information that the general scoring model does not capture. All RecordedPersons in a single census Record share the same household, and their roles (`head`, `spouse`, `child`, `boarder`) define an implicit relationship structure.

The pipeline treats 1926 as a first-class census source by normalising its QA-clean fields into the shared census ingest schema. Important 1926 fields such as `aform_name` and `updated_relationship_to_head` are preserved and mapped so the same household inference logic can operate consistently across all three census years.

The household inference algorithm operates on census Records before the general Person linkage pipeline:

1. For each census Record, extract all RecordedPersons with their roles and ages
1. Group RecordedPersons by household (all share the same `record_id`)
1. Create provisional Person conclusions for each RecordedPerson in the household
1. Create provisional Relationship conclusions based on role pairs:
   - `head` + `spouse` → `couple` Relationship (high prior)
   - `head` + `son` or `daughter` → `parent_child` Relationship (high prior, head is parent)
   - `spouse` + `son` or `daughter` → `parent_child` Relationship (medium prior, spouse is parent)
   - `head` + `sibling` → `sibling` Relationship (medium prior)
   - `son` + `son`, `daughter` + `daughter`, `son` + `daughter` → `sibling` Relationship (medium-low prior, inferred via shared parents)
1. Score these provisional conclusions at `score = 0.90` (household structure is high-confidence evidence)

These provisional conclusions become the seed for cross-source linkage in the subsequent pipeline stage. Cross-census linkage (1901 → 1911 → 1926) then attempts to link the same Person across the three census years using the age-drift model described in §5.6.

### 5.6 Age drift across census years

A Person appearing in multiple census years will show age progression. The expected age delta between two census records is the number of years between them, with a tolerance of ±3 years to account for age rounding, informant uncertainty, and transcription error.

For the three census years available:

| Census pair | Expected delta | Tolerance |
|---|---|---|
| 1901 → 1911 | +10 years | ±3 |
| 1911 → 1926 | +15 years | ±3 |
| 1901 → 1926 | +25 years | ±4 |

A candidate pair whose age delta falls within tolerance receives full credit on the birth year comparison feature. A delta outside tolerance is a strong negative signal but not an automatic disqualification — informant errors on age are common enough that the other features can compensate if they score strongly.

______________________________________________________________________

## 6. Relationship Inference

### 6.1 Role-pair rules

Relationship assertions are derived from the roles of RecordedPersons within a Record, once those RecordedPersons have been linked to Person conclusions. The following role-pair rules define the inferred Relationship type:

**Marriage and registration records:**

| Role 1 | Role 2 | Relationship type | Direction | Prior score |
|---|---|---|---|---|
| `groom` | `bride` | `couple` | Symmetric | 0.90 |
| `father` | `principal` | `parent_child` | father=parent | 0.90 |
| `mother` | `principal` | `parent_child` | mother=parent | 0.90 |
| `father_of_groom` | `groom` | `parent_child` | father=parent | 0.90 |
| `father_of_bride` | `bride` | `parent_child` | father=parent | 0.90 |
| `principal` | `godfather` | — | (no Relationship; noted in Event only) | — |
| `principal` | `godmother` | — | (no Relationship; noted in Event only) | — |
| `principal` | `witness` | — | (no Relationship; noted in Event only) | — |

**Census household records:**

| Role 1 | Role 2 | Relationship type | Direction | Prior score |
|---|---|---|---|---|
| `head` | `spouse` | `couple` | Symmetric | 0.90 |
| `head` | `son` | `parent_child` | head=parent | 0.85 |
| `head` | `daughter` | `parent_child` | head=parent | 0.85 |
| `spouse` | `son` | `parent_child` | spouse=parent | 0.80 |
| `spouse` | `daughter` | `parent_child` | spouse=parent | 0.80 |
| `head` | `mother` | `parent_child` | mother=parent | 0.85 |
| `head` | `father` | `parent_child` | father=parent | 0.85 |
| `son` | `son` | `sibling` | Symmetric | 0.75 |
| `daughter` | `daughter` | `sibling` | Symmetric | 0.75 |
| `son` | `daughter` | `sibling` | Symmetric | 0.75 |
| `head` | `sibling` | `sibling` | Symmetric | 0.80 |

**Census roles that do not generate automatic Relationship assertions:** `grandchild`, `in_law`, `niece_nephew`, `aunt_uncle`, `cousin`, `servant`, `visitor`, `boarder`. These roles are retained as evidence for researcher-led reasoning and contribute to co-occurring person features in linkage scoring, but do not trigger automatic Relationship creation.

**Grandchild inference:** A `grandchild` role implies a two-hop `parent_child` chain (head/spouse → intermediate child → grandchild). The algorithm does not create a grandparent Relationship directly. Instead it flags the grandchild Person as a candidate child of any `son` or `daughter` concluded in the same household whose age arithmetic is compatible. This flag is surfaced in the update knowledge session for researcher review.

**Occupier/lessor pairs** in Griffith's or Tithe records describe a land tenure relationship, not a personal relationship, and are not modelled as Relationships.

Prior scores reflect the strength of the role-pair evidence alone. Sibling inference scores (0.75–0.80) are lower than parent_child scores because sibling relationships in census records depend on a shared parent conclusion being correctly established first — the inference is one step removed from the direct evidence. These scores are stored on the `relationship_recorded_relationship` junction table (pre-v3.1 code: `relationship_record`) and contribute to derived confidence.

### 6.2 Relationship deduplication

Before a new Relationship assertion is committed, the algorithm checks whether an equivalent Relationship already exists between the same two Persons with the same type. If it does, the new Record is added to the existing Relationship's `record_ids` via a new junction row — strengthening the existing conclusion rather than creating a duplicate. This is the mechanism by which convergent evidence raises Relationship confidence over time.

A Relationship is considered equivalent if `type`, `person_id_1`, and `person_id_2` match (ignoring direction for symmetric types).

______________________________________________________________________

## 7. Event Linkage

### 7.1 Event construction

An Event conclusion is constructed when one or more Records are concluded to document the same real-world occurrence. The minimum viable Event is a single Record with a concluded type, date, and place — but confidence is `low` until a second independent Record corroborates it.

Event construction runs after Person linkage is complete for the relevant Records. The Event links the Persons who participated, the Place where it occurred, and the Records that document it.

### 7.2 Event candidate scoring

Two Records are candidates for the same Event if:

- They share the same `event_type` (from `record.event_type`)
- Their normalised dates are within a configurable tolerance (default ±1 year for `birth`, `baptism`, `death`, `burial`; ±0 years for `marriage` — marriage dates in this period are typically precise)
- Their resolved `place_authority` entries are the same or geographically proximate

Geographic proximity between `place_authority` entries is not currently modelled beyond exact match on `place_id`. Records with unresolved place strings that fall within the same inferred DED or parish are treated as a weak positive signal but not a definitive match. Full geographic proximity modelling is a future extension.

### 7.3 Record to Event linkage

When a Record is linked to an existing Event conclusion, the Record is added to `event_record`. Because event data is now inline on the Record, this single insertion is sufficient — there is no separate `event_recorded_event` junction to maintain. Rule R26 (which enforced consistency between those two tables) has been retired in schema v2.8.

______________________________________________________________________

## 8. Community-Level Analysis

### 8.1 Population queries

Once the conclusion layer is populated for a community, the following aggregate queries become available. These are expressed as SQL against the SQLite database.

**Note:** The queries below use the current code-level junction table name `person_record`. Once the v3.1 rename to `person_recorded_person` is implemented (Work Queue item 15), these queries should be updated accordingly.

**Total concluded Persons in the community:**

```sql
SELECT COUNT(DISTINCT p.person_id)
FROM person p
JOIN person_record pr ON p.person_id = pr.person_id
JOIN record r ON pr.record_id = r.record_id
JOIN source s ON r.source_id = s.source_id
WHERE s.repository_id IN (/* target repositories */);
```

**Persons spanning two or more census years:**

```sql
SELECT p.person_id, p.label, COUNT(DISTINCT s.source_id) AS census_count
FROM person p
JOIN person_record pr ON p.person_id = pr.person_id
JOIN record r ON pr.record_id = r.record_id
JOIN source s ON r.source_id = s.source_id
WHERE s.type = 'census'
GROUP BY p.person_id
HAVING census_count >= 2
ORDER BY census_count DESC;
```

**Linkage confidence distribution — how many Person-Record links are at each score band:**

```sql
SELECT
    CASE
        WHEN score >= 0.85 THEN 'high'
        WHEN score >= 0.60 THEN 'medium'
        WHEN score >= 0.30 THEN 'low'
        ELSE 'below_floor'
    END AS band,
    COUNT(*) AS link_count,
    AVG(verified) AS verification_rate
FROM person_record
GROUP BY band;
```

**Unverified high-score linkages — candidates for efficient researcher review:**

```sql
SELECT p.label, r.record_id, pr.score, s.title AS source_title
FROM person_record pr
JOIN person p ON pr.person_id = p.person_id
JOIN record r ON pr.record_id = r.record_id
JOIN source s ON r.source_id = s.source_id
WHERE pr.score >= 0.85 AND pr.verified = 0
ORDER BY pr.score DESC;
```

### 8.2 Relationship graph traversal

The relationship graph — Persons as nodes, Relationships as edges — is the primary analytical output of the reconstruction pipeline. It can be traversed to find:

- All Persons connected to a given Person within N degrees
- Household networks: all Persons who shared a household in any census year
- Family clusters: all Persons linked by `parent_child` or `couple` Relationships
- Isolated Persons: Persons with no Relationships, potentially duplicate conclusions or incomplete linkage

Graph traversal is implemented as recursive SQL using SQLite's `WITH RECURSIVE` clause or as Python graph operations using the `networkx` library. For the community GEDCOM output, the full relationship graph is materialised and exported.

### 8.3 GEDCOM export

The community GEDCOM file is a materialisation of the conclusion layer's relationship graph. It represents the intricate connections across a community that individual family tree research typically misses — the lateral connections between households, the witness networks at marriages, the godparent relationships at baptisms.

GEDCOM export is a post-processing step that reads the conclusion layer and translates it into standard GEDCOM 5.5.1 format. Each Person becomes an `INDI` record; each Relationship of type `couple` becomes a `FAM` record; `parent_child` Relationships populate `HUSB`, `WIFE`, and `CHIL` references within `FAM` records. Events map to standard GEDCOM event tags (`BIRT`, `MARR`, `DEAT`, etc.).

The `verified` flag is exported as a custom `_VERF` tag on each relevant record, allowing downstream tools to distinguish algorithmically-committed conclusions from researcher-verified ones.

GEDCOM export specification and implementation details are out of scope for this document and will be specified separately.

______________________________________________________________________

## 9. Implementation Notes

### 9.1 Splink configuration sketch

The following is an indicative Splink configuration for the Person linkage pipeline. Parameters are starting points and must be tuned against real data.

```python
from splink import Linker, SettingsCreator, DuckDBAPI
import splink.comparison_library as cl
from splink import block_on

settings = SettingsCreator(
    link_type="link_only",
    blocking_rules_to_generate_predictions=[
        block_on("place_id"),                                    # primary: same resolved place_authority entry
        block_on("surname_norm"),                                # fallback: normalised surname
    ],
    comparisons=[
        cl.JaroWinklerAtThresholds("surname_norm", [0.9, 0.8]),
        cl.JaroWinklerAtThresholds("forename_norm", [0.9, 0.8]),
        cl.AbsoluteDateDifferenceAtThresholds(
            "birth_year_est", [2, 5, 10]
        ),
        cl.ExactMatch("place_id").configure(term_frequency_adjustments=False),
        cl.JaroWinklerAtThresholds("occupation_norm", [0.85]),
    ],
    retain_matching_columns=True,
    retain_intermediate_calculation_columns=True,
)

linker = Linker(df_records, settings, db_api=DuckDBAPI())
linker.training.estimate_u_using_random_sampling(max_pairs=1e6)
linker.training.estimate_parameters_using_expectation_maximisation(
    block_on("surname_norm")
)
```

Term frequency adjustments for surname are configured separately using the surname frequency table computed from RecordedPerson data.

### 9.2 Entry points

The reconstruction module exposes the following entry points in `reconstruction.py`:

```python
def run_place_resolution(conn) -> list[dict]:
    """Run Place resolution across all unresolved place strings. Inserts
    place_record rows for matches above threshold; returns unresolved strings
    flagged for researcher attention."""

def run_initial_construction(conn, source_ids: list[int]) -> ReconstructionResult:
    """Run full initial construction pipeline for a set of sources.
    Returns proposed Person, Relationship, and Event conclusions."""

def run_incremental_linkage(conn, new_record_ids: list[int]) -> ReconstructionResult:
    """Link new Records to the existing conclusion layer.
    Returns proposed linkages and flagged contradictions."""

def compute_derived_confidence(conn, obj_type: str, obj_id: int) -> str:
    """Compute provisional confidence band for a conclusion object
    from its junction table scores. Returns 'high', 'medium', or 'low'."""

def export_gedcom(conn, output_path: str) -> None:
    """Export the full conclusion layer as a GEDCOM 5.5.1 file."""
```

______________________________________________________________________

## Appendix A — Name Variant Starter Fixture

The following entries seed the `name_variant` table for common Irish names encountered in 19th-century Connacht and Ulster records. This list is not exhaustive and should be extended as the researcher encounters additional variants in the target community.

**Forename variants (language forms and anglicisations):**

| Canonical | Variant | Type |
|---|---|---|
| mary | maire | language_form |
| mary | maria | language_form |
| mary | marie | language_form |
| mary | molly | abbreviation |
| patrick | padraig | language_form |
| patrick | pat | abbreviation |
| patrick | paddy | abbreviation |
| patrick | pk | abbreviation |
| john | sean | language_form |
| john | shane | language_form |
| john | jno | abbreviation |
| bridget | brid | abbreviation |
| bridget | bridie | abbreviation |
| bridget | bgt | abbreviation |
| margaret | mgt | abbreviation |
| margaret | marg | abbreviation |
| margaret | peggy | abbreviation |
| margaret | maggie | abbreviation |
| michael | michal | spelling |
| michael | michl | abbreviation |
| catherine | kathleen | language_form |
| catherine | kate | abbreviation |
| catherine | kitty | abbreviation |
| william | wm | abbreviation |
| thomas | thos | abbreviation |
| james | jas | abbreviation |
| charles | chas | abbreviation |

**Surname variants (common anglicisations and spelling variants):**

| Canonical | Variant | Type |
|---|---|---|
| murphy | o murchadha | anglicisation |
| murphy | murchadha | anglicisation |
| brennan | brannan | spelling |
| brennan | branon | spelling |
| mulligan | mullagan | spelling |
| mulligan | mulligen | spelling |
| kelly | o ceallaigh | anglicisation |
| gallagher | o gallchobhair | anglicisation |
| gallagher | gallaher | spelling |
| o brien | brien | spelling |
| mcnamara | macnamara | spelling |
| mcdermott | macdermott | spelling |
| mcdermott | dermott | spelling |

______________________________________________________________________

## Changelog

| Version | Date | Change |
|---|---|---|
| 1.0 | May 2026 | Initial version |
| 1.1 | May 2026 | Updated §6.1 role-pair rules to cover expanded census role vocabulary. Split table into marriage/registration roles and census household roles. Added `son`/`daughter` rows replacing generic `child`. Added `sibling` inference rows (head+sibling, and shared-child sibling pairs at 0.75–0.80 prior). Added `mother`/`father` census rows. Added grandchild inference note. Added godmother row. Documented roles that do not generate automatic assertions (`grandchild`, `in_law`, `niece_nephew`, `aunt_uncle`, `cousin`, `servant`, `visitor`, `boarder`). Updated §5.5 household structure inference to use `son`/`daughter` and include sibling provisional relationships. |
| 1.3 | 19 June 2026 | Removed Place as conclusion-layer object throughout. §1.1: reframed Record-to-Place as linking to pre-seeded `place_authority` (not creating Place conclusions); pipeline step 2 label updated. §2 Place Resolution fully rewritten: §2.1 clarifies that `place_authority` is a pre-seeded reference and resolution is a linking step only; §2.4 updated to match against `place_authority.name_en`; §2.5 replaced "new Place conclusion created" with unresolved-string flagging workflow. §1.5 Library stack: Jellyfish replaced by rapidfuzz (`rapidfuzz.distance.JaroWinkler.similarity`); phonetic (Soundex/Metaphone) blocking removed. §4.1: Soundex output removed from normalisation pipeline description. §5.1 blocking rule 2: Soundex blocking replaced by normalised surname Jaro-Winkler fallback. §5.3: co-occupant overlap score changed from Jaccard to Szymkiewicz–Simpson, with rationale. §1.6: junction table DDL example updated to v3.1 rename targets (`person_recorded_person`, FK to `recorded_person_id`); cross-reference note added. §9.1 Splink sketch: `link_and_dedupe` → `link_only`; `soundex_surname` blocking replaced by `surname_norm`; EM training block updated to match. |
| 1.2 | June 2026 | Updated for schema v2.8. §1.1 evidence layer description removes RecordedEvent. §1.6 junction table note updated to reflect dropped tables. §2.3 place_as_recorded field reference updated to `record.place_as_recorded`. §3.2 feature extractor description updated. §7.2 event candidate scoring uses `record.event_type`. §7.3 rewritten: `event_recorded_event` removed; Record-to-Event linkage via `event_record` only. |

______________________________________________________________________

*Related documents: `conceptual_model.md`, `data_dictionary.md`, `database_schema.md`, `validation_rules.md`, `session_bootstrap.md`*

*Schema version: v3.1 target (see database_schema.md §1)*
