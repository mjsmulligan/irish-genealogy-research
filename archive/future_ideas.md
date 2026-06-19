# GRA — Future Ideas and Deferred Features

*19 June 2026 — v1.2*
*Audience: Researcher and developer. This document collects features, capabilities, and design ideas that are not currently implemented and are not in the active work queue. Items here are not forgotten — they represent the considered direction of the system — but they are explicitly deferred to avoid scope creep in the current release cycle.*

*The primary project mandate values data analysis pipeline capabilities over reviewer UX and interface layer maintenance.*

---

## 1. Service Layer and Consumer Tier

### 1.1 Service layer (`src/service.py`)

The `ResearchService` class specified in `docs/service_api.md` is intended as the single interface through which downstream consumers read from and write to the knowledge base. It is fully designed but completely deferred.

**Prerequisite:** `flag` and `lead` tables must be added to `database_schema.md` and `schema.sql` before a service layer can be built. The DDL design is deferred — `service_api.md` is archived and no longer an active reference; the flag/lead schema will be specified when this work is unblocked.

**Scope of the service layer:**
- Research scope management (surname + townland + period filters)
- Knowledge retrieval functions (persons, households, records, relationships, events)
- Researcher signal capture (verify, reject, annotate, assert manual linkages)
- Proposal and flag surface (what the pipeline proposes; what contradictions it has detected)
- Session bootstrap queries (summary state of a research scope at session start)

### 1.2 Consumer tier

Three planned consumers, all depending on the deferred service layer:

**Claude (API consumer)** — Claude interacts with the knowledge base via the service API during research sessions to surface conclusions and receive researcher signal.

**Lovable UI** — a web-based researcher interface featuring a person browser, household viewer, proposal review queue, and flag resolution workflow.

**MCP server** — exposes the service layer as an MCP tool set for agent-based access, enabling structured service function calls.

### 1.3 Flag and lead tables

The `flag` and `lead` schema additions are needed before a service layer can surface contradictions and research suggestions. The DDL design is deferred — `service_api.md` is archived and no longer an active reference; the flag/lead schema will be specified and incorporated into `database_schema.md` and `schema.sql` when this work is unblocked.

### 1.4 Reviewer UX and Person Browser (R1-4)

Originally planned as milestone `R1-4` (Person Browser basics) to handle source coverage tracking and merge error flags. This has been deferred to future phases to keep the project's focus entirely on building data analysis pipelines rather than reviewer UX.

---

## 2. GEDCOM Export

GEDCOM 5.5.1 export materialises the conclusion layer's relationship graph for import into third-party tools (FamilySearch, Ancestry, genealogy desktop software).

**Design:**
- Each `person` conclusion → `INDI` record
- Each `relationship` of type `couple` → `FAM` record
- `parent_child` relationships populate `HUSB`, `WIFE`, `CHIL` references within `FAM` records
- Events map to standard GEDCOM tags (`BIRT`, `MARR`, `DEAT`, `CENS`, etc.)
- Source citations included via `SOUR` records referencing `source.title` and `record` URLs

**Deferred because:** Requires a complete conclusion layer (service layer + researcher review workflow) before the export is meaningful. A GEDCOM exported before proposals are reviewed would include too many low-confidence linkages.

---

## 3. GEDCOM-Seeded Research Scope

A researcher can upload their existing family tree as a GEDCOM file to match concluded Persons against the knowledge base evidence layer to surface corroboration, contradictions, and extensions.

**Design rationale (from `service_api.md §1.4`):**
