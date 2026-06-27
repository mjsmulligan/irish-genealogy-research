"""
GRA — Linkage Validation Module

Implements validation checks to improve linkage quality:

1. Age Progression Validation
   - Rejects linkages where age change is >3 years from expected
   - Prevents false positives like "age 42 → age 6"

2. Name Variant Validation
   - Approves known Irish name variants (Alice/Annie, Margaret/Maggie)
   - Rejects suspicious first-name changes (James/Patrick, John/Joseph)

3. Household Coherence Validation
   - Prevents same person_id appearing twice in same household/census

Applied after Splink scoring but before person_resolution clustering.
"""

from __future__ import annotations

from dataclasses import dataclass
import psycopg2
import psycopg2.extras
from typing import Optional


# ---------------------------------------------------------------------------
# Irish Name Variant Dictionary
# ---------------------------------------------------------------------------

# Approved variants: first name aliases commonly used in Irish census records
APPROVED_NAME_VARIANTS = {
    # Female names
    'alice': {'anna', 'anne', 'annie', 'alicia'},
    'anna': {'alice', 'anne', 'annie', 'ann'},
    'anne': {'alice', 'anna', 'annie', 'ann'},
    'annie': {'alice', 'anna', 'anne', 'ann'},
    'ann': {'alice', 'anna', 'anne', 'annie'},

    'margaret': {'maggie', 'meg', 'maggy', 'margie'},
    'maggie': {'margaret', 'meg', 'maggy', 'margie'},
    'meg': {'margaret', 'maggie', 'maggy', 'margie'},

    'elizabeth': {'liz', 'lizzie', 'liza', 'eliza', 'betty', 'beth'},
    'lizzie': {'elizabeth', 'liz', 'liza', 'eliza', 'betty', 'beth'},
    'liz': {'elizabeth', 'lizzie', 'liza', 'eliza', 'betty', 'beth'},

    'mary': {'marie', 'molly', 'moll', 'm'},
    'molly': {'mary', 'marie', 'moll'},

    'catherine': {'kate', 'kathryn', 'cathy', 'catherine', 'catharine'},
    'kate': {'catherine', 'kathryn', 'cathy', 'catharine'},
    'kathleen': {'kate', 'kathy', 'kay'},

    'josephine': {'josephina', 'jo', 'josie'},
    'josephina': {'josephine', 'jo', 'josie'},

    # Male names
    'william': {'liam', 'will', 'bill', 'willie', 'wm'},
    'liam': {'william', 'will', 'bill', 'willie'},
    'bill': {'william', 'liam', 'willie', 'wm'},

    'william': {'wm', 'will', 'bill'},
    'francis': {'frank', 'fran', 'frankie', 'ffrancis'},
    'frank': {'francis', 'fran', 'frankie'},

    'edward': {'ed', 'eddie', 'ted'},
    'eddie': {'edward', 'ed', 'ted'},

    'robert': {'rob', 'robbie', 'bob', 'bobby'},
    'robbie': {'robert', 'rob', 'bob', 'bobby'},
    'bob': {'robert', 'robbie', 'bobby'},

    'michael': {'mick', 'mike', 'mikey', 'micol'},
    'mick': {'michael', 'mike', 'mikey'},
    'mike': {'michael', 'mick', 'mikey'},

    'james': {'jim', 'jimmy', 'jas', 'jem'},
    'jim': {'james', 'jimmy', 'jas'},
    'jimmy': {'james', 'jim'},

    'john': {'jack', 'johnny', 'jon', 'sean', 'jean'},
    'jack': {'john', 'johnny'},
    'johnny': {'john', 'jack'},
    'sean': {'john', 'johnny', 'jack'},

    'thomas': {'tom', 'tommy', 'thom'},
    'tom': {'thomas', 'tommy'},
    'tommy': {'thomas', 'tom'},

    'patrick': {'pat', 'patty', 'paddy', 'pat', 'pádraig'},
    'pat': {'patrick', 'paddy'},
    'paddy': {'patrick', 'pat'},

    'daniel': {'dan', 'danny'},
    'dan': {'daniel', 'danny'},
    'danny': {'daniel', 'dan'},

    'henry': {'harry', 'hank'},
    'harry': {'henry', 'hank'},

    'charles': {'charlie', 'chuck', 'chas'},
    'charlie': {'charles', 'chuck', 'chas'},
    'chuck': {'charles', 'charlie'},
}


# ---------------------------------------------------------------------------
# Age Progression Validation
# ---------------------------------------------------------------------------

@dataclass
class AgeValidationResult:
    valid: bool
    deviation_years: float = 0.0
    message: str = ""


