"""
GRA — Household Structure Inference
Stage 3 of the reconstruction pipeline (census sources only).

For each census Record, reads all RecordedPersons and creates:
  - One Person conclusion per RecordedPerson
  - Relationships derived from role-pair rules (§6.1 reconstruction_algorithms.md)
  - One census Event per Record, linked to all persons and the resolved Place

Entry point: run_household_inference(conn, source_id) -> HouseholdInferenceResult
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

SCORE_VERSION = "household_v1.0"

# Prior scores from reconstruction_algorithms.md §6.1
_COUPLE_PRIOR          = 0.90
_PARENT_CHILD_HEAD     = 0.85   # head → son/daughter
_PARENT_CHILD_SPOUSE   = 0.80   # spouse → son/daughter
_PARENT_CHILD_DIRECT   = 0.90   # father/mother → principal (non-census)
_SIBLING_DIRECT        = 0.80   # head + sibling role
_SIBLING_INFERRED      = 0.75   # son+son, daughter+daughter, son+daughter
_PARENT_CHILD_SCORE    = 0.90   # junction score stored on person_record/relationship_record

# Score stored on person_record for household-inferred persons
_PERSON_RECORD_SCORE   = 0.90

# Census event score on event_record
_EVENT_RECORD_SCORE    = 0.90

# Gender derivation from role
_ROLE_GENDER: dict[str, str] = {
    "head":       None,    # ambiguous — use sex_as_recorded
    "spouse":     None,
    "son":        "male",
    "daughter":   "female",
    "sibling":    None,
    "grandchild": None,
    "in_law":     None,
    "niece_nephew": None,
    "aunt_uncle": None,
    "cousin":     None,
    "mother":     "female",
    "father":     "male",
    "servant":    None,
    "visitor":    None,
    "boarder":    None,
    "principal":  None,
}

_SEX_MAP = {"M": "male", "F": "female", "m": "male", "f": "female"}

# Roles that generate automatic Relationship assertions (§6.1)
_RELATIONSHIP_GENERATING_ROLES = {
    "head", "spouse", "son", "daughter", "sibling",
    "mother", "father",
}

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class HouseholdInferenceResult:
    persons_created: int = 0
    relationships_created: int = 0
    events_created: int = 0
    records_processed: int = 0
    couple_count: int = 0
    parent_child_count: int = 0
    sibling_count: int = 0
    skipped_records: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _next_ids(conn: sqlite3.Connection) -> dict[str, int]:
    """Return the next available primary key for each conclusion-layer table."""
    return {
        "person":       conn.execute("SELECT COALESCE(MAX(person_id), 0) + 1 FROM person").fetchone()[0],
        "relationship": conn.execute("SELECT COALESCE(MAX(relationship_id), 0) + 1 FROM relationship").fetchone()[0],
        "event":        conn.execute("SELECT COALESCE(MAX(event_id), 0) + 1 FROM event").fetchone()[0],
    }


def _gender_for_rp(rp: sqlite3.Row) -> str | None:
    """Determine gender: prefer role-derived gender, fall back to sex_as_recorded."""
    role_gender = _ROLE_GENDER.get(rp["role"])
    if role_gender:
        return role_gender
    return _SEX_MAP.get(rp["sex_as_recorded"] or "", None)


def _label(rp: sqlite3.Row, townland: str, year: int) -> str:
    """Construct the Person label."""
    name = rp["name_as_recorded"].strip()
    tl = townland.strip() if townland else "Unknown"
    return f"{name} ({year}, {tl})"


def _insert_person(
    conn: sqlite3.Connection,
    person_id: int,
    rp: sqlite3.Row,
    townland: str,
    year: int,
) -> None:
    gender = _gender_for_rp(rp)
    label = _label(rp, townland, year)
    conn.execute(
        "INSERT INTO person (person_id, label, gender) VALUES (?, ?, ?)",
        (person_id, label, gender),
    )
    # Insert birth_name into person_name
    name = rp["name_as_recorded"].strip()
    if name and name != "Unknown":
        pn_id = conn.execute(
            "SELECT COALESCE(MAX(person_name_id), 0) + 1 FROM person_name"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO person_name (person_name_id, person_id, value, type) VALUES (?, ?, ?, ?)",
            (pn_id, person_id, name, "birth_name"),
        )


def _insert_person_record(
    conn: sqlite3.Connection,
    person_id: int,
    record_id: int,
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO person_record (person_id, record_id, score, score_version, verified) "
        "VALUES (?, ?, ?, ?, 0)",
        (person_id, record_id, _PERSON_RECORD_SCORE, SCORE_VERSION),
    )


def _insert_relationship(
    conn: sqlite3.Connection,
    rel_id: int,
    rel_type: str,
    pid1: int,
    pid2: int,
    record_id: int,
    prior_score: float,
    notes: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO relationship (relationship_id, type, person_id_1, person_id_2, notes) "
        "VALUES (?, ?, ?, ?, ?)",
        (rel_id, rel_type, pid1, pid2, notes),
    )
    conn.execute(
        "INSERT INTO person_relationship (person_id, relationship_id) VALUES (?, ?)",
        (pid1, rel_id),
    )
    conn.execute(
        "INSERT OR IGNORE INTO person_relationship (person_id, relationship_id) VALUES (?, ?)",
        (pid2, rel_id),
    )
    conn.execute(
        "INSERT INTO relationship_record "
        "(relationship_id, record_id, score, score_version, verified) VALUES (?, ?, ?, ?, 0)",
        (rel_id, record_id, prior_score, SCORE_VERSION),
    )


def _insert_census_event(
    conn: sqlite3.Connection,
    event_id: int,
    record_id: int,
    recorded_event_id: int,
    place_id: int | None,
    census_date: str,
    person_ids: list[int],
) -> None:
    conn.execute(
        "INSERT INTO event (event_id, type, date, date_qualifier, place_id) "
        "VALUES (?, 'census', ?, 'exact', ?)",
        (event_id, census_date, place_id),
    )
    conn.execute(
        "INSERT INTO event_record (event_id, record_id, score, score_version, verified) "
        "VALUES (?, ?, ?, ?, 0)",
        (event_id, record_id, _EVENT_RECORD_SCORE, SCORE_VERSION),
    )
    conn.execute(
        "INSERT INTO event_recorded_event (event_id, recorded_event_id) VALUES (?, ?)",
        (event_id, recorded_event_id),
    )
    for pid in person_ids:
        conn.execute(
            "INSERT INTO event_person (event_id, person_id) VALUES (?, ?)",
            (event_id, pid),
        )
        conn.execute(
            "INSERT OR IGNORE INTO person_event (person_id, event_id) VALUES (?, ?)",
            (pid, event_id),
        )


# ---------------------------------------------------------------------------
# Relationship inference for a single household
# ---------------------------------------------------------------------------

def _infer_relationships(
    conn: sqlite3.Connection,
    rp_list: list[sqlite3.Row],
    pid_map: dict[int, int],    # recorded_person_id → person_id
    record_id: int,
    ids: dict[str, int],
    result: HouseholdInferenceResult,
) -> None:
    """
    Apply role-pair rules from reconstruction_algorithms.md §6.1 to
    generate Relationship conclusions for a single household.
    Modifies ids in-place to advance relationship_id counter.
    """
    # Index RecordedPersons by role (one-to-many)
    by_role: dict[str, list[sqlite3.Row]] = {}
    for rp in rp_list:
        by_role.setdefault(rp["role"], []).append(rp)

    def pid(rp: sqlite3.Row) -> int:
        return pid_map[rp["recorded_person_id"]]

    def make_rel(rel_type: str, p1: int, p2: int, score: float, notes: str | None = None) -> None:
        _insert_relationship(conn, ids["relationship"], rel_type, p1, p2, record_id, score, notes)
        ids["relationship"] += 1
        if rel_type == "couple":
            result.couple_count += 1
        elif rel_type == "parent_child":
            result.parent_child_count += 1
        elif rel_type == "sibling":
            result.sibling_count += 1
        result.relationships_created += 1

    heads   = by_role.get("head", [])
    spouses = by_role.get("spouse", [])
    sons    = by_role.get("son", [])
    daughters = by_role.get("daughter", [])
    siblings = by_role.get("sibling", [])
    mothers = by_role.get("mother", [])
    fathers = by_role.get("father", [])
    children = sons + daughters

    # head + spouse → couple
    for h in heads:
        for s in spouses:
            make_rel("couple", pid(h), pid(s), _COUPLE_PRIOR)

    # head + son/daughter → parent_child (head is parent)
    for h in heads:
        for c in children:
            make_rel("parent_child", pid(h), pid(c), _PARENT_CHILD_HEAD)

    # spouse + son/daughter → parent_child (spouse is parent)
    for s in spouses:
        for c in children:
            make_rel("parent_child", pid(s), pid(c), _PARENT_CHILD_SPOUSE)

    # head + sibling role → sibling relationship
    for h in heads:
        for sib in siblings:
            make_rel("sibling", pid(h), pid(sib), _SIBLING_DIRECT,
                     notes="Inferred from 'sibling' role relative to head")

    # head + mother/father → parent_child (mother/father is parent of head)
    for m in mothers:
        for h in heads:
            make_rel("parent_child", pid(m), pid(h), _PARENT_CHILD_HEAD,
                     notes="Head's mother named in census")
    for f in fathers:
        for h in heads:
            make_rel("parent_child", pid(f), pid(h), _PARENT_CHILD_HEAD,
                     notes="Head's father named in census")

    # son+son, daughter+daughter, son+daughter → sibling (inferred via shared parents)
    # Only generate if there is at least one parent in the household (head or spouse)
    if (heads or spouses) and len(children) > 1:
        # Generate pairs; avoid duplicates with i < j ordering
        for i in range(len(children)):
            for j in range(i + 1, len(children)):
                make_rel("sibling", pid(children[i]), pid(children[j]), _SIBLING_INFERRED,
                         notes="Inferred sibling: shared household parents")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_household_inference(
    conn: sqlite3.Connection,
    source_id: int,
) -> HouseholdInferenceResult:
    """
    Run household structure inference for all Records from the given census source.
    Creates Person, Relationship, and Event conclusions in the conclusion layer.

    Only processes Records that have no existing person_record entries
    (safe to call incrementally).
    """
    result = HouseholdInferenceResult()

    # Verify source exists and is a census
    source_row = conn.execute(
        "SELECT type, title FROM source WHERE source_id = ?", (source_id,)
    ).fetchone()
    if not source_row:
        raise ValueError(f"Source {source_id} not found.")
    if source_row["type"] != "census":
        raise ValueError(f"Source {source_id} ('{source_row['title']}') is not a census source.")

    # Fetch all records for this source that haven't been processed yet
    records = conn.execute(
        """
        SELECT r.record_id, re.recorded_event_id, re.date, re.place_as_recorded
        FROM record r
        JOIN recorded_event re ON re.record_id = r.record_id
        WHERE r.source_id = ?
          AND r.record_id NOT IN (SELECT DISTINCT record_id FROM person_record)
        ORDER BY r.record_id
        """,
        (source_id,),
    ).fetchall()

    if not records:
        print(f"  Household inference: no unprocessed records found for source {source_id}.")
        return result

    # Resolve place_record so we can link events to Place conclusions
    place_for_record: dict[int, int | None] = {}
    place_rows = conn.execute(
        "SELECT record_id, place_id FROM place_record"
    ).fetchall()
    for pr in place_rows:
        place_for_record[pr["record_id"]] = pr["place_id"]

    ids = _next_ids(conn)

    with conn:
        for rec in records:
            record_id = rec["record_id"]
            recorded_event_id = rec["recorded_event_id"]
            census_date = rec["date"] or "1911-04-02"
            census_year = int(census_date[:4])
            townland = rec["place_as_recorded"] or ""
            place_id = place_for_record.get(record_id)

            # Fetch all RecordedPersons for this record
            rp_list = conn.execute(
                "SELECT * FROM recorded_person WHERE record_id = ? ORDER BY recorded_person_id",
                (record_id,),
            ).fetchall()

            if not rp_list:
                result.skipped_records.append(
                    f"record_id={record_id}: no RecordedPersons"
                )
                continue

            # Create one Person per RecordedPerson
            pid_map: dict[int, int] = {}   # recorded_person_id → person_id
            household_pids: list[int] = []

            for rp in rp_list:
                person_id = ids["person"]
                _insert_person(conn, person_id, rp, townland, census_year)
                _insert_person_record(conn, person_id, record_id)
                pid_map[rp["recorded_person_id"]] = person_id
                household_pids.append(person_id)
                ids["person"] += 1
                result.persons_created += 1

            # Infer relationships from role pairs
            _infer_relationships(conn, rp_list, pid_map, record_id, ids, result)

            # Create census Event for this household
            event_id = ids["event"]
            _insert_census_event(
                conn, event_id, record_id, recorded_event_id,
                place_id, census_date, household_pids,
            )
            ids["event"] += 1
            result.events_created += 1
            result.records_processed += 1

    return result


def print_household_inference_report(result: HouseholdInferenceResult) -> None:
    """Print a human-readable summary of household inference results."""
    print(f"\n  HOUSEHOLD INFERENCE")
    print(f"    Records processed:     {result.records_processed:>6}")
    print(f"    Persons created:       {result.persons_created:>6}")
    print(f"    Relationships created: {result.relationships_created:>6}")
    print(f"      Couples:             {result.couple_count:>6}")
    print(f"      Parent-child:        {result.parent_child_count:>6}")
    print(f"      Siblings:            {result.sibling_count:>6}")
    print(f"    Events created:        {result.events_created:>6}")
    if result.skipped_records:
        print(f"\n  SKIPPED ({len(result.skipped_records)})")
        for note in result.skipped_records[:10]:
            print(f"    {note}")
        if len(result.skipped_records) > 10:
            print(f"    ... and {len(result.skipped_records) - 10} more")
