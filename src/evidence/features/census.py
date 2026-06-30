"""
GRA — Evidence Layer Features: Census Household

Builds one Pandas DataFrame per active census source, suitable for use as
Splink input in run_record_similarity().

Each row represents one Record (household).  Columns:

    unique_id               INTEGER  — record_id (Splink join key)
    source_id               INTEGER  — census source (3=1901, 4=1911, 5=1926)
    place_id                INTEGER  — resolved place_id from place_record, or NULL
    household_surname_norm  TEXT     — modal normalised surname across the household
    adult_forenames_sorted  TEXT     — pipe-joined sorted forenames, age > CHILD_DEPARTURE_AGE
                                       or role = 'head'/'spouse' with no age
    child_forenames_young   TEXT     — pipe-joined sorted forenames, age <= CHILD_DEPARTURE_AGE
    child_forenames_older   TEXT     — pipe-joined sorted forenames, age > CHILD_DEPARTURE_AGE
                                       excluding head/spouse (spinster/bachelor pattern)

Normalisation:
    Surnames and forenames are lowercased and stripped.  Pipe-joined sets are
    sorted alphabetically so Splink comparisons are order-independent.

Entry point:
    build_census_household_features(conn) -> list[pd.DataFrame]
"""

from __future__ import annotations

from collections import Counter

import pandas as pd

from src.constants import CENSUS_SOURCE_IDS, CHILD_DEPARTURE_AGE
from src.db.repository import Repository
from src.genealogy.names import APPROVED_NAME_VARIANTS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm(name: str | None) -> str:
    """Lowercase + strip a name string; return '' for None."""
    return (name or "").lower().strip()


def _soundex(s: str | None) -> str:
    """
    Compute Soundex phonetic code for Irish surnames.
    Handles Irish naming conventions: O'Brien/Brien/O Brien all → B650 (same code).
    Removes non-letter chars and Irish prefixes (O, Mac, etc.) before first consonant.
    """
    if not s:
        return ""

    s = _norm(s)
    if not s:
        return ""

    # Remove non-letter characters
    letters_only = ''.join(c for c in s if c.isalpha()).lower()
    if not letters_only:
        return ""

    # Handle Irish prefixes: skip 'o' and 'mac' if they're followed by consonants
    # O'Brien → remove O, keep Brien
    # Mac...  → remove Mac, keep the consonant
    idx = 0
    if letters_only.startswith('o') and len(letters_only) > 1:
        # Check if 'o' is a prefix (followed by a consonant) vs. a vowel in Ó...
        next_char = letters_only[1]
        if next_char not in 'aeiou':  # 'o' is a prefix if followed by consonant
            idx = 1
    elif letters_only.startswith('mac'):
        idx = 3

    core_name = letters_only[idx:]
    if not core_name:
        core_name = letters_only  # fallback if all chars removed

    # Keep first letter of the core name
    first = core_name[0].upper()

    # Soundex mapping: consonants → digits, vowels/H/W/Y → 0
    codes = {
        'a': '0', 'e': '0', 'i': '0', 'o': '0', 'u': '0',
        'h': '0', 'w': '0', 'y': '0',
        'b': '1', 'f': '1', 'p': '1', 'v': '1',
        'c': '2', 'g': '2', 'j': '2', 'k': '2', 'q': '2', 's': '2', 'x': '2', 'z': '2',
        'd': '3', 't': '3',
        'l': '4',
        'm': '5', 'n': '5',
        'r': '6',
    }

    # Convert remaining letters to digit sequence
    digits = ''.join(codes.get(c, '0') for c in core_name[1:])

    # Remove consecutive duplicates and zeros
    result = [first]
    for d in digits:
        if d != '0' and (not result or d != result[-1]):
            result.append(d)

    # Pad or trim to 4 characters
    soundex_code = ''.join(result)
    return (soundex_code + '000')[:4]


def _surname_from(name: str | None) -> str:
    """
    Extract the surname token from a name-as-recorded string.

    NAI names are typically "Forename Surname" or "Surname, Forename".
    We take the last whitespace-delimited token as a simple heuristic.
    """
    parts = _norm(name).split()
    return parts[-1] if parts else ""


def _forename_from(name: str | None) -> str:
    """Extract the first forename token (everything before the last token)."""
    parts = _norm(name).split()
    if len(parts) >= 2:
        return " ".join(parts[:-1])
    return parts[0] if parts else ""


