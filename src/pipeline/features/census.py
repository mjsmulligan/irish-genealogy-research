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
    Used by the household linkage pass and the evidence-layer similarity step
    (src/evidence/similarity.py).
    Features drawn exclusively from the evidence layer (recorded_person rows).
    Does NOT require household inference to have run — operates on raw evidence.

    Household features are role-independent to handle head changes across the
    25-year census span (death → spouse becomes head → son becomes head):

      household_surname_norm   — modal surname across all members; stable
                                  across head changes
      adult_forenames_sorted   — pipe-joined sorted forenames of all non-child
                                  members; compared with Szymkiewicz–Simpson
      child_forenames_young    — pipe-joined sorted forenames of children
                                  aged <= CHILD_DEPARTURE_AGE (primary signal)
      child_forenames_older    — pipe-joined sorted forenames of children
                                  aged > CHILD_DEPARTURE_AGE (softer signal)

    Szymkiewicz–Simpson (|A∩B| / min(|A|,|B|)) replaces Jaccard for name-set
    comparisons. Over a 25-year span children leave and adults die; the
    expanding union penalises valid continuations under Jaccard. S–S measures
    containment of the smaller set in the larger, which is the right question.

Called by src/pipeline/linkage.py and src/evidence/similarity.py.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

import pandas as pd
import psycopg2.extensions

from src.constants import CENSUS_SOURCE_IDS, CHILD_DEPARTURE_AGE

# Roles treated as children for household feature extraction
_CHILD_ROLES = {"son", "daughter"}

# Roles treated as adults (non-children) for the role-independent adult
# forename set. Includes head, spouse, and any other co-resident adult.
# Excludes child roles so the adult and child sets remain disjoint.
_ADULT_ROLES = {
    "head", "spouse", "mother", "father", "sibling",
    "in_law", "aunt_uncle", "grandchild", "visitor",
    "boarder", "servant", "niece_nephew", "cousin",
}

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

def _batch_spouse_names(
    conn: psycopg2.extensions.connection,
    person_ids: list[int],
) -> dict[int, str | None]:
    """
    Return a mapping of person_id → normalised spouse name for all
    person_ids in one query.

    Where a person has multiple couple relationships, the highest
    relationship_id is used as recency proxy.
    """
    if not person_ids:
        return {}
    placeholders = ",".join(["%s"] * len(person_ids))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT r.person_id_1 AS pid, pn.value AS spouse_name
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
            SELECT r.person_id_2 AS pid, pn.value AS spouse_name
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
        )
        rows = cur.fetchall()
    result: dict[int, str | None] = {}
    for row in rows:
        result[row["pid"]] = _normalise_name(row["spouse_name"])
    return result


def _batch_child_names(
    conn: psycopg2.extensions.connection,
    person_ids: list[int],
) -> dict[int, set[str]]:
    """
    Return a mapping of person_id → set of normalised child names for all
    person_ids in one query (person_id_1 = parent only).
    """
    if not person_ids:
        return {pid: set() for pid in person_ids}
    placeholders = ",".join(["%s"] * len(person_ids))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT r.person_id_1 AS parent_id, pn.value AS child_name
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
        )
        rows = cur.fetchall()
    result: dict[int, set[str]] = {pid: set() for pid in person_ids}
    for row in rows:
        normed = _normalise_name(row["child_name"])
        if normed:
            result[row["parent_id"]].add(normed)
    return result


def _batch_sibling_names(
    conn: psycopg2.extensions.connection,
    person_ids: list[int],
) -> dict[int, set[str]]:
    """
    Return a mapping of person_id → set of normalised sibling names for all
    person_ids in one query. Sibling relationships are symmetric.
    """
    if not person_ids:
        return {pid: set() for pid in person_ids}
    placeholders = ",".join(["%s"] * len(person_ids))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT r.person_id_1 AS focal_id, pn.value AS sibling_name
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
            SELECT r.person_id_2 AS focal_id, pn.value AS sibling_name
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
        )
        rows = cur.fetchall()
    result: dict[int, set[str]] = {pid: set() for pid in person_ids}
    for row in rows:
        normed = _normalise_name(row["sibling_name"])
        if normed:
            result[row["focal_id"]].add(normed)
    return result


# ---------------------------------------------------------------------------
# Person-level feature extractor (conclusion layer)
# ---------------------------------------------------------------------------

