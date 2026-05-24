# Irish Genealogy Research — Genealogical Constraints

*Version 1.1 — May 2026*
*Audience: Developers, data engineers, and reasoning sessions. This document defines the domain knowledge constraints that govern probabilistic record linkage and researcher recommendations. Read `conceptual_model.md`, `data_dictionary.md`, `reconstruction_algorithms.md`, and `repositories.md` first.*

---

## 1. Purpose and Scope

This document defines the genealogical constraints that operate on top of the data model and reconstruction pipeline. They are distinct from validation rules (`validation_rules.md`), which enforce data integrity, and from reconstruction algorithms (`reconstruction_algorithms.md`), which specify how linkage scores are computed. Genealogical constraints express domain knowledge about what is historically plausible in Irish records of the 19th and early 20th centuries.

Constraints serve two roles in the system:

**Linkage scoring** — constraints adjust or penalise Splink match probability scores before a linkage is committed. A candidate linkage that violates a constraint has its effective score reduced, potentially moving it from the auto-commit band into the propose band, or from the propose band into the auto-reject band.

**Researcher recommendations** — constraints drive the source coverage and completeness recommendations surfaced in the Person Browser. Given what is currently concluded about a Person, the system can compute which sources are eligible, which are already attached, and which gaps remain — and can flag anomalies in the existing conclusion layer that warrant researcher attention.

### 1.1 Probabilistic framing

All constraints are probabilistic weightings rather than absolute filters. A conclusion-layer linkage that violates a constraint is not automatically invalid — it is surfaced to the researcher as a flag requiring explicit verification. The researcher's judgment, expressed through the `verified` flag on the relevant junction row, always takes precedence over an algorithmically-computed penalty.

The language used throughout this document reflects this framing:

| Language | Meaning |
|---|---|
| **Near-zero probability** | Score penalty sufficient to move most candidates to auto-reject; surfaces as a strong flag if committed |
| **Significantly reduced probability** | Score penalty sufficient to move most candidates from auto-commit to propose |
| **Reduced probability** | Score penalty applied; linkage remains in propose band for researcher review |
| **Increased probability** | Positive signal; used in inference chains to support downstream conclusions |

### 1.2 Operational mode dependency

Some constraints only apply in **incremental linkage** mode, where an existing conclusion layer is available. These are noted explicitly. Constraints that apply in both modes are the default.

### 1.3 Relationship to validation rules

The hardest constraints in this document — those with near-zero probability language — are strong enough to also warrant Python validation rules. These are flagged with **[→ Validation rule candidate]** and are proposed as R40+ additions to `validation_rules.md`.

---

## 2. Chronological Constraints

### 2.1 Lifespan boundary

A `Record` linkage to a `Person` carries **near-zero probability** if the `RecordedEvent` date falls outside the Person's concluded lifespan.

Lifespan is bounded by:
- Lower bound: the Person's concluded birth `Event` date (or estimated birth year). Where no birth Event exists but a baptism Event does, the baptism date is accepted as the lower bound proxy.
- Upper bound: the Person's concluded death `Event` date (if known); otherwise unbounded.

**Age tolerance:** Birth years derived from census returns or civil death registrations carry an uncertainty of ±2 years (directly recorded ages) to ±5 years (informant-reported ages in later records). The lifespan boundary check applies this tolerance before flagging a violation.

**[→ Validation rule candidate]** A Record linkage where the RecordedEvent date is more than 5 years outside the Person's concluded lifespan bounds should be flagged for researcher review regardless of Splink score.

### 2.2 Life event sequence

For any concluded `Person`, their associated life `Event` objects must follow chronological order. Sequence violations indicate a conclusion-layer merge error.

**Mandatory sequence constraints:**

| Constraint | Description |
|---|---|
| Birth precedes baptism | Baptism date must be after or equal to birth date. Expected interval is days to weeks for infant baptism. A gap of more than 2 years is anomalous and warrants researcher attention. **Exception:** adult baptism — where the baptism RecordedPerson carries a recorded age greater than 1 year, the birth-precedes-baptism interval constraint does not apply. Adult conversion and late baptism are historically attested. |
| Birth precedes all other events | No marriage, census, residence, valuation, tithe, or military event may predate the birth event. |
| Marriage precedes death | A Person's death event must postdate any marriage event they participated in. |
| Death precedes burial | Burial date must be after or equal to death date. Expected interval is days. |
| All events precede death | No census, residence, valuation, tithe, or military event may postdate the death event. |

