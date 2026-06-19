# Irish Genealogy Research — Service API

*Version 1.0 — May 2026*
*Audience: Developers and system architects. This document specifies the service layer that exposes the knowledge base to all consumers. Read `conceptual_model.md`, `data_dictionary.md`, `database_schema.md`, and `reconstruction_algorithms.md` first.*

---

## 1. Architecture and Scope

### 1.1 Position in the three-tier architecture

The system is organised into three tiers:

```
┌─────────────────────────────────────────────────────────┐
│  CONSUMER TIER                                          │
│  Claude (API)   Lovable UI   MCP Server   Future        │
└──────────────────────┬──────────────────────────────────┘
                       │  service_api.py
┌──────────────────────▼──────────────────────────────────┐
│  SERVICE TIER                                           │
│  Research scope   Knowledge retrieval   Researcher      │
│  Evidence queries   Pipeline state      signal          │
│  Session bootstrap  Leads               Conventions     │
└──────────────────────┬──────────────────────────────────┘
                       │  db.py / DataStore
┌──────────────────────▼──────────────────────────────────┐
│  CORE TIER                                              │
│  SQLite (irish_genealogy.db)   Python DataStore         │
│  validator.py   reconstruction.py   schema.sql          │
└─────────────────────────────────────────────────────────┘
```

The service layer is the single interface through which all consumers read from and write to the knowledge base. Consumers do not call `db.py`, `validator.py`, or `reconstruction.py` directly. The service layer owns the translation between what consumers ask and what the database contains.

### 1.2 Two distinct operational paths

The system has two fundamentally different kinds of operations that must not be conflated:

**Back-office operations** — ingest, reconstruction, validation. These are deliberate, periodic, researcher-controlled operations that change what the knowledge base contains. They are batch-oriented, run directly in Python by the researcher, and are not exposed through the service API. The reconstruction pipeline (Splink, place resolution, person linkage, relationship inference) lives entirely in this path. When the pipeline runs, it writes conclusions, scores, and proposals directly to the database.

**Service API operations** — everything consumers need during a research session. This is what this document specifies. The service API is the research assistant interface: it reads the knowledge base, surfaces what the system has concluded, presents what is proposed or flagged, and captures the researcher's signal in return.

The service API does not trigger reconstruction. It does not run Splink. It does not ingest Records. Its write surface is intentionally narrow: researcher signals (verify, reject, annotate) and manual conclusion assertions where the researcher judges that the pipeline has missed something.

### 1.3 The research assistant model

The system is an active research collaborator, not a passive data store. The reconstruction pipeline does the mechanical work of genealogy at scale — transcribing patterns, linking records, inferring relationships, flagging contradictions. The service API is how that work is presented and how the researcher interacts with it.

The researcher's role resembles peer review more than authorship. The system proposes; the researcher reviews. The `verified` flag on a linkage is not a higher evidential standard — it is simply a signal that a human has looked at that specific finding. Much of the knowledge base will be unverified and still useful; verification is selective, not mandatory.

A research session typically begins with a **research scope** — a bounded question like "tell me about the Mulligans of Tullynaught" or "what do we know about this household in the 1901 census?" — and the service API organises its responses around that scope.

### 1.4 Known future extension: GEDCOM-seeded scope

A planned v2 capability is the ability to upload a personal GEDCOM file as the seed for a research scope. Instead of filtering the knowledge base by surname and townland, the researcher would provide their existing family tree and ask: "what does the knowledge base know about these people?" The system would match the GEDCOM's concluded Persons against its own evidence layer and surface corroboration, contradictions, and extensions.

This is documented here because it shapes the design of the research scope concept in v1. Research scope is a first-class object in the API — not merely a query parameter — so that v2 can introduce GEDCOM-seeded scope without an architectural rewrite. V1 scope is filter-based (surname, townland, period); v2 scope is conclusion-seeded (a set of Persons the researcher already believes in).

---

## 2. Conventions

### 2.1 Function signatures

All service functions are methods on a `ResearchService` class instantiated with an open database connection:

```python
from src.service import ResearchService

svc = ResearchService(conn)  # conn from open_db()
```

Functions follow consistent patterns:

