"""
GRA — Genealogy Layer: Genealogical Constraints

Pairwise evaluation of candidate RecordedPerson linkages against
genealogical constraints, and DB-level structural coherence checks.

Provides:
    GenderConsistencyResult  — result dataclass
    NameVariantResult        — result dataclass
    PairViolation            — named violation with code and message
    evaluate_gender_consistency() — GC constraint check
    evaluate_name_variant()       — GC constraint check
    evaluate_pair()               — unified pairwise constraint gate
    check_household_coherence()   — DB-level structural coherence check
    apply_constraints_to_linkages()  — scan all current linkages, return report
    remove_flagged_linkages()        — delete linkages from flagged report

GC codes referenced:
    GC-AGE  Age progression (genealogical_constraints.md §2.3)
    GC-NAM  Name variant (genealogical_constraints.md §3.1)
    GC-GEN  Gender consistency (genealogical_constraints.md §3.2)
    GC-HH   Household coherence (genealogical_constraints.md §4.1)

Authority: docs/genealogical_constraints.md
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import psycopg2
import psycopg2.extensions

from src.genealogy.names import (
    APPROVED_NAME_VARIANTS,
    infer_gender,
)
from src.genealogy.ages import evaluate_age_progression


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class GenderConsistencyResult:
    consistent: bool
    gender_1: str | None
    gender_2: str | None
    message: str = ""

    @property
    def has_flip(self) -> bool:
        return not self.consistent


@dataclass
class NameVariantResult:
    approved: bool
    reason: str = ""


@dataclass
class PairViolation:
    gc_code: str       # e.g. 'GC-GEN', 'GC-AGE', 'GC-NAM'
    message: str


@dataclass
class PairEvaluation:
    """
    Result of running all genealogical constraints against one candidate pair.
    violations is empty when the pair passes all checks.
    """
    violations: list[PairViolation] = field(default_factory=list)

    @property
    def passes(self) -> bool:
        return len(self.violations) == 0


@dataclass
class ConstraintReport:
    """Aggregate result of applying constraints to all current linkages."""
    total_linkages_checked: int = 0
    total_violations: int = 0
    age_violations: int = 0
    name_mismatches: int = 0
    gender_flips: int = 0
    household_errors: int = 0
    flagged_pairs: list[dict] = field(default_factory=list)

    @property
    def violation_rate(self) -> float:
        if self.total_linkages_checked == 0:
            return 0.0
        return 100.0 * self.total_violations / self.total_linkages_checked


# ---------------------------------------------------------------------------
# Constraint functions
# ---------------------------------------------------------------------------

def evaluate_gender_consistency(name1: str | None, name2: str | None) -> GenderConsistencyResult:
    """
    Check whether two name strings imply the same gender.

    A gender flip is strong evidence of different people even when ages
    and surnames match.  Returns consistent=True when either gender is
    ambiguous (conservative: don't reject on uncertain data).

    Authority: genealogical_constraints.md §3.2
    """
    g1 = infer_gender(name1)
    g2 = infer_gender(name2)

    if g1 is None or g2 is None:
        return GenderConsistencyResult(
            consistent=True,
            gender_1=g1,
            gender_2=g2,
            message="Cannot infer gender from one or both names",
        )

    if g1 != g2:
        return GenderConsistencyResult(
            consistent=False,
            gender_1=g1,
            gender_2=g2,
            message=f"Gender flip: {name1} ({g1}) vs {name2} ({g2})",
        )

    return GenderConsistencyResult(
        consistent=True,
        gender_1=g1,
        gender_2=g2,
        message=f"Gender consistent: both {g1}",
    )


def evaluate_name_variant(name1: str | None, name2: str | None) -> NameVariantResult:
    """
    Check whether two full name strings are plausibly the same person's name.

    Checks first-name variant approval (using APPROVED_NAME_VARIANTS) and
    requires surname match when the first names differ.

    Authority: genealogical_constraints.md §3.1
    """
    if not name1 or not name2:
        return NameVariantResult(approved=False, reason="Missing name data")

    if name1.lower().strip() == name2.lower().strip():
        return NameVariantResult(approved=True, reason="Exact match")

    parts1 = name1.lower().strip().split()
    parts2 = name2.lower().strip().split()

    if not parts1 or not parts2:
        return NameVariantResult(approved=False, reason="Cannot parse names")

    first1, first2 = parts1[0], parts2[0]

    if first1 == first2:
        return NameVariantResult(approved=True, reason="First names match")

    def _surnames_match() -> bool:
        s1 = ' '.join(parts1[1:]) if len(parts1) > 1 else ''
        s2 = ' '.join(parts2[1:]) if len(parts2) > 1 else ''
        return s1 == s2

    # Check both directions in the variant graph
    for a, b in [(first1, first2), (first2, first1)]:
        if a in APPROVED_NAME_VARIANTS and b in APPROVED_NAME_VARIANTS[a]:
            if _surnames_match():
                return NameVariantResult(
                    approved=True,
                    reason=f"Approved variant: {first1} ↔ {first2}",
                )
            else:
                s1 = ' '.join(parts1[1:])
                s2 = ' '.join(parts2[1:])
                return NameVariantResult(
                    approved=False,
                    reason=f"Surname mismatch: {s1} vs {s2}",
                )

    return NameVariantResult(
        approved=False,
        reason=f"Different first names: {first1} vs {first2}",
    )


def evaluate_pair(
    name1: str | None,
    age1: float | None,
    source_id_1: int,
    name2: str | None,
    age2: float | None,
    source_id_2: int,
) -> PairEvaluation:
    """
    Run all genealogical constraints against a candidate pair of RecordedPersons.

    This is the single authoritative gate used by:
        - evidence/features/census_person.py  (Splink feature classification)
        - conclusion/person_resolution.py     (pre-clustering filter)
        - conclusion/relationship_resolution.py (household extension guard)
        - conclusion/validation_cleanup.py    (post-conclusion sweep)
        - review/findings.py                  (researcher-facing reports)

    Returns a PairEvaluation; check .passes for go/no-go, .violations for detail.

    Constraint order: gender first (highest-confidence disqualifier), then age,
    then name (only when no gender flip — gender flip already covers the name issue).

    Authority: docs/genealogical_constraints.md
    """
    result = PairEvaluation()

    # GC-GEN: gender consistency
    gender_check = evaluate_gender_consistency(name1, name2)
    if not gender_check.consistent:
        result.violations.append(PairViolation(gc_code='GC-GEN', message=gender_check.message))

    # GC-AGE: age progression (only when ages are available)
    if age1 is not None and age2 is not None:
        age_check = evaluate_age_progression(age1, source_id_1, age2, source_id_2)
        if not age_check.valid:
            result.violations.append(PairViolation(gc_code='GC-AGE', message=age_check.message))

    # GC-NAM: name variant (skip when gender flip already present — redundant)
    if not gender_check.has_flip:
        name_check = evaluate_name_variant(name1, name2)
        if not name_check.approved:
            result.violations.append(PairViolation(gc_code='GC-NAM', message=name_check.reason))

    return result


# ---------------------------------------------------------------------------
# DB-level structural checks
# ---------------------------------------------------------------------------

def check_household_coherence(
    conn: psycopg2.extensions.connection,
) -> tuple[int, int, list[str]]:
    """
    Check for structurally impossible linkages in person_recorded_person.

    Two checks:
        1. Same person_id appearing twice within the same household Record
           (within-household duplicate)
        2. Same person_id appearing in different households in the same census
           (across-household duplicate — same-census person appears twice)

    Returns:
        (within_household_errors, same_census_errors, error_descriptions)

    Authority: genealogical_constraints.md §4.1
    """
    within_errors: list[str] = []
    census_errors: list[str] = []

    with conn.cursor() as cur:

        # Check 1: duplicate person_ids within the same household
        cur.execute("""
            SELECT
                prp1.person_id,
                rp1.recorded_person_id AS rp1_id,
                rp2.recorded_person_id AS rp2_id,
                r1.record_id,
                r1.date,
                rp1.name_as_recorded AS name1,
                rp2.name_as_recorded AS name2
            FROM person_recorded_person prp1
            JOIN person_recorded_person prp2
                ON prp1.person_id = prp2.person_id
               AND prp1.recorded_person_id < prp2.recorded_person_id
            JOIN recorded_person rp1 ON prp1.recorded_person_id = rp1.recorded_person_id
            JOIN recorded_person rp2 ON prp2.recorded_person_id = rp2.recorded_person_id
            JOIN record r1 ON rp1.record_id = r1.record_id
            JOIN record r2 ON rp2.record_id = r2.record_id
            WHERE r1.record_id = r2.record_id
            ORDER BY prp1.person_id, rp1.recorded_person_id
        """)
        for row in cur.fetchall():
            within_errors.append(
                f"Person {row['person_id']}: {row['name1']} (rp {row['rp1_id']}) "
                f"and {row['name2']} (rp {row['rp2_id']}) "
                f"appear in same household {row['record_id']} ({row['date']})"
            )

        # Check 2: duplicate person_ids across different households, same census
        cur.execute("""
            SELECT
                prp1.person_id,
                rp1.recorded_person_id AS rp1_id,
                rp2.recorded_person_id AS rp2_id,
                r1.record_id AS record1_id,
                r2.record_id AS record2_id,
                r1.date,
                s.source_id,
                rp1.name_as_recorded AS name1,
                rp2.name_as_recorded AS name2
            FROM person_recorded_person prp1
            JOIN person_recorded_person prp2
                ON prp1.person_id = prp2.person_id
               AND prp1.recorded_person_id < prp2.recorded_person_id
            JOIN recorded_person rp1 ON prp1.recorded_person_id = rp1.recorded_person_id
            JOIN recorded_person rp2 ON prp2.recorded_person_id = rp2.recorded_person_id
            JOIN record r1 ON rp1.record_id = r1.record_id
            JOIN record r2 ON rp2.record_id = r2.record_id
            JOIN source s ON r1.source_id = s.source_id
            WHERE r1.source_id = r2.source_id
              AND r1.record_id != r2.record_id
              AND EXTRACT(YEAR FROM r1.date::date) = EXTRACT(YEAR FROM r2.date::date)
            ORDER BY prp1.person_id, rp1.recorded_person_id
        """)
        for row in cur.fetchall():
            date_str = row['date']
            year = date_str.split('-')[0] if isinstance(date_str, str) else date_str.year
            census_errors.append(
                f"Person {row['person_id']}: {row['name1']} (rp {row['rp1_id']}) "
                f"and {row['name2']} (rp {row['rp2_id']}) "
                f"appear in different households ({row['record1_id']}, {row['record2_id']}) "
                f"in same census {row['source_id']} ({year})"
            )

    return len(within_errors), len(census_errors), within_errors + census_errors


# ---------------------------------------------------------------------------
# Full linkage sweep
# ---------------------------------------------------------------------------

def apply_constraints_to_linkages(
    conn: psycopg2.extensions.connection,
) -> ConstraintReport:
    """
    Apply all genealogical constraints to every current linkage pair in
    person_recorded_person and return a ConstraintReport.

    This is the authoritative sweep used by conclusion/validation_cleanup.py
    and the validate-linkages CLI command.
    """
    report = ConstraintReport()

    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                prp.person_id,
                prp.recorded_person_id            AS rp1_id,
                prp2.recorded_person_id           AS rp2_id,
                rp.name_as_recorded               AS name1,
                rp.age_as_recorded                AS age1_raw,
                rp2.name_as_recorded              AS name2,
                rp2.age_as_recorded               AS age2_raw,
                r.source_id                       AS source_id_1,
                r2.source_id                      AS source_id_2,
                r.date                            AS date1,
                r2.date                           AS date2
            FROM person_recorded_person prp
            JOIN person_recorded_person prp2
                ON prp.person_id = prp2.person_id
               AND prp.recorded_person_id < prp2.recorded_person_id
            JOIN recorded_person rp  ON prp.recorded_person_id  = rp.recorded_person_id
            JOIN recorded_person rp2 ON prp2.recorded_person_id = rp2.recorded_person_id
            JOIN record r  ON rp.record_id  = r.record_id
            JOIN record r2 ON rp2.record_id = r2.record_id
            ORDER BY prp.person_id, rp.recorded_person_id
        """)

        for row in cur.fetchall():
            report.total_linkages_checked += 1

            try:
                age1 = float(row['age1_raw']) if row['age1_raw'] else None
                age2 = float(row['age2_raw']) if row['age2_raw'] else None
            except (ValueError, TypeError):
                age1 = age2 = None

            evaluation = evaluate_pair(
                name1=row['name1'],
                age1=age1,
                source_id_1=row['source_id_1'],
                name2=row['name2'],
                age2=age2,
                source_id_2=row['source_id_2'],
            )

            if not evaluation.passes:
                report.total_violations += 1
                for v in evaluation.violations:
                    if v.gc_code == 'GC-GEN':
                        report.gender_flips += 1
                    elif v.gc_code == 'GC-AGE':
                        report.age_violations += 1
                    elif v.gc_code == 'GC-NAM':
                        report.name_mismatches += 1

                report.flagged_pairs.append({
                    'person_id':        row['person_id'],
                    'recorded_person_id_1': row['rp1_id'],
                    'recorded_person_id_2': row['rp2_id'],
                    'name_1':           row['name1'],
                    'age_1':            row['age1_raw'],
                    'date_1':           row['date1'],
                    'name_2':           row['name2'],
                    'age_2':            row['age2_raw'],
                    'date_2':           row['date2'],
                    'violations':       '; '.join(v.message for v in evaluation.violations),
                })

    # Household coherence (DB-structural, separate from pair evaluation)
    within_errors, census_errors, _ = check_household_coherence(conn)
    report.household_errors = within_errors + census_errors
    report.total_violations += report.household_errors

    return report


def remove_flagged_linkages(
    conn: psycopg2.extensions.connection,
    report: ConstraintReport,
    dry_run: bool = False,
) -> tuple[int, str]:
    """
    Remove both sides of every flagged linkage pair from person_recorded_person.

    Each flagged pair has two recorded_person IDs; both linkages are removed.
    Without dry_run, changes are committed immediately.

    Returns:
        (count_removed, summary_message)
    """
    if not report.flagged_pairs:
        return 0, "No flagged pairs to remove"

    count = 0
    with conn.cursor() as cur:
        for pair in report.flagged_pairs:
            for rp_id in (pair['recorded_person_id_1'], pair['recorded_person_id_2']):
                if dry_run:
                    count += 1
                else:
                    cur.execute(
                        """
                        DELETE FROM person_recorded_person
                        WHERE person_id = %s AND recorded_person_id = %s
                        """,
                        (pair['person_id'], rp_id),
                    )
                    count += 1

    if not dry_run:
        conn.commit()

    verb = "Would remove" if dry_run else "Removed"
    return count, f"{verb} {count} linkage(s) across {len(report.flagged_pairs)} flagged pair(s)"
