# Session Changelog — 26 June 2026

## Topic
Transcription pipeline discovery — NLI Catholic parish register HTR strategy

---

## Decisions Made

### 1. Transcription pipeline spawned as a separate repo
The `src/transcription/` scope previously planned within GRA will instead become an independent project with its own repository. Rationale:
- No coupling to GRA internals (no schema, DAL, or evidence/conclusion layer knowledge)
- Only interface with GRA is CSV output — the schemas defined 25 June 2026
- Different dependency profile (computer vision, ML, document processing)
- Reusable across other register types beyond NLI Catholic parish registers
- Different iteration cadence and potentially different contributors

The CSV schemas (register index, parish baptism, parish marriage) defined 25 June 2026 are the formal interface contract between the two repos. These are considered stable.

### 2. HTR approach — hybrid tiered pipeline
Rejected: single-tool approach (pure Transkribus, pure local model, pure vision LLM).
Adopted: **triage-first, tiered routing** — analogous to real-world archive pipeline practice where pages are categorised prior to transcription to determine which solution to apply.

**Quality tiers:**
- **Tier 1 (clean):** Local HTR model → field parser → CSV
- **Tier 2 (moderate):** Local HTR model + census confidence adjustment → CSV; low-confidence fields flagged
- **Tier 3 (degraded):** Transkribus (B2022 Irish model) → field parser → CSV; output also feeds ground truth accumulation
- **Tier 4 (irrecoverable):** Human review; bulk `[?]` with transcription note

**Key model:** Transkribus Beyond 2022 (B2022) model — trained on 759,000 words across 50 Irish archival handwriting styles including parish registers. Used for Tier 3, and as ground truth source for local model fine-tuning. Access via UI export (PAGE XML) rather than API (API requires Organisation plan).

**Local model:** Kraken — pip-installable, Python-native, full pipeline (layout + HTR), fine-tunable on accumulated ground truth, character-level confidence scores, model zoo on Zenodo.

### 3. Pipeline stage architecture
Universal across all pages regardless of tier:

1. **Image acquisition** — scriptable bulk download from NLI URL pattern per register
2. **Image QA** — quality classification and tier assignment per page
3. **Layout detection** — universal first pass; produces entry block bounding boxes. Required for all pages because coordinates are part of the CSV output contract.
4. **Tiered HTR** — routes each entry block by QA tier; input is bounding box crop
5. **Field parsing** — semantic field extraction from HTR text per entry block
6. **Confidence scoring** — census vocabulary adjustment per field (optional; degrades gracefully if vocab file absent)
7. **CSV assembly** — coordinates + parsed fields + confidence + envelope metadata → CSV row

Layout detection is universal (not just a preprocessing step for uncertain pages) because bounding box coordinates are required for every CSV row. Layout detection failure is a meaningful pipeline event — pages that fail segmentation are flagged for human review; no partial rows emitted.

### 4. Bounding box coordinates added to CSV schema
All three CSV schemas (register index, parish baptism, parish marriage) gain five new fields in the source envelope:

| Field | Type | Notes |
|---|---|---|
| `image_filename` | string | Source image file (may already exist as provenance field) |
| `bbox_x_min` | integer | Left edge, pixels |
| `bbox_y_min` | integer | Top edge, pixels |
| `bbox_x_max` | integer | Right edge, pixels |
| `bbox_y_max` | integer | Bottom edge, pixels |

Coordinate system: pixel coordinates on source image. Unit of reference: entry block (not individual fields). All five fields are nullable — layout detection failure does not block record emission, but flags the record.

Bounding box format chosen over centroid+dimensions because: (a) layout detection models output bbox natively, (b) direct mapping to image crop/highlight operations in a viewer.

### 5. Census vocabulary file — interface contract (OPEN)
GRA will export a parish-level name/place vocabulary file consumed by the transcription pipeline's confidence scoring module. The transcription pipeline checks for the file by convention (`{parish_id}_vocab.json`); if absent, confidence scoring is skipped and the pipeline continues.

**This contract is not yet finalised.** A dedicated session is required to define the file format, field structure, and purpose precisely before either side implements against it.

Preliminary sketch (starting point only, not a decision):
```json
{
  "parish_id": "vtls000631954",
  "generated_at": "2026-06-26T11:00:00Z",
  "source": "census",
  "census_years": [1901, 1911],
  "surnames": { "Doherty": 142, "Gallagher": 98 },
  "forenames_male": { "Patrick": 201, "James": 187 },
  "forenames_female": { "Mary": 198, "Bridget": 143 },
  "townlands": { "Tullynaught": 12 }
}
```

Design principles agreed:
- File existence check only — no configuration, no hard dependency
- Confidence adjustment is a signal, not a correction — transcription value never changes
- Census data used post-transcription, not at transcription time (preserves recorded-as-is contract)
- Raw counts preferred over normalised frequencies
- Gendered forename sets for accurate confidence matching
- Townlands as a separate set from surnames

GRA-side implementation: new CLI command `python -m src.cli export-vocab --parish <parish_id> --output <path>`

### 6. Proposed transcription repo module structure
```
src/
  acquisition/    # image download, register index
  qa/             # image quality classification and tier assignment
  layout/         # entry block detection, bbox output
  htr/            # local Kraken model, Transkribus export parser
  parsing/        # semantic field extraction from HTR text
  confidence/     # census vocabulary signal and adjustment
  assembly/       # CSV construction
  pipeline/       # orchestration and routing logic
  groundtruth/    # training data accumulation from Tier 3 output
```

---

## Image Quality Observations (vtls000631954 sample)

Four pages reviewed from same register, same parish, spanning ~1873–1881:

- `_031`, `_036`: Clean — white paper, clear ink, good contrast. Straightforward HTR targets.
- `_026`: Moderate — darker background, slight fade, different priest hand. Illustrates within-register handwriting variability.
- `_007`: Degraded — heavy mottling, foxing, contrast loss, bleed-through. Marginal reads even for human transcribers.

Key observation: these are **prose-block entries**, not columnar tables. Each entry is a self-contained block (record number, date, child, father, mother, sponsors, priest). No column grid. Field extraction requires semantic parsing of HTR text output, not column mapping.

---

## Open Items

- **Vocabulary file contract** — format, field structure, and purpose. Dedicated session required before either repo implements against it.
- **Field parser design** — semantic structure of baptism and marriage entry blocks. Rules-based with LLM escalation for parse failures proposed but not decided.
- **Local model bootstrapping** — what base Kraken model to start from before sufficient ground truth exists.
- **Transkribus B2022 model availability** — confirm it is accessible in the public model catalog on a free account before committing to it as the Tier 3 solution.

---

## New Work Queue Items (GRA ROADMAP)

- **Item 38:** `export-vocab` CLI command — aggregate census name/place distributions by parish, export to vocabulary file for transcription pipeline consumption. Blocked on vocabulary file contract (open item above).
- **Item 39:** Spawned transcription repo — create new GitHub repository for NLI Catholic parish register transcription pipeline. CSV schemas from 25 June 2026 as the interface contract with GRA.