- **Lookups by ID** return a dict or `None`.
- **Searches and queries** return a list of dicts, empty list if nothing found.
- **Summaries** return a structured dict with named sections.
- **Researcher signals** return a `SignalResult` dict with `ok: bool` and `error: str | None`.

### 2.2 Hydration levels

Functions that return collections support two hydration levels via an optional `hydration` parameter:

- `"summary"` (default) — primary key, label/name, derived confidence band, record count. Suitable for lists and session bootstrap.
- `"full"` — all fields including assembled junction arrays, all linkage scores. Suitable for detailed inspection of a single object.

Single-object fetches by ID always return full hydration.

### 2.3 Research scope parameter

Functions that are scope-aware accept an optional `scope` dict. If omitted, the function operates across the full knowledge base. Scope filters are additive (AND logic).

```python
scope = {
    "surname":    str | None,     # normalised surname to filter on
    "townland":   str | None,     # place name or place_id
    "place_id":   int | None,     # resolved Place conclusion ID (preferred over townland string)
    "period_from": int | None,    # earliest year of interest (inclusive)
    "period_to":   int | None,    # latest year of interest (inclusive)
    "source_ids":  list[int] | None,  # restrict to specific Sources
}
```

Future versions will extend this dict to support `"gedcom_persons": list[dict]` as a conclusion-seeded scope.

### 2.4 Confidence bands

Derived confidence is returned as a string band: `"high"`, `"medium"`, or `"low"`. The derivation is provisional (record count only) until the full derivation function is specified — see `reconstruction_algorithms.md` §1.4. The band is always labelled `"confidence_provisional": true` in return dicts until the derivation function is finalised.

### 2.5 Error handling

All functions return normally or raise a `ServiceError` (a thin wrapper around a message string and an optional cause). Callers should catch `ServiceError` and treat it as a user-facing message. Database constraint errors that escape the service layer are a bug, not a `ServiceError`.

```python
class ServiceError(Exception):
    def __init__(self, message: str, cause: Exception | None = None):
        self.message = message
        self.cause = cause
```

### 2.6 Pagination

Functions returning potentially large collections accept `limit: int = 50` and `offset: int = 0`. Default limit is 50. Pass `limit=0` to return all results (use with care on large datasets).

---

## 3. Research Scope

### 3.1 `describe_scope(scope, conn) -> dict`

Returns a high-level description of what the knowledge base contains within the given scope. This is the natural entry point for a research session — it answers "what do we have on this?" before any detailed queries.

```python
def describe_scope(scope: dict, conn) -> dict:
```

**Returns:**

```python
{
    "scope":              dict,   # the scope as interpreted
    "person_count":       int,    # concluded Persons in scope
    "record_count":       int,    # Records in scope (linked + unlinked)
    "unlinked_records":   int,    # Records not yet linked to any Person
    "source_coverage":    list[dict],  # one entry per Source represented
        # { source_id, title, type, record_count, coverage }
    "place_coverage":     list[dict],  # resolved Places in scope
        # { place_id, name, record_count }
    "confidence_summary": dict,   # { high: int, medium: int, low: int }
        # counts of Person conclusions by confidence band
    "lead_count":         int,    # number of open leads in scope
    "flag_count":         int,    # number of active flags in scope
}
```

**Example:**

```python
scope = {"surname": "mulligan", "place_id": 7}
summary = svc.describe_scope(scope)
# → "14 concluded Persons, 87 Records across 5 sources, 12 unlinked Records,
#    3 open leads, 1 active flag"
```

---

## 4. Knowledge Retrieval

These functions answer "what do we know about X?" — returning concluded objects from the conclusion layer with their supporting evidence and derived confidence.

### 4.1 `get_person(person_id, conn) -> dict | None`

Returns a fully hydrated Person conclusion including all linked Records (with scores), all Events, all Relationships, and all names. Returns `None` if not found.

```python
def get_person(person_id: int, conn) -> dict | None:
```

**Returns** (full hydration):

```python
{
    "person_id":            int,
    "label":                str,
    "gender":               str | None,
    "names":                list[dict],   # { value, type }
    "confidence":           str,          # "high" / "medium" / "low"
    "confidence_provisional": bool,
    "record_linkages":      list[dict],   # { record_id, score, score_version, verified, source_title, raw_text_preview }
    "relationships":        list[dict],   # { relationship_id, type, other_person_id, other_person_label, confidence }
    "events":               list[dict],   # { event_id, type, date, date_qualifier, place_name }
    "notes":                str | None,
    "private":              bool,
}
```

