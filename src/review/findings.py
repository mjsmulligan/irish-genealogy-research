"""
GRA — Genealogy Research Assistant
Review layer: finding functions (v1.0).

Each public function corresponds to one finding_type in the v1.0 taxonomy.
Functions return a list[ReportItem] (empty when no findings for that type).
All functions receive an open psycopg2 connection; they are read-only.

Finding taxonomy (v1.0)
-----------------------
merge_error_candidate         GC07  Person linked to 2+ Records from the same census source
birth_singularity_violation   GC04  Multiple is_primary=1 birth Events on one Person
death_singularity_violation   GC05  Multiple is_primary=1 death Events on one Person
life_event_sequence_violation GC02  Chronological order broken across life Events
parent_age_implausible        GC12  Parent–child birth-year gap outside plausible range
marriage_age_implausible      GC13  Person under 15 at marriage date
lifespan_boundary_violated    GC01  Record date outside concluded lifespan
unlinked_recorded_person       —    RecordedPerson with no Person conclusion
single_census_appearance       —    Person appears in only one census, no death Event
link_conflict_resolved         —    RecordedPerson's opinion revised during relationship resolution

Design notes
------------
- All SQL lives here, not in dal/; these are ad-hoc analytical queries, not
  reusable DAL primitives.  (DAL repos cover CRUD; findings functions cover
  read-only research-reporting queries.)
- Thresholds match genealogical_constraints.md and constants.py conventions.
- Detail strings must include actual DB values (years, IDs, gaps) so the
  researcher can evaluate each finding without running additional queries.
- Conservative thresholds: prefer under-reporting to noise.
"""

from __future__ import annotations

import re

import psycopg2.extensions

from src.review.report import ReportItem

# ---------------------------------------------------------------------------
# Thresholds (from genealogical_constraints.md)
# ---------------------------------------------------------------------------

_AGE_TOLERANCE      = 2    # years — applied to derived/estimated birth years
_SEQ_TOLERANCE      = 2    # years — life-event sequence check
_LIFESPAN_TOLERANCE = 5    # years — lifespan boundary check
_MIN_PARENT_GAP     = 15   # years — minimum parent–child birth-year gap
_MAX_MATERNAL_GAP   = 50   # years — maximum mother–child birth-year gap
_MAX_PATERNAL_GAP   = 70   # years — maximum father–child birth-year gap
_MIN_MARRIAGE_AGE   = 15   # years

# Event types that are evidence of being alive (used in sequence checks)
_LIVING_EVENT_TYPES = frozenset({"census", "residence", "valuation", "tithe", "military_service"})

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _year(date_str: str | None) -> int | None:
    """Extract four-digit year from an ISO 8601 partial date string."""
    if not date_str:
        return None
    m = re.match(r"^(\d{4})", date_str.strip())
    return int(m.group(1)) if m else None


def _person_label(conn: psycopg2.extensions.connection, person_id: int) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT label FROM person WHERE person_id = %s", (person_id,))
        row = cur.fetchone()
    return row["label"] if row else str(person_id)


def _derive_birth_year(conn: psycopg2.extensions.connection, person_id: int) -> int | None:
    """
    Best available birth-year estimate for a Person.

    Priority:
    1. is_primary birth Event date
    2. is_primary baptism Event date (lower bound proxy)
    3. Earliest census RecordedPerson age back-calculated from record date
    """
    with conn.cursor() as cur:
        # 1. Primary birth Event
        cur.execute(
            """
            SELECT e.date FROM event e
            JOIN person_event pe ON pe.event_id = e.event_id
            WHERE pe.person_id = %s AND e.type = 'birth' AND e.is_primary = 1
              AND e.date IS NOT NULL
            LIMIT 1
            """,
            (person_id,),
        )
        row = cur.fetchone()
        if row:
            y = _year(row["date"])
            if y:
                return y

        # 2. Primary baptism Event
        cur.execute(
            """
            SELECT e.date FROM event e
            JOIN person_event pe ON pe.event_id = e.event_id
            WHERE pe.person_id = %s AND e.type = 'baptism' AND e.is_primary = 1
              AND e.date IS NOT NULL
            LIMIT 1
            """,
            (person_id,),
        )
        row = cur.fetchone()
        if row:
            y = _year(row["date"])
            if y:
                return y

        # 3. Derive from census RecordedPerson age + record date
        cur.execute(
            """
            SELECT rp.age, r.date
            FROM person_recorded_person prp
            JOIN recorded_person rp ON rp.recorded_person_id = prp.recorded_person_id
            JOIN record r ON r.record_id = rp.record_id
            JOIN source s ON s.source_id = r.source_id
            WHERE prp.person_id = %s
              AND s.type = 'census'
              AND rp.age IS NOT NULL
              AND r.date IS NOT NULL
            ORDER BY rp.age ASC
            LIMIT 1
            """,
            (person_id,),
        )
        row = cur.fetchone()
        if row and row["age"] is not None:
            census_year = _year(str(row["date"]))
            if census_year:
                return census_year - int(row["age"])

    return None


