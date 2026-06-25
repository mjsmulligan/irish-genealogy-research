# Session: R3 Parish Records — Early Discovery
*25 June 2026*

## Scope

Early discovery for R3 parish records ingest. Explored the NLI Catholic parish register collection (`registers.nli.ie`), reviewed LLM transcription experiments, examined source images, and defined the parish CSV ingest schema.

---

## Key Decisions

### 1. CSV as universal ingest contract
All ingest pipelines consume CSVs. ETL producing those CSVs is a separate upstream concern. Parish records follow the same pattern as census: image → CSV (via transcription ETL) → ingest pipeline. This means the ingest pipeline does not need to know how the CSV was produced.

### 2. `/transcription` scope
Parish record transcription lives in a new `src/transcription/` scope — distinct from ingest. Transcription owns: image access, AI prompting, human review workflow, output validation. A dedicated session will design this scope. The ingest pipeline is the consumer of its output.

### 3. Transcription model: hybrid AI + human review
AI (vision LLM) does a first-pass transcription to CSV. Human reviewer verifies source fidelity against the source image. The reviewer's question is not "is this valid?" but "does this CSV row faithfully represent what is written on the page?"

### 4. Recorded-as-is is the transcription contract
The transcription layer's only job is to copy what is written. No interpretation, no disambiguation, no normalisation. Specific prohibitions discovered from image review:
- If a record has no number in the source, `record_no` is empty — not an invented prefix (the `B_` prefix in Tawnawilly CSV was a model invention)
- If a number appears twice in the source, both records get that number — not a disambiguated suffix (the `p36` suffix was a model invention)
- Illegitimate birth annotations go in `notes`, not `child_firstname` — the child name field is empty if no name was recorded; the mother's name goes in the mother fields
- `[?]` means illegible; empty means absent in source — these are distinct states

### 5. Three-file structure per register
- `{register_id}_index.csv` — one row per image page; drives transcription workflow
- `{register_id}_baptisms.csv` — baptism records
- `{register_id}_marriages.csv` — marriage records

Pages with both record types (mixed pages) produce rows in both event CSVs.

### 6. Separate baptism and marriage schemas with shared envelope
Event-specific fields differ structurally (child/parents/sponsors vs groom/bride/witnesses). Forcing them into one schema would require empty columns or role conflation — both violate recorded-as-is. The common envelope (source metadata + transcription metadata) is shared.

### 7. Sponsor modelled in both RecordedPerson role vocabulary and RecordedRelationship type vocabulary
- As a `RecordedPerson` role: `sponsor` sits alongside `head`, `servant` etc. — answers "what was this person's role in this record?"
- As a `RecordedRelationship` type: child↔sponsor dyad — answers "what is the recorded connection between these two people?"
- Semantic: "appeared as sponsor in a religious ceremony recorded in this source" — no kinship implied
- Sponsor presence is a weak kinship signal and research lead, not a confirmed relationship; any kinship inference is a downstream conclusion

### 8. Witness in marriage records is structurally parallel to sponsor in baptism records
`witness1`, `witness2` as full-name strings. Same recorded-as-is treatment.

### 9. High-resolution image URL pattern
`https://registers.nli.ie/static/high/{register_id_no_vtls}/{full_vtls_filename}.jpg`
Example: `https://registers.nli.ie/static/high/000631954/vtls000631954_004.jpg`
The `image_url_hq` field in the index CSV is a derived field from this pattern.

---

## Source Image Findings (Tawnawilly, pages 4, 6, 7, 26, 31, 36)

**Register format is free-form, not a pre-printed grid.** Each entry is a compact cluster: date + record number + child name + townland on one line, then parent names in a curly-brace grouping, then sponsor names in a curly-brace grouping, then priest initials. Format varies by priest and era.

**Absent vs illegible is a meaningful distinction.** Records 9, 10, 12 (page 4) have no parent block in the source — the priest did not record parents. This is structurally absent, not illegible. Empty field + `transcription_notes` captures this; `[?]` is reserved for illegibility only.

**Illegitimate birth convention (record 32, page 6).** The priest wrote the status annotation in the child name position, recorded the mother's name and address on the next line, and left the father fields empty. The prior CSV transcription lost the mother entirely. The transcription prompt must handle this structural variant explicitly.

**Index LLM misclassification (page 7).** The index first-pass labelled page 7 as "Marriages" but it contains baptisms. Human verification of the index `record_type` field is mandatory before committing transcription resources.

**Multiple numbering conventions within a single register (pages 26, 31, 36):**
- Two-digit sequential (most pages)
- Four-digit cumulative across volumes (page 26: records 1946–1961 — a different priest running a parish-wide cumulative count)
- Unnumbered date-headed entries (page 31: no record numbers, just date headers — the `B_` prefix was a model invention)
- Duplicate numbers (page 36: No. 122 used twice — genuine source duplication)

**Format varies substantially by priest.** Curly-brace groupings, vertical lists, date-headed blocks — all within the same 45-image register.

---

## CSV Schemas

### Register Index CSV

| Field | Type | Notes |
|---|---|---|
| `register_id` | string | e.g. `vtls000631954` |
| `parish` | string | As recorded on register |
| `diocese` | string | As recorded on register |
| `county` | string | As recorded on register |
| `page_number` | integer | Page within register |
| `image_url` | string | Viewer URL: `registers.nli.ie/pages/{register_id}_{NNN}` |
| `image_url_hq` | string | Direct image URL: `registers.nli.ie/static/high/{id_no_vtls}/{filename}.jpg` |
| `record_type` | string | `baptism` / `marriage` / `mixed` / `other` — human-verified |
| `date_range_raw` | string | As extracted, e.g. `Dec. 1872 to Jan. 1873` |
| `raw_extracted_text` | string | LLM first-pass raw text from image |
| `transcription_status` | string | `pending` / `transcribed` / `skipped` |

