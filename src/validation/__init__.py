"""GRA — Validation Layer

Quality assurance for linkages: age progression, name variants, household coherence.
"""

from src.validation.linkage_validation import (
    validate_all_linkages,
    validate_age_progression,
    validate_name_variant,
    validate_household_coherence,
    remove_flagged_linkages,
    ValidationReport,
    AgeValidationResult,
    NameVariantResult,
    APPROVED_NAME_VARIANTS,
)

__all__ = [
    'validate_all_linkages',
    'validate_age_progression',
    'validate_name_variant',
    'validate_household_coherence',
    'remove_flagged_linkages',
    'ValidationReport',
    'AgeValidationResult',
    'NameVariantResult',
    'APPROVED_NAME_VARIANTS',
]
