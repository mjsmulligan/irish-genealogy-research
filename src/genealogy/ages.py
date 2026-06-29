"""
GRA — Genealogy Layer: Age Progression Rules

Authoritative source for census age tolerance values and age-progression
evaluation used across the evidence, conclusion, and review layers.

Provides:
    CENSUS_AGE_TOLERANCE    — per-pair tolerance dict (replaces hardcoded ±2)
    AgeProgressionResult    — result dataclass
    evaluate_age_progression() — single authoritative age check

Authority: docs/genealogical_constraints.md §2.3
"""

from __future__ import annotations

from dataclasses import dataclass

from src.constants import SOURCE_ID_1901, SOURCE_ID_1911, SOURCE_ID_1926


# ---------------------------------------------------------------------------
# Census-pair age tolerances
# ---------------------------------------------------------------------------
# Tolerances reflect census round-number age reporting biases and the
# longer the span, the higher the acceptable deviation.
# Keys are (earlier_source_id, later_source_id); order matters.
#
# Authority: genealogical_constraints.md §2.3

CENSUS_AGE_TOLERANCE: dict[tuple[int, int], float] = {
    (SOURCE_ID_1901, SOURCE_ID_1911): 3.0,  # 10-year span
    (SOURCE_ID_1911, SOURCE_ID_1926): 3.0,  # 15-year span
    (SOURCE_ID_1901, SOURCE_ID_1926): 4.0,  # 25-year span
}

# Convenience: source_id → census year, used throughout the codebase.
# Previously duplicated as a bare dict literal {3: 1901, 4: 1911, 5: 1926}
# in person_resolution.py, relationship_resolution.py, and linkage_validation.py.
CENSUS_YEAR: dict[int, int] = {
    SOURCE_ID_1901: 1901,
    SOURCE_ID_1911: 1911,
    SOURCE_ID_1926: 1926,
}


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class AgeProgressionResult:
    valid: bool
    deviation_years: float = 0.0
    message: str = ""


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def evaluate_age_progression(
    age1: float,
    source_id_1: int,
    age2: float,
    source_id_2: int,
) -> AgeProgressionResult:
    """
    Evaluate whether age progression between two census appearances is plausible.

    Derives the census years and tolerance automatically from source IDs,
    using CENSUS_AGE_TOLERANCE. Callers never hardcode a tolerance value.

    Args:
        age1:        Recorded age in the first census
        source_id_1: Source ID of the first census record
        age2:        Recorded age in the second census
        source_id_2: Source ID of the second census record

    Returns:
        AgeProgressionResult with valid=True if plausible, False if not.
        If either year is unknown (source not in CENSUS_YEAR), returns valid=True
        with an explanatory message rather than rejecting the pair.

    Authority: genealogical_constraints.md §2.3
    """
    if not age1 or not age2:
        return AgeProgressionResult(valid=True, message="Cannot validate: missing age data")

    year1 = CENSUS_YEAR.get(source_id_1)
    year2 = CENSUS_YEAR.get(source_id_2)

    if year1 is None or year2 is None:
        return AgeProgressionResult(
            valid=True,
            message=f"Cannot validate: unknown source_id(s) {source_id_1}, {source_id_2}"
        )

    # Ensure consistent ordering (earlier → later)
    if year1 > year2:
        age1, age2 = age2, age1
        source_id_1, source_id_2 = source_id_2, source_id_1
        year1, year2 = year2, year1

    tolerance = CENSUS_AGE_TOLERANCE.get(
        (source_id_1, source_id_2),
        3.0,  # Conservative default for any unrecognised pair
    )

    years_between = year2 - year1
    expected_age2 = age1 + years_between
    deviation = age2 - expected_age2

    # Age regression: person aged backwards — hard reject regardless of tolerance
    if age2 < age1:
        return AgeProgressionResult(
            valid=False,
            deviation_years=deviation,
            message=(
                f"Age regression: {age1:.0f}y ({year1}) → {age2:.0f}y ({year2}), "
                f"decreased {age1 - age2:.0f}y (impossible)"
            ),
        )

    valid = abs(deviation) <= tolerance
    return AgeProgressionResult(
        valid=valid,
        deviation_years=deviation,
        message=(
            f"Age progression: {age1:.0f}y ({year1}) → {age2:.0f}y ({year2}), "
            f"expected {expected_age2:.0f}y, deviation {deviation:+.1f}y "
            f"(tolerance ±{tolerance:.0f}y)"
        ),
    )
