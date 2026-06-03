"""
GRA — Genealogy Research Assistant
Validation framework: genealogical constraint rules R40–R46.

Entry points
------------
validate(conn)                      → list[str]   Full DB scan, all Python-only rules.
validate_object(obj_type, obj)      → list[str]   Pre-write structural/vocabulary check.
validate_genealogical(conn, person_id) → list[str]  R40–R46 for a single Person.

Rule codes
----------
R40  Birth Event singularity            (GC04)
R41  Death Event singularity            (GC05)
R42  Census Record singularity/source   (GC07)
R43  Life event sequence                (GC02)
R44  Parent age plausibility            (GC12)
R45  Marriage age plausibility          (GC13)
R46  Lifespan boundary                  (GC01)

All genealogical rules produce *warnings* (not hard errors).
A warning does not prevent a linkage from being committed — it surfaces
the issue for researcher review.  The researcher's verified=1 flag is the
mechanism for acknowledging and overriding a warning.

Thresholds (from genealogical_constraints.md)
---------------------------------------------
- Minimum parent–child birth-year gap:  15 years  (net of ±2 yr tolerance)
- Maximum maternal birth-year gap:      50 years  (net of ±2 yr tolerance)
- Maximum paternal birth-year gap:      70 years  (net of ±2 yr tolerance)
- Minimum marriage age:                 15 years  (net of ±2 yr tolerance)
- Lifespan boundary tolerance:           5 years
- Age tolerance on derived birth years:  2 years
- Life-event sequence tolerance:         2 years
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

_AGE_TOLERANCE        = 2    # years — applied to all derived/estimated birth years
_LIFESPAN_TOLERANCE   = 5    # years — applied to lifespan boundary check (R46)
_SEQ_TOLERANCE        = 2    # years — applied to life event sequence check (R43)
_MIN_PARENT_GAP       = 15   # years — minimum parent–child birth year gap
_MAX_MATERNAL_GAP     = 50   # years — maximum mother–child birth year gap
_MAX_PATERNAL_GAP     = 70   # years — maximum father–child birth year gap
_MIN_MARRIAGE_AGE     = 15   # years — minimum age at marriage

# Census source IDs (R42)
_CENSUS_SOURCE_IDS = {3, 4, 5}

# Event types that must not post-date a death (R43)
_LIVING_EVENT_TYPES = {"census", "residence", "valuation", "tithe", "military_service"}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _year_from_date(date_str: str | None) -> int | None:
    """Extract the four-digit year from an ISO 8601 partial date string."""
    if not date_str:
        return None
    m = re.match(r"^(\d{4})", date_str.strip())
    return int(m.group(1)) if m else None


def _derive_birth_year(conn: sqlite3.Connection, person_id: int) -> int | None:
    """
    Attempt to derive an estimated birth year for a Person from their
    concluded Events (birth or baptism) or, as a fallback, from the
    age and census date recorded in linked Records.

    Returns the best available estimate, or None if no birth year
    can be established.
    """
    # 1. Birth Event date
    row = conn.execute(
        """
        SELECT e.date FROM event e
        JOIN person_event ep ON ep.event_id = e.event_id
        WHERE ep.person_id = ? AND e.type = 'birth' AND e.date IS NOT NULL
        LIMIT 1
        """,
        (person_id,),
    ).fetchone()
    if row:
        year = _year_from_date(row["date"])
        if year:
            return year

    # 2. Baptism Event date (proxy lower bound)
    row = conn.execute(
        """
        SELECT e.date FROM event e
        JOIN person_event ep ON ep.event_id = e.event_id
        WHERE ep.person_id = ? AND e.type = 'baptism' AND e.date IS NOT NULL
        LIMIT 1
        """,
        (person_id,),
    ).fetchone()
    if row:
        year = _year_from_date(row["date"])
        if year:
            return year

    # 3. Derive from census RecordedPerson age + census date
    row = conn.execute(
        """
        SELECT rp.age, re.date
        FROM person_record pr
        JOIN record r ON r.record_id = pr.record_id
        JOIN source s ON s.source_id = r.source_id
        JOIN recorded_person rp ON rp.record_id = r.record_id
        WHERE pr.person_id = ?
          AND s.type = 'census'
          AND rp.age IS NOT NULL
          AND r.date IS NOT NULL
        ORDER BY pr.age ASC
        LIMIT 1
        """,
        (person_id,),
    ).fetchone()
    if row and row["age"] is not None:
        census_year = _year_from_date(row["date"])
        if census_year:
            return census_year - row["age"]

    return None


def _derive_death_year(conn: sqlite3.Connection, person_id: int) -> int | None:
    """Return the concluded death year for a Person, or None."""
    row = conn.execute(
        """
        SELECT e.date FROM event e
        JOIN person_event ep ON ep.event_id = e.event_id
        WHERE ep.person_id = ? AND e.type = 'death' AND e.date IS NOT NULL
        LIMIT 1
        """,
        (person_id,),
    ).fetchone()
    if row:
        return _year_from_date(row["date"])
    return None


def _get_event_years(
    conn: sqlite3.Connection, person_id: int
) -> dict[str, list[int]]:
    """
    Return a dict mapping event type → list of concluded years for that
    Person.  Only events with a non-null date are included.
    """
    rows = conn.execute(
        """
        SELECT e.type, e.date FROM event e
        JOIN person_event ep ON ep.event_id = e.event_id
        WHERE ep.person_id = ? AND e.date IS NOT NULL
        ORDER BY e.date
        """,
        (person_id,),
    ).fetchall()

    result: dict[str, list[int]] = {}
    for row in rows:
        year = _year_from_date(row["date"])
        if year is not None:
            result.setdefault(row["type"], []).append(year)
    return result


def _person_label(conn: sqlite3.Connection, person_id: int) -> str:
    row = conn.execute(
        "SELECT label FROM person WHERE person_id = ?", (person_id,)
    ).fetchone()
    return row["label"] if row else str(person_id)


# ---------------------------------------------------------------------------
# R40 — Birth Event singularity
# ---------------------------------------------------------------------------

def _r40(conn: sqlite3.Connection, person_id: int) -> list[str]:
    """
    R40: A Person may not have more than one birth Event.
    """
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM event e
        JOIN person_event ep ON ep.event_id = e.event_id
        WHERE ep.person_id = ? AND e.type = 'birth'
        """,
        (person_id,),
    ).fetchone()
    n = row["n"]
    if n > 1:
        return [
            f"[R40] Person {person_id}: has {n} birth Events — "
            f"maximum 1 permitted; probable merge error"
        ]
    return []


