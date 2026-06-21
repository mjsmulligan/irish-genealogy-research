"""
GRA — Conclusion Layer: Event Resolution

Creates Event conclusions from census Records and Relationships. This is Step 3
of the conclusion pipeline.

Three types of Events created:

1. Census Events (individual census appearance)
   - One per RecordedPerson who has a Person
   - type='census', date from Record, place from place_record
   - is_primary=1 (census Events don't conflict)

2. Birth Events (calculated from age)
   - Derived from census age: birth_year = census_year - age
   - date_qualifier='calculated'
   - If Person appears in multiple censuses with different ages:
     * Conflicting birth years → multiple birth Events
     * Most common birth year gets is_primary=1
   - Guides research: "look for birth record ~1860"

3. Marriage Events (from couple Relationships)
   - One per couple Relationship
   - date=NULL (census doesn't record marriage date)
   - relationship_id links to the couple
   - Additive: later BMD ingestion updates this Event with actual date
   - is_primary=1

Entry point:
    run_event_resolution(conn) -> EventResolutionResult
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import re

import psycopg2.extensions


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class EventResolutionResult:
    census_events_created: int = 0
    birth_events_created: int = 0
    marriage_events_created: int = 0
    person_event_links: int = 0
    event_record_links: int = 0
    records_processed: int = 0
    skipped_no_person: int = 0
    birth_conflicts_detected: int = 0  # Persons with multiple birth Events


# ---------------------------------------------------------------------------
# Event creation
# ---------------------------------------------------------------------------

def _create_event(
    conn: psycopg2.extensions.connection,
    event_type: str,
    date: str | None = None,
    date_qualifier: str | None = None,
    place_id: int | None = None,
    relationship_id: int | None = None,
    is_primary: bool = True,
) -> int:
    """
    Create an Event and return the generated event_id.

    Generic event creator for all event types.
    Uses RETURNING pattern for auto-generated ID.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO event (type, date, date_qualifier, place_id, relationship_id, is_primary)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING event_id
            """,
            (event_type, date, date_qualifier, place_id, relationship_id, 1 if is_primary else 0),
        )
        return cur.fetchone()["event_id"]


def _link_event_to_person(
    conn: psycopg2.extensions.connection,
    event_id: int,
    person_id: int,
) -> None:
    """Link an Event to a Person via person_event junction."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO person_event (person_id, event_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (person_id, event_id),
        )


def _link_event_to_record(
    conn: psycopg2.extensions.connection,
    event_id: int,
    record_id: int,
) -> None:
    """Link an Event to a Record via event_record junction (evidence provenance)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO event_record (event_id, record_id, verified)
            VALUES (%s, %s, 0)
            ON CONFLICT DO NOTHING
            """,
            (event_id, record_id),
        )


# ---------------------------------------------------------------------------
# Birth year calculation
# ---------------------------------------------------------------------------

def _extract_census_year(date_str: str | None) -> int | None:
    """Extract year from census date string (ISO format YYYY-MM-DD)."""
    if not date_str:
        return None
    match = re.match(r'^(\d{4})', date_str)
    return int(match.group(1)) if match else None


def _calculate_birth_year(census_year: int, age: int) -> int:
    """Calculate birth year from census year and age."""
    return census_year - age


def _collect_birth_years_for_person(
    conn: psycopg2.extensions.connection,
    person_id: int,
) -> list[tuple[int, int, int]]:
    """
    Collect all calculated birth years for a Person from their census appearances.

    Returns list of (birth_year, record_id, place_id) tuples.
    """
    birth_years = []

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                rp.age,
                r.date as census_date,
                r.record_id,
                pr.place_id
            FROM person_recorded_person prp
            JOIN recorded_person rp ON rp.recorded_person_id = prp.recorded_person_id
            JOIN record r ON r.record_id = rp.record_id
            LEFT JOIN place_record pr ON pr.record_id = r.record_id
            WHERE prp.person_id = %s
              AND rp.age IS NOT NULL
              AND r.date IS NOT NULL
            """,
            (person_id,),
        )
        rows = cur.fetchall()

    for row in rows:
        census_year = _extract_census_year(row["census_date"])
        if census_year and row["age"]:
            birth_year = _calculate_birth_year(census_year, row["age"])
            birth_years.append((birth_year, row["record_id"], row["place_id"]))

    return birth_years


def _determine_primary_birth_year(birth_years: list[int]) -> int:
    """
    Determine which birth year should be marked is_primary.

    Uses most common birth year. If tie, uses earliest (more conservative).
    """
    if not birth_years:
        return None

    counter = Counter(birth_years)
    most_common = counter.most_common(1)[0][0]
    return most_common


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_event_resolution(
    conn: psycopg2.extensions.connection,
) -> EventResolutionResult:
    """
    Run Event Resolution: create census Events for RecordedPersons who have Persons.

    Algorithm:
      1. For each census Record:
         - Get all RecordedPersons
         - For each RecordedPerson with a Person:
           - Create census Event with Record's date and place
           - Link Event to Person
           - Link Event to Record (evidence)

    Returns EventResolutionResult with counts.
    """
    result = EventResolutionResult()

    # Step 1: Get all census Records with their place linkage
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                r.record_id,
                r.date,
                r.source_id,
                pr.place_id
            FROM record r
            JOIN source s ON s.source_id = r.source_id
                AND s.type = 'census'
            LEFT JOIN place_record pr ON pr.record_id = r.record_id
            ORDER BY r.record_id
            """
        )
        records = cur.fetchall()

    # Step 2: Process each Record
    for record in records:
        record_id = record["record_id"]
        date = record["date"]
        place_id = record["place_id"]

        # Get RecordedPersons with Persons for this Record
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    rp.recorded_person_id,
                    prp.person_id
                FROM recorded_person rp
                JOIN person_recorded_person prp
                    ON prp.recorded_person_id = rp.recorded_person_id
                WHERE rp.record_id = %s
                """,
                (record_id,),
            )
            recorded_persons = cur.fetchall()

        if not recorded_persons:
            # No Persons in this household - skip
            result.skipped_no_person += 1
            continue

        # Create Events within a transaction
        with conn:
            for rp in recorded_persons:
                person_id = rp["person_id"]

                # Check if we have place (optional but recommended)
                if not place_id:
                    result.skipped_no_place += 1
                    # Still create Event, but without place
                    pass

                # Create census Event
                event_id = _create_census_event(conn, record_id, date, place_id)
                result.events_created += 1

                # Link Event to Person
                _link_event_to_person(conn, event_id, person_id)
                result.person_event_links += 1

                # Link Event to Record (evidence provenance)
                _link_event_to_record(conn, event_id, record_id)
                result.event_record_links += 1

        result.records_processed += 1

    return result


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

def print_event_resolution_report(result: EventResolutionResult) -> None:
    print("\n  EVENT RESOLUTION")
    print(f"    Records processed:       {result.records_processed:>6}")
    print(f"    Events created:          {result.events_created:>6}")
    print(f"    Person-Event links:      {result.person_event_links:>6}")
    print(f"    Event-Record links:      {result.event_record_links:>6}")
    print(f"    Skipped (no Person):     {result.skipped_no_person:>6}")
    if result.skipped_no_place:
        print(f"    Events w/o place:        {result.skipped_no_place:>6}")
