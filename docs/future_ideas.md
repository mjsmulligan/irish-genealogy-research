# GRA — Future Ideas and Deferred Features

*20 June 2026 — v1.3*

*This document collects features, capabilities, and design ideas that are
not currently implemented and are not in the active work queue. Items here
are not forgotten — they represent considered directions for the system —
but are explicitly deferred to avoid scope creep in the current rebuild.
The primary mandate values a working data analysis pipeline over reviewer
UX and consumer interfaces.*

---

## 1. Consumer Tier

The conclusion layer rebuild (see ROADMAP §2.3) opens the door to multiple
consumer types. The key insight from the rebuild plan is that conclusions
need not be created exclusively by a human researcher — heuristics, an LLM,
and an agent are all valid conclusion authors. This shapes what a consumer
tier looks like.

### 1.1 CLI as primary consumer (current)

The CLI (`python -m src.cli`) is the current and near-term consumer. It
drives the full pipeline and surfaces conclusions via `summary`. No changes
needed here until the conclusion layer is complete.

### 1.2 Claude as reasoning consumer

Claude interacts with the knowledge base during research sessions to reason
over conclusions, surface connections across households, and assist with
narrative outputs. The mechanism (direct DB queries vs. a structured API vs.
MCP) is an open design question deferred until the conclusion layer exists.

### 1.3 MCP server

Exposing the conclusion layer as an MCP tool set would allow agent-based
access — structured function calls for person lookup, household retrieval,
relationship traversal, and researcher signal capture. Depends on a stable
conclusion layer API.

### 1.4 Researcher UI

A web-based interface (e.g. Lovable) for proposal review, person browsing,
household viewing, and flag resolution. Explicitly deferred — the pipeline
must be stable and producing meaningful conclusions before a review UI adds
value. No design decisions have been made.

---

## 2. Researcher Signal: Flag and Lead Tables

The retired `training_labels` table was the first attempt at capturing
researcher signal (proposed linkages for review). Its retirement leaves an
open design gap: how does a researcher communicate corrections, verifications,
and research leads back into the system?

The `flag` and `lead` table concepts address this:

- **flag** — a researcher-asserted contradiction or quality concern attached
  to a Person, Relationship, or Event conclusion (e.g. "birth year
  inconsistent across sources", "two households may be the same family")
- **lead** — a researcher-noted research direction not yet actable by the
  pipeline (e.g. "check parish register for baptism in Inver 1843–1848")

The DDL design for both tables is deferred pending the conclusion layer
redesign. They will be specified and added to `database_schema.md` and
`schema.sql` when the conclusion layer is stable enough to surface the
contradictions and gaps that flags and leads would track.

---

## 3. GEDCOM Export

GEDCOM 5.5.1 export materialises the conclusion layer's relationship graph
for import into third-party tools (FamilySearch, Ancestry, genealogy desktop
software).

**Design:**
- Each `person` conclusion → `INDI` record
- Each `relationship` of type `couple` → `FAM` record
- `parent_child` relationships populate `HUSB`, `WIFE`, `CHIL` references
  within `FAM` records
- Events map to standard GEDCOM tags (`BIRT`, `MARR`, `DEAT`, `CENS`, etc.)
- Source citations included via `SOUR` records referencing `source.title`
  and `record` URLs

**Deferred because:** meaningful export requires a complete, reviewed
conclusion layer. A GEDCOM exported before researcher review would include
too many low-confidence linkages to be useful downstream.

---

## 4. GEDCOM-Seeded Research Scope

A researcher uploads their existing family tree as a GEDCOM file. GRA parses
the GEDCOM, matches its persons against the evidence layer, and surfaces
corroboration, contradictions, and extensions — using the researcher's tree
as a prior to guide reconstruction rather than building from scratch.

**Design rationale:** One Place Study methodology often starts with partial
knowledge. A researcher who already has partial trees for a townland could
dramatically accelerate the linkage phase by seeding known relationships into
the conclusion layer before the pipeline runs.

**Deferred because:** requires a stable conclusion layer and a defined
researcher signal mechanism (see §2) before GEDCOM import can interact with
the pipeline meaningfully.

---

## 5. Full-County Scale: Blocking Strategy

At Donegal 1911 scale (~168K records), exhaustive N:M comparison across all
records produces ~237B comparisons — computationally infeasible without
blocking.

**Current status:** surname blocking is identified as the highest-priority
blocker for Release 2+ scale. Post-blocking estimate: ~12M comparisons
(manageable with Splink + DuckDB).

**Deferred because:** Tullynaught/Clogher test data is small enough that
blocking is not needed to validate the pipeline. Blocking strategy design
and implementation is a Release 2 task.