### 4.2 `search_persons(scope, conn, hydration, limit, offset) -> list[dict]`

Returns Person conclusions matching the scope. The primary search function for building lists of people.

```python
def search_persons(
    scope: dict,
    conn,
    hydration: str = "summary",
    limit: int = 50,
    offset: int = 0
) -> list[dict]:
```

**Summary hydration returns:**

```python
{
    "person_id":    int,
    "label":        str,
    "names":        list[str],    # name values only
    "confidence":   str,
    "record_count": int,
    "birth_year":   int | None,   # derived from linked Records
    "place_name":   str | None,   # primary resolved Place name
}
```

### 4.3 `get_relationship(relationship_id, conn) -> dict | None`

Returns a fully hydrated Relationship conclusion.

```python
def get_relationship(relationship_id: int, conn) -> dict | None:
```

**Returns:**

```python
{
    "relationship_id":  int,
    "type":             str,
    "person_1":         dict,   # { person_id, label }
    "person_2":         dict,   # { person_id, label }
    "confidence":       str,
    "confidence_provisional": bool,
    "record_linkages":  list[dict],   # { record_id, score, verified, source_title }
    "events":           list[dict],   # events on this Relationship (e.g. marriage)
    "notes":            str | None,
}
```

### 4.4 `get_event(event_id, conn) -> dict | None`

Returns a fully hydrated Event conclusion.

```python
def get_event(event_id: int, conn) -> dict | None:
```

**Returns:**

```python
{
    "event_id":         int,
    "type":             str,
    "date":             str | None,
    "date_qualifier":   str | None,
    "place":            dict | None,   # { place_id, name }
    "confidence":       str,
    "confidence_provisional": bool,
    "persons":          list[dict],    # { person_id, label }
    "relationship":     dict | None,   # { relationship_id, type } if present
    "record_linkages":  list[dict],    # { record_id, score, verified, source_title }
    "recorded_events":  list[dict],    # { recorded_event_id, date_as_recorded, place_as_recorded }
    "notes":            str | None,
}
```

### 4.5 `get_place(place_id, conn) -> dict | None`

Returns a fully hydrated Place conclusion.

```python
def get_place(place_id: int, conn) -> dict | None:
```

**Returns:**

```python
{
    "place_id":         int,
    "name":             str,
    "townland_ie_url":  str | None,
    "logainm_id":       int | None,
    "logainm_url":      str | None,
    "record_count":     int,
    "record_linkages":  list[dict],   # { record_id, score, verified, source_title }
    "notes":            str | None,
}
```

### 4.6 `get_family_network(person_id, conn, depth) -> dict`

Returns the relationship graph centred on a Person up to `depth` degrees. The primary function for building a narrative picture of a family — parents, children, siblings, spouses, and their connections.

```python
def get_family_network(
    person_id: int,
    conn,
    depth: int = 2
) -> dict:
```

**Returns:**

```python
{
    "root_person_id":   int,
    "depth":            int,
    "persons":          list[dict],       # summary hydration for each Person in the network
    "relationships":    list[dict],       # all Relationships within the network
        # { relationship_id, type, person_id_1, person_id_2, confidence }
    "events":           list[dict],       # key Events (births, marriages, deaths) in the network
}
```

---

## 5. Evidence Queries

These functions answer questions about the evidence layer — what Records exist, what they contain, and how they relate to conclusions.

### 5.1 `get_record(record_id, conn) -> dict | None`

Returns a fully hydrated Record including its RecordedEvent, all RecordedPersons, the constructed deep link URL, and any conclusion linkages.

```python
def get_record(record_id: int, conn) -> dict | None:
```

**Returns:**

```python
{
    "record_id":        int,
    "source":           dict,   # { source_id, title, type }
    "raw_text":         str,
    "record_url":       str | None,   # constructed deep link; null if source has no template
    "recorded_event":   dict,         # { type, date_as_recorded, date, date_qualifier, place_as_recorded }
    "recorded_persons": list[dict],   # { recorded_person_id, name_as_recorded, role, age_as_recorded, age, occupation_as_recorded }
    "linked_persons":   list[dict],   # { person_id, label, score, verified }
    "linked_events":    list[dict],   # { event_id, type, date, score, verified }
    "linked_places":    list[dict],   # { place_id, name, score, verified }
    "notes":            str | None,
}
```