# ---------------------------------------------------------------------------
# R41 — Death Event singularity
# ---------------------------------------------------------------------------

def _r41(conn: sqlite3.Connection, person_id: int) -> list[str]:
    """
    R41: A Person may not have more than one death Event.
    """
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM event e
        JOIN person_event ep ON ep.event_id = e.event_id
        WHERE ep.person_id = ? AND e.type = 'death'
        """,
        (person_id,),
    ).fetchone()
    n = row["n"]
    if n > 1:
        return [
            f"[R41] Person {person_id}: has {n} death Events — "
            f"maximum 1 permitted; probable merge error"
        ]
    return []


# ---------------------------------------------------------------------------
# R42 — Census Record singularity per source
# ---------------------------------------------------------------------------

def _r42(conn: sqlite3.Connection, person_id: int) -> list[str]:
    """
    R42: A Person may not have more than one unverified Record from the
    same census source (source_ids 3, 4, 5).
    """
    rows = conn.execute(
        """
        SELECT s.source_id, s.title, COUNT(*) AS n
        FROM person_record pr
        JOIN record r ON r.record_id = pr.record_id
        JOIN source s ON s.source_id = r.source_id
        WHERE pr.person_id = ?
          AND s.source_id IN (3, 4, 5)
          AND pr.verified = 0
        GROUP BY s.source_id
        HAVING n > 1
        """,
        (person_id,),
    ).fetchall()

    warnings = []
    for row in rows:
        warnings.append(
            f"[R42] Person {person_id}: has {row['n']} unverified Records from "
            f"census source {row['source_id']} ('{row['title']}') — "
            f"maximum 1 expected; probable merge error or double enumeration"
        )
    return warnings


# ---------------------------------------------------------------------------
# R43 — Life event sequence
# ---------------------------------------------------------------------------

def _r43(conn: sqlite3.Connection, person_id: int) -> list[str]:
    """
    R43: Concluded life Events for a Person must follow chronological order.

    Checks:
      - birth before baptism (with adult-baptism carve-out)
      - birth before all other events
      - marriage before death
      - death before burial
      - no census/residence/valuation/tithe/military after death
    """
    warnings = []
    event_years = _get_event_years(conn, person_id)

    def earliest(event_type: str) -> int | None:
        years = event_years.get(event_type)
        return min(years) if years else None

    def latest(event_type: str) -> int | None:
        years = event_years.get(event_type)
        return max(years) if years else None

    birth_year  = earliest("birth")
    death_year  = earliest("death")
    burial_year = earliest("burial")

    # birth before baptism
    baptism_year = earliest("baptism")
    if birth_year is not None and baptism_year is not None:
        # Adult-baptism carve-out: if any baptism RecordedPerson has age > 1,
        # skip the interval check for that event.
        # Simplified: skip if the gap is > 2 years (could indicate adult baptism)
        # A proper implementation would inspect RecordedPerson.age on linked records.
        gap = baptism_year - birth_year
        if gap < 0 and abs(gap) > _SEQ_TOLERANCE:
            warnings.append(
                f"[R43] Person {person_id}: sequence violation — "
                f"baptism date {baptism_year} precedes birth date {birth_year} "
                f"(net of {_SEQ_TOLERANCE}yr tolerance)"
            )

    # birth before all other non-birth events
    if birth_year is not None:
        for etype, years in event_years.items():
            if etype in ("birth", "baptism"):
                continue
            for y in years:
                if y < birth_year - _SEQ_TOLERANCE:
                    warnings.append(
                        f"[R43] Person {person_id}: sequence violation — "
                        f"{etype} date {y} precedes birth date {birth_year} "
                        f"(net of {_SEQ_TOLERANCE}yr tolerance)"
                    )

    # marriage before death
    if death_year is not None:
        marriage_years = event_years.get("marriage", [])
        for my in marriage_years:
            if my > death_year + _SEQ_TOLERANCE:
                warnings.append(
                    f"[R43] Person {person_id}: sequence violation — "
                    f"marriage date {my} follows death date {death_year} "
                    f"(net of {_SEQ_TOLERANCE}yr tolerance)"
                )

    # death before burial
    if death_year is not None and burial_year is not None:
        if burial_year < death_year - _SEQ_TOLERANCE:
            warnings.append(
                f"[R43] Person {person_id}: sequence violation — "
                f"burial date {burial_year} precedes death date {death_year} "
                f"(net of {_SEQ_TOLERANCE}yr tolerance)"
            )

    # living events after death
    if death_year is not None:
        for etype in _LIVING_EVENT_TYPES:
            for y in event_years.get(etype, []):
                if y > death_year + _SEQ_TOLERANCE:
                    warnings.append(
                        f"[R43] Person {person_id}: sequence violation — "
                        f"{etype} date {y} follows death date {death_year} "
                        f"(net of {_SEQ_TOLERANCE}yr tolerance)"
                    )

    return warnings


# ---------------------------------------------------------------------------
# R44 — Parent age plausibility
# ---------------------------------------------------------------------------

def _r44(conn: sqlite3.Connection, person_id: int) -> list[str]:
    """
    R44: For parent_child Relationships where this Person is the parent,
    the birth-year gap to the child must be ≥ 15 years (net of tolerance).
    For female parents, gap must also be ≤ 50 years.
    For male parents, gap must also be ≤ 70 years.
    """
    warnings = []

    # Find all parent_child relationships where this person is person_id_1 (parent)
    children = conn.execute(
        """
        SELECT r.relationship_id, r.person_id_2 AS child_id, p.gender
        FROM relationship r
        JOIN person p ON p.person_id = r.person_id_1
        WHERE r.person_id_1 = ? AND r.type = 'parent_child'
        """,
        (person_id,),
    ).fetchall()

    if not children:
        return []

    parent_birth_year = _derive_birth_year(conn, person_id)
    if parent_birth_year is None:
        return [
            f"[SKIP] R44 for Person {person_id} skipped: "
            f"birth year not determinable from concluded Events or linked Records"
        ]

    for child_row in children:
        child_id = child_row["child_id"]
        child_birth_year = _derive_birth_year(conn, child_id)
        if child_birth_year is None:
            warnings.append(
                f"[SKIP] R44 for Relationship {child_row['relationship_id']} skipped: "
                f"child Person {child_id} birth year not determinable"
            )
            continue

        # Apply tolerance to both estimates
        gap = child_birth_year - parent_birth_year
        effective_gap_min = gap + _AGE_TOLERANCE  # best case for min check
        effective_gap_max = gap - _AGE_TOLERANCE  # worst case for max check

        if effective_gap_min < _MIN_PARENT_GAP:
            warnings.append(
                f"[R44] Relationship {child_row['relationship_id']} (parent_child): "
                f"parent Person {person_id} birth year ~{parent_birth_year} — "
                f"child Person {child_id} birth year ~{child_birth_year} — "
                f"gap of {gap} years is below minimum of {_MIN_PARENT_GAP}; "
                f"probable merge error"
            )

        gender = child_row["gender"]
        if gender == "female" and effective_gap_max > _MAX_MATERNAL_GAP:
            warnings.append(
                f"[R44] Relationship {child_row['relationship_id']} (parent_child): "
                f"female parent Person {person_id} birth year ~{parent_birth_year} — "
                f"child Person {child_id} birth year ~{child_birth_year} — "
                f"gap of {gap} years exceeds maternal maximum of {_MAX_MATERNAL_GAP}; "
                f"probable merge error"
            )
        elif gender == "male" and effective_gap_max > _MAX_PATERNAL_GAP:
            warnings.append(
                f"[R44] Relationship {child_row['relationship_id']} (parent_child): "
                f"male parent Person {person_id} birth year ~{parent_birth_year} — "
                f"child Person {child_id} birth year ~{child_birth_year} — "
                f"gap of {gap} years exceeds paternal maximum of {_MAX_PATERNAL_GAP}; "
                f"probable merge error"
            )

    return warnings


# ---------------------------------------------------------------------------
# R45 — Marriage age plausibility
# ---------------------------------------------------------------------------

def _r45(conn: sqlite3.Connection, person_id: int) -> list[str]:
    """
    R45: For each marriage Event linked to this Person, the gap between
    the Person's birth year and the marriage year must be ≥ 15 years
    (net of ±2yr tolerance).
    """
    warnings = []

    birth_year = _derive_birth_year(conn, person_id)
    if birth_year is None:
        # Can't evaluate without a birth year — skip silently
        return []

    marriage_events = conn.execute(
        """
        SELECT e.event_id, e.date FROM event e
        JOIN person_event ep ON ep.event_id = e.event_id
        WHERE ep.person_id = ? AND e.type = 'marriage' AND e.date IS NOT NULL
        """,
        (person_id,),
    ).fetchall()

    for ev in marriage_events:
        marriage_year = _year_from_date(ev["date"])
        if marriage_year is None:
            continue

        age_at_marriage = marriage_year - birth_year
        # Apply tolerance: use best-case age (birth_year could be _AGE_TOLERANCE later)
        effective_age = age_at_marriage + _AGE_TOLERANCE

        if effective_age < _MIN_MARRIAGE_AGE:
            warnings.append(
                f"[R45] Person {person_id}: marriage Event {ev['event_id']} "
                f"dated {ev['date']} — concluded birth year ~{birth_year} "
                f"places Person at age ~{age_at_marriage} at marriage; "
                f"minimum age is {_MIN_MARRIAGE_AGE}; probable merge error"
            )

    return warnings


# ---------------------------------------------------------------------------
# R46 — Lifespan boundary
# ---------------------------------------------------------------------------

def _r46(conn: sqlite3.Connection, person_id: int) -> list[str]:
    """
    R46: For each Record linked to this Person, the RecordedEvent date
    must fall within the Person's concluded lifespan (±5yr tolerance).
    """
    warnings = []

    birth_year = _derive_birth_year(conn, person_id)
    death_year = _derive_death_year(conn, person_id)

    if birth_year is None and death_year is None:
        return [
            f"[SKIP] R46 for Person {person_id} skipped: "
            f"birth year and death year not determinable; lifespan bounds unavailable"
        ]

    # Fetch all linked Records with their RecordedEvent dates
    linked = conn.execute(
        """
        SELECT pr.record_id, r.date AS event_date
        FROM person_record pr
        JOIN record r ON r.record_id = pr.record_id
        WHERE pr.person_id = ? AND r.date IS NOT NULL
        """,
        (person_id,),
    ).fetchall()

    for row in linked:
        record_year = _year_from_date(row["event_date"])
        if record_year is None:
            continue

        # Lower bound check
        if birth_year is not None:
            lower = birth_year - _LIFESPAN_TOLERANCE
            if record_year < lower:
                warnings.append(
                    f"[R46] person_record (person_id={person_id}, "
                    f"record_id={row['record_id']}): RecordedEvent date {record_year} "
                    f"is more than {_LIFESPAN_TOLERANCE} years before birth year "
                    f"~{birth_year}; probable merge error"
                )

        # Upper bound check (only if death year known)
        if death_year is not None:
            upper = death_year + _LIFESPAN_TOLERANCE
            if record_year > upper:
                warnings.append(
                    f"[R46] person_record (person_id={person_id}, "
                    f"record_id={row['record_id']}): RecordedEvent date {record_year} "
                    f"is more than {_LIFESPAN_TOLERANCE} years after death year "
                    f"{death_year}; probable merge error"
                )

    return warnings


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def validate_genealogical(
    conn: sqlite3.Connection,
    person_id: int,
) -> list[str]:
    """
    Run all genealogical constraint rules (R40–R46) for a single Person.

    Returns a flat list of warning strings. An empty list means no
    genealogical constraint violations were detected for this Person.

    Warnings are advisory — they do not prevent linkages from being
    committed.  The researcher's verified=1 flag is the mechanism for
    acknowledging and overriding a warning.

    Usage:
        conn = open_db("genealogy.db")
        warnings = validate_genealogical(conn, person_id=42)
        for w in warnings:
            print(w)
    """
    warnings: list[str] = []
    warnings += _r40(conn, person_id)
    warnings += _r41(conn, person_id)
    warnings += _r42(conn, person_id)
    warnings += _r43(conn, person_id)
    warnings += _r44(conn, person_id)
    warnings += _r45(conn, person_id)
    warnings += _r46(conn, person_id)
    return warnings


def validate(conn: sqlite3.Connection) -> list[str]:
    """
    Run all Python-enforced validation rules across the full database.

    Currently implements the genealogical constraint rules (R40–R46)
    for every Person in the database.  Structural, referential, and
    vocabulary rules (R01–R39) are enforced by the DB schema itself
    (NOT NULL, CHECK, REFERENCES) and are not duplicated here.

    Returns a flat list of warning strings, one per violation found.
    An empty list means no violations detected.

    Usage:
        conn = open_db("genealogy.db")
        warnings = validate(conn)
        for w in warnings:
            print(w)
    """
    all_warnings: list[str] = []

    person_ids = [
        row[0]
        for row in conn.execute("SELECT person_id FROM person ORDER BY person_id").fetchall()
    ]

    for pid in person_ids:
        all_warnings += validate_genealogical(conn, pid)

    return all_warnings


def validate_object(obj_type: str, obj: dict[str, Any]) -> list[str]:
    """
    Pre-write structural and vocabulary check for a single object.

    Validates required fields are present and non-empty for the given
    object type.  Does not require a database connection — runs against
    the dict in isolation before any INSERT is attempted.

    obj_type must be one of:
        'repository', 'source', 'record',
        'recorded_person', 'person', 'relationship', 'event', 'place'

    Returns a flat list of error strings.  An empty list means the
    object passes pre-write validation.

    Usage:
        errors = validate_object('person', {"person_id": 1, "label": "John"})
    """
    errors: list[str] = []
    obj_id = obj.get(f"{obj_type}_id", "?")

    # Required fields by object type (R01–R09)
    _REQUIRED: dict[str, list[str]] = {
        "repository":      ["repository_id", "name", "url"],
        "source":          ["source_id", "repository_id", "title", "type"],
        "record":          ["record_id", "source_id", "raw_text"],
        "recorded_person": ["recorded_person_id", "record_id", "name_as_recorded", "role"],
        "person":          ["person_id", "label"],
        "relationship":    ["relationship_id", "type", "person_id_1", "person_id_2"],
        "event":           ["event_id", "type"],
        "place":           ["place_id", "name"],
    }

    # Fields that must also be non-empty strings (not just non-null)
    _NON_EMPTY: dict[str, list[str]] = {
        "repository":      ["name", "url"],
        "source":          ["title"],
        "record":          ["raw_text"],
        "recorded_person": ["name_as_recorded", "role"],
        "person":          ["label"],
        "place":           ["name"],
        "event":           ["type"],
        "relationship":    ["type"],
    }

    required = _REQUIRED.get(obj_type, [])
    non_empty = _NON_EMPTY.get(obj_type, [])

    rule_map = {
        "repository":      "R01",
        "source":          "R02",
        "record":          "R03",
        "recorded_person": "R05",
        "person":          "R06",
        "relationship":    "R07",
        "event":           "R08",
        "place":           "R09",
    }
    rule = rule_map.get(obj_type, "R??")

    for field in required:
        val = obj.get(field)
        if val is None:
            errors.append(
                f"[{rule}] {obj_type.capitalize()} {obj_id}: "
                f"required field '{field}' is absent or null"
            )
        elif field in non_empty and isinstance(val, str) and not val.strip():
            errors.append(
                f"[{rule}] {obj_type.capitalize()} {obj_id}: "
                f"required field '{field}' is absent or empty"
            )

    # R22: Relationship self-reference (belt-and-suspenders alongside DB CHECK)
    if obj_type == "relationship":
        p1 = obj.get("person_id_1")
        p2 = obj.get("person_id_2")
        if p1 is not None and p2 is not None and p1 == p2:
            errors.append(
                f"[R22] Relationship {obj_id}: "
                f"person_id_1 and person_id_2 are the same ({p1}); self-reference not permitted"
            )

    # R36: Date format validation
    _DATE_RE = re.compile(
        r"^\d{4}$"                     # YYYY
        r"|^\d{4}-(0[1-9]|1[0-2])$"   # YYYY-MM
        r"|^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"  # YYYY-MM-DD
    )
    date_fields = ["date"] if obj_type in ("record", "event") else []

    for field in date_fields:
        val = obj.get(field)
        if val is not None and not _DATE_RE.match(str(val)):
            errors.append(
                f"[R36] {obj_type.capitalize()} {obj_id}: "
                f"date='{val}' is not a valid ISO 8601 partial date"
            )

    # R38: Score range on linkage junction objects
    if "score" in obj:
        score = obj["score"]
        if score is not None:
            try:
                score_f = float(score)
                if not (0.0 <= score_f <= 1.0):
                    errors.append(
                        f"[R38] {obj_type.capitalize()} {obj_id}: "
                        f"score={score} is outside valid range [0.0, 1.0]"
                    )
            except (TypeError, ValueError):
                errors.append(
                    f"[R38] {obj_type.capitalize()} {obj_id}: "
                    f"score='{score}' is not a valid number"
                )

    # R39: Verified flag
    if "verified" in obj:
        verified = obj.get("verified")
        if verified not in (0, 1, None):
            errors.append(
                f"[R39] {obj_type.capitalize()} {obj_id}: "
                f"verified={verified} must be 0 or 1"
            )

    return errors


# ---------------------------------------------------------------------------
# CLI convenience
# ---------------------------------------------------------------------------


def _print_warnings(warnings: list[str], label: str) -> None:
    if not warnings:
        print(f"  {label}: no violations found.")
    else:
        print(f"  {label}: {len(warnings)} warning(s)")
        for w in warnings:
            print(f"    {w}")


if __name__ == "__main__":
    import argparse
    from src.db import open_db, check_version

    parser = argparse.ArgumentParser(
        prog="python -m src.validator",
        description="GRA validation — run genealogical constraint rules",
    )
    parser.add_argument("--db", default="genealogy.db", help="Database path")
    parser.add_argument(
        "--person", type=int, default=None,
        help="Validate a single Person by ID (omit to validate all)"
    )
    args = parser.parse_args()

    conn = open_db(args.db)
    check_version(conn)

    if args.person is not None:
        warnings = validate_genealogical(conn, args.person)
        _print_warnings(warnings, f"Person {args.person}")
    else:
        warnings = validate(conn)
        _print_warnings(warnings, "Full database")