def _derive_death_year(conn: psycopg2.extensions.connection, person_id: int) -> int | None:
    """Return the is_primary death year for a Person, or None."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT e.date FROM event e
            JOIN person_event pe ON pe.event_id = e.event_id
            WHERE pe.person_id = %s AND e.type = 'death' AND e.is_primary = 1
              AND e.date IS NOT NULL
            LIMIT 1
            """,
            (person_id,),
        )
        row = cur.fetchone()
    return _year(row["date"]) if row else None


def _get_active_person_ids(conn: psycopg2.extensions.connection) -> list[int]:
    """Return all active Person IDs, ordered."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT person_id FROM person WHERE status = 'active' ORDER BY person_id"
        )
        return [r["person_id"] for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# GC07 — merge_error_candidate
# ---------------------------------------------------------------------------

def find_merge_error_candidates(
    conn: psycopg2.extensions.connection,
) -> list[ReportItem]:
    """
    GC07: A Person linked to 2+ active Records from the same census source is
    a probable merge error — two distinct household members have been collapsed
    into one Person.

    Query: person_recorded_person → recorded_person → record → source
    grouped by (person_id, source_id), HAVING count > 1.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                prp.person_id,
                r.source_id,
                s.title   AS source_title,
                COUNT(DISTINCT r.record_id) AS record_count,
                ARRAY_AGG(DISTINCT r.record_id ORDER BY r.record_id) AS record_ids
            FROM person_recorded_person prp
            JOIN recorded_person rp ON rp.recorded_person_id = prp.recorded_person_id
            JOIN record r ON r.record_id = rp.record_id
            JOIN source s ON s.source_id = r.source_id
            JOIN person p ON p.person_id = prp.person_id
            WHERE s.type = 'census'
              AND p.status = 'active'
            GROUP BY prp.person_id, r.source_id, s.title
            HAVING COUNT(DISTINCT r.record_id) > 1
            ORDER BY COUNT(DISTINCT r.record_id) DESC, prp.person_id
            """
        )
        rows = cur.fetchall()

    items = []
    for row in rows:
        pid = row["person_id"]
        label = _person_label(conn, pid)
        record_ids = list(row["record_ids"])
        source_count = row["record_count"]

        items.append(ReportItem(
            finding_type="merge_error_candidate",
            priority=0,  # assigned by priority.py
            person_id=pid,
            relationship_id=None,
            event_id=None,
            record_ids=record_ids,
            title=f"Person {pid} ({label}) linked to {source_count} Records from "
                  f"same census source: {row['source_title']}",
            detail=(
                f"Person {pid} ({label}) is linked to {source_count} distinct Records "
                f"(record_ids: {', '.join(str(r) for r in record_ids)}) from the same "
                f"census source '{row['source_title']}' (source_id={row['source_id']}). "
                f"Each Record represents a separate census household return. "
                f"A single Person should not appear in multiple households in the same "
                f"census; this is a probable merge error (GC07). "
                f"Review the linked RecordedPersons to determine whether these are the "
                f"same individual or two distinct people who have been incorrectly merged."
            ),
            recommended_action="Review and split Person if Records represent distinct individuals.",
        ))

    return items


# ---------------------------------------------------------------------------
# GC04 — birth_singularity_violation
# ---------------------------------------------------------------------------

def find_birth_singularity_violations(
    conn: psycopg2.extensions.connection,
) -> list[ReportItem]:
    """
    GC04: A Person with multiple Events of type 'birth' marked is_primary=1.
    Exactly one birth Event should be marked is_primary; rebuild_consensus
    should ensure this, but this check catches any inconsistency.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pe.person_id, COUNT(*) AS primary_count,
                   ARRAY_AGG(e.event_id ORDER BY e.event_id) AS event_ids,
                   ARRAY_AGG(e.date ORDER BY e.event_id) AS event_dates
            FROM event e
            JOIN person_event pe ON pe.event_id = e.event_id
            JOIN person p ON p.person_id = pe.person_id
            WHERE e.type = 'birth' AND e.is_primary = 1 AND p.status = 'active'
            GROUP BY pe.person_id
            HAVING COUNT(*) > 1
            ORDER BY pe.person_id
            """
        )
        rows = cur.fetchall()

    items = []
    for row in rows:
        pid = row["person_id"]
        label = _person_label(conn, pid)
        event_ids = list(row["event_ids"])
        dates = [d or "unknown" for d in row["event_dates"]]
        date_pairs = ", ".join(
            f"event {eid} ({d})" for eid, d in zip(event_ids, dates)
        )

        items.append(ReportItem(
            finding_type="birth_singularity_violation",
            priority=0,
            person_id=pid,
            relationship_id=None,
            event_id=None,
            record_ids=[],
            title=f"Person {pid} ({label}) has {row['primary_count']} birth Events "
                  f"marked is_primary",
            detail=(
                f"Person {pid} ({label}) has {row['primary_count']} birth Events "
                f"with is_primary=1: {date_pairs}. "
                f"Exactly one birth Event should be primary (GC04). "
                f"This indicates a rebuild_consensus failure or a merge error — "
                f"two distinct birth Events were concluded and both marked primary. "
                f"Review the underlying Records to determine which date is correct."
            ),
            recommended_action=(
                "Run rebuild_consensus, or manually set is_primary=0 on all but one "
                "birth Event."
            ),
        ))

    return items


# ---------------------------------------------------------------------------
# GC05 — death_singularity_violation
# ---------------------------------------------------------------------------

def find_death_singularity_violations(
    conn: psycopg2.extensions.connection,
) -> list[ReportItem]:
    """
    GC05: A Person with multiple Events of type 'death' marked is_primary=1.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pe.person_id, COUNT(*) AS primary_count,
                   ARRAY_AGG(e.event_id ORDER BY e.event_id) AS event_ids,
                   ARRAY_AGG(e.date ORDER BY e.event_id) AS event_dates
            FROM event e
            JOIN person_event pe ON pe.event_id = e.event_id
            JOIN person p ON p.person_id = pe.person_id
            WHERE e.type = 'death' AND e.is_primary = 1 AND p.status = 'active'
            GROUP BY pe.person_id
            HAVING COUNT(*) > 1
            ORDER BY pe.person_id
            """
        )
        rows = cur.fetchall()

    items = []
    for row in rows:
        pid = row["person_id"]
        label = _person_label(conn, pid)
        event_ids = list(row["event_ids"])
        dates = [d or "unknown" for d in row["event_dates"]]
        date_pairs = ", ".join(
            f"event {eid} ({d})" for eid, d in zip(event_ids, dates)
        )

        items.append(ReportItem(
            finding_type="death_singularity_violation",
            priority=0,
            person_id=pid,
            relationship_id=None,
            event_id=None,
            record_ids=[],
            title=f"Person {pid} ({label}) has {row['primary_count']} death Events "
                  f"marked is_primary",
            detail=(
                f"Person {pid} ({label}) has {row['primary_count']} death Events "
                f"with is_primary=1: {date_pairs}. "
                f"Exactly one death Event should be primary (GC05). "
                f"This indicates a rebuild_consensus failure or a merge error."
            ),
            recommended_action=(
                "Run rebuild_consensus, or manually set is_primary=0 on all but one "
                "death Event."
            ),
        ))

    return items


# ---------------------------------------------------------------------------
# GC02 — life_event_sequence_violation
# ---------------------------------------------------------------------------

def find_life_event_sequence_violations(
    conn: psycopg2.extensions.connection,
) -> list[ReportItem]:
    """
    GC02: Chronological order broken across a Person's concluded Events.

    Checks (each with _SEQ_TOLERANCE slack):
    - birth before baptism (infant baptism; adult-baptism not checked)
    - birth before all other non-birth/baptism events
    - death before burial
    - no 'living' events (census, residence, etc.) after death

    Note: thresholds are conservative — only flag clear violations.
    Detail strings include actual values so the researcher can distinguish
    genuine errors from census age-recording imprecision.
    """
    person_ids = _get_active_person_ids(conn)
    items = []

    for pid in person_ids:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT e.event_id, e.type, e.date, e.is_primary
                FROM event e
                JOIN person_event pe ON pe.event_id = e.event_id
                WHERE pe.person_id = %s AND e.date IS NOT NULL
                ORDER BY e.date, e.event_id
                """,
                (pid,),
            )
            events = cur.fetchall()

        if not events:
            continue

        # Build type → list[(event_id, year)] map
        by_type: dict[str, list[tuple[int, int]]] = {}
        for ev in events:
            y = _year(str(ev["date"]))
            if y is not None:
                by_type.setdefault(ev["type"], []).append((ev["event_id"], y))

        def earliest_year(etype: str) -> int | None:
            pairs = by_type.get(etype)
            return min(p[1] for p in pairs) if pairs else None

        birth_year = earliest_year("birth")
        death_year = earliest_year("death")
        burial_year = earliest_year("burial")

        violations: list[str] = []

        # birth before baptism
        baptism_year = earliest_year("baptism")
        if birth_year is not None and baptism_year is not None:
            gap = baptism_year - birth_year
            if gap < 0 and abs(gap) > _SEQ_TOLERANCE:
                violations.append(
                    f"baptism ({baptism_year}) precedes birth ({birth_year}); "
                    f"gap = {abs(gap)} yrs (tolerance = {_SEQ_TOLERANCE} yrs)"
                )

        # birth before all other events
        if birth_year is not None:
            for etype, pairs in by_type.items():
                if etype in ("birth", "baptism"):
                    continue
                for eid, y in pairs:
                    if y < birth_year - _SEQ_TOLERANCE:
                        violations.append(
                            f"{etype} event {eid} ({y}) precedes birth ({birth_year}); "
                            f"gap = {birth_year - y} yrs"
                        )

        # death before burial
        if death_year is not None and burial_year is not None:
            if burial_year < death_year - _SEQ_TOLERANCE:
                violations.append(
                    f"burial ({burial_year}) precedes death ({death_year}); "
                    f"gap = {death_year - burial_year} yrs"
                )

        # no living events after death
        if death_year is not None:
            for etype in _LIVING_EVENT_TYPES:
                for eid, y in by_type.get(etype, []):
                    if y > death_year + _SEQ_TOLERANCE:
                        violations.append(
                            f"{etype} event {eid} ({y}) follows death ({death_year}); "
                            f"gap = {y - death_year} yrs"
                        )

        if not violations:
            continue

        label = _person_label(conn, pid)
        detail_lines = [
            f"Person {pid} ({label}) has {len(violations)} life-event sequence "
            f"violation(s) (GC02, tolerance = {_SEQ_TOLERANCE} yrs):"
        ]
        for v in violations:
            detail_lines.append(f"  • {v}")
        detail_lines.append(
            "Note: age recording in census data is imprecise (±1–2 yrs). "
            "Review actual values above before concluding a genuine error."
        )

        items.append(ReportItem(
            finding_type="life_event_sequence_violation",
            priority=0,
            person_id=pid,
            relationship_id=None,
            event_id=None,
            record_ids=[],
            title=f"Person {pid} ({label}): {len(violations)} life-event sequence "
                  f"violation(s)",
            detail="\n".join(detail_lines),
            recommended_action=(
                "Review event dates. If values are within census age-recording "
                "imprecision, no action needed. Otherwise, check for a merge error."
            ),
        ))

    return items