def validate_age_progression(
    age_year1: float,
    census_year1: int,
    age_year2: float,
    census_year2: int,
    tolerance_years: float = 2.0,
) -> AgeValidationResult:
    """
    Validate that age progression between two census records is plausible.

    Args:
        age_year1: Age in first census
        census_year1: Year of first census (e.g., 1901)
        age_year2: Age in second census
        census_year2: Year of second census (e.g., 1911)
        tolerance_years: Acceptable deviation from expected progression (default ±2 years)

    Returns:
        AgeValidationResult with valid=True if ages are consistent, False if impossible

    Logic:
        Expected age progression: age_year2 ≈ age_year1 + (census_year2 - census_year1)
        We allow ±tolerance_years to account for age rounding and misstatement
    """
    if not (age_year1 and age_year2):
        return AgeValidationResult(
            valid=True,
            message="Cannot validate: missing age data"
        )

    years_between_censuses = census_year2 - census_year1
    expected_age_year2 = age_year1 + years_between_censuses
    actual_deviation = age_year2 - expected_age_year2

    is_valid = abs(actual_deviation) <= tolerance_years

    return AgeValidationResult(
        valid=is_valid,
        deviation_years=actual_deviation,
        message=(
            f"Age progression: {age_year1}y ({census_year1}) → {age_year2}y ({census_year2}), "
            f"expected {expected_age_year2}y, deviation {actual_deviation:+.1f}y"
        )
    )


# ---------------------------------------------------------------------------
# Name Variant Validation
# ---------------------------------------------------------------------------

@dataclass
class NameVariantResult:
    approved: bool
    reason: str = ""


def validate_name_variant(name1: str, name2: str) -> NameVariantResult:
    """
    Validate if two names are acceptable variants of the same person.

    Args:
        name1: First name (e.g., "Alice Boyle")
        name2: Second name (e.g., "Annie Boyle")

    Returns:
        NameVariantResult with approved=True if names are compatible
    """
    if not (name1 and name2):
        return NameVariantResult(approved=False, reason="Missing name data")

    # Exact match is always valid
    if name1.lower().strip() == name2.lower().strip():
        return NameVariantResult(approved=True, reason="Exact match")

    # Extract first names (before first space)
    parts1 = name1.lower().strip().split()
    parts2 = name2.lower().strip().split()

    if not parts1 or not parts2:
        return NameVariantResult(approved=False, reason="Cannot parse names")

    first1 = parts1[0]
    first2 = parts2[0]

    # Check if first names are approved variants
    if first1 in APPROVED_NAME_VARIANTS:
        if first2 in APPROVED_NAME_VARIANTS[first1]:
            # Also check surnames match
            surname1 = ' '.join(parts1[1:]).lower() if len(parts1) > 1 else ""
            surname2 = ' '.join(parts2[1:]).lower() if len(parts2) > 1 else ""

            if surname1 == surname2:
                return NameVariantResult(
                    approved=True,
                    reason=f"Approved variant: {first1} ↔ {first2}"
                )
            else:
                return NameVariantResult(
                    approved=False,
                    reason=f"Surname mismatch: {surname1} vs {surname2}"
                )

    # Check reverse
    if first2 in APPROVED_NAME_VARIANTS:
        if first1 in APPROVED_NAME_VARIANTS[first2]:
            surname1 = ' '.join(parts1[1:]).lower() if len(parts1) > 1 else ""
            surname2 = ' '.join(parts2[1:]).lower() if len(parts2) > 1 else ""

            if surname1 == surname2:
                return NameVariantResult(
                    approved=True,
                    reason=f"Approved variant: {first1} ↔ {first2}"
                )

    # Different first names = suspicious
    if first1 != first2:
        return NameVariantResult(
            approved=False,
            reason=f"Different first names: {first1} vs {first2}"
        )

    return NameVariantResult(
        approved=True,
        reason="Names match"
    )


# ---------------------------------------------------------------------------
# Household Coherence Validation
# ---------------------------------------------------------------------------