def build_census_features(conn: psycopg2.extensions.connection) -> list[pd.DataFrame]:
    """
    Build feature DataFrames for all census Person conclusions, one DataFrame
    per census source. Splink's link_only mode receives a list of DataFrames
    and generates cross-source candidate pairs only — never within-source.

    Each DataFrame has one row per person_id with columns:
        unique_id, person_id, source_id, surname_norm, forename_norm,
        birth_year_est, place_id, place_raw, spouse_name_norm,
        child_names, sibling_names

    Relationship features require household inference to have run first.
    Returns an empty list if no census Person conclusions exist.
    """
    placeholders = ",".join(["%s"] * len(CENSUS_SOURCE_IDS))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                p.person_id,
                s.source_id,
                pn.value            AS full_name,
                r.record_id,
                r.date              AS census_date,
                r.place_as_recorded AS place_raw,
                pr2.place_id        AS place_id
            FROM person p
            JOIN person_name pn ON pn.person_id = p.person_id
                AND pn.type = 'birth_name'
                AND pn.person_name_id = (
                    SELECT MIN(pn2.person_name_id)
                    FROM person_name pn2
                    WHERE pn2.person_id = p.person_id AND pn2.type = 'birth_name'
                )
            JOIN person_recorded_person pr ON pr.person_id = p.person_id
            JOIN record r         ON r.record_id  = pr.record_id
            JOIN source s         ON s.source_id  = r.source_id
                                  AND s.source_id IN ({placeholders})
            LEFT JOIN place_record pr2 ON pr2.record_id = r.record_id
            ORDER BY r.record_id, p.person_id
            """,
            CENSUS_SOURCE_IDS,
        )
        person_rows = cur.fetchall()

    if not person_rows:
        return []

    record_ids = list({row["record_id"] for row in person_rows})
    rp_placeholders = ",".join(["%s"] * len(record_ids))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT record_id, age
            FROM recorded_person
            WHERE record_id IN ({rp_placeholders})
            ORDER BY record_id, recorded_person_id
            """,
            record_ids,
        )
        rp_rows = cur.fetchall()

    rp_ages_by_record: dict[int, list] = defaultdict(list)
    for rp in rp_rows:
        rp_ages_by_record[rp["record_id"]].append(rp["age"])

    all_person_ids = [row["person_id"] for row in person_rows]
    spouse_map   = _batch_spouse_names(conn, all_person_ids)
    children_map = _batch_child_names(conn, all_person_ids)
    siblings_map = _batch_sibling_names(conn, all_person_ids)

    record_person_pos: dict[int, int] = defaultdict(int)
    records = []
    for row in person_rows:
        full_name          = row["full_name"] or ""
        forename, surname  = _split_name(full_name)
        place_raw          = _normalise_name(row["place_raw"]) if row["place_raw"] else None
        place_id           = int(row["place_id"]) if row["place_id"] is not None else None
        record_id          = row["record_id"]
        person_id          = row["person_id"]

        pos  = record_person_pos[record_id]
        ages = rp_ages_by_record[record_id]
        age  = ages[pos] if pos < len(ages) else None
        record_person_pos[record_id] += 1

        children = children_map.get(person_id, set())
        siblings = siblings_map.get(person_id, set())

        records.append({
            "unique_id":        person_id,
            "person_id":        person_id,
            "source_id":        row["source_id"],
            "surname_norm":     surname,
            "forename_norm":    forename,
            "birth_year_est":   _birth_year_est(age, row["census_date"]),
            "place_id":         place_id,
            "place_raw":        place_raw,
            "spouse_name_norm": spouse_map.get(person_id),
            "child_names":      "|".join(sorted(children)) or None,
            "sibling_names":    "|".join(sorted(siblings)) or None,
        })

    if not records:
        return []

    df = pd.DataFrame(records)
    df["place_id"]      = df["place_id"].astype("Int64")
    df["child_names"]   = df["child_names"].replace("", None)
    df["sibling_names"] = df["sibling_names"].replace("", None)
    df = df.drop_duplicates(subset=["unique_id", "source_id"], keep="first")

    result: list[pd.DataFrame] = []
    for source_id in sorted(df["source_id"].unique()):
        result.append(df[df["source_id"] == source_id].reset_index(drop=True))
    return result


# ---------------------------------------------------------------------------
# Household-level feature extractor (evidence layer)
# ---------------------------------------------------------------------------