### 5.2 `search_records(scope, conn, hydration, limit, offset) -> list[dict]`

Returns Records matching the scope. Useful for browsing the evidence layer within a research context.

```python
def search_records(
    scope: dict,
    conn,
    hydration: str = "summary",
    limit: int = 50,
    offset: int = 0
) -> list[dict]:
```

**Summary hydration returns:**

```python
{
    "record_id":        int,
    "source_title":     str,
    "source_type":      str,
    "date":             str | None,
    "place_as_recorded": str | None,
    "principal_names":  list[str],    # name_as_recorded for principal RecordedPersons
    "linked":           bool,         # whether linked to at least one Person conclusion
}
```

### 5.3 `get_unlinked_records(scope, conn, limit, offset) -> list[dict]`

Returns Records within scope that are not linked to any Person conclusion. These are the primary candidates for the next reconstruction pass — the unworked evidence.

```python
def get_unlinked_records(
    scope: dict,
    conn,
    limit: int = 50,
    offset: int = 0
) -> list[dict]:
```

Returns summary hydration as per `search_records`.

### 5.4 `get_records_for_person(person_id, conn) -> list[dict]`

Returns all Records linked to a Person, ordered by score descending. Useful for auditing the evidence base for a specific conclusion.

```python
def get_records_for_person(person_id: int, conn) -> list[dict]:
```

Returns full hydration as per `get_record` for each linked Record.

---

## 6. Pipeline State

These functions expose what the reconstruction pipeline has produced — its conclusions, its proposals, and its flags. This is the primary interface for reviewing the system's automated research output.

### 6.1 `get_proposals(scope, conn, limit, offset) -> list[dict]`

Returns linkage proposals from the pipeline that are within the propose band (score 0.30–0.85) and have not yet been acted on by the researcher. These are the system's "I think this might be true, please check" items.

```python
def get_proposals(
    scope: dict,
    conn,
    limit: int = 50,
    offset: int = 0
) -> list[dict]:
```

**Returns:**

```python
[{
    "proposal_type":    str,   # "person_record" | "relationship_record" | "event_record" | "place_record"
    "subject_id":       int,   # person_id / relationship_id / event_id / place_id
    "subject_label":    str,
    "record_id":        int,
    "record_summary":   dict,  # { source_title, date, place_as_recorded, principal_names }
    "score":            float,
    "score_version":    str,
    "verified":         int,   # always 0 for proposals
}]
```

### 6.2 `get_flags(scope, conn, limit, offset) -> list[dict]`

Returns active flags raised by the pipeline — contradictions, anomalies, and items requiring researcher attention. Flags are distinct from proposals: a proposal says "I think these match"; a flag says "something here doesn't add up."

```python
def get_flags(
    scope: dict,
    conn,
    limit: int = 50,
    offset: int = 0
) -> list[dict]:
```

**Returns:**

```python
[{
    "flag_id":          int,
    "flag_type":        str,   # see §6.4 for flag type vocabulary
    "severity":         str,   # "contradiction" | "anomaly" | "attention"
    "subject_type":     str,   # "person" | "record" | "relationship" | "event"
    "subject_id":       int,
    "subject_label":    str,
    "description":      str,   # human-readable explanation of the flag
    "record_ids":       list[int],   # Records involved in the flag
    "created_at":       str,   # ISO 8601 datetime
    "resolved":         bool,
}]
```

### 6.3 `get_auto_committed(scope, conn, limit, offset) -> list[dict]`

Returns linkages that the pipeline committed automatically (score ≥ 0.85) but that have not been researcher-verified. These represent the bulk of the pipeline's high-confidence work. The researcher can scan this list to spot-check the system's conclusions.

```python
def get_auto_committed(
    scope: dict,
    conn,
    limit: int = 50,
    offset: int = 0
) -> list[dict]:
```

Returns the same shape as `get_proposals` but filtered to `score >= 0.85` and `verified = 0`.

### 6.4 Flag type vocabulary

