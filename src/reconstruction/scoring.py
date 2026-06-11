"""
GRA — Evidence Scoring and Consensus Building
Stage 5 of the reconstruction pipeline (runs after link).

For each merged person, aggregates record votes per Event and marks the
highest-vote variant as is_primary=true. All alternatives are retained with
is_primary=false.

Entry point: rebuild_consensus(conn) -> RebuildConsensusResult

Idempotent — safe to rerun any number of times. Resets all is_primary flags
before recomputing, so re-runs after additional linkage are always correct.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

SCORE_VERSION = "consensus_v1.0"

# Event types that participate in consensus arbitration.
# Extend as additional source types are introduced in Release 2+.
_CONSENSUS_EVENT_TYPES = (
    "birth", "baptism", "marriage", "death", "burial",
    "census", "residence", "emigration",
    "valuation", "tithe", "military_service", "pension", "folklore",
)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class RebuildConsensusResult:
    persons_processed: int = 0
    event_types_arbitrated: int = 0
    primary_events_set: int = 0
    alternative_events_set: int = 0
    ties_broken: int = 0          # cases where deterministic tiebreak was used
    orphaned_events: int = 0      # events with no supporting records (vote_count=0)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

def rebuild_consensus(conn: sqlite3.Connection) -> RebuildConsensusResult:
    """
    Rebuild person consensus: for each person + event_type, count supporting
    records per event, then mark the highest-vote event as is_primary=true and
    all others as is_primary=false.

    Tie-breaking: when two events have equal vote counts, the event with the
    lower event_id wins. This is deterministic and stable across reruns.

    Orphaned events (no supporting records in event_record) receive vote_count=0
    and are set to is_primary=false unless they are the only event of that type
    for a person, in which case they are set to is_primary=true.

    Algorithm:
        FOR each person_id:
            FOR each event_type with events for this person:
                votes = count of event_record rows per event_id
                winner = event with max(votes), tiebreak by min(event_id)
                UPDATE event SET is_primary = (event_id == winner)
    """
    result = RebuildConsensusResult()

    # Fetch all person_ids. We process all persons, not just merged ones,
    # so that single-source persons are also correctly initialised.
    person_ids = [
        row[0] for row in conn.execute("SELECT person_id FROM person ORDER BY person_id")
    ]

    for person_id in person_ids:
        result.persons_processed += 1

        # Get all events for this person via the person_event junction.
        events = conn.execute(
            """
            SELECT e.event_id, e.type
            FROM event e
            JOIN person_event pe ON pe.event_id = e.event_id
            WHERE pe.person_id = ?
            ORDER BY e.type, e.event_id
            """,
            (person_id,),
        ).fetchall()

        if not events:
            continue

        # Group event_ids by event_type.
        by_type: dict[str, list[int]] = {}
        for row in events:
            eid, etype = row[0], row[1]
            by_type.setdefault(etype, []).append(eid)

        for event_type, event_ids in by_type.items():
            result.event_types_arbitrated += 1

            if len(event_ids) == 1:
                # Single event of this type — trivially primary.
                eid = event_ids[0]
                conn.execute(
                    "UPDATE event SET is_primary = 1 WHERE event_id = ?", (eid,)
                )
                result.primary_events_set += 1

                # Track orphaned events (no supporting records).
                vote = conn.execute(
                    "SELECT COUNT(*) FROM event_record WHERE event_id = ?", (eid,)
                ).fetchone()[0]
                if vote == 0:
                    result.orphaned_events += 1
                continue

            # Multiple events of the same type — count votes per event.
            vote_rows = conn.execute(
                """
                SELECT e.event_id,
                       COUNT(er.record_id) AS vote_count
                FROM event e
                LEFT JOIN event_record er ON er.event_id = e.event_id
                WHERE e.event_id IN ({placeholders})
                GROUP BY e.event_id
                ORDER BY vote_count DESC, e.event_id ASC
                """.format(placeholders=",".join("?" * len(event_ids))),
                event_ids,
            ).fetchall()

            if not vote_rows:
                # Defensive: no rows returned; skip this group.
                result.errors.append(
                    f"person_id={person_id} event_type={event_type}: "
                    f"vote query returned no rows for event_ids={event_ids}"
                )
                continue

            # Detect ties at the top.
            top_votes = vote_rows[0][1]
            tied = [r for r in vote_rows if r[1] == top_votes]
            if len(tied) > 1:
                result.ties_broken += 1

            # winner = first row (max votes, min event_id due to ORDER BY)
            winner_id = vote_rows[0][0]

            for row in vote_rows:
                eid, vote_count = row[0], row[1]
                is_primary = 1 if eid == winner_id else 0
                conn.execute(
                    "UPDATE event SET is_primary = ? WHERE event_id = ?",
                    (is_primary, eid),
                )
                if is_primary:
                    result.primary_events_set += 1
                else:
                    result.alternative_events_set += 1
                if vote_count == 0:
                    result.orphaned_events += 1

    conn.commit()
    return result


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_rebuild_consensus_report(result: RebuildConsensusResult) -> None:
    print()
    print("=" * 60)
    print("  REBUILD CONSENSUS")
    print("=" * 60)
    print(f"  Persons processed:         {result.persons_processed:>6}")
    print(f"  Event types arbitrated:    {result.event_types_arbitrated:>6}")
    print(f"  Primary events set:        {result.primary_events_set:>6}")
    print(f"  Alternative events set:    {result.alternative_events_set:>6}")
    if result.ties_broken:
        print(f"  Ties broken (by event_id): {result.ties_broken:>6}")
    if result.orphaned_events:
        print(f"  Orphaned events (0 votes): {result.orphaned_events:>6}")
    if result.errors:
        print(f"\n  Errors ({len(result.errors)}):")
        for e in result.errors:
            print(f"    {e}")
    print()
    print("=" * 60)
    print()