# ---------------------------------------------------------------------------
# GC12 — parent_age_implausible
# ---------------------------------------------------------------------------

def find_parent_age_implausible(
    conn: psycopg2.extensions.connection,
) -> list[ReportItem]:
    """
    GC12: Parent–child birth-year gap outside plausible range.
    Minimum: 15 years (net of ±2 yr tolerance).
    Maximum: 50 years maternal, 70 years paternal.
    Gender-unknown parents skip the maximum check.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.relationship_id, r.person_id_1 AS parent_id,
                   r.person_id_2 AS child_id,
                   p.gender AS parent_gender
            FROM relationship r
            JOIN person p ON p.person_id = r.person_id_1
            WHERE r.type = 'parent_child'
              AND r.status = 'active'
            ORDER BY r.relationship_id
            """
        )
        rels = cur.fetchall()

    items = []
    for rel in rels:
        parent_id = rel["parent_id"]
        child_id = rel["child_id"]
        rid = rel["relationship_id"]
        gender = rel["parent_gender"]

        parent_birth = _derive_birth_year(conn, parent_id)
        child_birth = _derive_birth_year(conn, child_id)

        if parent_birth is None or child_birth is None:
            continue  # cannot evaluate; skip silently

        gap = child_birth - parent_birth
        # Best-case gap for minimum check (tolerance closes the gap)
        effective_min = gap + _AGE_TOLERANCE
        # Worst-case gap for maximum check (tolerance widens the gap)
        effective_max = gap - _AGE_TOLERANCE

        violations: list[str] = []

        if effective_min < _MIN_PARENT_GAP:
            violations.append(
                f"gap of {gap} yrs is below minimum of {_MIN_PARENT_GAP} yrs "
                f"(parent birth ~{parent_birth}, child birth ~{child_birth})"
            )

        if gender == "female" and effective_max > _MAX_MATERNAL_GAP:
            violations.append(
                f"gap of {gap} yrs exceeds maternal maximum of {_MAX_MATERNAL_GAP} yrs "
                f"(parent birth ~{parent_birth}, child birth ~{child_birth})"
            )
        elif gender == "male" and effective_max > _MAX_PATERNAL_GAP:
            violations.append(
                f"gap of {gap} yrs exceeds paternal maximum of {_MAX_PATERNAL_GAP} yrs "
                f"(parent birth ~{parent_birth}, child birth ~{child_birth})"
            )

        if not violations:
            continue

        parent_label = _person_label(conn, parent_id)
        child_label = _person_label(conn, child_id)

        items.append(ReportItem(
            finding_type="parent_age_implausible",
            priority=0,
            person_id=parent_id,
            relationship_id=rid,
            event_id=None,
            record_ids=[],
            title=(
                f"Relationship {rid}: parent {parent_id} ({parent_label}) / "
                f"child {child_id} ({child_label}) — age gap implausible"
            ),
            detail=(
                f"Relationship {rid} (parent_child): parent Person {parent_id} "
                f"({parent_label}, gender={gender or 'unknown'}) "
                f"birth year ~{parent_birth}; child Person {child_id} "
                f"({child_label}) birth year ~{child_birth}; "
                f"gap = {gap} yrs. Violation(s): "
                + "; ".join(violations)
                + f". Tolerance applied: ±{_AGE_TOLERANCE} yrs on each estimated year. "
                f"GC12 — probable merge error if violation is not explained by "
                f"census age imprecision."
            ),
            recommended_action=(
                "Verify birth year estimates. If confirmed implausible, review the "
                "underlying RecordedRelationships for a mis-assigned relationship."
            ),
        ))

    return items