| Code | Severity | Description |
|---|---|---|
| `date_contradiction` | contradiction | Two Records linked to the same Event have incompatible dates |
| `age_contradiction` | contradiction | Age on a Record is inconsistent with the concluded birth year for the linked Person |
| `duplicate_person` | contradiction | Two Person conclusions share enough features to be potentially the same individual |
| `lifespan_violation` | contradiction | A concluded Event date falls outside the possible lifespan of the linked Person |
| `parent_age_anomaly` | anomaly | A concluded parent_child Relationship implies an implausible parental age |
| `unresolved_place` | attention | A Record contains a place string that could not be resolved to any Place conclusion |
| `orphaned_record` | attention | A Record remains unlinked after a reconstruction pass in which similar Records were linked |
| `low_source_coverage` | attention | A concluded Person has records from only one source type; corroboration from other sources is possible but absent |

---

## 7. Leads

Leads are the system's proactive output — findings it considers worth the researcher's attention that are not errors or contradictions. Where flags say "something is wrong", leads say "here is something interesting."

### 7.1 `get_leads(scope, conn, limit, offset) -> list[dict]`

Returns open leads within scope, ordered by the system's estimate of research value.

```python
def get_leads(
    scope: dict,
    conn,
    limit: int = 20,
    offset: int = 0
) -> list[dict]:
```

**Returns:**

```python
[{
    "lead_id":          int,
    "lead_type":        str,   # see §7.2 for lead type vocabulary
    "title":            str,   # short human-readable summary, e.g. "3 unlinked 1901 census Records match the Mulligan family pattern"
    "description":      str,   # fuller explanation of why this lead is interesting
    "subject_type":     str | None,
    "subject_id":       int | None,
    "subject_label":    str | None,
    "record_ids":       list[int],
    "estimated_value":  str,   # "high" | "medium" | "low" — system's estimate of research value
    "created_at":       str,
    "resolved":         bool,
}]
```

### 7.2 Lead type vocabulary

| Code | Description |
|---|---|
| `unlinked_cluster` | A cluster of unlinked Records in scope that pattern-match an existing Person or family |
| `extension_candidate` | An existing Person conclusion may be extendable — Records in another source suggest the same individual at a different life stage |
| `relationship_candidate` | Two Person conclusions in scope have co-occurring Records suggesting a Relationship not yet asserted |
| `new_person_candidate` | Unlinked Records suggest a Person conclusion that the pipeline did not create — possible gap in reconstruction coverage |
| `corroboration_available` | A conclusion with `low` confidence has potential corroborating Records in a source not yet fully linked |

### 7.3 `resolve_lead(lead_id, resolution, conn) -> SignalResult`

Marks a lead as resolved. The researcher uses this to indicate they have followed up on the lead, whether or not it led to new conclusions.

```python
def resolve_lead(
    lead_id: int,
    resolution: str,   # "followed_up" | "not_relevant" | "deferred"
    conn
) -> SignalResult:
```

---

## 8. Researcher Signal

These functions capture the researcher's response to the system's output. The write surface is intentionally narrow — the researcher signals agreement, disagreement, or annotation. The system does the rest.

### 8.1 `verify_linkage(junction_table, subject_id, record_id, conn) -> SignalResult`

Sets `verified = 1` on a specific linkage junction row. This is the primary positive signal: "I have reviewed this and agree."

```python
def verify_linkage(
    junction_table: str,   # "person_record" | "relationship_record" | "event_record" | "place_record"
    subject_id: int,
    record_id: int,
    conn
) -> SignalResult:
```

**Returns:**

```python
{
    "ok":       bool,
    "error":    str | None,
}
```

### 8.2 `reject_linkage(junction_table, subject_id, record_id, reason, conn) -> SignalResult`

Removes a linkage and records the reason. Used when the researcher disagrees with a pipeline proposal or auto-committed linkage. The Record is returned to unlinked status for the relevant junction type. The rejection reason is stored in the notes field of the relevant conclusion object.

```python
def reject_linkage(
    junction_table: str,
    subject_id: int,
    record_id: int,
    reason: str,
    conn
) -> SignalResult:
```

### 8.3 `annotate(obj_type, obj_id, note, conn) -> SignalResult`

Appends a researcher note to a conclusion object. Notes accumulate — they are not replaced, they are appended with an ISO 8601 timestamp prefix. This is the primary mechanism for the researcher to record reasoning that the system cannot infer.

