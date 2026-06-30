"""
GRA — Conclusion Layer: Event Resolution

Creates Event conclusions from census Records and Relationships. This is Step 3
of the conclusion pipeline.

Three types of Events created:

1. Census Events (household census appearance)
   - One per Record (household) — all Persons in the household share the event
   - type='census', date from Record, place from place_record
   - is_primary=1 (census Events record distinct moments in time; no conflict)
   - All Persons linked to RecordedPersons in the household are attached via
     person_event; the Record is attached via event_record

2. Birth Events (calculated from age)
   - Derived from census age: birth_year = census_year - age
   - date='YYYY-01-01', date_qualifier='calculated'
   - place_id = census place (person likely born in same area)
   - Collected per Person across all census appearances
   - Birth years within ±2 years → ONE Event, is_primary=1
   - Birth years diverging beyond ±2 → MULTIPLE Events (one per distinct year),
     most common year gets is_primary=1 (by vote count); ties → earliest year wins
   - Guides research: "look for birth record ~1860"

3. Marriage Events (from couple Relationships)
   - One per couple Relationship
   - type='marriage', date=NULL (census doesn't record marriage date)
   - date_qualifier=NULL, is_primary=1
   - relationship_id links to the couple Relationship
   - Linked to both Persons via person_event
   - Linked to all Records that show the couple together via event_record
   - Additive: later BMD ingestion adds a new Event with the actual date rather
     than overwriting this one; a null date does not conflict with a dated record

Entry point:
    run_event_resolution(conn) -> EventResolutionResult
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import re
import uuid

from src.db.repository import Repository
from src.audit import AuditLog


# ---------------------------------------------------------------------------
# Tolerance for collapsing birth years to a single Event
# ---------------------------------------------------------------------------

BIRTH_YEAR_TOLERANCE: int = 2   # years; within this range → one consensus Event


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
    skipped_no_person: int = 0       # Records where no RecordedPerson has a Person
    birth_conflicts_detected: int = 0  # Persons with multiple birth Events (diverged ages)


# ---------------------------------------------------------------------------
# Generic event creation helpers
# ---------------------------------------------------------------------------

def _create_event(
    repo: Repository,
    event_type: str,
    date: str | None = None,
    date_qualifier: str | None = None,
    place_id: int | None = None,
    relationship_id: int | None = None,
    is_primary: bool = True,
    change_group_id: str = "",
) -> int:
    """
    Create an Event row and return the generated event_id.

    Uses RETURNING pattern for the GENERATED ALWAYS AS IDENTITY PK.
    """
    result = repo.execute_returning(
        """
        INSERT INTO event (type, date, date_qualifier, place_id, relationship_id, is_primary)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING event_id
        """,
        (event_type, date, date_qualifier, place_id, relationship_id, 1 if is_primary else 0),
    )
    event_id = result["event_id"]

    # Log event creation
    AuditLog.log_create(
        repo,
        entity_type="event",
        entity_id=event_id,
        values={"type": event_type, "date": date or "NULL", "date_qualifier": date_qualifier or "NULL", "is_primary": is_primary},
        reason=f"Created via event resolution ({event_type})",
        change_group_id=change_group_id,
    )

    return event_id


def _link_event_to_person(
    repo: Repository,
    event_id: int,
    person_id: int,
    change_group_id: str = "",
) -> None:
    """Link an Event to a Person via person_event junction. ON CONFLICT DO NOTHING."""
    repo.execute(
        """
        INSERT INTO person_event (person_id, event_id)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
        """,
        (person_id, event_id),
    )

    # Log the linkage
    AuditLog.log_create(
        repo,
        entity_type="person_event",
        entity_id=event_id,
        values={"person_id": person_id},
        reason="Linked via event resolution",
        change_group_id=change_group_id,
    )


def _link_event_to_record(
    repo: Repository,
    event_id: int,
    record_id: int,
    change_group_id: str = "",
) -> None:
    """Link an Event to a Record via event_record junction (evidence provenance)."""
    repo.execute(
        """
        INSERT INTO event_record (event_id, record_id, verified)
        VALUES (%s, %s, 0)
        ON CONFLICT DO NOTHING
        """,
        (event_id, record_id),
    )

    # Log the linkage
    AuditLog.log_create(
        repo,
        entity_type="event_record",
        entity_id=event_id,
        values={"record_id": record_id},
        reason="Evidence provenance for event resolution",
        change_group_id=change_group_id,
    )


def _bulk_create_events(
    repo: Repository,
    events: list[dict],
) -> list[int]:
    """
    Bulk create Events and return list of generated event_ids.

    Each dict must have keys: type, date, date_qualifier, place_id,
    relationship_id, is_primary

    Returns list of event_ids in same order as input.
    """
    if not events:
        return []

    values_template = "(%s, %s, %s, %s, %s, %s)"
    values_clause = ", ".join([values_template] * len(events))

    values = []
    for e in events:
        values.extend([
            e["type"], e["date"], e["date_qualifier"],
            e["place_id"], e["relationship_id"],
            1 if e["is_primary"] else 0
        ])

    rows = repo.fetch_all(
        f"INSERT INTO event (type, date, date_qualifier, place_id, relationship_id, is_primary) "
        f"VALUES {values_clause} "
        f"RETURNING event_id",
        tuple(values)
    )
    return [row["event_id"] for row in rows]


def _bulk_link_events_to_persons(
    repo: Repository,
    links: list[tuple[int, int]],
) -> None:
    """Bulk insert person_event links. Expects (person_id, event_id) tuples. ON CONFLICT DO NOTHING."""
    if not links:
        return

    values_template = "(%s, %s)"
    values_clause = ", ".join([values_template] * len(links))
    values = [item for pair in links for item in pair]  # Flatten

    repo.execute(
        f"INSERT INTO person_event (person_id, event_id) "
        f"VALUES {values_clause} "
        f"ON CONFLICT DO NOTHING",
        tuple(values)
    )


def _bulk_link_events_to_records(
    repo: Repository,
    links: list[tuple[int, int]],
) -> None:
    """Bulk insert event_record links."""
    if not links:
        return

    values_template = "(%s, %s, 0)"  # verified=0
    values_clause = ", ".join([values_template] * len(links))
    values = [item for pair in links for item in pair]  # Flatten

    repo.execute(
        f"INSERT INTO event_record (event_id, record_id, verified) "
        f"VALUES {values_clause} "
        f"ON CONFLICT DO NOTHING",
        tuple(values)
    )


# ---------------------------------------------------------------------------
# Census Event creation
# ---------------------------------------------------------------------------

def _create_census_event(
    repo: Repository,
    record_id: int,
    date: str | None,
    place_id: int | None,
) -> int:
    """
    Create one census Event for a single census Record.

    Census Events are always is_primary=1 — they record distinct moments in
    time and do not conflict with each other.
    """
    return _create_event(
        repo,
        event_type="census",
        date=date,
        date_qualifier=None,
        place_id=place_id,
        relationship_id=None,
        is_primary=True,
    )


# ---------------------------------------------------------------------------
# Birth Event creation
# ---------------------------------------------------------------------------

def _extract_census_year(date_str: str | None) -> int | None:
    """Extract four-digit year from a census date string (ISO format YYYY-MM-DD)."""
    if not date_str:
        return None
    match = re.match(r"^(\d{4})", date_str)
    return int(match.group(1)) if match else None


def _collect_birth_evidence_for_person(
    repo: Repository,
    person_id: int,
) -> list[tuple[int, int, int | None]]:
    """
    Collect (birth_year, record_id, place_id) tuples for a Person from all
    their census appearances.

    Returns only rows where age IS NOT NULL and census date IS NOT NULL.
    """
    rows = repo.fetch_all(
        """
        SELECT
            rp.age,
            r.date AS census_date,
            r.record_id,
            pr.place_id
        FROM person_recorded_person prp
        JOIN recorded_person rp ON rp.recorded_person_id = prp.recorded_person_id
        JOIN record r           ON r.record_id = rp.record_id
        LEFT JOIN place_record pr ON pr.record_id = r.record_id
        WHERE prp.person_id = %s
          AND rp.age IS NOT NULL
          AND r.date IS NOT NULL
        """,
        (person_id,),
    )

    evidence = []
    for row in rows:
        census_year = _extract_census_year(row["census_date"])
        if census_year and row["age"] is not None:
            birth_year = census_year - int(row["age"])
            evidence.append((birth_year, row["record_id"], row["place_id"]))
    return evidence


def _group_birth_evidence(
    evidence: list[tuple[int, int, int | None]],
) -> dict[int, list[tuple[int, int | None]]]:
    """
    Group birth evidence into buckets where years are within BIRTH_YEAR_TOLERANCE
    of each other.  Each bucket key is the representative (canonical) birth year.

    Algorithm:
      - Sort evidence by birth_year
      - Greedily assign to the first open bucket whose representative year is
        within BIRTH_YEAR_TOLERANCE of the current year
      - If none fits, open a new bucket

    Returns {canonical_year: [(record_id, place_id), ...]}
    """
    # Sort by birth year so we process in order
    sorted_evidence = sorted(evidence, key=lambda t: t[0])

    # {canonical_year: [(record_id, place_id), ...]}
    buckets: dict[int, list[tuple[int, int | None]]] = {}

    for birth_year, record_id, place_id in sorted_evidence:
        # Find a bucket whose canonical year is within tolerance
        matched_key = None
        for key in buckets:
            if abs(birth_year - key) <= BIRTH_YEAR_TOLERANCE:
                matched_key = key
                break

        if matched_key is not None:
            buckets[matched_key].append((record_id, place_id))
        else:
            # New bucket — use this birth_year as canonical
            buckets[birth_year] = [(record_id, place_id)]

    return buckets


def _create_birth_events_for_person(
    repo: Repository,
    person_id: int,
    evidence: list[tuple[int, int, int | None]],
) -> tuple[int, int, int]:
    """
    Create birth Event(s) for a Person.

    If all evidence groups into one bucket → one birth Event, is_primary=1.
    If multiple buckets → one Event per bucket; the bucket with the most
    supporting records gets is_primary=1 (ties: earliest year wins).

    Returns (events_created, person_event_links, event_record_links).
    """
    if not evidence:
        return 0, 0, 0

    buckets = _group_birth_evidence(evidence)

    # Determine which bucket is primary: largest count, tie → earliest year
    primary_year = max(
        buckets,
        key=lambda y: (len(buckets[y]), -y),
    )

    events_created = 0
    pe_links = 0
    er_links = 0

    for canonical_year, records in buckets.items():
        is_primary = (canonical_year == primary_year)

        # Choose place from most common place_id in this bucket (ignore None)
        place_candidates = [pid for _, pid in records if pid is not None]
        place_id: int | None = None
        if place_candidates:
            place_id = Counter(place_candidates).most_common(1)[0][0]

        date_str = f"{canonical_year}-01-01"

        event_id = _create_event(
            repo,
            event_type="birth",
            date=date_str,
            date_qualifier="calculated",
            place_id=place_id,
            relationship_id=None,
            is_primary=is_primary,
            change_group_id=change_group_id,
        )
        events_created += 1

        _link_event_to_person(repo, event_id, person_id, change_group_id)
        pe_links += 1

        for record_id, _ in records:
            _link_event_to_record(repo, event_id, record_id, change_group_id)
            er_links += 1

    return events_created, pe_links, er_links


# ---------------------------------------------------------------------------
# Marriage Event creation
# ---------------------------------------------------------------------------

def _get_couple_relationships(
    repo: Repository,
) -> list[dict]:
    """
    Return all couple Relationships with both Persons.

    Row keys: relationship_id, person_id_1, person_id_2
    """
    return repo.fetch_all(
        """
        SELECT relationship_id, person_id_1, person_id_2
        FROM relationship
        WHERE type = 'couple'
        """
    )


def _get_records_for_couple(
    repo: Repository,
    person_id_1: int,
    person_id_2: int,
) -> list[int]:
    """
    Return record_ids for all census Records that show person_id_1 and person_id_2
    appearing together (i.e. both RecordedPersons within the same Record).

    These become the provenance links on the marriage Event.
    """
    rows = repo.fetch_all(
        """
        SELECT DISTINCT rp1.record_id
        FROM person_recorded_person prp1
        JOIN recorded_person rp1 ON rp1.recorded_person_id = prp1.recorded_person_id
        JOIN person_recorded_person prp2 ON prp2.person_id = %s
        JOIN recorded_person rp2 ON rp2.recorded_person_id = prp2.recorded_person_id
            AND rp2.record_id = rp1.record_id
        WHERE prp1.person_id = %s
        """,
        (person_id_2, person_id_1),
    )
    return [row["record_id"] for row in rows]


def _create_marriage_event(
    repo: Repository,
    relationship_id: int,
    person_id_1: int,
    person_id_2: int,
    supporting_record_ids: list[int],
) -> tuple[int, int, int]:
    """
    Create one marriage Event for a couple Relationship.

    date=NULL, date_qualifier=NULL (census doesn't record marriage date).
    Linked to both Persons via person_event.
    Linked to all supporting Records via event_record.

    Returns (events_created, person_event_links, event_record_links).
    """
    event_id = _create_event(
        repo,
        event_type="marriage",
        date=None,
        date_qualifier=None,
        place_id=None,
        relationship_id=relationship_id,
        is_primary=True,
    )

    _link_event_to_person(repo, event_id, person_id_1)
    _link_event_to_person(repo, event_id, person_id_2)
    pe_links = 2

    er_links = 0
    for record_id in supporting_record_ids:
        _link_event_to_record(repo, event_id, record_id)
        er_links += 1

    return 1, pe_links, er_links


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_event_resolution(
    repo: Repository,
) -> EventResolutionResult:
    """
    Run Event Resolution: create census, birth, and marriage Events.

    Algorithm:

    Pass 1 — Census Events:
      For each census Record:
        - Get all distinct Persons linked (via any RecordedPerson) to this Record
        - Create ONE census Event for the Record
        - Link Event to the Record (provenance) and to each Person (person_event)

    Pass 2 — Birth Events:
      For each Person who appeared in at least one census:
        - Collect (birth_year, record_id, place_id) tuples from all census ages
        - Group into tolerance buckets (±2 years)
        - One bucket → one birth Event, is_primary=1
        - Multiple buckets → one Event per bucket; most-supported is primary

    Pass 3 — Marriage Events:
      For each couple Relationship:
        - Create one marriage Event (date=NULL) linked to the Relationship
        - Link to both Persons
        - Link to Records that show them together (provenance)

    Returns EventResolutionResult with counts.
    """
    result = EventResolutionResult()
    run_change_group_id = str(uuid.uuid4())

    # ------------------------------------------------------------------
    # Pass 1: Census Events
    # ------------------------------------------------------------------
    # Design intent (conceptual_model.md): one census Event per Record,
    # capturing that "this household was enumerated."  All Persons linked
    # to RecordedPersons in the household are attached via person_event.
    # This replaces the previous per-RecordedPerson loop that created N
    # duplicate Events for an N-person household (item 25 fix).

    # Fetch all census Records with their place linkage
    records = repo.fetch_all(
        """
        SELECT
            r.record_id,
            r.date,
            pr.place_id
        FROM record r
        JOIN source s ON s.source_id = r.source_id AND s.type = 'census'
        LEFT JOIN place_record pr ON pr.record_id = r.record_id
        ORDER BY r.record_id
        """
    )

    # Collect census event data for bulk creation
    events_to_create = []
    record_to_persons = {}  # Map record_id -> list of person_ids
    record_ids_ordered = []  # Track order for matching with event_ids

    for record in records:
        record_id = record["record_id"]
        date = record["date"]
        place_id = record["place_id"]

        # Get distinct Persons linked to this household (via any RecordedPerson)
        linked_persons_rows = repo.fetch_all(
            """
            SELECT DISTINCT prp.person_id
            FROM recorded_person rp
            JOIN person_recorded_person prp
                ON prp.recorded_person_id = rp.recorded_person_id
            WHERE rp.record_id = %s
            """,
            (record_id,),
        )
        linked_persons = [row["person_id"] for row in linked_persons_rows]

        if not linked_persons:
            result.skipped_no_person += 1
            result.records_processed += 1
            continue

        events_to_create.append({
            "type": "census",
            "date": date,
            "date_qualifier": "exact",
            "place_id": place_id,
            "relationship_id": None,
            "is_primary": True,
        })
        record_to_persons[record_id] = linked_persons
        record_ids_ordered.append(record_id)
        result.records_processed += 1

    # Bulk create all census events
    event_ids = _bulk_create_events(repo, events_to_create)
    result.census_events_created = len(event_ids)

    # Build link lists
    event_record_links = [(event_ids[i], record_ids_ordered[i])
                          for i in range(len(event_ids))]

    person_event_links = []
    for i, event_id in enumerate(event_ids):
        record_id = record_ids_ordered[i]
        for person_id in record_to_persons[record_id]:
            person_event_links.append((person_id, event_id))

    # Bulk insert all links
    _bulk_link_events_to_records(repo, event_record_links)
    _bulk_link_events_to_persons(repo, person_event_links)

    result.event_record_links += len(event_record_links)
    result.person_event_links += len(person_event_links)

    # ------------------------------------------------------------------
    # Pass 2: Birth Events
    # ------------------------------------------------------------------

    # Get all Persons who have at least one RecordedPerson in a census Record
    person_ids_rows = repo.fetch_all(
        """
        SELECT DISTINCT prp.person_id
        FROM person_recorded_person prp
        JOIN recorded_person rp ON rp.recorded_person_id = prp.recorded_person_id
        JOIN record r ON r.record_id = rp.record_id
        JOIN source s ON s.source_id = r.source_id AND s.type = 'census'
        ORDER BY prp.person_id
        """
    )
    person_ids = [row["person_id"] for row in person_ids_rows]

    # Collect all birth events to create
    birth_events_to_create = []
    birth_person_links = []  # (person_id, event_index_in_batch)
    birth_record_links = []  # (record_id, event_index_in_batch)

    for person_id in person_ids:
        evidence = _collect_birth_evidence_for_person(repo, person_id)
        if not evidence:
            continue

        buckets = _group_birth_evidence(evidence)
        if not buckets:
            continue

        # Determine which bucket is primary
        primary_year = max(buckets, key=lambda y: (len(buckets[y]), -y))

        # Track if this person has multiple birth events (conflict)
        if len(buckets) > 1:
            result.birth_conflicts_detected += 1

        for canonical_year, records in buckets.items():
            is_primary = (canonical_year == primary_year)

            # Choose place from most common place_id in this bucket
            place_candidates = [pid for _, pid in records if pid is not None]
            place_id: int | None = None
            if place_candidates:
                place_id = Counter(place_candidates).most_common(1)[0][0]

            date_str = f"{canonical_year}-01-01"

            event_idx = len(birth_events_to_create)
            birth_events_to_create.append({
                "type": "birth",
                "date": date_str,
                "date_qualifier": "calculated",
                "place_id": place_id,
                "relationship_id": None,
                "is_primary": is_primary,
            })

            # Track person link (will be filled with actual event_id later)
            birth_person_links.append((person_id, event_idx))

            # Track record links
            for record_id, _ in records:
                birth_record_links.append((record_id, event_idx))

    # Bulk create all birth events
    if birth_events_to_create:
        event_ids = _bulk_create_events(repo, birth_events_to_create)
        result.birth_events_created = len(event_ids)

        # Build actual link tuples using generated event_ids
        person_event_links = [(person_id, event_ids[idx])
                              for person_id, idx in birth_person_links]
        event_record_links = [(event_ids[idx], record_id)
                              for record_id, idx in birth_record_links]

        # Bulk insert links
        _bulk_link_events_to_persons(repo, person_event_links)
        _bulk_link_events_to_records(repo, event_record_links)

        result.person_event_links += len(person_event_links)
        result.event_record_links += len(event_record_links)

    # ------------------------------------------------------------------
    # Pass 3: Marriage Events
    # ------------------------------------------------------------------

    couples = _get_couple_relationships(repo)

    # Collect all marriage events to create
    marriage_events_to_create = []
    marriage_person_links = []  # (person_id, event_index_in_batch)
    marriage_record_links = []  # (record_id, event_index_in_batch)

    for couple in couples:
        rel_id = couple["relationship_id"]
        pid1 = couple["person_id_1"]
        pid2 = couple["person_id_2"]

        supporting_records = _get_records_for_couple(repo, pid1, pid2)

        event_idx = len(marriage_events_to_create)
        marriage_events_to_create.append({
            "type": "marriage",
            "date": None,
            "date_qualifier": None,
            "place_id": None,
            "relationship_id": rel_id,
            "is_primary": True,
        })

        # Track person links (both persons for this couple)
        marriage_person_links.append((pid1, event_idx))
        marriage_person_links.append((pid2, event_idx))

        # Track record links
        for record_id in supporting_records:
            marriage_record_links.append((record_id, event_idx))

    # Bulk create all marriage events
    if marriage_events_to_create:
        event_ids = _bulk_create_events(repo, marriage_events_to_create)
        result.marriage_events_created = len(event_ids)

        # Build actual link tuples using generated event_ids
        person_event_links = [(person_id, event_ids[idx])
                              for person_id, idx in marriage_person_links]
        event_record_links = [(event_ids[idx], record_id)
                              for record_id, idx in marriage_record_links]

        # Bulk insert links
        _bulk_link_events_to_persons(repo, person_event_links)
        _bulk_link_events_to_records(repo, event_record_links)

        result.person_event_links += len(person_event_links)
        result.event_record_links += len(event_record_links)

    return result


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

def print_event_resolution_report(result: EventResolutionResult) -> None:
    print("\n  EVENT RESOLUTION")
    print(f"    Records processed:       {result.records_processed:>6}")
    print(f"    Skipped (no Person):     {result.skipped_no_person:>6}")
    print(f"    Census events created:   {result.census_events_created:>6}")
    print(f"    Birth events created:    {result.birth_events_created:>6}")
    if result.birth_conflicts_detected:
        print(f"    Birth conflicts (split): {result.birth_conflicts_detected:>6}")
    print(f"    Marriage events created: {result.marriage_events_created:>6}")
    print(f"    Person-Event links:      {result.person_event_links:>6}")
    print(f"    Event-Record links:      {result.event_record_links:>6}")