# ---------------------------------------------------------------------------
# GC13 — marriage_age_implausible
# ---------------------------------------------------------------------------

def find_marriage_age_implausible(
    conn: psycopg2.extensions.connection,
) -> list[ReportItem]:
    """
    GC13: Person under 15 years old at a concluded marriage Event date.
    Birth year derived from is_primary birth Event (with Record-age fallback).
    Tolerance ±2 yrs applied.
    """
    person_ids = _get_active_person_ids(conn)
    items = []

    for pid in person_ids:
        birth_year = _derive_birth_year(conn, pid)
        if birth_year is None:
            continue

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT e.event_id, e.date
                FROM event e
                JOIN person_event pe ON pe.event_id = e.event_id
                WHERE pe.person_id = %s AND e.type = 'marriage' AND e.date IS NOT NULL
                ORDER BY e.date
                """,
                (pid,),
            )
            marriages = cur.fetchall()

        for ev in marriages:
            marriage_year = _year(str(ev["date"]))
            if marriage_year is None:
                continue

            age_at_marriage = marriage_year - birth_year
            # Apply tolerance: best-case age (birth year could be _AGE_TOLERANCE later)
            effective_age = age_at_marriage + _AGE_TOLERANCE

            if effective_age < _MIN_MARRIAGE_AGE:
                label = _person_label(conn, pid)
                items.append(ReportItem(
                    finding_type="marriage_age_implausible",
                    priority=0,
                    person_id=pid,
                    relationship_id=None,
                    event_id=ev["event_id"],
                    record_ids=[],
                    title=(
                        f"Person {pid} ({label}): age ~{age_at_marriage} at marriage "
                        f"event {ev['event_id']} — below minimum of {_MIN_MARRIAGE_AGE}"
                    ),
                    detail=(
                        f"Person {pid} ({label}): marriage Event {ev['event_id']} "
                        f"dated {ev['date']} (year {marriage_year}). "
                        f"Concluded birth year ~{birth_year}. "
                        f"Age at marriage ~{age_at_marriage} yrs "
                        f"(minimum {_MIN_MARRIAGE_AGE} yrs, GC13). "
                        f"Tolerance applied: ±{_AGE_TOLERANCE} yrs on birth year "
                        f"(best-case age = {effective_age}). "
                        f"Probable merge error or incorrect birth year estimate."
                    ),
                    recommended_action=(
                        "Verify birth year and marriage date. Check whether the marriage "
                        "Event is correctly attributed to this Person."
                    ),
                ))

    return items


# ---------------------------------------------------------------------------
# GC01 — lifespan_boundary_violated
# ---------------------------------------------------------------------------

def find_lifespan_boundary_violated(
    conn: psycopg2.extensions.connection,
) -> list[ReportItem]:
    """
    GC01: A Record linked to a Person has a date outside the Person's
    concluded lifespan bounds (±5 yr tolerance).

    Lower bound: is_primary birth year (or baptism year).
    Upper bound: is_primary death year (only checked if death is concluded).
    """
    person_ids = _get_active_person_ids(conn)
    items = []

    for pid in person_ids:
        birth_year = _derive_birth_year(conn, pid)
        death_year = _derive_death_year(conn, pid)

        if birth_year is None and death_year is None:
            continue

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.record_id, r.date AS record_date
                FROM person_recorded_person prp
                JOIN recorded_person rp ON rp.recorded_person_id = prp.recorded_person_id
                JOIN record r ON r.record_id = rp.record_id
                WHERE prp.person_id = %s AND r.date IS NOT NULL
                ORDER BY r.date
                """,
                (pid,),
            )
            linked = cur.fetchall()

        violations: list[tuple[int, str]] = []  # (record_id, description)

        for row in linked:
            record_year = _year(str(row["record_date"]))
            if record_year is None:
                continue

            if birth_year is not None:
                lower = birth_year - _LIFESPAN_TOLERANCE
                if record_year < lower:
                    delta = birth_year - record_year
                    violations.append((
                        row["record_id"],
                        f"Record {row['record_id']} date {record_year} is "
                        f"{delta} yrs before birth year ~{birth_year} "
                        f"(tolerance = {_LIFESPAN_TOLERANCE} yrs)"
                    ))

            if death_year is not None:
                upper = death_year + _LIFESPAN_TOLERANCE
                if record_year > upper:
                    delta = record_year - death_year
                    violations.append((
                        row["record_id"],
                        f"Record {row['record_id']} date {record_year} is "
                        f"{delta} yrs after death year {death_year} "
                        f"(tolerance = {_LIFESPAN_TOLERANCE} yrs)"
                    ))

        if not violations:
            continue

        label = _person_label(conn, pid)
        record_ids = [v[0] for v in violations]
        detail_lines = [
            f"Person {pid} ({label}) lifespan boundary violation(s) (GC01):",
            f"  Concluded birth year: ~{birth_year or 'unknown'}",
            f"  Concluded death year: {death_year or 'not concluded'}",
        ]
        for _, desc in violations:
            detail_lines.append(f"  • {desc}")

        items.append(ReportItem(
            finding_type="lifespan_boundary_violated",
            priority=0,
            person_id=pid,
            relationship_id=None,
            event_id=None,
            record_ids=record_ids,
            title=(
                f"Person {pid} ({label}): {len(violations)} Record(s) outside "
                f"concluded lifespan"
            ),
            detail="\n".join(detail_lines),
            recommended_action=(
                "Review the flagged Records. A large delta suggests a merge error; "
                "a small delta (within census age precision) may be recording noise."
            ),
        ))

    return items


