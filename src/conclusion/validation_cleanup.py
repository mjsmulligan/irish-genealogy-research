"""
GRA — Conclusion Layer: Validation Cleanup

Final QA gate: removes linkages that fail validation checks (age progression,
name variants, household coherence) before finalizing conclusions.

This is Step 4 of the conclusion pipeline, running after event resolution.
Ensures that the person_recorded_person table contains only valid linkages.

Entry point:
    run_validation_cleanup(conn) -> ValidationCleanupResult
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg2.extensions

from src.validation import validate_all_linkages, remove_flagged_linkages


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ValidationCleanupResult:
    linkages_checked: int = 0
    violations_found: int = 0
    linkages_removed: int = 0
    age_violations_removed: int = 0
    name_violations_removed: int = 0
    gender_flips_removed: int = 0
    household_violations_removed: int = 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_validation_cleanup(
    conn: psycopg2.extensions.connection,
) -> ValidationCleanupResult:
    """
    Run validation cleanup: remove all flagged linkages from conclusions.

    This is the final QA gate after person resolution, relationship resolution,
    and event resolution have completed. Any linkages that fail validation rules
    are removed to ensure clean conclusions.

    Returns ValidationCleanupResult with counts of violations found and removed.
    """
    result = ValidationCleanupResult()

    # Step 1: Validate all current linkages
    report = validate_all_linkages(conn)

    result.linkages_checked = report.total_linkages_checked
    result.violations_found = report.total_violations
    result.age_violations_removed = report.age_violations
    result.name_violations_removed = report.name_mismatches
    result.gender_flips_removed = report.gender_flips
    result.household_violations_removed = report.household_errors

    if not report.flagged_pairs:
        # No violations found, nothing to remove
        return result

    # Step 2: Remove flagged linkages
    count_removed, _ = remove_flagged_linkages(conn, report, dry_run=False)
    result.linkages_removed = count_removed

    return result


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

def print_validation_cleanup_report(result: ValidationCleanupResult) -> None:
    print("\n[4/4] Validation cleanup...")
    print()
    print(f"  VALIDATION CLEANUP")
    print(f"    Linkages checked:        {result.linkages_checked:>6}")
    print(f"    Violations found:        {result.violations_found:>6}")
    print(f"      Age progression:       {result.age_violations_removed:>6}")
    print(f"      Name mismatches:       {result.name_violations_removed:>6}")
    print(f"      Gender flips:          {result.gender_flips_removed:>6}")
    print(f"      Household errors:      {result.household_violations_removed:>6}")
    print(f"    Linkages removed:        {result.linkages_removed:>6}")
    print()
