"""
GRA — Census Feature Extractor
Builds flat feature DataFrames for Splink from census evidence.

Two extractors are provided:

build_census_features()
    One row per Person per census source (person-level).
    Used by the general cross-census person linkage pass (linkage.py).
    Features drawn from the conclusion layer (person_name, relationship graph).
    Relationship features require household inference to have run first.

build_census_household_features()
    One row per census Record (household-level).
    Used by the household linkage pass (linkage.py run_census_household_linkage).
    Features drawn exclusively from the evidence layer (recorded_person rows).
    Does NOT require household inference to have run — operates on raw evidence.

    Household features are role-independent to handle head changes across the
    25-year census span (death → spouse becomes head → son becomes head):

      household_surname_norm   — modal surname across all members; stable
                                  across head changes
      adult_forenames_sorted   — pipe-joined sorted forenames of all non-child
                                  members; compared with Szymkiewicz–Simpson
      child_forenames_sorted   — pipe-joined sorted child forenames; compared
                                  with Szymkiewicz–Simpson

    Szymkiewicz–Simpson (|A∩B| / min(|A|,|B|)) replaces Jaccard for name-set
    comparisons. Over a 25-year span children leave and adults die; the
    expanding union penalises valid continuations under Jaccard. S–S measures
    containment of the smaller set in the larger, which is the right question.

Called by src/reconstruction/linkage.py — not invoked directly.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict

import pandas as pd

# Census source IDs
CENSUS_SOURCE_IDS = (3, 4, 5)

# Roles treated as children for household feature extraction
_CHILD_ROLES = {"son", "daughter"}

# Roles treated as head / spouse
_HEAD_ROLES   = {"head"}
_SPOUSE_ROLES = {"spouse"}

# Roles treated as adults (non-children) for the role-independent adult
# forename set. Includes head, spouse, and any other co-resident adult.
# Excludes child roles so the adult and child sets remain disjoint.
_ADULT_ROLES = {
    "head", "spouse", "mother", "father", "sibling",
    "in_law", "aunt_uncle", "grandchild", "visitor",
    "boarder", "servant", "niece_nephew", "cousin",
}

# Age threshold for child departure prior.
# Children aged > _CHILD_DEPARTURE_AGE are treated as "older resident children"
# (the spinster/bachelor pattern). Children aged <= _CHILD_DEPARTURE_AGE are
# "young children" — definitively still dependents at the time of the census.
_CHILD_DEPARTURE_AGE: int = 20

# Abbreviation expansions for name normalisation (mirrors reconstruction_algorithms.md §4.1)
_FORENAME_ABBREV: dict[str, str] = {
    "wm":    "william",
    "thos":  "thomas",
    "jas":   "james",
    "jno":   "john",
    "chas":  "charles",
    "mgt":   "margaret",
    "marg":  "margaret",
    "pat":   "patrick",
    "pk":    "patrick",
    "brid":  "bridget",
    "bgt":   "bridget",
    "michl": "michael",
}

_FADA = str.maketrans("áéíóúÁÉÍÓÚ", "aeiouAEIOU")


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _normalise_name(raw: str | None) -> str | None:
    """
    Apply name normalisation pipeline from reconstruction_algorithms.md §4.1:
    1. Lowercase
    2. Strip fada (diacritics)
    3. Strip apostrophes and hyphens
    4. Normalise whitespace
    Abbreviation expansion is NOT applied here — use _normalise_forename for
    forename tokens to avoid corrupting surnames that match abbreviation keys.
    """
    if not raw:
        return None
    s = raw.lower().translate(_FADA)
    s = re.sub(r"['\-]", " ", s)
    s = " ".join(s.split())
    return s or None


def _normalise_forename(raw: str | None) -> str | None:
    """Normalise a forename token, including abbreviation expansion."""
    normed = _normalise_name(raw)
    if not normed:
        return None
    tokens = normed.split()
    tokens = [_FORENAME_ABBREV.get(t, t) for t in tokens]
    return " ".join(tokens)


def _split_name(full_name: str | None) -> tuple[str | None, str | None]:
    """
    Split a 'Firstname Surname' string into (forename_norm, surname_norm).
    Forename receives abbreviation expansion; surname does not.
    NAI census format is always 'firstname surname' from the ingest mapping.
    """
    if not full_name:
        return None, None
    parts = full_name.strip().split()
    if len(parts) == 1:
        return None, _normalise_name(parts[0])
    return _normalise_forename(parts[0]), _normalise_name(" ".join(parts[1:]))


def _forename_from_full(full_name: str | None) -> str | None:
    """Extract and normalise the forename token only from a full name string."""
    if not full_name:
        return None
    parts = full_name.strip().split()
    return _normalise_forename(parts[0]) if parts else None


def _birth_year_est(age: int | None, census_date: str | None) -> int | None:
    """
    Derive estimated birth year from age and census date string.
    Clamped to 1750–1926 to suppress transcription errors (e.g. age=999).
    """
    if age is None or not census_date:
        return None
    m = re.match(r"^(\d{4})", census_date)
    if not m:
        return None
    raw = int(m.group(1)) - int(age)
    return raw if 1750 <= raw <= 1926 else None


# ---------------------------------------------------------------------------
# Relationship feature lookups (conclusion layer — person-level extractor only)
# ---------------------------------------------------------------------------

def _spouse_name(conn: sqlite3.Connection, person_id: int) -> str | None:
    """
    Return the normalised birth name of the most recently concluded spouse,
    or None if no couple relationship exists.

    Where a person has multiple couple relationships (serial marriage), the
    highest relationship_id is used as a proxy for recency — a deliberate
    simplification until marriage event dates are reliably populated.
    """
    row = conn.execute(
        """
        SELECT pn.value
        FROM relationship r
        JOIN person_name pn ON pn.person_id = CASE
            WHEN r.person_id_1 = ? THEN r.person_id_2
            ELSE r.person_id_1
        END
        WHERE r.type = 'couple'
          AND (r.person_id_1 = ? OR r.person_id_2 = ?)
          AND pn.type = 'birth_name'
          AND pn.person_name_id = (
              SELECT MIN(pn2.person_name_id)
              FROM person_name pn2
              WHERE pn2.person_id = pn.person_id AND pn2.type = 'birth_name'
          )
        ORDER BY r.relationship_id DESC
        LIMIT 1
        """,
        (person_id, person_id, person_id),
    ).fetchone()
    return _normalise_name(row[0]) if row else None


def _child_names(conn: sqlite3.Connection, person_id: int) -> set[str]:
    """
    Return the set of normalised birth names of all concluded children
    (parent_child relationships where this person is person_id_1 = parent).
    """
    rows = conn.execute(
        """
        SELECT pn.value
        FROM relationship r
        JOIN person_name pn ON pn.person_id = r.person_id_2
        WHERE r.type = 'parent_child'
          AND r.person_id_1 = ?
          AND pn.type = 'birth_name'
          AND pn.person_name_id = (
              SELECT MIN(pn2.person_name_id)
              FROM person_name pn2
              WHERE pn2.person_id = pn.person_id AND pn2.type = 'birth_name'
          )
        """,
        (person_id,),
    ).fetchall()
    return {_normalise_name(row[0]) for row in rows if row[0]}


def _sibling_names(conn: sqlite3.Connection, person_id: int) -> set[str]:
    """
    Return the set of normalised birth names of all concluded siblings.
    Sibling relationships are symmetric so both endpoints are checked.
    """
    rows = conn.execute(
        """
        SELECT pn.value
        FROM relationship r
        JOIN person_name pn ON pn.person_id = CASE
            WHEN r.person_id_1 = ? THEN r.person_id_2
            ELSE r.person_id_1
        END
        WHERE r.type = 'sibling'
          AND (r.person_id_1 = ? OR r.person_id_2 = ?)
          AND pn.type = 'birth_name'
          AND pn.person_name_id = (
              SELECT MIN(pn2.person_name_id)
              FROM person_name pn2
              WHERE pn2.person_id = pn.person_id AND pn2.type = 'birth_name'
          )
        """,
        (person_id, person_id, person_id),
    ).fetchall()
    return {_normalise_name(row[0]) for row in rows if row[0]}


# ---------------------------------------------------------------------------
# Batch relationship lookups (used by build_census_features)
# ---------------------------------------------------------------------------

def _batch_spouse_names(
    conn: sqlite3.Connection,
    person_ids: list[int],
) -> dict[int, str | None]:
    """
    Return a mapping of person_id → normalised spouse name for all
    person_ids in one query, replacing per-person calls to _spouse_name().

    Where a person has multiple couple relationships, the highest
    relationship_id is used as recency proxy (same logic as _spouse_name).
    """
    if not person_ids:
        return {}
    placeholders = ",".join("?" * len(person_ids))
    rows = conn.execute(
        f"""
        SELECT
            r.person_id_1     AS pid,
            pn.value          AS spouse_name
        FROM relationship r
        JOIN person_name pn ON pn.person_id = r.person_id_2
            AND pn.type = 'birth_name'
            AND pn.person_name_id = (
                SELECT MIN(pn2.person_name_id)
                FROM person_name pn2
                WHERE pn2.person_id = r.person_id_2 AND pn2.type = 'birth_name'
            )
        WHERE r.type = 'couple'
          AND r.person_id_1 IN ({placeholders})
          AND r.relationship_id = (
              SELECT MAX(r2.relationship_id)
              FROM relationship r2
              WHERE r2.type = 'couple' AND r2.person_id_1 = r.person_id_1
          )
        UNION ALL
        SELECT
            r.person_id_2     AS pid,
            pn.value          AS spouse_name
        FROM relationship r
        JOIN person_name pn ON pn.person_id = r.person_id_1
            AND pn.type = 'birth_name'
            AND pn.person_name_id = (
                SELECT MIN(pn2.person_name_id)
                FROM person_name pn2
                WHERE pn2.person_id = r.person_id_1 AND pn2.type = 'birth_name'
            )
        WHERE r.type = 'couple'
          AND r.person_id_2 IN ({placeholders})
          AND r.relationship_id = (
              SELECT MAX(r2.relationship_id)
              FROM relationship r2
              WHERE r2.type = 'couple' AND r2.person_id_2 = r.person_id_2
          )
        """,
        person_ids + person_ids,
    ).fetchall()

    # Last row per pid wins (highest relationship_id floats last via UNION ALL
    # order, but we deduplicate with keep-last to be safe).
    result: dict[int, str | None] = {}
    for row in rows:
        result[row["pid"]] = _normalise_name(row["spouse_name"])
    return result


def _batch_child_names(
    conn: sqlite3.Connection,
    person_ids: list[int],
) -> dict[int, set[str]]:
    """
    Return a mapping of person_id → set of normalised child names for all
    person_ids in one query, replacing per-person calls to _child_names().

    Only parent_child relationships where the person is person_id_1 (parent)
    are included, consistent with the original _child_names() logic.
    """
    if not person_ids:
        return {pid: set() for pid in person_ids}
    placeholders = ",".join("?" * len(person_ids))
    rows = conn.execute(
        f"""
        SELECT
            r.person_id_1   AS parent_id,
            pn.value        AS child_name
        FROM relationship r
        JOIN person_name pn ON pn.person_id = r.person_id_2
            AND pn.type = 'birth_name'
            AND pn.person_name_id = (
                SELECT MIN(pn2.person_name_id)
                FROM person_name pn2
                WHERE pn2.person_id = r.person_id_2 AND pn2.type = 'birth_name'
            )
        WHERE r.type = 'parent_child'
          AND r.person_id_1 IN ({placeholders})
        """,
        person_ids,
    ).fetchall()

    result: dict[int, set[str]] = {pid: set() for pid in person_ids}
    for row in rows:
        normed = _normalise_name(row["child_name"])
        if normed:
            result[row["parent_id"]].add(normed)
    return result


def _batch_sibling_names(
    conn: sqlite3.Connection,
    person_ids: list[int],
) -> dict[int, set[str]]:
    """
    Return a mapping of person_id → set of normalised sibling names for all
    person_ids in one query, replacing per-person calls to _sibling_names().

    Sibling relationships are symmetric so both endpoints are checked.
    """
    if not person_ids:
        return {pid: set() for pid in person_ids}
    placeholders = ",".join("?" * len(person_ids))
    rows = conn.execute(
        f"""
        SELECT
            r.person_id_1 AS focal_id,
            pn.value      AS sibling_name
        FROM relationship r
        JOIN person_name pn ON pn.person_id = r.person_id_2
            AND pn.type = 'birth_name'
            AND pn.person_name_id = (
                SELECT MIN(pn2.person_name_id)
                FROM person_name pn2
                WHERE pn2.person_id = r.person_id_2 AND pn2.type = 'birth_name'
            )
        WHERE r.type = 'sibling'
          AND r.person_id_1 IN ({placeholders})
        UNION ALL
        SELECT
            r.person_id_2 AS focal_id,
            pn.value      AS sibling_name
        FROM relationship r
        JOIN person_name pn ON pn.person_id = r.person_id_1
            AND pn.type = 'birth_name'
            AND pn.person_name_id = (
                SELECT MIN(pn2.person_name_id)
                FROM person_name pn2
                WHERE pn2.person_id = r.person_id_1 AND pn2.type = 'birth_name'
            )
        WHERE r.type = 'sibling'
          AND r.person_id_2 IN ({placeholders})
        """,
        person_ids + person_ids,
    ).fetchall()

    result: dict[int, set[str]] = {pid: set() for pid in person_ids}
    for row in rows:
        normed = _normalise_name(row["sibling_name"])
        if normed:
            result[row["focal_id"]].add(normed)
    return result



def build_census_features(conn: sqlite3.Connection) -> list[pd.DataFrame]:
    """
    Build feature DataFrames for all census Person conclusions, one DataFrame
    per census source.  Splink's link_only mode receives a list of DataFrames
    and generates cross-source candidate pairs only — never within-source.

    Each DataFrame has one row per person_id and the following columns:

        unique_id            int     — Splink required PK; equals person_id
        person_id            int     — GRA Person primary key
        source_id            int     — census source (3=1901, 4=1911, 5=1926)
        surname_norm         str     — normalised surname
        forename_norm        str     — normalised forename
        birth_year_est       int     — estimated birth year (census year - age)
        place_id             int     — resolved Place conclusion id (blocking anchor)
        place_raw            str     — normalised place string (fallback if unresolved)
        spouse_name_norm     str     — normalised name of concluded spouse; null if none
        child_names          str     — pipe-joined sorted normalised child names;
                                       null if no concluded children
        sibling_names        str     — pipe-joined sorted normalised sibling names;
                                       null if no concluded siblings

    child_names and sibling_names are passed to Splink as pipe-joined strings.
    Szymkiewicz–Simpson overlap (|A∩B| / min(|A|,|B|)) is computed inside
    Splink's CustomComparison via DuckDB's string_split / list_intersect
    array functions (see linkage.py _build_settings).

    Relationship features require household inference to have run first.

    Returns an empty list if no census Person conclusions exist.
    """
    # Fetch all person-level features from the conclusion layer.
    # We no longer join recorded_person by name_as_recorded = pn.value (brittle;
    # breaks on transcription/case variance). Instead we fetch person and
    # recorded_person rows for each record separately and pair them positionally
    # in Python, consistent with _persons_for_record in linkage.py.
    person_rows = conn.execute(
        f"""
        SELECT
            p.person_id,
            s.source_id,
            pn.value                AS full_name,
            r.record_id,
            r.date                  AS census_date,
            r.place_as_recorded     AS place_raw,
            pr2.place_id            AS place_id
        FROM person p
        JOIN person_name pn ON pn.person_id = p.person_id
            AND pn.type = 'birth_name'
            AND pn.person_name_id = (
                SELECT MIN(pn2.person_name_id)
                FROM person_name pn2
                WHERE pn2.person_id = p.person_id AND pn2.type = 'birth_name'
            )
        JOIN person_record pr ON pr.person_id = p.person_id
        JOIN record r         ON r.record_id  = pr.record_id
        JOIN source s         ON s.source_id  = r.source_id
                              AND s.source_id IN ({",".join("?" * len(CENSUS_SOURCE_IDS))})
        LEFT JOIN place_record pr2 ON pr2.record_id = r.record_id
        ORDER BY r.record_id, p.person_id
        """,
        CENSUS_SOURCE_IDS,
    ).fetchall()

    if not person_rows:
        return []

    # Fetch recorded_person rows for all relevant records in one query.
    record_ids = list({row["record_id"] for row in person_rows})
    placeholders = ",".join("?" * len(record_ids))
    rp_rows = conn.execute(
        f"""
        SELECT record_id, age
        FROM recorded_person
        WHERE record_id IN ({placeholders})
        ORDER BY record_id, recorded_person_id
        """,
        record_ids,
    ).fetchall()

    # Build positional lookup: record_id → [age, age, ...] in recorded order.
    rp_ages_by_record: dict[int, list] = defaultdict(list)
    for rp in rp_rows:
        rp_ages_by_record[rp["record_id"]].append(rp["age"])

    # Batch-fetch all relationship features in three queries — one per
    # relationship type — replacing the previous per-person N+1 pattern.
    all_person_ids = [row["person_id"] for row in person_rows]
    spouse_map  = _batch_spouse_names(conn, all_person_ids)
    children_map = _batch_child_names(conn, all_person_ids)
    siblings_map = _batch_sibling_names(conn, all_person_ids)

    # Track position within each record to pair person to evidence row.
    record_person_pos: dict[int, int] = defaultdict(int)

    records = []
    for row in person_rows:
        full_name  = row["full_name"] or ""
        forename, surname = _split_name(full_name)
        place_raw  = _normalise_name(row["place_raw"]) if row["place_raw"] else None
        place_id   = int(row["place_id"]) if row["place_id"] is not None else None
        record_id  = row["record_id"]
        person_id  = row["person_id"]

        # Pair this person with its positional evidence row.
        pos  = record_person_pos[record_id]
        ages = rp_ages_by_record[record_id]
        age  = ages[pos] if pos < len(ages) else None
        record_person_pos[record_id] += 1

        children = children_map.get(person_id, set())
        siblings = siblings_map.get(person_id, set())

        records.append({
            "unique_id":         person_id,
            "person_id":         person_id,
            "source_id":         row["source_id"],
            "surname_norm":      surname,
            "forename_norm":     forename,
            "birth_year_est":    _birth_year_est(age, row["census_date"]),
            "place_id":          place_id,
            "place_raw":         place_raw,
            "spouse_name_norm":  spouse_map.get(person_id),
            "child_names":       "|".join(sorted(children)) or None,
            "sibling_names":     "|".join(sorted(siblings)) or None,
        })

    if not records:
        return []

    df = pd.DataFrame(records)
    df["place_id"] = df["place_id"].astype("Int64")
    df["child_names"]   = df["child_names"].replace("", None)
    df["sibling_names"] = df["sibling_names"].replace("", None)
    df = df.drop_duplicates(subset=["unique_id", "source_id"], keep="first")

    result: list[pd.DataFrame] = []
    for source_id in sorted(df["source_id"].unique()):
        result.append(df[df["source_id"] == source_id].reset_index(drop=True))
    return result


# ---------------------------------------------------------------------------
# Household-level feature extractor (household linkage pass)
# ---------------------------------------------------------------------------

def _modal_surname(rp_rows: list[sqlite3.Row]) -> str | None:
    """
    Return the most common normalised surname across all household members.

    Using the modal surname rather than the head's surname makes the feature
    stable across head changes (death → spouse becomes head → son becomes head).
    In a same-surname household this is always the shared surname. In a mixed
    household (servants, in-laws) it remains the family surname by plurality.

    Falls back to the head's surname if no mode can be determined (single row).
    """
    counts: Counter = Counter()
    for rp in rp_rows:
        _, surname = _split_name(rp["name_as_recorded"] or "")
        if surname:
            counts[surname] += 1
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def _extract_household_row(
    record_id: int,
    source_id: int,
    census_date: str | None,
    place_id: int | None,
    place_raw: str | None,
    rp_rows: list[sqlite3.Row],
) -> dict:
    """
    Build one household feature row from a list of RecordedPerson rows
    belonging to a single census Record.

    Features are role-independent to handle head changes across the 25-year
    census span. A death making the spouse the new head, or a son becoming
    head, should not break household continuity matching.

    Surname: modal surname across all members (stable across head changes).

    Adult forenames: all non-child member forenames as a sorted pipe-joined
    set. A Patrick + Mary household where Mary becomes head in 1911 produces
    the same adult forename set both years. Compared with Szymkiewicz–Simpson
    so departed adults reduce score gracefully rather than collapsing it.

    Child forenames: split into two age-based buckets using the departure
    prior. Over the 25-year census span, children grow up and leave.

      child_forenames_young  — children aged <= _CHILD_DEPARTURE_AGE (20).
        These are definitively still dependents at the time of this census
        and the most reliable cross-census continuity signal. Used as the
        primary S–S comparison feature.

      child_forenames_older  — children aged > 20 (the spinster/bachelor
        pattern). Present in this census but likely departed by the next.
        Used as a secondary S–S comparison feature; absence does not
        strongly penalise a valid household continuation.

      child_forenames_sorted — all children regardless of age. Retained for
        backward compatibility and summary statistics.

    When age is missing from a recorded_person row, the child is placed in
    child_forenames_young (conservative: treat as young rather than discard).

    Szymkiewicz–Simpson = |A ∩ B| / min(|A|, |B|). For the young child set
    over 25 years: {Bridget(4), Patrick(7), James(9)} in 1901 (all young)
    vs {Patrick, James} in 1926 → 2/2 = 1.0 rather than Jaccard's 2/3 ≈ 0.67.

    Features:
        unique_id                int   — Splink required PK; equals record_id
        record_id                int   — GRA Record primary key
        source_id                int   — census source id
        household_surname_norm   str   — modal surname across all members
        adult_forenames_sorted   str   — pipe-joined sorted adult forenames
        child_forenames_young    str   — pipe-joined sorted child forenames,
                                         aged <= 20 (primary continuity signal)
        child_forenames_older    str   — pipe-joined sorted child forenames,
                                         aged > 20 (spinster/bachelor pattern)
        child_forenames_sorted   str   — pipe-joined sorted child forenames, all
        adult_count              int   — count of non-child members
        child_count              int   — count of son + daughter members
        household_size           int   — total RecordedPerson count
        place_id                 int   — resolved place_id (blocking anchor)
        place_raw                str   — normalised place string (fallback)
    """
    adult_forenames:       list[str] = []
    child_forenames_young: list[str] = []
    child_forenames_older: list[str] = []

    for rp in rp_rows:
        role     = rp["role"]
        name_raw = rp["name_as_recorded"] or ""
        fn       = _forename_from_full(name_raw)
        if not fn:
            continue

        if role in _CHILD_ROLES:
            age = rp["age"]
            if age is None or int(age) <= _CHILD_DEPARTURE_AGE:
                child_forenames_young.append(fn)
            else:
                child_forenames_older.append(fn)
        elif role in _ADULT_ROLES:
            adult_forenames.append(fn)

    all_children = sorted(child_forenames_young + child_forenames_older)

    return {
        "unique_id":               record_id,
        "record_id":               record_id,
        "source_id":               source_id,
        "household_surname_norm":  _modal_surname(rp_rows),
        "adult_forenames_sorted":  "|".join(sorted(adult_forenames)) or None,
        "child_forenames_young":   "|".join(sorted(child_forenames_young)) or None,
        "child_forenames_older":   "|".join(sorted(child_forenames_older)) or None,
        "child_forenames_sorted":  "|".join(all_children) or None,
        "adult_count":             len(adult_forenames),
        "child_count":             len(all_children),
        "household_size":          len(rp_rows),
        "place_id":                place_id,
        "place_raw":               place_raw,
    }


def build_census_household_features(conn: sqlite3.Connection) -> list[pd.DataFrame]:
    """
    Build household-level feature DataFrames for the household linkage pass.

    One row per census Record (household). Features are extracted entirely
    from the evidence layer — recorded_person roles and ages, record event
    fields, and place_record. Does NOT require household inference to have
    run; operates on raw evidence before any conclusions are formed.

    Returns one DataFrame per census source present in the data, ordered by
    source_id ascending. Splink's link_only mode receives these as a list
    and generates cross-source household candidate pairs.

    Each DataFrame has one row per record_id with columns as described in
    _extract_household_row(), including the age-split child forename columns
    (child_forenames_young, child_forenames_older, child_forenames_sorted).

    Returns an empty list if no census Records exist.
    """
    # Fetch all census Records with their resolved place_id.
    # One row per record — place_record is LEFT JOIN so unresolved places
    # produce null place_id (NullLevel fires in blocking/comparison).
    record_rows = conn.execute(
        f"""
        SELECT
            r.record_id,
            r.source_id,
            r.date          AS census_date,
            r.place_as_recorded,
            pr.place_id
        FROM record r
        JOIN source s ON s.source_id = r.source_id
                      AND s.source_id IN ({",".join("?" * len(CENSUS_SOURCE_IDS))})
        LEFT JOIN place_record pr ON pr.record_id = r.record_id
        ORDER BY r.source_id, r.record_id
        """,
        CENSUS_SOURCE_IDS,
    ).fetchall()

    if not record_rows:
        return []

    # Build a lookup: record_id → list of RecordedPerson rows.
    # Fetched once for all census records to avoid N+1 queries.
    record_ids = [row["record_id"] for row in record_rows]
    placeholders = ",".join("?" * len(record_ids))

    rp_by_record: dict[int, list[sqlite3.Row]] = {rid: [] for rid in record_ids}
    for rp in conn.execute(
        f"""
        SELECT record_id, role, name_as_recorded, age
        FROM recorded_person
        WHERE record_id IN ({placeholders})
        ORDER BY record_id, recorded_person_id
        """,
        record_ids,
    ).fetchall():
        rp_by_record[rp["record_id"]].append(rp)

    # Build one feature row per Record.
    rows_out = []
    for rec in record_rows:
        record_id  = rec["record_id"]
        source_id  = rec["source_id"]
        place_id   = int(rec["place_id"]) if rec["place_id"] is not None else None
        place_raw  = _normalise_name(rec["place_as_recorded"]) if rec["place_as_recorded"] else None
        rp_list    = rp_by_record.get(record_id, [])

        rows_out.append(_extract_household_row(
            record_id   = record_id,
            source_id   = source_id,
            census_date = rec["census_date"],
            place_id    = place_id,
            place_raw   = place_raw,
            rp_rows     = rp_list,
        ))

    if not rows_out:
        return []

    df = pd.DataFrame(rows_out)

    # Nullable integer columns — prevent pandas float64 coercion.
    df["place_id"]       = df["place_id"].astype("Int64")
    df["adult_count"]    = df["adult_count"].astype("Int64")
    df["child_count"]    = df["child_count"].astype("Int64")
    df["household_size"] = df["household_size"].astype("Int64")

    # Replace empty strings with None so NullLevel fires correctly.
    for col in ("household_surname_norm", "adult_forenames_sorted",
                "child_forenames_young", "child_forenames_older",
                "child_forenames_sorted", "place_raw"):
        df[col] = df[col].replace("", None)

    # Split into one DataFrame per census source for Splink link_only.
    result: list[pd.DataFrame] = []
    for source_id in sorted(df["source_id"].unique()):
        result.append(df[df["source_id"] == source_id].reset_index(drop=True))
    return result