def validate_household_coherence(conn: psycopg2.extensions.connection) -> tuple[int, list[str]]:
    """
    Check for impossible linkages: same person_id appearing twice in same household/census.

    Returns:
        (error_count, error_descriptions)
    """
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        # Find duplicate person_ids within same household/census
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
                AND prp1.recorded_person_id != prp2.recorded_person_id
            JOIN recorded_person rp1 ON prp1.recorded_person_id = rp1.recorded_person_id
            JOIN recorded_person rp2 ON prp2.recorded_person_id = rp2.recorded_person_id
            JOIN record r1 ON rp1.record_id = r1.record_id
            JOIN record r2 ON rp2.record_id = r2.record_id
            WHERE r1.record_id = r2.record_id  -- same household
            ORDER BY prp1.person_id, rp1.recorded_person_id
        """)

        errors = []
        for row in cur.fetchall():
            errors.append(
                f"Person {row['person_id']}: {row['name1']} (rp {row['rp1_id']}) "
                f"and {row['name2']} (rp {row['rp2_id']}) "
                f"appear in same household {row['record_id']} ({row['date']})"
            )

    return len(errors), errors


# ---------------------------------------------------------------------------
# Comprehensive Linkage Validation
# ---------------------------------------------------------------------------

@dataclass
class ValidationReport:
    age_violations: int = 0
    name_mismatches: int = 0
    household_errors: int = 0
    total_linkages_checked: int = 0
    total_violations: int = 0
    flagged_pairs: list[dict] = None

    def __post_init__(self):
        if self.flagged_pairs is None:
            self.flagged_pairs = []

    @property
    def violation_rate(self) -> float:
        if self.total_linkages_checked == 0:
            return 0.0
        return 100.0 * self.total_violations / self.total_linkages_checked


def remove_flagged_linkages(
    conn: psycopg2.extensions.connection,
    report: ValidationReport,
    dry_run: bool = False,
) -> tuple[int, str]:
    """
    Remove linkages flagged by validation.

    Args:
        conn: Database connection
        report: ValidationReport from validate_all_linkages()
        dry_run: If True, don't actually delete, just count

    Returns:
        (count_removed, message)
    """
    if not report.flagged_pairs:
        return 0, "No flagged pairs to remove"

    count = 0
    with conn.cursor() as cur:
        for pair in report.flagged_pairs:
            if dry_run:
                count += 1
            else:
                # Delete the linkage
                cur.execute(
                    """
                    DELETE FROM person_recorded_person
                    WHERE person_id = %s
                        AND recorded_person_id = %s
                    """,
                    (pair['person_id'], pair['recorded_person_id_1'])
                )
                count += 1

    if not dry_run:
        conn.commit()

    return count, f"{'Would remove' if dry_run else 'Removed'} {count} flagged linkages"


def validate_all_linkages(conn: psycopg2.extensions.connection) -> ValidationReport:
    """
    Run all validation checks across all linkages.

    Returns:
        ValidationReport with counts and flagged pairs for review/removal
    """
    report = ValidationReport()

    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        # Get all current linkages
        cur.execute("""
            SELECT
                prp.person_id,
                prp.recorded_person_id,
                rp.name_as_recorded,
                rp.age_as_recorded,
                r.date,
                rp2.name_as_recorded AS other_name,
                rp2.age_as_recorded AS other_age,
                r2.date AS other_date
            FROM person_recorded_person prp
            JOIN recorded_person rp ON prp.recorded_person_id = rp.recorded_person_id
            JOIN record r ON rp.record_id = r.record_id
            JOIN person_recorded_person prp2
                ON prp.person_id = prp2.person_id
                AND prp.recorded_person_id < prp2.recorded_person_id
            JOIN recorded_person rp2 ON prp2.recorded_person_id = rp2.recorded_person_id
            JOIN record r2 ON rp2.record_id = r2.record_id
            ORDER BY prp.person_id, rp.recorded_person_id
        """)

        for row in cur.fetchall():
            report.total_linkages_checked += 1

            violations = []

            # Check age progression
            try:
                age1 = float(row['age_as_recorded']) if row['age_as_recorded'] else None
                age2 = float(row['other_age']) if row['other_age'] else None
                year1 = int(row['date'][:4])
                year2 = int(row['other_date'][:4])

                if age1 and age2 and year1 and year2:
                    age_result = validate_age_progression(age1, year1, age2, year2)
                    if not age_result.valid:
                        violations.append(f"Age: {age_result.message}")
                        report.age_violations += 1
            except (ValueError, TypeError):
                pass

            # Check name variant
            name_result = validate_name_variant(row['name_as_recorded'], row['other_name'])
            if not name_result.approved:
                violations.append(f"Name: {name_result.reason}")
                report.name_mismatches += 1

            # Flag if any violations
            if violations:
                report.total_violations += 1
                report.flagged_pairs.append({
                    'person_id': row['person_id'],
                    'recorded_person_id_1': row['recorded_person_id'],
                    'name_1': row['name_as_recorded'],
                    'age_1': row['age_as_recorded'],
                    'date_1': row['date'],
                    'recorded_person_id_2': row['recorded_person_id'],
                    'name_2': row['other_name'],
                    'age_2': row['other_age'],
                    'date_2': row['other_date'],
                    'violations': '; '.join(violations),
                })

    # Check household coherence
    hh_errors, hh_descriptions = validate_household_coherence(conn)
    report.household_errors = hh_errors
    report.total_violations += hh_errors

    return report