```python
def annotate(
    obj_type: str,   # "person" | "relationship" | "event" | "place" | "record"
    obj_id: int,
    note: str,
    conn
) -> SignalResult:
```

### 8.4 `assert_linkage(junction_table, subject_id, record_id, conn) -> SignalResult`

Manually asserts a linkage that the pipeline did not produce — the researcher's judgment that a Record belongs to a particular conclusion. The linkage is committed with `score = null`, `score_version = null`, and `verified = 1`. A null score distinguishes manually-asserted linkages from algorithmically-scored ones.

```python
def assert_linkage(
    junction_table: str,
    subject_id: int,
    record_id: int,
    conn
) -> SignalResult:
```

### 8.5 `create_person(label, gender, names, notes, conn) -> dict`

Creates a new Person conclusion manually. Used when the researcher identifies an individual from the evidence that the pipeline did not create a conclusion for. Returns the new Person dict (full hydration). The new Person has no record linkages — these are added separately via `assert_linkage`.

```python
def create_person(
    label: str,
    conn,
    gender: str | None = None,
    names: list[dict] | None = None,   # [{ "value": str, "type": str }]
    notes: str | None = None,
) -> dict:
```

### 8.6 `create_relationship(type, person_id_1, person_id_2, conn, notes) -> dict`

Creates a new Relationship conclusion manually. Used when the researcher asserts a connection the pipeline did not infer. Returns the new Relationship dict.

```python
def create_relationship(
    type: str,
    person_id_1: int,
    person_id_2: int,
    conn,
    notes: str | None = None,
) -> dict:
```

### 8.7 `resolve_flag(flag_id, resolution, conn) -> SignalResult`

Marks a flag as resolved. Resolution options reflect the possible outcomes: the flag identified a real problem that has been corrected, or the flag was a false positive.

```python
def resolve_flag(
    flag_id: int,
    resolution: str,   # "corrected" | "false_positive" | "deferred"
    conn
) -> SignalResult:
```

---

## 9. Session Bootstrap

These functions exist specifically to support Claude sessions. A Claude session has no persistent memory — at the start of every session, Claude must load sufficient context to be a useful research assistant. These functions provide that context efficiently, without requiring Claude to issue many individual queries.

### 9.1 `get_session_context(scope, conn) -> dict`

Returns a structured context object suitable for injection into a Claude session prompt. It is designed to answer: "what does this research assistant need to know before they can help?" in a single call.

```python
def get_session_context(scope: dict, conn) -> dict:
```

**Returns:**

```python
{
    "scope_summary":        str,   # human-readable description of the scope
    "knowledge_summary":    dict,  # from describe_scope()
    "key_persons":          list[dict],  # up to 20 highest-confidence Persons in scope, summary hydration
    "key_relationships":    list[dict],  # up to 10 highest-confidence Relationships in scope
    "open_proposals":       int,   # count only — detail fetched on demand
    "active_flags":         list[dict],  # all active flags in scope (full detail — usually few)
    "top_leads":            list[dict],  # top 5 leads by estimated value
    "unlinked_record_count": int,
    "source_coverage":      list[dict],  # from describe_scope()
    "schema_version":       str,   # e.g. "2.4"
    "bootstrap_timestamp":  str,   # ISO 8601
}
```

The context object is intentionally bounded. It provides enough for Claude to understand what the research is about and what needs attention, without loading the entire knowledge base. Claude fetches detail on demand using other service functions as the session develops.

### 9.2 `summarise_person_for_session(person_id, conn) -> str`

Returns a prose summary of a Person conclusion suitable for inclusion in a Claude session prompt or response. The summary includes the Person's names, estimated birth year, place, known relationships, and the evidence base (source types and record count). This is the narrative form of `get_person`.

```python
def summarise_person_for_session(person_id: int, conn) -> str:
```

**Example output:**

```
John Mulligan (Boyle 1890) — male, b. ~1862, Straness, Co. Roscommon.
Confidence: medium (2 Records, 2 source types).
Names: John Mulligan (birth name).
Relationships: couple with Mary Brennan (Boyle 1890) [marriage 1890, confidence medium].
  parent_child with Patrick Mulligan (b. ~1894) [confidence low, 1 Record].
Evidence: Civil Marriage Registration 1890 (score 0.91, verified); Census 1901 (score 0.88, unverified).
Notes: Father Patrick Mulligan named in marriage record — not yet concluded as Person.
```