**Date qualifier handling:** Where an event date carries a qualifier of `about`, `estimated`, or `calculated`, the sequence check applies the applicable age tolerance before flagging a violation. A sequence cannot be confirmed violated if the uncertainty ranges of the two event dates overlap.

**[→ Validation rule candidate]** A confirmed sequence violation (non-overlapping date ranges in wrong order) should be flagged as a merge error candidate regardless of individual linkage scores.

### 2.3 Census age drift

A Person appearing in multiple census Records should show consistent age progression. The expected age delta between census years, with tolerance, is:

| Census pair | Expected delta | Tolerance |
|---|---|---|
| 1901 → 1911 | +10 years | ±3 |
| 1911 → 1926 | +15 years | ±3 |
| 1901 → 1926 | +25 years | ±4 |

A candidate pair whose age delta falls outside tolerance has a **significantly reduced probability**. It is not automatically disqualified — informant errors on age are common enough that strong agreement on other features (name, place, household members) can compensate.

*Cross-reference: this constraint is also specified in `reconstruction_algorithms.md` §5.6. The two specifications must be kept in sync. This document is the authoritative source for the genealogical rationale; `reconstruction_algorithms.md` is the authoritative source for the implementation.*

---

## 3. Event Singularity Constraints

### 3.1 Birth singularity

A concluded `Person` may have no more than one birth `Event`. Multiple birth Records in the evidence layer (e.g., a civil birth registration and a baptism record for the same individual) must be synthesised into a single birth Event. Conflicting dates are reconciled using date qualifier and source type priority:

- Civil birth registration date takes precedence over baptism date where both exist.
- The baptism record is linked to a `baptism` Event, not a second `birth` Event.

**[→ Validation rule candidate]** More than one birth Event linked to a single Person via `person_event` is a merge error candidate.

### 3.2 Death singularity

A concluded `Person` may have no more than one death `Event`. A concluded death Event does not preclude a separate burial Event.

**[→ Validation rule candidate]** More than one death Event linked to a single Person via `person_event` is a merge error candidate.

### 3.3 Marriage and serial marriage

A `couple` Relationship has exactly one primary marriage `Event`. Multiple Records corroborating the same marriage (e.g., a civil registration and a parish register entry) are synthesised into that single Event — they do not produce separate Events.

Serial marriage — a Person participating in more than one `couple` Relationship across their lifetime — is historically common in 19th-century Ireland, principally due to early widowhood. This is modelled as multiple distinct `couple` Relationships on the same Person, each with its own marriage Event. There is no constraint against a Person having more than one couple Relationship.

For serial marriage conclusions to be valid, the chronological sequence must hold: the first marriage Event must predate the death Event of the first spouse, and the second marriage Event must postdate that death Event.

**Short widowhood interval:** A gap of less than 6 months between a concluded first spouse death Event and a second marriage Event is **reduced probability**. Remarriage this quickly was not biologically impossible but was socially uncommon in 19th-century Irish Catholic practice and warrants researcher attention. It may indicate a date error in one of the underlying Records rather than a genuine rapid remarriage.

### 3.4 Census singularity

A concluded `Person` has a **near-zero probability** of being linked to more than one `Record` from the same census source (source_ids 3, 4, or 5) within their `record_ids`. Multiple linkages to the same census source signal a high probability of a merge error.

**Known exception:** Double enumeration did occur historically, most commonly for households near DED administrative boundaries. If the researcher verifies a second census linkage, the `verified` flag on the second junction row documents this judgment.

---

## 4. Source Eligibility Constraints

These constraints govern which sources are worth searching for a given Person, based on what is currently concluded about them. They are the primary input to Person Browser source coverage recommendations. All eligibility assessments are computed at query time from the Person's concluded birth year, death year, gender, and attached records.

### 4.1 Source eligibility by birth year