### Parish Baptism CSV

**Source metadata** (shared envelope):

| Field | Type | Notes |
|---|---|---|
| `register_id` | string | e.g. `vtls000631954` |
| `parish` | string | e.g. `Tawnawilly` |
| `diocese` | string | e.g. `Raphoe` |
| `county` | string | e.g. `Donegal` |
| `image_url` | string | Viewer URL for source page |
| `image_url_hq` | string | Direct high-res image URL |
| `page` | integer | Page number within register |

**Record identity:**

| Field | Type | Notes |
|---|---|---|
| `record_no` | string | As written in source, including suffixes. Empty if no number in source. |

**Event:**

| Field | Type | Notes |
|---|---|---|
| `event_date` | string | As written: `21 Jan 1873`, `Jun 1873`, `Jan 1873` all valid |
| `event_type` | string | Fixed: `baptism` |

**Child:**

| Field | Type | Notes |
|---|---|---|
| `child_firstname` | string | As written. Empty if no name recorded (e.g. illegitimate births). |
| `child_surname` | string | As written. Nullable — many registers do not record it. |
| `child_gender` | string | As written or inferred from register column, if present. Nullable. |

**Father:**

| Field | Type | Notes |
|---|---|---|
| `father_firstname` | string | As written. Empty if absent in source. |
| `father_surname` | string | As written. Empty if absent in source. |

**Mother:**

| Field | Type | Notes |
|---|---|---|
| `mother_firstname` | string | As written. Empty if absent in source. |
| `mother_surname` | string | As written. Some registers record maiden name, some married name — not interpreted at transcription stage. |

**Sponsors** (full-name strings, not split):

| Field | Type | Notes |
|---|---|---|
| `sponsor1` | string | Full name as written |
| `sponsor2` | string | Full name as written |
| `sponsor3` | string | Full name as written. Nullable. |
| `sponsor4` | string | Full name as written. Nullable. |

**Annotations:**

| Field | Type | Notes |
|---|---|---|
| `townland` | string | As written. Nullable — many registers record it sparsely or not at all. |
| `priest` | string | As written, all variants preserved |
| `notes` | string | Free-text annotations from the register as written: `Illegitimate`, `Vagus`, `deceased`, etc. |
| `transcription_notes` | string | Transcriber observations about source structure: e.g. "no parent block in source", "illegitimate birth — mother recorded in header position". Not source content. |

**Transcription metadata** (shared envelope):

| Field | Type | Notes |
|---|---|---|
| `transcription_source` | string | e.g. `claude_vision_v1`, `human`, `hybrid_claude_human` |
| `transcription_date` | string | ISO 8601 date |
| `review_status` | string | `raw` / `reviewed` / `verified` |

---

### Parish Marriage CSV

**Source metadata** — identical to baptism envelope.

**Record identity** — identical to baptism.

**Event:**

| Field | Type | Notes |
|---|---|---|
| `event_date` | string | As written |
| `event_type` | string | Fixed: `marriage` |

**Parties:**

| Field | Type | Notes |
|---|---|---|
| `groom_firstname` | string | As written |
| `groom_surname` | string | As written |
| `bride_firstname` | string | As written |
| `bride_surname` | string | As written. In Catholic registers typically pre-marriage (maiden) surname — not interpreted at transcription stage. |

**Witnesses** (full-name strings):

| Field | Type | Notes |
|---|---|---|
| `witness1` | string | Full name as written |
| `witness2` | string | Full name as written |

**Annotations:**

| Field | Type | Notes |
|---|---|---|
| `priest` | string | As written |
| `notes` | string | Free-text annotations as written |
| `transcription_notes` | string | Transcriber structural observations |

**Transcription metadata** — identical to baptism envelope.

---

## Evidence Model Implications

### New role vocabulary
`sponsor` added to `RecordedPerson` role vocabulary alongside `head`, `servant`, `visitor` etc.

### New relationship type vocabulary
`sponsor` added to `RecordedRelationship` type vocabulary. Semantic: "appeared as sponsor in a religious ceremony recorded in this source." No kinship implied. Child↔sponsor dyad is a research lead, not a confirmed relationship.

`witness` added to `RecordedRelationship` type vocabulary for marriage records. Parallel treatment to sponsor.

### Ingest pipeline mirrors census pipeline
Parish baptism ingest: Record (the register entry) → RecordedPersons (child, father, mother, sponsor×n) → RecordedRelationships (child→father, child→mother, child→sponsor×n). Same Person/Relationship/Event conclusion pipeline applies downstream.

### Open design thread
How the baptism record (strongest possible birth event evidence) interacts with the birth Event conclusion is deferred. A transcribed baptism is more direct evidence than a census-inferred birth year — the conclusion layer will need to handle source weighting when both exist for the same person.

---

## Scope Decisions (Deferred)

- Universal BMD schema: deferred until more register types are ingested and cross-source patterns emerge
- `/transcription` scope design: dedicated session
- Ingest pipeline implementation for parish records: after transcription scope is designed
- `src/evidence/census.py` rename (it is source-specific, not generic): noted, deferred