def _modal_surname(rp_rows: list[dict]) -> str | None:
    """
    Return the most common normalised surname across all household members.

    Using the modal surname rather than the head's surname makes the feature
    stable across head changes (death → spouse becomes head → son becomes head).
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
    rp_rows: list[dict],
) -> dict:
    """
    Build one household feature row from a list of RecordedPerson dicts
    belonging to a single census Record.

    Features are role-independent to handle head changes across the 25-year
    census span.

    Child forenames are split into two age-based buckets using CHILD_DEPARTURE_AGE:
      child_forenames_young — children aged <= CHILD_DEPARTURE_AGE (primary signal)
      child_forenames_older — children aged > CHILD_DEPARTURE_AGE (softer signal)

    When age is missing, the child is placed in child_forenames_young
    (conservative: treat as young rather than discard).

    Returns a dict with columns:
        unique_id, record_id, source_id, household_surname_norm,
        adult_forenames_sorted, child_forenames_young, child_forenames_older,
        child_forenames_sorted, adult_count, child_count, household_size,
        place_id, place_raw
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
            if age is None or int(age) <= CHILD_DEPARTURE_AGE:
                child_forenames_young.append(fn)
            else:
                child_forenames_older.append(fn)
        elif role in _ADULT_ROLES:
            adult_forenames.append(fn)

    all_children = sorted(child_forenames_young + child_forenames_older)

    return {
        "unique_id":              record_id,
        "record_id":              record_id,
        "source_id":              source_id,
        "household_surname_norm": _modal_surname(rp_rows),
        "adult_forenames_sorted": "|".join(sorted(adult_forenames)) or None,
        "child_forenames_young":  "|".join(sorted(child_forenames_young)) or None,
        "child_forenames_older":  "|".join(sorted(child_forenames_older)) or None,
        "child_forenames_sorted": "|".join(all_children) or None,
        "adult_count":            len(adult_forenames),
        "child_count":            len(all_children),
        "household_size":         len(rp_rows),
        "place_id":               place_id,
        "place_raw":              place_raw,
    }


def build_census_household_features(
    conn: psycopg2.extensions.connection,
) -> list[pd.DataFrame]:
    """
    Build household-level feature DataFrames for all census Records present
    in the database. One DataFrame per census source, ordered by source_id.

    Features are extracted entirely from the evidence layer — recorded_person
    roles and names, record event fields, and place_record. Does NOT require
    household inference to have run; operates on raw evidence before any
    conclusions are formed.

    Used by:
      - src/evidence/similarity.py  (evidence-layer Splink run → RecordSimilarity)
      - src/pipeline/linkage.py     (conclusion-layer household pass, superseded)

    Splink's link_only mode receives the list of DataFrames and generates
    cross-source household candidate pairs only — never within-source.

    Returns an empty list if no census Records exist.
    """
    placeholders = ",".join(["%s"] * len(CENSUS_SOURCE_IDS))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                r.record_id,
                r.source_id,
                r.date              AS census_date,
                r.place_as_recorded,
                pr.place_id
            FROM record r
            JOIN source s ON s.source_id = r.source_id
                          AND s.source_id IN ({placeholders})
            LEFT JOIN place_record pr ON pr.record_id = r.record_id
            ORDER BY r.source_id, r.record_id
            """,
            CENSUS_SOURCE_IDS,
        )
        record_rows = cur.fetchall()

    if not record_rows:
        return []

    record_ids    = [row["record_id"] for row in record_rows]
    rp_placeholders = ",".join(["%s"] * len(record_ids))

    rp_by_record: dict[int, list[dict]] = {rid: [] for rid in record_ids}
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT record_id, role, name_as_recorded, age
            FROM recorded_person
            WHERE record_id IN ({rp_placeholders})
            ORDER BY record_id, recorded_person_id
            """,
            record_ids,
        )
        for rp in cur.fetchall():
            rp_by_record[rp["record_id"]].append(rp)

    rows_out = []
    for rec in record_rows:
        record_id = rec["record_id"]
        place_id  = int(rec["place_id"]) if rec["place_id"] is not None else None
        place_raw = _normalise_name(rec["place_as_recorded"]) if rec["place_as_recorded"] else None
        rows_out.append(_extract_household_row(
            record_id   = record_id,
            source_id   = rec["source_id"],
            census_date = rec["census_date"],
            place_id    = place_id,
            place_raw   = place_raw,
            rp_rows     = rp_by_record.get(record_id, []),
        ))

    if not rows_out:
        return []

    df = pd.DataFrame(rows_out)
    df["place_id"]       = df["place_id"].astype("Int64")
    df["adult_count"]    = df["adult_count"].astype("Int64")
    df["child_count"]    = df["child_count"].astype("Int64")
    df["household_size"] = df["household_size"].astype("Int64")

    for col in ("household_surname_norm", "adult_forenames_sorted",
                "child_forenames_young", "child_forenames_older",
                "child_forenames_sorted", "place_raw"):
        df[col] = df[col].replace("", None)

    result: list[pd.DataFrame] = []
    for source_id in sorted(df["source_id"].unique()):
        result.append(df[df["source_id"] == source_id].reset_index(drop=True))
    return result