# ---------------------------------------------------------------------------
# unlinked_recorded_person
# ---------------------------------------------------------------------------

def find_unlinked_recorded_persons(
    conn: psycopg2.extensions.connection,
) -> list[ReportItem]:
    """
    RecordedPersons with no Person conclusion (no row in person_recorded_person).
    These are individuals from the evidence layer who have not been absorbed
    into any Person by the conclusion pipeline.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT rp.recorded_person_id,
                   rp.name_as_recorded,
                   rp.record_id,
                   r.date AS record_date,
                   s.title AS source_title
            FROM recorded_person rp
            JOIN record r ON r.record_id = rp.record_id
            JOIN source s ON s.source_id = r.source_id
            WHERE NOT EXISTS (
                SELECT 1 FROM person_recorded_person prp
                WHERE prp.recorded_person_id = rp.recorded_person_id
            )
            ORDER BY rp.recorded_person_id
            """
        )
        rows = cur.fetchall()

    items = []
    for row in rows:
        items.append(ReportItem(
            finding_type="unlinked_recorded_person",
            priority=0,
            person_id=None,
            relationship_id=None,
            event_id=None,
            record_ids=[row["record_id"]],
            title=(
                f"RecordedPerson {row['recorded_person_id']} "
                f"({row['name_as_recorded']}) has no Person conclusion"
            ),
            detail=(
                f"RecordedPerson {row['recorded_person_id']} "
                f"(name_as_recorded='{row['name_as_recorded']}', "
                f"record_id={row['record_id']}, "
                f"source='{row['source_title']}', "
                f"record date={row['record_date'] or 'unknown'}) "
                f"has no row in person_recorded_person — this individual "
                f"has not been linked to any Person conclusion. "
                f"They either scored below the person resolution threshold "
                f"(0.65) or were not covered by the household matching step."
            ),
            recommended_action=(
                "Review this RecordedPerson. If they represent a real individual, "
                "create a Person conclusion manually or lower the resolution threshold."
            ),
        ))

    return items


