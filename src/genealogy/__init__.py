"""
GRA — Genealogy Layer

Materialisation of docs/genealogical_constraints.md.

This layer owns all domain knowledge about what is and is not genealogically
plausible.  It is called by the evidence layer (Splink feature building),
the conclusion layer (pre-clustering filters and post-conclusion cleanup),
and the review layer (researcher-facing findings).

Public interface
----------------
Names:
    APPROVED_NAME_VARIANTS      dict of known Irish first-name aliases
    IRISH_MALE_NAMES            frozenset of male first names
    IRISH_FEMALE_NAMES          frozenset of female first names
    classify_forename()         'exact' | 'approved' | 'suspicious'
    infer_gender()              'M' | 'F' | None

Ages:
    CENSUS_AGE_TOLERANCE        per-pair tolerance dict
    CENSUS_YEAR                 source_id → census year mapping
    AgeProgressionResult
    evaluate_age_progression()

Constraints (pairwise evaluation and DB sweeps):
    GenderConsistencyResult
    NameVariantResult
    PairViolation
    PairEvaluation
    ConstraintReport
    evaluate_gender_consistency()
    evaluate_name_variant()
    evaluate_pair()             unified pairwise gate (use this everywhere)
    check_household_coherence()
    apply_constraints_to_linkages()
    remove_flagged_linkages()
"""

from src.genealogy.names import (
    APPROVED_NAME_VARIANTS,
    IRISH_MALE_NAMES,
    IRISH_FEMALE_NAMES,
    classify_forename,
    infer_gender,
)

from src.genealogy.ages import (
    CENSUS_AGE_TOLERANCE,
    CENSUS_YEAR,
    AgeProgressionResult,
    evaluate_age_progression,
)

from src.genealogy.constraints import (
    GenderConsistencyResult,
    NameVariantResult,
    PairViolation,
    PairEvaluation,
    ConstraintReport,
    evaluate_gender_consistency,
    evaluate_name_variant,
    evaluate_pair,
    check_household_coherence,
    apply_constraints_to_linkages,
    remove_flagged_linkages,
)

__all__ = [
    # names
    'APPROVED_NAME_VARIANTS',
    'IRISH_MALE_NAMES',
    'IRISH_FEMALE_NAMES',
    'classify_forename',
    'infer_gender',
    # ages
    'CENSUS_AGE_TOLERANCE',
    'CENSUS_YEAR',
    'AgeProgressionResult',
    'evaluate_age_progression',
    # constraints
    'GenderConsistencyResult',
    'NameVariantResult',
    'PairViolation',
    'PairEvaluation',
    'ConstraintReport',
    'evaluate_gender_consistency',
    'evaluate_name_variant',
    'evaluate_pair',
    'check_household_coherence',
    'apply_constraints_to_linkages',
    'remove_flagged_linkages',
]
