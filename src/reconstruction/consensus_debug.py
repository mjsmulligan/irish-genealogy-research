"""
GRA — Consensus Debug Log
Dataclasses, population helpers, and file writer for the rebuild-consensus
debug log.  Imported by scoring.py when debug mode is active.

The accumulator (ConsensusDebugLog) is populated inline during
rebuild_consensus() — no separate helper functions are needed because all
relevant data is already available as local variables inside the person loop.

Public API
----------
Constants:
    DEBUG_LOG_FILENAME          — hardcoded output filename for this stage
    SCORE_VERSION               — re-exported from scoring constants

Dataclasses:
    OrphanedEventRecord         — one event with zero supporting records
    TieBreakRecord              — one arbitration where a deterministic
                                  tiebreak was applied
    NoEventPersonRecord         — one person with no events at all
    HighAlternativeRecord       — one person with an unusually high count of
                                  non-primary events for a single event type
    ConsensusDebugLog           — accumulator; mutated inline by scoring.py

Writer:
    write_consensus_debug_log(path_dir, debug, result)
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.reconstruction.scoring import RebuildConsensusResult

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEBUG_LOG_FILENAME = "consensus_debug.log"

# Thresholds for Section 3 analysis — defined here so they are visible to
# both the accumulator population code in scoring.py and the analysis in
# write_consensus_debug_log().
HIGH_ALTERNATIVE_THRESHOLD = 3   # non-primary events of one type for one person
ORPHAN_RATE_WARN            = 0.05  # 5 % of all events orphaned → flag
TIE_RATE_WARN               = 0.10  # 10 % of arbitrations used tiebreak → flag

_W = 78  # page width for section separators


# ---------------------------------------------------------------------------
# Helper records — captured during the person loop in scoring.py
# ---------------------------------------------------------------------------

@dataclass
class OrphanedEventRecord:
    """An event that has no supporting records in event_record (vote_count=0)."""
    person_id:   int
    person_label: str
    event_id:    int
    event_type:  str
    is_primary:  bool   # True when it was the only event of that type


@dataclass
class TieBreakRecord:
    """An arbitration where two or more events had equal vote counts."""
    person_id:    int
    person_label: str
    event_type:   str
    tied_event_ids: list[int]
    winner_id:    int
    vote_count:   int   # the tied vote count (same for all tied events)


@dataclass
class NoEventPersonRecord:
    """A person in the conclusion layer who has no events at all."""
    person_id:    int
    person_label: str


@dataclass
class HighAlternativeRecord:
    """A person with an unusually large number of non-primary events of one type."""
    person_id:        int
    person_label:     str
    event_type:       str
    alternative_count: int   # number of non-primary events of this type


# ---------------------------------------------------------------------------
# Accumulator
# ---------------------------------------------------------------------------

@dataclass
class ConsensusDebugLog:
    """
    Populated inline by rebuild_consensus() during its person loop.

    scoring.py creates one instance and passes it to rebuild_consensus()
    when debug mode is active.  The writer is called once rebuild_consensus()
    returns.
    """
    run_ts:                str = ""
    score_version:         str = ""

    # Per-person detail lists — appended to during the person loop
    orphaned_events:       list[OrphanedEventRecord]    = field(default_factory=list)
    tie_breaks:            list[TieBreakRecord]         = field(default_factory=list)
    no_event_persons:      list[NoEventPersonRecord]    = field(default_factory=list)
    high_alternatives:     list[HighAlternativeRecord]  = field(default_factory=list)

    # Label cache — populated by scoring.py before the person loop so that
    # detail records can carry human-readable labels without a DB round-trip
    # per record.  keyed by person_id.
    _label_cache: dict[int, str] = field(default_factory=dict)

    def label(self, person_id: int) -> str:
        """Return human-readable label for person_id, falling back to the id."""
        return self._label_cache.get(person_id, str(person_id))

    def record_orphaned_event(
        self,
        person_id: int,
        event_id: int,
        event_type: str,
        is_primary: bool,
    ) -> None:
        self.orphaned_events.append(OrphanedEventRecord(
            person_id=person_id,
            person_label=self.label(person_id),
            event_id=event_id,
            event_type=event_type,
            is_primary=is_primary,
        ))

    def record_tie_break(
        self,
        person_id: int,
        event_type: str,
        tied_event_ids: list[int],
        winner_id: int,
        vote_count: int,
    ) -> None:
        self.tie_breaks.append(TieBreakRecord(
            person_id=person_id,
            person_label=self.label(person_id),
            event_type=event_type,
            tied_event_ids=list(tied_event_ids),
            winner_id=winner_id,
            vote_count=vote_count,
        ))

    def record_no_event_person(self, person_id: int) -> None:
        self.no_event_persons.append(NoEventPersonRecord(
            person_id=person_id,
            person_label=self.label(person_id),
        ))

    def record_high_alternatives(
        self,
        person_id: int,
        event_type: str,
        alternative_count: int,
    ) -> None:
        self.high_alternatives.append(HighAlternativeRecord(
            person_id=person_id,
            person_label=self.label(person_id),
            event_type=event_type,
            alternative_count=alternative_count,
        ))


# ---------------------------------------------------------------------------
# Formatting helpers (mirrors debug.py conventions)
# ---------------------------------------------------------------------------

def _hr(char: str = "─") -> str:
    return char * _W


def _wrap(text: str, indent: str = "    ", width: int = 74) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = indent
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current.rstrip())
            current = indent + word + " "
        else:
            current += word + " "
    if current.strip():
        lines.append(current.rstrip())
    return lines


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def write_consensus_debug_log(
    path_dir: str,
    debug: ConsensusDebugLog,
    result: "RebuildConsensusResult",
) -> None:
    """
    Write the three-section consensus debug log to path_dir/consensus_debug.log.

    path_dir is the run output directory (the same directory used for
    household_debug.log and person_debug.log).  The filename is hardcoded
    via DEBUG_LOG_FILENAME so the caller does not need to manage filenames.
    """
    out: list[str] = []

    def emit(*args: str) -> None:
        out.extend(args)

    def section(title: str) -> None:
        emit("", "═" * _W, f"  {title}", "═" * _W)

    def sub(title: str) -> None:
        emit("", f"  ── {title}", f"  {'─' * (_W - 5)}")

    def kv(label: str, value: Any, width: int = 38) -> None:
        emit(f"  {label:<{width}} {value}")

    # ── Header ──────────────────────────────────────────────────────────────
    emit(
        "GRA Reconstruction Pipeline — Consensus Debug Log",
        f"Generated : {debug.run_ts}",
        f"Score ver : {debug.score_version}",
    )

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 1 — PIPELINE SUMMARY
    # ═══════════════════════════════════════════════════════════════════════
    section("SECTION 1 — PIPELINE SUMMARY")

    sub("Arbitration overview")
    kv("Persons processed:",        result.persons_processed)
    kv("Persons with no events:",   len(debug.no_event_persons))
    kv("Event types arbitrated:",   result.event_types_arbitrated)
    kv("Primary events set:",       result.primary_events_set)
    kv("Alternative events set:",   result.alternative_events_set)
    kv("Ties broken (by event_id):", result.ties_broken)
    kv("Orphaned events (0 votes):", result.orphaned_events)

    total_events = result.primary_events_set + result.alternative_events_set
    if total_events > 0:
        orphan_rate = result.orphaned_events / total_events
        tie_rate    = result.ties_broken / max(result.event_types_arbitrated, 1)
        kv("Orphan rate:",  f"{orphan_rate:.1%}")
        kv("Tie-break rate:", f"{tie_rate:.1%}")

    if result.errors:
        sub(f"Arbitration errors ({len(result.errors)})")
        for err in result.errors:
            emit(f"    {err}")

    sub("High-alternative persons (> {HIGH_ALTERNATIVE_THRESHOLD} non-primary events of one type)".format(
        HIGH_ALTERNATIVE_THRESHOLD=HIGH_ALTERNATIVE_THRESHOLD
    ))
    if debug.high_alternatives:
        kv("Count:", len(debug.high_alternatives))
        # Show the worst offenders in summary
        worst = sorted(debug.high_alternatives, key=lambda r: -r.alternative_count)
        for rec in worst[:5]:
            emit(f"    pid={rec.person_id} ({rec.person_label})  "
                 f"type={rec.event_type}  alternatives={rec.alternative_count}")
        if len(worst) > 5:
            emit(f"    ... and {len(worst) - 5} more (see Section 2)")
    else:
        emit("    None detected.")

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 2 — DETAIL
    # ═══════════════════════════════════════════════════════════════════════
    section("SECTION 2 — DETAIL")

    # ── Persons with no events ───────────────────────────────────────────
    sub(f"Persons with no events ({len(debug.no_event_persons)})")
    if debug.no_event_persons:
        emit(
            "  These persons exist in the conclusion layer but have no events",
            "  linked via person_event. They will be invisible to any event-",
            "  driven query and likely represent inference or linkage gaps.",
            "",
        )
        for rec in sorted(debug.no_event_persons, key=lambda r: r.person_id):
            emit(f"    pid={rec.person_id}  {rec.person_label}")
    else:
        emit("    None — all persons have at least one event.")

    # ── Orphaned events ──────────────────────────────────────────────────
    sub(f"Orphaned events — zero supporting records ({len(debug.orphaned_events)})")
    if debug.orphaned_events:
        emit(
            "  These events have no rows in event_record. They were created",
            "  by inference or conclusion derivation but were never linked to",
            "  a source record. primary=True means they were the only event",
            "  of that type for the person, so they won by default.",
            "",
        )
        hdr = (
            f"  {'PID':>6}  "
            f"{'PERSON':<30}  "
            f"{'EVENT_TYPE':<18}  "
            f"{'EID':>6}  "
            f"{'PRIMARY'}"
        )
        emit(hdr, "  " + "─" * (_W - 2))
        for rec in sorted(debug.orphaned_events, key=lambda r: (r.person_id, r.event_type)):
            emit(
                f"  {rec.person_id:>6}  "
                f"{rec.person_label[:30]:<30}  "
                f"{rec.event_type:<18}  "
                f"{rec.event_id:>6}  "
                f"{'yes' if rec.is_primary else 'no'}"
            )
    else:
        emit("    None — all events have at least one supporting record.")

    # ── Tie-break detail ─────────────────────────────────────────────────
    sub(f"Tie-breaks applied ({len(debug.tie_breaks)})")
    if debug.tie_breaks:
        emit(
            "  Ties occur when two or more events of the same type for one",
            "  person have equal vote counts. The lower event_id wins.",
            "  A high tie rate suggests many persons have conflicting events",
            "  with equal record support — a possible over-merging signal.",
            "",
        )
        for rec in sorted(debug.tie_breaks, key=lambda r: (r.person_id, r.event_type)):
            tied_str = ", ".join(str(e) for e in rec.tied_event_ids)
            emit(
                f"  pid={rec.person_id} ({rec.person_label})  "
                f"type={rec.event_type}  "
                f"votes={rec.vote_count}  "
                f"tied=[{tied_str}]  winner={rec.winner_id}"
            )
    else:
        emit("    None — all arbitrations had a clear winner.")

    # ── High-alternative persons (full list) ─────────────────────────────
    sub(f"High-alternative persons — full list ({len(debug.high_alternatives)})")
    if debug.high_alternatives:
        emit(
            f"  Persons with more than {HIGH_ALTERNATIVE_THRESHOLD} non-primary events of one",
            "  type. High counts indicate a person was merged across more",
            "  records than expected — possible false merge upstream.",
            "",
        )
        hdr = (
            f"  {'PID':>6}  "
            f"{'PERSON':<30}  "
            f"{'EVENT_TYPE':<18}  "
            f"{'ALTERNATIVES':>12}"
        )
        emit(hdr, "  " + "─" * (_W - 2))
        for rec in sorted(debug.high_alternatives,
                          key=lambda r: (-r.alternative_count, r.person_id)):
            emit(
                f"  {rec.person_id:>6}  "
                f"{rec.person_label[:30]:<30}  "
                f"{rec.event_type:<18}  "
                f"{rec.alternative_count:>12}"
            )
    else:
        emit(f"    None — no person exceeded {HIGH_ALTERNATIVE_THRESHOLD} alternatives for any event type.")

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 3 — CLAUDE ANALYSIS NOTES
    # ═══════════════════════════════════════════════════════════════════════
    section("SECTION 3 — CLAUDE ANALYSIS NOTES")
    emit(
        "",
        "  This section is written for Claude to read at the start of a research session.",
        "  It summarises what the consensus stage found, what looks suspicious, and what",
        "  to investigate next.  References to reconstruction_algorithms.md and",
        "  genealogical_constraints.md are included where relevant.",
        "",
    )

    issues:    list[str] = []
    positives: list[str] = []
    actions:   list[str] = []

    total_events = result.primary_events_set + result.alternative_events_set

    # ── Persons with no events ───────────────────────────────────────────
    n_no_event = len(debug.no_event_persons)
    if n_no_event > 0:
        pct = 100 * n_no_event / max(result.persons_processed, 1)
        issues.append(
            f"{n_no_event} persons ({pct:.0f}% of {result.persons_processed} processed) "
            f"have no events. These persons exist in the conclusion layer but were never "
            f"reached by inference or linkage — they are invisible to any event-driven "
            f"query. Likely causes: (1) the person was created by a merge but the source "
            f"record's events were not propagated via person_event; (2) household inference "
            f"created the person but did not emit a census event for them."
        )
        actions.append(
            "In Section 2, review the no-event persons list. For each, check whether a "
            "person_record row exists (the person is linked to a source record) but no "
            "person_event row was written. If so, the event derivation step in inference "
            "or linkage is missing a person_event INSERT for this person's record type."
        )
    else:
        positives.append(
            "All persons in the conclusion layer have at least one event — "
            "inference and linkage event derivation achieved full coverage."
        )

    # ── Orphaned event rate ──────────────────────────────────────────────
    if total_events > 0:
        orphan_rate = result.orphaned_events / total_events
        if orphan_rate > ORPHAN_RATE_WARN:
            issues.append(
                f"{result.orphaned_events} events ({orphan_rate:.1%} of {total_events}) "
                f"have zero supporting records in event_record. Orphaned events are set "
                f"to is_primary=true when they are the only event of their type for a "
                f"person, meaning they will appear as consensus facts despite having no "
                f"evidential basis. This is most likely caused by events created during "
                f"inference that were never linked back to a source record via event_record."
            )
            actions.append(
                "Cross-reference the orphaned events in Section 2 with the inference "
                "pipeline. For each orphaned event, verify whether an event_record row "
                "should have been written when the event was created. If the event was "
                "derived rather than directly recorded (e.g. a calculated birth year range "
                "rather than a census age), this may be by design — document it in "
                "reconstruction_algorithms.md if so."
            )
        else:
            positives.append(
                f"Orphaned event rate: {orphan_rate:.1%} ({result.orphaned_events} events) — "
                f"within acceptable bounds. Almost all events have at least one supporting "
                f"record in event_record."
            )

    # ── Tie-break rate ───────────────────────────────────────────────────
    if result.event_types_arbitrated > 0:
        tie_rate = result.ties_broken / result.event_types_arbitrated
        if tie_rate > TIE_RATE_WARN:
            issues.append(
                f"{result.ties_broken} arbitrations ({tie_rate:.1%} of "
                f"{result.event_types_arbitrated}) required a deterministic tiebreak "
                f"(lower event_id wins). A high tie rate means many persons have two or "
                f"more conflicting events of the same type backed by equal record counts. "
                f"In a three-census dataset this is expected only where a person appears "
                f"in exactly two sources — both census events get one vote each. If the "
                f"tie rate is high relative to the proportion of two-source persons, "
                f"it may indicate false merges creating spurious event competition."
            )
            actions.append(
                "Compare the tie-break rate against the proportion of persons linked "
                "across exactly two census years. If tie_rate >> two-source proportion, "
                "inspect the high-alternative persons in Section 2 — those are the most "
                "likely false-merge candidates to investigate in a review session."
            )
        else:
            positives.append(
                f"Tie-break rate: {tie_rate:.1%} ({result.ties_broken} arbitrations) — "
                f"low. Most persons have a clear winning event per type."
            )

    # ── High-alternative persons ─────────────────────────────────────────
    n_high_alt = len(debug.high_alternatives)
    if n_high_alt > 0:
        worst = max(debug.high_alternatives, key=lambda r: r.alternative_count)
        issues.append(
            f"{n_high_alt} person-event-type combination(s) exceed {HIGH_ALTERNATIVE_THRESHOLD} "
            f"non-primary events. The worst case is pid={worst.person_id} "
            f"({worst.person_label}) with {worst.alternative_count} alternative "
            f"{worst.event_type} events. In a three-census dataset, a person can "
            f"legitimately have at most three census events — more than that is a "
            f"strong signal of a false merge in the linkage stage."
        )
        actions.append(
            f"In the update-knowledge session, review the {n_high_alt} high-alternative "
            f"persons in Section 2. For each, check how many distinct census sources "
            f"contributed — more sources than census years means a merge was incorrect. "
            f"Use the person_record and event_record tables to trace which records were "
            f"linked to the person and whether they are genuinely the same individual."
        )
    else:
        positives.append(
            f"No person exceeds {HIGH_ALTERNATIVE_THRESHOLD} non-primary events for any "
            f"event type — alternative event accumulation is within expected bounds."
        )

    # ── Errors ───────────────────────────────────────────────────────────
    if result.errors:
        issues.append(
            f"{len(result.errors)} arbitration error(s) were recorded during the run. "
            f"These are cases where the vote query returned no rows for a known event_id "
            f"list — a defensive guard that should never fire in a consistent database. "
            f"Their presence suggests a referential integrity problem: an event_id exists "
            f"in person_event but not in the event table."
        )
        actions.append(
            "For each error in Section 1, run: "
            "SELECT * FROM event WHERE event_id IN (<ids>) "
            "to verify the event rows exist. If they do not, the person_event junction "
            "has stale rows pointing to deleted events — a cascade delete may be missing "
            "from the schema."
        )

    # ── Emit findings ────────────────────────────────────────────────────
    sub("Issues detected")
    if issues:
        for i, issue in enumerate(issues, 1):
            emit(f"  ISSUE {i}:")
            emit(*_wrap(issue))
            emit("")
    else:
        emit("  None detected.")

    sub("What looks good")
    if positives:
        for pos in positives:
            emit(*_wrap("✓ " + pos, indent="  "))
    else:
        emit("  Nothing to highlight.")

    sub("Recommended actions")
    if actions:
        for i, action in enumerate(actions, 1):
            emit(f"  ACTION {i}:")
            emit(*_wrap(action))
            emit("")
    else:
        emit("  No actions recommended — consensus stage looks healthy.")

    emit("", "═" * _W, "  End of GRA Consensus Debug Log", "═" * _W, "")
    dest = Path(path_dir) / DEBUG_LOG_FILENAME
    dest.write_text("\n".join(out), encoding="utf-8")