# ---------------------------------------------------------------------------
# single_census_appearance
# ---------------------------------------------------------------------------

def find_single_census_appearance(
    conn: psycopg2.extensions.connection,
) -> list[ReportItem]:
    """
    Persons who appear in only one census (one distinct census source across
    all linked Records) and have no concluded death Event.

    This is a research prompt: the Person may have emigrated, died between
    censuses, or simply not been matched across censuses.  Not a constraint
    violation — priority will be lower than schema-state findings.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                p.person_id,
                p.label,
                COUNT(DISTINCT r.source_id) AS census_source_count,
                ARRAY_AGG(DISTINCT s.title ORDER BY s.title) AS census_sources,
                MIN(r.date) AS earliest_date
            FROM person p
            JOIN person_recorded_person prp ON prp.person_id = p.person_id
            JOIN recorded_person rp ON rp.recorded_person_id = prp.recorded_person_id
            JOIN record r ON r.record_id = rp.record_id
            JOIN source s ON s.source_id = r.source_id
            WHERE s.type = 'census'
              AND p.status = 'active'
              AND NOT EXISTS (
                  SELECT 1 FROM event e
                  JOIN person_event pe ON pe.event_id = e.event_id
                  WHERE pe.person_id = p.person_id AND e.type = 'death'
              )
            GROUP BY p.person_id, p.label
            HAVING COUNT(DISTINCT r.source_id) = 1
            ORDER BY p.person_id
            """
        )
        rows = cur.fetchall()

    items = []
    for row in rows:
        pid = row["person_id"]
        sources_str = ", ".join(row["census_sources"])

        items.append(ReportItem(
            finding_type="single_census_appearance",
            priority=0,
            person_id=pid,
            relationship_id=None,
            event_id=None,
            record_ids=[],
            title=(
                f"Person {pid} ({row['label']}): appears in one census only "
                f"({sources_str}), no death Event"
            ),
            detail=(
                f"Person {pid} ({row['label']}) is linked to Records from only "
                f"one census source ({sources_str}). No death Event has been "
                f"concluded for this Person. Possible explanations: "
                f"(a) emigrated between censuses; "
                f"(b) died between censuses; "
                f"(c) present in another census but not matched (name variation, "
                f"poor handwriting, or below similarity threshold). "
                f"Earliest known census date: {row['earliest_date'] or 'unknown'}."
            ),
            recommended_action=(
                "Review other census sources for a plausible match. Consider whether "
                "a death Event should be added based on contextual evidence."
            ),
        ))

    return items


