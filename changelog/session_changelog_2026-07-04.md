# Session Changelog — 4 July 2026

## R4: Headstone Inscriptions (Historic Graves) — Discovery & Design

### Context

A community-run graveyard survey (Historic Graves, `historicgraves.com`) was identified as a new potential evidence source: local volunteers photographed and transcribed headstones at St. Agatha's, a graveyard in Donegal parish, as part of a Heritage Council-funded community project (survey conducted July 2021, 923 memorials). This is a **death/memorial record type**, distinct from both the R3 parish register pipeline (baptism/marriage) and NAI census — filling a source-type gap rather than extending an existing one.

### Site investigation

- Static Drupal 7 site. No API, no bulk CSV/JSON export — data is paginated HTML (36 pages × 25 rows for St. Agatha's). Scrapable via direct page fetch.
- Licence: **CC BY-NC-ND 4.0**. Decision: treated as acceptable for internal/non-published research use (Mike's call, non-commercial community-spirit alignment); not cleared for redistribution.
- Per-grave page structure: full verbatim epitaph text, plus a structured "People commemorated" index field (name/surname/death-year).
- **Key finding: the structured index field is not exhaustive.** Sampled three grave pages (DG-SAGA-0001, 0002, 0011); in each case the structured field captured only a single "headline" person, while the epitaph text named multiple individuals — up to 7 across 3 generations on one stone (DG-SAGA-0002: John Cassidy, wife Isabelle *née* Sweeney, 5 children, each with birth and death years). All genealogically useful content — full names, lifespans, marital/filial relationships, *née* surnames, townland — lives only in the freetext epitaph, not the structured fields.
- Multi-person, multi-generation, multi-date-per-record is the norm, not the exception, for family headstones.

### Architectural design decisions

**1. Foundational layer — Repository/Source mapping.** Confirmed direct fit with existing model, no schema change:
- Repository 9: Historic Graves (`historicgraves.com`)
- Source 14: St. Agatha's, `type=headstone_inscription` (new source type vocab code — see below), one Source per graveyard, following the existing per-volume pattern used for Catholic Parish Registers (Source 9).

**2. Evidence layer — Record.** One gravestone = one Record. `event_type='burial'` — used categorically (this Record documents a burial site) rather than instantially (a single dated occurrence). `date`/`date_as_recorded`/`place_as_recorded` remain null; these are genuinely not properties of the gravestone-as-Record. `raw_text` = full epitaph, verbatim. This required no change to Rule 3 ("one event per Record") — it's the same pattern already established by census Records, which carry a single `event_type='census'` while richer conclusions (birth, marriage) are derived downstream from person-level evidence, not from the Record's own inline fields.

**3. Evidence layer — RecordedPerson.** New nullable fields, playing the same evidential role `age_as_recorded` already plays in birth-event derivation:

| Field | Type | Description |
|---|---|---|
| `event_type` | string | Primary event this evidence documents (§6.2 vocab), e.g. `death` |
| `date_as_recorded` | string | Verbatim date string for the primary event |
| `date` | date | Normalised |
| `date_qualifier` | string | §6.3 vocab |
| `secondary_event_type` | string | e.g. `birth` |
| `secondary_date_as_recorded` | string | Verbatim date string for the secondary event |
| `secondary_date` | date | Normalised |
| `secondary_date_qualifier` | string | §6.3 vocab |

Rationale for a fixed pair rather than a generalised date-array or child table: headstones overwhelmingly carry at most two dates per person (birth + death), and a third-date case has not yet been observed in real data. A more general solution (e.g. a `RecordedPersonDate` child table, considered and rejected this session) is deferred until an actual 3-date case is found in practice — deliberate deferral over speculative generality. Convention agreed: death is primary when both are present (usually the reason the stone exists); either pair may be null independently (e.g. "erected 1887" or an age-only stone use only the primary pair, or none at all).

**4. RecordedRelationship.** No vocab changes required. Existing types (`couple`, `parent_child`, `sibling`) fully cover headstone family structure, including multi-generational groupings, within a single Record (no cross-Record linkage needed, unlike the cross-census candidate-match case).

**5. Role vocabulary.** `role=deceased` (already existing) covers commemorated dead. Living dedicators ("erected by his loving family") get `role=unknown` or null — still valid person-mention evidence even without date or relationship data.

**6. Conclusion layer — deferred to implementation.** New Pass 4 in `event_resolution.py`: Death/Burial Event derivation from `RecordedPerson` date evidence, structurally mirroring the existing Pass 2 (birth-event-from-age derivation) — bucket/vote grouping, `is_primary` arbitration via Rule 9's existing singular-per-lifetime taxonomy (death/burial already covered). Noted side effect: this also gives inscribed birth years (`date_qualifier=exact`) as a competing, generally higher-quality alternative to the existing census-age-derived birth Events (`date_qualifier=calculated`) — should generally win `is_primary` under existing vote logic once implemented.

**7. Grave-level survey metadata** (survey date, contributors, grave lat/long) — agreed to live in `Record.notes` as free text rather than as new dedicated Record columns. Rationale: unique to this source type, two practical resolution paths already exist (graveyard is a known location; the source link can always be reconstructed), so dedicated schema fields were judged unnecessary overhead at this stage.

### CSV column schema (Source 14 — St. Agatha's)

One row per commemorated person; grave-level fields repeat across rows for the same grave (same convention as census `image_group` repetition):

```
grave_code, epitaph_text, survey_date, contributors, person_sequence,
name_as_recorded, role_as_recorded, sex_as_recorded,
event_type, date_as_recorded, secondary_event_type, secondary_date_as_recorded,
age_as_recorded, place_as_recorded
```

| Column | Maps to |
|---|---|
| `grave_code` | `Record.record_parameters.grave_code` (e.g. `dg-saga-0002`) |
| `epitaph_text` | `Record.raw_text` |
| `survey_date`, `contributors` | `Record.notes` |
| `person_sequence` | Row ordering within grave (name_as_recorded may be blank) |
| `name_as_recorded` | `RecordedPerson.name_as_recorded` — three-state convention (blank / `[?]` / value), consistent with R3 |
| `role_as_recorded` | `RecordedPerson.role`, mapped to controlled vocab at ingest |
| `sex_as_recorded`, `age_as_recorded`, `place_as_recorded` | `RecordedPerson` fields, unchanged from existing schema |
| `event_type`, `date_as_recorded`, `secondary_event_type`, `secondary_date_as_recorded` | New `RecordedPerson` fields (see above) |

`record_url_template`: `https://historicgraves.com/st-agatha-s/{grave_code}/grave`, `record_parameter_names: [grave_code]`.

### Not yet resolved / carried forward

- Full extraction of relationship and multi-date detail from epitaph freetext is an NLP problem against already-digitised text (no OCR/vision-LLM step needed, unlike R3) — extraction-step design deferred to a future session, same treatment as R3's transcription pipeline.
- Coverage of other graveyards relevant to the parish not yet surveyed — St. Agatha's was the only one investigated this session.
- Doc updates (data_dictionary.md, repositories.md, conceptual_model.md, database_schema.md, migration 006) designed but not yet written — see work queue items added below.

### Work queue items added

| # | Item | Priority |
|---|---|---|
| 48 | Migration 006 / schema v4.5 — add 8 new nullable `RecordedPerson` date fields (primary + secondary event_type/date_as_recorded/date/date_qualifier) for headstone and future multi-date sources. Update `data_dictionary.md` §3.3. **`conceptual_model.md` requires actual rule-text changes:** Rule 1 (Evidence cohesion) currently states event fields "live directly on the Record" and describes RecordedPerson only as a child row — needs rewriting to acknowledge RecordedPerson can itself carry event-shaped data for some source types. §4.5 (Record event fields) needs a clarifying line that Record's own event fields can serve a purely categorical role (e.g. `burial`) while specific event instances are evidenced at RecordedPerson level. §4.6 (RecordedPerson) needs the new fields described, symmetrically with §4.5. | High (R4) |
| 49 | Add `headstone_inscription` to `data_dictionary.md` §6.1 Source Types vocab. | High (R4) |
| 50 | Add Repository 9 (Historic Graves) and Source 14 (St. Agatha's) to `repositories.md`, following the per-volume Source pattern established for Catholic Parish Registers (Source 9). No structural changes needed, data only. | High (R4) |
| 51 | **Scrape St. Agatha's headstone data to CSV.** Build scraper against `historicgraves.com/graveyard/st-agatha-s/dg-saga` (36 pages, 923 memorials) producing a CSV matching the column schema above. Next session. | High (R4) |
| 52 | `src/evidence/headstone.py` — ingest pipeline, CSV → Record + RecordedPerson + RecordedRelationship. Blocked on items 48–51. | Medium (R4) |
| 53 | `event_resolution.py` Pass 4 — Death/Burial Event derivation from `RecordedPerson` date evidence, mirroring existing Pass 2 birth-event derivation. Blocked on item 48. | Medium (R4) |
| 54 | **`database_schema.md` is stale — still SQLite, not PostgreSQL.** Discovered while scoping item 48: the document is written entirely against SQLite (`PRAGMA user_version`, `sqlite3.Connection`, SQLite DDL) despite the live stack having migrated to PostgreSQL/Supabase (`psycopg2`, `DATABASE_URL`) months ago. Listed as "✅ Current" at v3.2 in the ROADMAP doc status table, but does not reflect the live schema at all. Unrelated to R4 — full rewrite against actual `psycopg2`/Postgres DDL and `SCHEMA_VERSION` conventions needed. | High |