### 9.3 `summarise_scope_for_session(scope, conn) -> str`

Returns a prose summary of the current research scope suitable for inclusion in a Claude session prompt. Covers what the scope covers, what the system has found, and what the most pressing items of attention are.

```python
def summarise_scope_for_session(scope: dict, conn) -> str:
```

**Example output:**

```
Research scope: Mulligan surname, Tullynaught townland.
Knowledge base contains 14 concluded Persons, 87 Records across 5 sources (Griffith's Valuation,
Tithe Applotment, Census 1901, Census 1911, Civil Birth Registrations).
Confidence distribution: 3 high, 7 medium, 4 low.
12 Records are unlinked — most are from the 1901 census and may extend existing Person conclusions.
Active flags: 1 contradiction (age inconsistency on Patrick Mulligan, person_id=42).
Top lead: 3 unlinked 1901 census Records match the Mulligan household pattern — likely candidates
for extension of existing family network.
```

---

## 10. Implementation Notes

### 10.1 File location

```
src/
  service.py   — ResearchService class; all functions in this document
```

### 10.2 Transaction handling

All write operations (§8) execute within a single SQLite transaction. If any step fails, the transaction is rolled back and a `ServiceError` is raised. The database is never left in a partial state by a service layer write.

### 10.3 Flags and leads table

Flags and leads require a dedicated storage table not currently in `database_schema.md`. These tables should be added in a `database_schema.md` v2.5 update:

```sql
CREATE TABLE flag (
    flag_id         INTEGER PRIMARY KEY,
    flag_type       TEXT    NOT NULL,
    severity        TEXT    NOT NULL CHECK (severity IN ('contradiction', 'anomaly', 'attention')),
    subject_type    TEXT    NOT NULL,
    subject_id      INTEGER NOT NULL,
    description     TEXT    NOT NULL,
    created_at      TEXT    NOT NULL,   -- ISO 8601
    resolved        INTEGER NOT NULL DEFAULT 0 CHECK (resolved IN (0, 1)),
    resolution      TEXT,
    notes           TEXT
);

CREATE TABLE lead (
    lead_id             INTEGER PRIMARY KEY,
    lead_type           TEXT    NOT NULL,
    title               TEXT    NOT NULL,
    description         TEXT    NOT NULL,
    subject_type        TEXT,
    subject_id          INTEGER,
    estimated_value     TEXT    NOT NULL CHECK (estimated_value IN ('high', 'medium', 'low')),
    created_at          TEXT    NOT NULL,   -- ISO 8601
    resolved            INTEGER NOT NULL DEFAULT 0 CHECK (resolved IN (0, 1)),
    resolution          TEXT,
    notes               TEXT
);

CREATE TABLE flag_record (
    flag_id     INTEGER NOT NULL REFERENCES flag (flag_id),
    record_id   INTEGER NOT NULL REFERENCES record (record_id),
    PRIMARY KEY (flag_id, record_id)
);

CREATE TABLE lead_record (
    lead_id     INTEGER NOT NULL REFERENCES lead (lead_id),
    record_id   INTEGER NOT NULL REFERENCES record (record_id),
    PRIMARY KEY (lead_id, record_id)
);
```

### 10.4 Relationship to back-office operations

The service API does not call reconstruction functions. However, the back-office reconstruction pipeline writes flags and leads to the database as part of its output, making them available to `get_flags` and `get_leads` immediately after a reconstruction pass. The pipeline is also responsible for creating `auto_committed` linkages — the service API reads these but does not create them.

### 10.5 Validation on write

All service layer write operations call `DataStore.validate_object()` before committing. Consumers do not call the validator directly. A validation failure raises a `ServiceError` with the relevant `[Rnn]` error codes in the message.

---

## Changelog

| Version | Date | Change |
|---|---|---|
| 1.0 | May 2026 | Initial version |

---

*Related documents: `conceptual_model.md`, `data_dictionary.md`, `database_schema.md`, `validation_rules.md`, `reconstruction_algorithms.md`*

*Schema version: 2.4 — May 2026*
