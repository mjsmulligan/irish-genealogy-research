"""
GRA — Genealogy Layer: Irish Name Knowledge

Authoritative source for Irish name variant and gender dictionaries used
across the evidence, conclusion, and review layers.

Provides:
    APPROVED_NAME_VARIANTS  — dict of known first-name aliases in Irish census records
    IRISH_MALE_NAMES        — set of male first names (normalised, lowercase)
    IRISH_FEMALE_NAMES      — set of female first names (normalised, lowercase)
    classify_forename()     — classify a single forename as 'exact', 'approved', or 'suspicious'
    infer_gender()          — infer 'M', 'F', or None from a full name string

Authority: docs/genealogical_constraints.md
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Approved name variants
# ---------------------------------------------------------------------------
# Known first-name aliases commonly found in Irish census records.
# Keys and values are all lowercase normalised forms.
# A name that appears as a key OR as a value in any set is 'approved'.
# A name that appears in neither is 'suspicious'.

APPROVED_NAME_VARIANTS: dict[str, set[str]] = {
    # Female names
    'alice':     {'anna', 'anne', 'annie', 'alicia'},
    'anna':      {'alice', 'anne', 'annie', 'ann'},
    'anne':      {'alice', 'anna', 'annie', 'ann'},
    'annie':     {'alice', 'anna', 'anne', 'ann'},
    'ann':       {'alice', 'anna', 'anne', 'annie'},

    'margaret':  {'maggie', 'meg', 'maggy', 'margie'},
    'maggie':    {'margaret', 'meg', 'maggy', 'margie'},
    'meg':       {'margaret', 'maggie', 'maggy', 'margie'},

    'elizabeth': {'liz', 'lizzie', 'liza', 'eliza', 'betty', 'beth'},
    'lizzie':    {'elizabeth', 'liz', 'liza', 'eliza', 'betty', 'beth'},
    'liz':       {'elizabeth', 'lizzie', 'liza', 'eliza', 'betty', 'beth'},

    'mary':      {'marie', 'molly', 'moll', 'm'},
    'molly':     {'mary', 'marie', 'moll'},

    'catherine': {'kate', 'kathryn', 'cathy', 'catharine'},
    'kate':      {'catherine', 'kathryn', 'cathy', 'catharine'},
    'kathleen':  {'kate', 'kathy', 'kay'},

    'josephine': {'josephina', 'jo', 'josie'},
    'josephina': {'josephine', 'jo', 'josie'},

    # Male names
    'william':   {'liam', 'will', 'bill', 'willie', 'wm'},
    'liam':      {'william', 'will', 'bill', 'willie'},
    'bill':      {'william', 'liam', 'willie', 'wm'},
    'wm':        {'william', 'bill'},

    'francis':   {'frank', 'fran', 'frankie', 'ffrancis'},
    'frank':     {'francis', 'fran', 'frankie'},

    'edward':    {'ed', 'eddie', 'ted'},
    'eddie':     {'edward', 'ed', 'ted'},

    'robert':    {'rob', 'robbie', 'bob', 'bobby'},
    'robbie':    {'robert', 'rob', 'bob', 'bobby'},
    'bob':       {'robert', 'robbie', 'bobby'},

    'michael':   {'mick', 'mike', 'mikey', 'micol'},
    'mick':      {'michael', 'mike', 'mikey'},
    'mike':      {'michael', 'mick', 'mikey'},

    'james':     {'jim', 'jimmy', 'jas', 'jem'},
    'jim':       {'james', 'jimmy', 'jas'},
    'jimmy':     {'james', 'jim'},

    'john':      {'jack', 'johnny', 'jon', 'sean', 'jean'},
    'jack':      {'john', 'johnny'},
    'johnny':    {'john', 'jack'},
    'sean':      {'john', 'johnny', 'jack'},

    'thomas':    {'tom', 'tommy', 'thom'},
    'tom':       {'thomas', 'tommy'},
    'tommy':     {'thomas', 'tom'},

    'patrick':   {'pat', 'patty', 'paddy', 'pádraig'},
    'pat':       {'patrick', 'paddy'},
    'paddy':     {'patrick', 'pat'},

    'daniel':    {'dan', 'danny'},
    'dan':       {'daniel', 'danny'},
    'danny':     {'daniel', 'dan'},

    'henry':     {'harry', 'hank'},
    'harry':     {'henry', 'hank'},

    'charles':   {'charlie', 'chuck', 'chas'},
    'charlie':   {'charles', 'chuck', 'chas'},
    'chuck':     {'charles', 'charlie'},
}

# Pre-computed set of all names that appear anywhere in the variant graph,
# as either a key or a value. Used for O(1) 'approved' lookup.
_ALL_APPROVED: frozenset[str] = frozenset(
    list(APPROVED_NAME_VARIANTS.keys()) +
    [v for variants in APPROVED_NAME_VARIANTS.values() for v in variants]
)


# ---------------------------------------------------------------------------
# Gender dictionaries
# ---------------------------------------------------------------------------

IRISH_MALE_NAMES: frozenset[str] = frozenset({
    'william', 'liam', 'will', 'bill', 'willie', 'wm',
    'francis', 'frank', 'fran', 'frankie',
    'edward', 'ed', 'eddie', 'ted',
    'robert', 'rob', 'robbie', 'bob', 'bobby',
    'michael', 'mick', 'mike', 'mikey',
    'james', 'jim', 'jimmy', 'jas', 'jem',
    'john', 'jack', 'johnny', 'jon', 'sean', 'jean',
    'thomas', 'tom', 'tommy', 'thom',
    'patrick', 'pat', 'paddy', 'pádraig',
    'daniel', 'dan', 'danny',
    'henry', 'harry', 'hank',
    'charles', 'charlie', 'chuck', 'chas',
    'richard', 'rick', 'dick', 'ricky',
    'joseph', 'joe', 'joey',
    'george', 'georgie',
    'anthony', 'tony', 'ant',
    'peter', 'pete',
    'paul', 'paulo',
    'stephen', 'steve', 'steven',
    'andrew', 'andy',
    'brian', 'bryan',
    'martin', 'marty',
    'kevin', 'kev',
    'david', 'dave', 'davy',
    'owen',
    'bertram', 'bert',
    'humphrey', 'humphry',
    'lawrence', 'larry', 'laurence',
    'gerald', 'gerry',
    'oliver', 'ollie',
})

IRISH_FEMALE_NAMES: frozenset[str] = frozenset({
    'mary', 'marie', 'molly', 'moll',
    'margaret', 'maggie', 'meg', 'maggy', 'margie',
    'elizabeth', 'liz', 'lizzie', 'liza', 'eliza', 'betty', 'beth',
    'catherine', 'kate', 'kathryn', 'cathy', 'catharine',
    'kathleen', 'kathy', 'kay',
    'josephine', 'josephina', 'jo', 'josie',
    'alice', 'anna', 'anne', 'annie', 'ann',
    'susan', 'sue', 'suzanne',
    'patricia', 'pat',
    'barbara', 'barb',
    'sarah', 'sara', 'sally',
    'jessica', 'jess', 'jessie',
    'janet', 'jane', 'janey',
    'helen', 'helena',
    'sandra', 'sandy',
    'ashley', 'ash',
    'theresa', 'teresa', 'terry',
    'frances', 'fran', 'francie',
    'dorothy', 'dot', 'dotty',
    'gloria',
    'rose', 'rosie',
    'joyce',
    'diane', 'dianne',
    'evelyn', 'eve',
    'joan', 'joanne',
    'christine', 'christie', 'chris', 'chrissie',
    'carolyn', 'carol', 'carole',
    'rachel',
    'maria',
    'nora', 'norah',
    'bridget', 'brigid', 'bridie', 'bride',
    'monica', 'moira',
    'siobhan', 'siobhán',
    'sheila',
})


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def classify_forename(forename: str | None) -> str:
    """
    Classify a single forename against the Irish name variant dictionary.

    Returns:
        'exact'     — the forename itself is a key in APPROVED_NAME_VARIANTS
                      (a canonical form with known aliases)
        'approved'  — the forename appears as a variant value (a known alias)
        'suspicious'— the forename is not in the dictionary at all

    This three-way distinction is used by Splink comparison levels:
        exact ↔ exact         → highest confidence (same canonical form)
        approved ↔ approved   → medium confidence (both are known Irish names)
        suspicious present    → lower confidence (unknown name change)
    """
    if not forename:
        return 'suspicious'

    norm = forename.strip().lower().split()[0] if forename.strip() else ''
    if not norm:
        return 'suspicious'

    if norm in APPROVED_NAME_VARIANTS:
        return 'exact'

    if norm in _ALL_APPROVED:
        return 'approved'

    return 'suspicious'


def infer_gender(name: str | None) -> str | None:
    """
    Infer gender from the first token of a full name string.

    Returns:
        'M'  — name is in IRISH_MALE_NAMES
        'F'  — name is in IRISH_FEMALE_NAMES
        None — name is ambiguous or missing
    """
    if not name:
        return None

    first = name.strip().lower().split()[0] if name.strip() else ''
    if not first:
        return None

    if first in IRISH_MALE_NAMES:
        return 'M'
    if first in IRISH_FEMALE_NAMES:
        return 'F'
    return None
