"""
GRA — Household Structure Inference
Stage 3 of the reconstruction pipeline (census sources only).

For each census Record, reads all RecordedPersons and creates:
  - One Person conclusion per RecordedPerson
  - Relationships derived from role-pair rules (§6.1 reconstruction_algorithms.md)
  - One census Event per Record, linked to all persons and the resolved Place

Entry point: run_household_inference(conn) -> HouseholdInferenceResult
Processes all census sources (3, 4, 5) that have ingested records in one pass.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

SCORE_VERSION = "household_v1.0"

# Prior scores from reconstruction_algorithms.md §6.1
_COUPLE_PRIOR        = 0.90
_PARENT_CHILD_HEAD   = 0.85
_PARENT_CHILD_SPOUSE = 0.80
_SIBLING_DIRECT      = 0.80
_SIBLING_INFERRED    = 0.75
_PERSON_RECORD_SCORE = 0.90
_EVENT_RECORD_SCORE  = 0.90

# Gender derivation from role
_ROLE_GENDER: dict[str, str | None] = {
    "head": None, "spouse": None, "son": "male", "daughter": "female",
    "sibling": None, "grandchild": None, "in_law": None,
    "niece_nephew": None, "aunt_uncle": None, "cousin": None,
    "mother": "female", "father": "male",
    "servant": None, "visitor": None, "boarder": None, "principal": None,
}

_SEX_MAP = {"M": "male", "F": "female", "m": "male", "f": "female"}


# ---------------------------------------------------------------------------
# Result type
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
    return {
        "person":       conn.execute("SELECT COALESCE(MAX(person_id), 0) + 1 FROM person").fetchone()[0],
        "relationship": conn.execute("SELECT COALESCE(MAX(relationship_id), 0) + 1 FROM relationship").fetchone()[0],
        "event":        conn.execute("SELECT COALESCE(MAX(event_id), 0) + 1 FROM event").fetchone()[0],
        "person_name":  conn.execute("SELECT COALESCE(MAX(person_name_id), 0) + 1 FROM person_name").fetchone()[0],
    }


def _gender_for_rp(rp: sqlite3.Row) -> str | None:
    role_gender = _ROLE_GENDER.get(rp["role"])
    if role_gender:
        return role_gender
    return _SEX_MAP.get(rp["sex_as_recorded"] or "", None)


def _label(rp: sqlite3.Row, townland: str) -> str:
    name = rp["name_as_recorded"].strip()
    tl = townland.strip() if townland else "Unknown"
    return f"{name} ({tl})"


def _insert_person(conn, person_id, rp, townland, ids):
    gender = _gender_for_rp(rp)
    label = _label(rp, townland)
    conn.execute(
        "INSERT INTO person (person_id, label, gender) VALUES (?, ?, ?)",
        (person_id, label, gender),
    )
    name = rp["name_as_recorded"].strip()
    if name and name != "Unknown":
        pn_id = ids["person_name"]
        ids["person_name"] += 1
        conn.execute(
            "INSERT INTO person_name (person_name_id, person_id, value, type) VALUES (?, ?, ?, ?)",
            (pn_id, person_id, name, "birth_name"),
        )


def _insert_person_record(conn, person_id, record_id):
    conn.execute(
        "INSERT OR IGNORE INTO person_record "
        "(person_id, record_id, score, score_version, verified) VALUES (?, ?, ?, ?, 0)",
        (person_id, record_id, _PERSON_RECORD_SCORE, SCORE_VERSION),
    )


def _insert_relationship(conn, rel_id, rel_type, pid1, pid2, record_id, prior_score, notes=None):
    conn.execute(
        "INSERT INTO relationship (relationship_id, type, person_id_1, person_id_2, notes) "
        "VALUES (?, ?, ?, ?, ?)",
        (rel_id, rel_type, pid1, pid2, notes),
    )
    conn.execute(
        "INSERT INTO relationship_record "
        "(relationship_id, record_id, score, score_version, verified) VALUES (?, ?, ?, ?, 0)",
        (rel_id, record_id, prior_score, SCORE_VERSION),
    )


def _insert_census_event(conn, event_id, record_id, place_id, census_date, person_ids):
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
    for pid in person_ids:
        conn.execute(
            "INSERT INTO person_event (person_id, event_id) VALUES (?, ?)",
            (pid, event_id),
        )


# ---------------------------------------------------------------------------
# Relationship inference for a single household
# ---------------------------------------------------------------------------

def _infer_relationships(conn, rp_list, pid_map, record_id, ids, result):
    by_role: dict[str, list] = {}
    for rp in rp_list:
        by_role.setdefault(rp["role"], []).append(rp)

    def pid(rp): return pid_map[rp["recorded_person_id"]]

    def make_rel(rel_type, p1, p2, score, notes=None):
        _insert_relationship(conn, ids["relationship"], rel_type, p1, p2, record_id, score, notes)
        ids["relationship"] += 1
        if rel_type == "couple":          result.couple_count += 1
        elif rel_type == "parent_child":  result.parent_child_count += 1
        elif rel_type == "sibling":       result.sibling_count += 1
        result.relationships_created += 1

    heads     = by_role.get("head", [])
    spouses   = by_role.get("spouse", [])
    sons      = by_role.get("son", [])
    daughters = by_role.get("daughter", [])
    siblings  = by_role.get("sibling", [])
    mothers   = by_role.get("mother", [])
    fathers   = by_role.get("father", [])
    children  = sons + daughters

    for h in heads:
        for s in spouses:
            make_rel("couple", pid(h), pid(s), _COUPLE_PRIOR)
    for h in heads:
        for c in children:
            make_rel("parent_child", pid(h), pid(c), _PARENT_CHILD_HEAD)
    for s in spouses:
        for c in children:
            make_rel("parent_child", pid(s), pid(c), _PARENT_CHILD_SPOUSE)
    for h in heads:
        for sib in siblings:
            make_rel("sibling", pid(h), pid(sib), _SIBLING_DIRECT,
                     notes="Inferred from sibling role relative to head")
    for m in mothers:
        for h in heads:
            make_rel("parent_child", pid(m), pid(h), _PARENT_CHILD_HEAD,
                     notes="Head's mother named in census")
    for f in fathers:
        for h in heads:
            make_rel("parent_child", pid(f), pid(h), _PARENT_CHILD_HEAD,
                     notes="Head's father named in census")
    if (heads or spouses) and len(children) > 1:
        for i in range(len(children)):
            for j in range(i + 1, len(children)):
                make_rel("sibling", pid(children[i]), pid(children[j]), _SIBLING_INFERRED,
                         notes="Inferred sibling: shared household parents")


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

_CENSUS_SOURCE_IDS = (3, 4, 5)


def _run_single_source(
    conn: sqlite3.Connection,
    source_id: int,
    ids: dict,
    result: HouseholdInferenceResult,
    place_for_record: dict[int, int | None],
) -> None:
    """
    Process all unprocessed Records for one census source.
    Mutates ids and result in place.
    """
    records = conn.execute(
        """
        SELECT r.record_id, r.date, r.place_as_recorded
        FROM record r
        WHERE r.source_id = ?
          AND r.record_id NOT IN (SELECT DISTINCT record_id FROM person_record)
        ORDER BY r.record_id
        """,
        (source_id,),
    ).fetchall()

    if not records:
        return

    for rec in records:
        record_id   = rec["record_id"]
        census_date = rec["date"] or "1901-03-31"
        census_year = int(census_date[:4])
        townland    = rec["place_as_recorded"] or ""
        place_id    = place_for_record.get(record_id)

        rp_list = conn.execute(
            "SELECT * FROM recorded_person WHERE record_id = ? ORDER BY recorded_person_id",
            (record_id,),
        ).fetchall()

        if not rp_list:
            result.skipped_records.append(f"record_id={record_id}: no RecordedPersons")
            continue

        pid_map: dict[int, int] = {}
        household_pids: list[int] = []

        for rp in rp_list:
            person_id = ids["person"]
            _insert_person(conn, person_id, rp, townland, ids)
            _insert_person_record(conn, person_id, record_id)
            pid_map[rp["recorded_person_id"]] = person_id
            household_pids.append(person_id)
            ids["person"] += 1
            result.persons_created += 1

        _infer_relationships(conn, rp_list, pid_map, record_id, ids, result)

        event_id = ids["event"]
        _insert_census_event(
            conn, event_id, record_id, place_id, census_date, household_pids,
        )
        ids["event"] += 1
        result.events_created += 1
        result.records_processed += 1


def run_household_inference(conn: sqlite3.Connection) -> HouseholdInferenceResult:
    """
    Run household structure inference for all unprocessed census Records
    across all three census sources (3=1901, 4=1911, 5=1926).

    Creates Person, Relationship, and Event conclusions.
    Safe to call incrementally — only unprocessed records are touched.
    Sources not yet ingested are silently skipped.
    """
    result = HouseholdInferenceResult()

    # Determine which census sources have ingested records
    active_sources = [
        row[0] for row in conn.execute(
            "SELECT DISTINCT source_id FROM record WHERE source_id IN (3, 4, 5)"
        ).fetchall()
    ]

    if not active_sources:
        print("  Household inference: no census records found.")
        return result

    # Build place_id lookup once for all sources
    place_for_record: dict[int, int | None] = {
        row["record_id"]: row["place_id"]
        for row in conn.execute("SELECT record_id, place_id FROM place_record").fetchall()
    }

    ids = _next_ids(conn)

    with conn:
        for source_id in sorted(active_sources):
            _run_single_source(conn, source_id, ids, result, place_for_record)

    return result


def print_household_inference_report(result: HouseholdInferenceResult) -> None:
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