The following table summarises eligibility for each source given a Person's estimated birth year. Eligibility is `certain` (source coverage clearly includes the Person's active years), `possible` (Person may appear but as a minor or in a peripheral role), `ineligible` (coverage predates or postdates the Person's plausible active years), or `unknown` (insufficient birth year information to assess).

| Source | Type | Coverage | Eligibility logic |
|---|---|---|---|
| 1 — Griffith's Valuation | valuation | c.1847–1864 | Eligible if birth year ≤ 1843 (age ≥ 21 at survey; applies to `occupier` role — see §4.2). Possible if birth year 1844–1849 (age 15–20; may appear in a non-occupier capacity). Ineligible if birth year > 1849. |
| 2 — Tithe Applotment Books | tithe | 1823–1837 | Eligible if birth year ≤ 1816 (age ≥ 21 at latest survey date 1837; applies to `occupier` role). Possible if birth year 1817–1822. Ineligible if birth year > 1822. |
| 3 — Census 1901 | census | 1901 | Certain if birth year ≤ 1900 and death year unknown or > 1901. Possible if birth year 1901 (infant). Ineligible if death year < 1901 or birth year > 1901. |
| 4 — Census 1911 | census | 1911 | Certain if birth year ≤ 1910 and death year unknown or > 1911. Possible if birth year 1911 (infant). Ineligible if death year < 1911 or birth year > 1911. |
| 5 — Census 1926 | census | 1926 | Certain if birth year ≤ 1925 and death year unknown or > 1926. Possible if birth year 1926 (infant). Ineligible if death year < 1926 or birth year > 1926. |
| 6 — Civil Birth Registrations | birth_registration | 1864–1925 | Eligible if birth year in 1864–1925. Ineligible otherwise. Note: non-compliance was significant among Catholics 1864–1880 — absence of a record in this period is not conclusive evidence the Person was not born (see §4.4). |
| 7 — Civil Marriage Registrations | marriage_registration | 1845–1950 | Eligible if Person has a concluded marriage Event, or birth year suggests marriage-age years fall within 1845–1950. |
| 8 — Civil Death Registrations | death_registration | 1864–1975 | Eligible if death year unknown and birth year suggests Person could have died within 1864–1975. Ineligible if death year is concluded and falls outside coverage. |
| 9 — Catholic Parish Registers | parish_register | Typically 1820s–1880s | **Primary source for events predating civil registration.** Eligible if birth year falls within parish register coverage for the target community. Highest priority for any Person with a birth year before 1864. Coverage varies by parish — community-specific assessment required. |
| 10 — BMH Witness Statements | military | Events 1913–1921 | Eligible if birth year ≤ 1903 (age ≥ 18 in 1921) and death year unknown or > 1913. Reduced probability if no military service evidence exists. Note: statements frequently name non-participant third parties — family members, neighbours, comrades — so a Person need not have been a participant to appear. |
| 11 — Military Service Pensions | military | Service 1916–1923 | Eligible if birth year ≤ 1905 (age ≥ 18 in 1923) and death year unknown or > 1916. Reduced probability if no military service evidence exists. |
| 12 — Duchas Schools Collection | folklore | 1937–1939 | Eligible if Person is a named informant (birth year ≤ 1929, age ≥ 8 in 1937) or a named subject of a collected story. Low baseline probability — most persons are not named in folklore records. |

### 4.2 Land record occupier age constraint

A linkage between a `Person` and a Griffith's Valuation or Tithe Applotment Record in which the RecordedPerson carries the `occupier` role has a **near-zero probability** of validity if the Person's concluded birth year places them under 21 years of age at the time the record was created.

Rationale: land occupancy in this period required legal capacity. Persons under 21 could appear in land records in other roles (household member, son listed under a parent's holding, witness to a lessor arrangement) but not as the principal occupier.

This constraint applies to the `occupier` role only. It does not apply to `lessor` or other roles that may appear in land records.

### 4.3 Female occupier inference

A female `Person` linked to a Griffith's Valuation or Tithe Applotment Record in the `occupier` role is historically anomalous but not invalid. When verified, this linkage carries a strong positive inference chain:

1. The female Person is very likely a widow at the time of the record.
2. A deceased male spouse is strongly implied — a `couple` Relationship should exist or be created, with the spouse carrying a concluded death `Event` predating the land record date.
3. If no `couple` Relationship exists for this Person, the system should surface this as a recommendation to the researcher.

**Tithe amplification:** A female occupier in the Tithe Applotment Books (1823–1837) carries an even stronger widowhood signal than in Griffith's. Tithe records predate the Famine and female land occupancy at this period was extremely uncommon. The inference chain above applies with **increased probability** for Tithe source linkages.

This inference chain operates in incremental linkage mode only, where the existing relationship graph can be checked.

### 4.4 Civil registration completeness expectation

For any Person born in Ireland after 1864, the civil registration sources (6, 7, 8) represent the most reliable documentary baseline. The following expectations apply:

- A birth Record (source 6) should exist for every Person born 1864–1925. Absence after thorough search is itself evidence — it may indicate the birth was not registered, the Person was born outside the coverage period, or the birth year estimate is incorrect.
- A marriage Record (source 7) should exist for every Person with a concluded marriage Event dated 1864 or later.
- A death Record (source 8) should exist for every Person with a concluded death Event dated 1864 or later.

**Catholic non-compliance 1864–1880:** Non-compliance with civil birth registration was significantly higher among Catholics than Protestants in the earliest years of registration. Catholic priests were initially resistant to the civil system and did not always encourage registration. Absence of a civil birth record for a Catholic Person born between 1864 and 1880 is therefore less conclusive than absence for the same period among Protestants or for later decades. The researcher should be informed of this context when a Catholic birth record is absent in this window.

These are expectations, not certainties. Non-compliance, index gaps, and transcription omissions are all historically documented. The system surfaces absent expected records as researcher recommendations, not as errors.

---

## 5. Biological Plausibility Constraints

### 5.1 Minimum and maximum parent age

**Minimum parent age:** If a concluded `Person` participates in a `parent_child` Relationship as the parent, the chronological gap between the parent's concluded birth year and the child's concluded birth year must be at least 15 years, accounting for age tolerances on both. A gap below 15 years has a **near-zero probability** of biological validity. A gap between 15 and 18 years is **reduced probability** and warrants researcher attention.

**Maximum maternal age:** A female `Person` in a `parent_child` Relationship as the mother where the gap between the mother's concluded birth year and the child's concluded birth year exceeds 50 years has a **near-zero probability** of biological validity. Motherhood after age 50 is at or beyond the documented biological ceiling and should be treated as a strong merge error signal.

**Maximum paternal age:** A male `Person` in a `parent_child` Relationship as the father where the gap exceeds 70 years is **reduced probability**. Late fatherhood is biologically attested but rare enough to warrant a flag. The asymmetry between the maternal and paternal ceilings is deliberate and reflects different biological constraints.

**[→ Validation rule candidate]** A parent_child Relationship where the concluded birth year gap is less than 15 years (net of tolerances) or where the maternal gap exceeds 50 years should be flagged regardless of linkage scores.

### 5.2 Minimum marriage age

If a concluded `Person` participates in a marriage `Event`, the chronological gap between their concluded birth year and the marriage date must be at least 15 years, accounting for age tolerance.

A gap below 15 years has a **near-zero probability** and should be surfaced as a merge error candidate. Gaps between 15 and 18 years are historically attested in 19th-century Ireland but are **reduced probability** and warrant researcher attention.

**[→ Validation rule candidate]** A Person linked to a marriage Event where their concluded birth year places them under 15 at the time of marriage should be flagged.

### 5.3 Sibling birth spacing

Where two Persons are linked by a `sibling` Relationship and both have concluded birth years, the following thresholds apply:

- A gap of less than 9 months is **near-zero probability** for biological siblings. **Exception:** a gap of 0 months (same birth date) is plausible for twins and should not be flagged if both Records show the same or near-identical date.
- A gap of 9 to 12 months is **reduced probability**. Consecutive siblings within a year (sometimes called Irish twins) are historically attested and culturally recognised in Irish records of this period, but the frequency warrants researcher awareness rather than escalation.

---

## 6. Co-Residency Constraints

These constraints apply in incremental linkage mode only, where the relationship graph is populated.

### 6.1 Parent-child co-residency expectation

Where two Persons are linked by a `parent_child` Relationship and both have Records from the same census source, there is a high prior probability that the child appears in the parent's household if the child is under approximately 12 years of age at the census date.

A parent-child Relationship where census Records exist for both Persons but they do not appear in the same household Record is **reduced probability** when the child's concluded age at the census date is under 12. The threshold of 12 reflects Irish domestic service practice — children entered service or left the household for other reasons from as young as 12, making absence from the parental household increasingly normal from that age upward.

Absence may indicate:
- A merge error (the child Record has been linked to the wrong Person)
- The child was in domestic service, schooling, or otherwise absent from the household
- The parent's census Record has not yet been ingested

The system should surface this as a recommendation for researcher attention rather than a hard flag.

### 6.2 Couple co-residency expectation

Where two Persons are linked by a `couple` Relationship and Records from the same census source exist for both, there is a high prior probability that they appear in the same household Record unless one spouse has a concluded death Event predating the census.

A couple Relationship where both Persons have census Records from the same year but in different households is **reduced probability** unless a death Event accounts for the separation. The system should surface this as a recommendation.

### 6.3 Household membership consistency

Where a census Record is linked to a Person as `head`, the other RecordedPersons in that Record (spouse, children, boarders) should resolve to Persons who have concluded Relationships with the head. Unresolved household members — RecordedPersons in a head's census Record with no linked Person conclusion — represent high-value linkage targets and should be surfaced as recommendations.

---

## 7. Community and Network Constraints

### 7.1 Naming pattern consistency (GC18)

In 19th-century Irish Catholic communities, the generational naming convention was strong and broadly predictable: first son named after the paternal grandfather, second son after the maternal grandfather, first daughter after the maternal grandmother, second daughter after the paternal grandmother. This pattern was widely followed, though not universal.

This constraint functions as a positive inference tool in incremental linkage mode:

- Where a Person has a concluded `parent_child` Relationship and the child's name matches the expected naming pattern relative to a concluded grandparent, this is an **increased probability** signal supporting both the parent-child Relationship and the name link to the grandparent generation.
- In the Person Browser, this can surface as a proactive recommendation: "expected naming pattern suggests searching for a [name] in the grandparent generation of this family."

This constraint also functions as a negative disambiguation signal: where two Records contain identical names in the same townland, the existing relationship graph can be checked to determine whether generational arithmetic makes a same-Person conclusion plausible. See `reconstruction_algorithms.md` §4.3 for the full specification of the patronymic disambiguation algorithm.

*Cross-reference: `reconstruction_algorithms.md` §4.3.*

### 7.2 Witness and godparent network inference (GC19)

In Irish Catholic practice, witnesses to marriages and godparents at baptisms were almost always drawn from the immediate family or close neighbours of the principal parties. A RecordedPerson appearing in a `witness`, `godfather`, or `godmother` role in a Record is therefore a high-probability candidate for a concluded Relationship with the principal persons in that Record — typically a sibling, close cousin, or immediate neighbour.

This inference operates as a linkage recommendation in incremental linkage mode:

- Unresolved RecordedPersons in witness or godparent roles (i.e., RecordedPersons with no linked Person conclusion) represent high-value linkage targets and should be surfaced as recommendations in the Person Browser.
- Where a witness or godparent name matches a known Person in the community relationship graph, the system should propose a candidate linkage for researcher review.
- A confirmed witness or godparent linkage is **increased probability** evidence for a sibling or close-family Relationship between the witness/godparent and the principal persons in the Record.

This constraint does not generate automatic Relationship conclusions — it generates linkage recommendations for researcher judgment.

### 7.3 Occupation consistency across sources (GC20)

A Person's occupation as recorded across multiple sources should be broadly consistent, with expected progression over time. The following patterns apply:

| Pattern | Signal |
|---|---|
| Farmer's son (1901) → Farmer (1911) | Consistent — expected progression as a son inherits or acquires land |
| Labourer (1901) → Farmer (1911) | Weakly positive — upward mobility through land acquisition, attested post-Land Acts |
| Farmer (1901) → Labourer (1911) | **Reduced probability** — downward occupational mobility was uncommon except in specific post-Famine or eviction contexts |
| Professional occupation → Agricultural occupation (or vice versa) across consecutive sources | **Reduced probability** — warrants researcher attention |

Occupation inconsistency is a weak signal and should only be applied when other features score well. Occupation reversal alone should never move a linkage to auto-reject. It is surfaced as a flag rather than a penalty in most cases.

---

## 8. Record-Specific Inference Constraints

### 8.1 Death registration informant as relationship signal (GC21)

Civil death registrations (source 8) record the informant's qualification in the `informant_qualification` column — typically "son of the deceased", "daughter of the deceased", "present at death", "in attendance". Where the informant qualification asserts a family relationship, this constitutes a direct relationship assertion in the evidence layer and should be used to support or create `parent_child` or `sibling` Relationship conclusions.

Specifically:

- An informant recorded as "son of the deceased" or "daughter of the deceased" who resolves to a Person conclusion is strong evidence for a `parent_child` Relationship between that Person (as child) and the deceased Person.
- An informant recorded as "brother of the deceased" or "sister of the deceased" similarly supports a `sibling` Relationship.
- Where no Person conclusion exists for a named informant, the informant is a high-value linkage target and should be surfaced as a recommendation.

The `informant_qualification` field in source 8's column schema carries this information. The Python feature extractor for death registration sources should parse this field and generate the appropriate Relationship candidates.

### 8.2 Geographical coherence (GC22)

A Person's Records should show geographically coherent place patterns. A Person consistently associated with one townland across multiple sources who then appears in a Record from a distant county carries a **reduced probability** for that distant Record linkage unless a contextual explanation exists.

Contextual explanations that normalise geographical discontinuity include:

- Emigration: a Person disappearing from local Records after 1845–1860 with no further local evidence may have emigrated. The absence of further local Records is consistent with this conclusion.
- Internal migration: movement to Dublin, Belfast, or other urban centres was common post-Famine and increased through the late 19th century. A Person reappearing in an urban Record after a gap is historically plausible.
- Military service: a Person with military source linkages may appear in Records from any location.
- Domestic service: young women in particular moved to urban centres for service positions from the 1880s onward.

The primary mechanism for this constraint is the Splink place match score — a Record with an unresolved or mismatched `place_id` already scores lower on the place comparison feature. This constraint adds the researcher recommendation layer: where a place discontinuity exists that is not explained by the above contexts, the system should surface it for researcher attention rather than silently penalising the score.

---

## 9. Source Coverage and Completeness

This section defines the framework for computing source coverage and completeness for a Person conclusion. This is the primary input to the Person Browser source coverage display. All computations are query-time derivations — nothing in this section implies a stored field on the `person` table or any other table.

### 9.1 Source eligibility states

For each of the 12 sources, a Person's relationship to that source is one of four states:

| State | Meaning |
|---|---|
| `attached` | One or more Records from this source are linked to this Person via `person_record` |
| `eligible` | Source coverage and Person's concluded attributes make a Record plausible; no Record currently attached |
| `possible` | Source coverage overlaps with the Person's lifespan but a Record is unlikely (e.g., Person is a minor in a land record source, or source is low-density) |
| `ineligible` | Source coverage definitively excludes this Person based on concluded birth year, death year, or gender |

### 9.2 Coverage score

A Person's coverage score is the ratio of `attached` sources to `eligible + attached` sources:

```
coverage_score = attached_count / (attached_count + eligible_count)
```

A coverage score of 1.0 means all eligible sources have at least one Record attached. It does not mean the Person is fully documented — it means no known eligible sources remain unsearched.

### 9.3 Completeness signal

Completeness is a richer signal than coverage score alone. A Person is considered well-documented when:

- All eligible sources are `attached`
- The birth, marriage (if applicable), and death Events are each supported by at least two independent Records
- The derived confidence for all concluded Events and Relationships is `high`

The system may surface a "high completeness" indicator when all three conditions are met. This is advisory — the researcher remains the final authority on whether a Person conclusion is complete.

### 9.4 Incompleteness recommendations

The system generates actionable recommendations for each `eligible` source not yet attached. Recommendations are ranked by expected evidential value. The ranking is conditional on the Person's estimated birth year, since source priority differs significantly between persons active before and after 1864.

**For Persons with birth year before 1864 (pre-civil registration):**

1. **Catholic Parish Registers (9)** — highest priority; primary source for baptism, marriage, and burial events in this period
2. **Land record sources (1, 2)** — high priority; Griffith's and Tithe are the principal census substitutes
3. **Census sources (3, 4, 5)** — high priority where the Person survived to census years
4. **Civil registration sources (6, 7, 8)** — applicable only for events after 1864

**For Persons with birth year 1864 or later (civil registration period):**

1. **Civil registration sources (6, 7, 8)** — highest priority; structured, indexed, highly reliable
2. **Census sources (3, 4, 5)** — high priority; provide household and relationship context
3. **Catholic Parish Registers (9)** — high priority for baptism and marriage events where civil records are absent or incomplete
4. **Land record sources (1, 2)** — applicable for persons born before ~1843 whose active years overlap with survey coverage
5. **Military sources (10, 11)** — medium priority; only relevant where military service is evidenced or plausible
6. **Folklore collection (12)** — low priority; low density of named individuals

---

## 10. Constraint Application Summary

The following table summarises all constraints, their type, and their implementation path.

| ID | Constraint | Type | Implementation |
|---|---|---|---|
| GC01 | Lifespan boundary | Chronological | Score penalty; researcher flag |
| GC02 | Life event sequence | Chronological | Score penalty; merge error flag |
| GC03 | Census age drift | Chronological | Score penalty |
| GC04 | Birth singularity | Singularity | Merge error flag; validation rule candidate |
| GC05 | Death singularity | Singularity | Merge error flag; validation rule candidate |
| GC06 | Marriage per couple Relationship | Singularity | Score penalty |
| GC07 | Census singularity | Singularity | Score penalty; validation rule candidate |
| GC08 | Source eligibility by birth year | Source eligibility | Person Browser recommendation |
| GC09 | Land record occupier age | Source eligibility | Score penalty |
| GC10 | Female occupier inference | Source eligibility | Inference recommendation |
| GC11 | Civil registration completeness | Source eligibility | Person Browser recommendation |
| GC12 | Minimum and maximum parent age | Biological | Score penalty; validation rule candidate |
| GC13 | Minimum marriage age | Biological | Score penalty; validation rule candidate |
| GC14 | Sibling birth spacing | Biological | Score penalty |
| GC15 | Parent-child co-residency | Co-residency | Researcher recommendation (incremental mode only) |
| GC16 | Couple co-residency | Co-residency | Researcher recommendation (incremental mode only) |
| GC17 | Household membership consistency | Co-residency | Linkage target recommendation (incremental mode only) |
| GC18 | Naming pattern consistency | Community | Inference recommendation; disambiguation signal (incremental mode only) |
| GC19 | Witness and godparent network | Community | Linkage target recommendation (incremental mode only) |
| GC20 | Occupation consistency | Community | Researcher flag |
| GC21 | Death registration informant | Record-specific | Relationship candidate; linkage target recommendation |
| GC22 | Geographical coherence | Record-specific | Researcher recommendation; score context |

---

## Changelog

| Version | Date | Change |
|---|---|---|
| 1.0 | May 2026 | Initial version — GC01–GC17 |
| 1.1 | May 2026 | Added adult baptism carve-out to GC02. Added short widowhood interval signal to GC03 (§3.3). Clarified occupier role scope in GC09 and §4.1 eligibility table. Added Tithe amplification note to GC10. Added Catholic non-compliance context to GC11 and §4.1. Added maximum maternal and paternal age thresholds to GC12. Revised co-residency age threshold in GC15 from 15 to 12 years to reflect domestic service practice. Split §7 (previously Source Coverage) into §7 Community and Network Constraints, §8 Record-Specific Inference Constraints, and §9 Source Coverage and Completeness. Added GC18 (naming pattern consistency), GC19 (witness and godparent network), GC20 (occupation consistency), GC21 (death registration informant), GC22 (geographical coherence). Made source priority ranking in §9.4 conditional on birth year, with parish registers ranked highest for pre-1864 persons. Added cross-references to `reconstruction_algorithms.md` for GC03 and GC18. |

---

*Related documents: `conceptual_model.md`, `data_dictionary.md`, `repositories.md`, `validation_rules.md`, `reconstruction_algorithms.md`*

*Schema version: 2.4 — May 2026*