def _normalize_forename(forename: str | None) -> str:
    """
    Map forename variants to their canonical form using APPROVED_NAME_VARIANTS.

    The APPROVED_NAME_VARIANTS dict is bidirectional (each variant is both a key
    and a value). To canonicalize, we find all equivalent names in the equivalence
    class and return the longest one (e.g., 'patrick' not 'pat', 'patrick').

    This ensures Pat ↔ Patrick comparisons reach full similarity scores in Splink.
    """
    if not forename:
        return ""

    norm = _norm(forename)
    if not norm:
        return ""

    if norm not in APPROVED_NAME_VARIANTS and not any(norm in variants for variants in APPROVED_NAME_VARIANTS.values()):
        return norm

    all_equiv = {norm}
    if norm in APPROVED_NAME_VARIANTS:
        all_equiv.update(APPROVED_NAME_VARIANTS[norm])

    for canonical, variants in APPROVED_NAME_VARIANTS.items():
        if norm in variants:
            all_equiv.add(canonical)
            all_equiv.update(variants)

    return max(all_equiv, key=len)


def _build_household_row(record_id: int, source_id: int, members: list[dict], place_id: int | None) -> dict:
    """
    Aggregate a list of RecordedPerson dicts into a single household feature row.

    Adult roles: 'head', 'spouse', 'wife', 'husband', or age > CHILD_DEPARTURE_AGE
    Young child: age <= CHILD_DEPARTURE_AGE and not head/spouse
    Older child: age > CHILD_DEPARTURE_AGE and not head/spouse (spinster/bachelor)
    """
    _ADULT_ROLES = {"head", "spouse", "wife", "husband"}

    surnames: list[str] = []
    adult_forenames: list[str] = []
    child_forenames_young: list[str] = []
    child_forenames_older: list[str] = []

    for m in members:
        role = _norm(m.get("role"))
        age = m.get("age")
        forename = _forename_from(m.get("name_as_recorded"))
        forename_normalized = _normalize_forename(forename)
        surname = _surname_from(m.get("name_as_recorded"))

        if surname:
            surnames.append(surname)

        is_adult_role = role in _ADULT_ROLES
        is_young_child = (age is not None and age <= CHILD_DEPARTURE_AGE and not is_adult_role)
        is_older_child = (age is not None and age > CHILD_DEPARTURE_AGE and not is_adult_role)

        if is_adult_role or (age is not None and age > CHILD_DEPARTURE_AGE):
            if forename_normalized:
                adult_forenames.append(forename_normalized)

        if is_young_child and forename_normalized:
            child_forenames_young.append(forename_normalized)

        if is_older_child and forename_normalized:
            child_forenames_older.append(forename_normalized)

    # Modal surname across all members
    if surnames:
        modal_surname = Counter(surnames).most_common(1)[0][0]
    else:
        modal_surname = None

    def pipe_join(names: list[str]) -> str | None:
        if not names:
            return None
        return "|".join(sorted(set(names)))

    return {
        "unique_id": record_id,
        "source_id": source_id,
        "place_id": place_id,
        "household_surname_norm": modal_surname,
        "soundex_household_surname": _soundex(modal_surname),
        "adult_forenames_sorted": pipe_join(adult_forenames),
        "child_forenames_young": pipe_join(child_forenames_young),
        "child_forenames_older": pipe_join(child_forenames_older),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_census_household_features(
    repo: Repository,
) -> list[pd.DataFrame]:
    """
    Build one Pandas DataFrame per active census source for Splink
    household-level (record) similarity.

    Returns a list of DataFrames, one per source that has at least one Record.
    Sources with no Records are omitted.  The list will typically have 2–3
    entries (1901, 1911, 1926).

    Each DataFrame has Splink-required column 'unique_id' set to record_id.
    """
    result: list[pd.DataFrame] = []

    for source_id in CENSUS_SOURCE_IDS:
        # Fetch all Records for this source
        records = repo.fetch_all(
            """
            SELECT r.record_id, r.source_id,
                   pr.place_id
            FROM record r
            LEFT JOIN place_record pr ON pr.record_id = r.record_id
            WHERE r.source_id = %s
            ORDER BY r.record_id
            """,
            (source_id,),
        )

        if not records:
            continue

        rows: list[dict] = []
        for rec in records:
            record_id = rec["record_id"]
            place_id = rec["place_id"]

            # Fetch all RecordedPersons for this household
            members = repo.fetch_all(
                """
                SELECT name_as_recorded, role, age
                FROM recorded_person
                WHERE record_id = %s
                ORDER BY recorded_person_id
                """,
                (record_id,),
            )

            rows.append(
                _build_household_row(record_id, source_id, members, place_id)
            )

        df = pd.DataFrame(rows)
        # Ensure Splink-required types
        df["unique_id"] = df["unique_id"].astype(int)
        df["source_id"] = df["source_id"].astype(int)
        result.append(df)

    return result