# ---------------------------------------------------------------------------
# link_conflict_resolved — Opinion revision during relationship resolution
# ---------------------------------------------------------------------------

def find_link_conflicts_resolved(
    conn: psycopg2.extensions.connection,
) -> list[ReportItem]:
    """
    RecordedPersons whose Person linkage was revised (opinion revision) during
    relationship resolution when Step 2 (household matching) attempted to link
    them to a different Person than Step 1 assigned.

    This finding logs the genealogical decision chain: when stronger household
    evidence emerges, which RecordedPersons were involved in the conflict, and
    what resolution was chosen (kept existing vs. overwritten).

    Note: This is metadata audit trail, not an error. It helps researchers
    understand why their conclusion diverged from simpler step 1 clustering.
    """
    # Query metadata table tracking opinion revisions
    # (Currently tracked in memory only; stored for next audit session)
    # This is a placeholder for future integration with audit trail storage.
    # For now, return empty list until audit trail persistence is implemented.
    return []


# ---------------------------------------------------------------------------
# Public aggregator
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# unlinked_in_populated_household (discovery for false negatives)
# ---------------------------------------------------------------------------

def find_unlinked_in_populated_households(
    conn: psycopg2.extensions.connection,
) -> list[ReportItem]:
    """
    Find unlinked RecordedPersons in households that contain linked persons.

    Distinguishes two cases:
    1. **Weak scorers** (similarity 0.40–0.50): Almost linked to other censuses—show
       the candidate and why the pair scored below threshold. High-value for manual
       linkage or threshold tuning.
    2. **Isolated records** (no similarity pairs): Only appear in this census, no cross-census
       records. Likely emigrated, married out, or died young. Informational only.

    This is a discovery tool: helps researchers spot systematic patterns and understand
    whether unlinked persons represent missed matches or natural data gaps.
    """
    items = []

    with conn.cursor() as cur:
        # Find households with both linked AND unlinked persons
        cur.execute("""
            SELECT
                r.record_id,
                r.date AS record_date,
                r.place_as_recorded AS place_name,
                r.source_id,
                COUNT(*) FILTER (WHERE prp.person_id IS NOT NULL) as linked_count,
                COUNT(*) FILTER (WHERE prp.person_id IS NULL) as unlinked_count
            FROM record r
            JOIN recorded_person rp ON rp.record_id = r.record_id
            LEFT JOIN person_recorded_person prp ON prp.recorded_person_id = rp.recorded_person_id
            GROUP BY r.record_id, r.date, r.place_as_recorded, r.source_id
            HAVING COUNT(*) FILTER (WHERE prp.person_id IS NOT NULL) >= 1
              AND COUNT(*) FILTER (WHERE prp.person_id IS NULL) >= 1
            ORDER BY r.record_id
        """)
        households_with_mixed = cur.fetchall()

    if not households_with_mixed:
        return []

    from src.validation import validate_name_variant

    for household in households_with_mixed:
        record_id = household["record_id"]

        # Get linked persons in this household
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    prp.person_id,
                    p.label,
                    rp.name_as_recorded,
                    rp.age,
                    rp.role
                FROM person_recorded_person prp
                JOIN person p ON p.person_id = prp.person_id
                JOIN recorded_person rp ON rp.recorded_person_id = prp.recorded_person_id
                JOIN record r ON r.record_id = rp.record_id
                WHERE r.record_id = %s
                ORDER BY rp.role DESC, rp.name_as_recorded
            """, (record_id,))
            linked_persons = cur.fetchall()

        # Get unlinked persons in this household with their best similarity scores
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    rp.recorded_person_id,
                    rp.name_as_recorded,
                    rp.age,
                    rp.role,
                    MAX(rr.score) FILTER (WHERE rr.score < 0.50) as best_weak_score,
                    MAX(CASE WHEN rr.score < 0.50 THEN rr.recorded_person_id_2 END)
                        FILTER (WHERE rr.recorded_person_id_1 = rp.recorded_person_id AND rr.score < 0.50)
                        as weak_match_id_2,
                    MAX(CASE WHEN rr.score < 0.50 THEN rr.recorded_person_id_1 END)
                        FILTER (WHERE rr.recorded_person_id_2 = rp.recorded_person_id AND rr.score < 0.50)
                        as weak_match_id_1
                FROM recorded_person rp
                LEFT JOIN recorded_relationship rr ON
                    (rr.recorded_person_id_1 = rp.recorded_person_id OR rr.recorded_person_id_2 = rp.recorded_person_id)
                    AND rr.type = 'similarity' AND rr.score < 0.50
                WHERE rp.record_id = %s
                  AND NOT EXISTS (
                      SELECT 1 FROM person_recorded_person
                      WHERE recorded_person_id = rp.recorded_person_id
                  )
                GROUP BY rp.recorded_person_id, rp.name_as_recorded, rp.age, rp.role
                ORDER BY best_weak_score DESC NULLS LAST, rp.role DESC, rp.name_as_recorded
            """, (record_id,))
            unlinked_with_scores = cur.fetchall()

        if not unlinked_with_scores:
            continue

        # Separate weak scorers from isolated records
        weak_scorers = [u for u in unlinked_with_scores if u['best_weak_score'] is not None]
        isolated = [u for u in unlinked_with_scores if u['best_weak_score'] is None]

        # Format detail
        detail_lines = [
            f"Household {record_id} ({household['place_name']}, {household['record_date']})",
            "",
            f"Contains {household['linked_count']} linked person(s) and {household['unlinked_count']} unlinked:",
            "",
            "✓ Linked persons:",
        ]

        for lp in linked_persons:
            detail_lines.append(
                f"  • Person {lp['person_id']} ({lp['label']}): "
                f"{lp['name_as_recorded']} (age {lp['age'] or '?'}, {lp['role']})"
            )

        # Weak scorers section
        if weak_scorers:
            detail_lines.append("")
            detail_lines.append("⚠ Weak scorers (0.40–0.50 similarity to other census):")
            for ws in weak_scorers:
                match_id = ws['weak_match_id_2'] or ws['weak_match_id_1']
                detail_lines.append(
                    f"  • RecordedPerson {ws['recorded_person_id']}: {ws['name_as_recorded']} "
                    f"(age {ws['age'] or '?'}, {ws['role']}) → "
                    f"score {ws['best_weak_score']:.2f} with rp_id {match_id}"
                )
            detail_lines.append("")
            detail_lines.append(
                "These persons scored just below the 0.50 linking threshold. Strong candidates "
                "for manual linkage or threshold adjustment."
            )

        # Isolated records section
        if isolated:
            detail_lines.append("")
            detail_lines.append("○ Isolated records (no cross-census records found):")
            for record in isolated:
                detail_lines.append(
                    f"  • RecordedPerson {record['recorded_person_id']}: {record['name_as_recorded']} "
                    f"(age {record['age'] or '?'}, {record['role']})"
                )
            detail_lines.append("")
            detail_lines.append(
                "These persons appear ONLY in this census. Likely emigrated, married out of area, "
                "or died young. Can be linked to household parents for context, but no cross-census "
                "verification possible."
            )

        detail_lines.append("")
        detail_lines.append(
            "Research action: Weak scorers warrant immediate review for manual linkage. "
            "Isolated records are informational—decide whether to link to household parents based on "
            "genealogical judgment."
        )

        title_parts = []
        if weak_scorers:
            title_parts.append(f"{len(weak_scorers)} weak scorers")
        if isolated:
            title_parts.append(f"{len(isolated)} isolated")

        items.append(ReportItem(
            finding_type="unlinked_in_populated_household",
            priority=1 if weak_scorers else 3,  # Higher priority if there are weak scorers
            person_id=None,
            relationship_id=None,
            event_id=None,
            record_ids=[record_id],
            title=f"Household {record_id}: {' + '.join(title_parts)}",
            detail="\n".join(detail_lines),
            recommended_action=(
                "For weak scorers: Review candidates and consider manual linkage or threshold tuning. "
                "For isolated records: Link to household for genealogical context if appropriate, or note as "
                "emigrated/deceased."
            ),
        ))

    return items


def run_all_findings(
    conn: psycopg2.extensions.connection,
) -> list[ReportItem]:
    """
    Run all v1.0 finding functions and return the combined list.
    Priority scores are not yet assigned — that is done by priority.py.
    """
    items: list[ReportItem] = []
    items.extend(find_merge_error_candidates(conn))
    items.extend(find_birth_singularity_violations(conn))
    items.extend(find_death_singularity_violations(conn))
    items.extend(find_life_event_sequence_violations(conn))
    items.extend(find_parent_age_implausible(conn))
    items.extend(find_marriage_age_implausible(conn))
    items.extend(find_lifespan_boundary_violated(conn))
    items.extend(find_unlinked_recorded_persons(conn))
    items.extend(find_single_census_appearance(conn))
    items.extend(find_link_conflicts_resolved(conn))
    items.extend(find_unlinked_in_populated_households(conn))
    return items
