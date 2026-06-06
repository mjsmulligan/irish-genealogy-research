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

Called by src/reconstruction/linkage.py — not invoked directly.
"""

from __future__ import annotations

import re
import sqlite3

import pandas as pd

# Census source IDs
CENSUS_SOURCE_IDS = (3, 4, 5)

# Roles treated as children for household feature extraction
_CHILD_ROLES = {"son", "daughter"}

# Roles treated as head / spouse
_HEAD_ROLES   = {"head"}
_SPOUSE_ROLES = {"spouse"}

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
# Person-level feature extractor (general cross-census linkage pass)
# ---------------------------------------------------------------------------

def build_census_features(conn: sqlite3.Connection) -> list[pd.DataFrame]:
    """
    Build feature DataFrames for all census Person conclusions, one DataFrame
    per census source.  Splink's link_and_dedupe mode requires a list of
    DataFrames so it can produce both within-source and cross-source candidate
    pairs.

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
    Jaccard overlap is computed inside Splink's CustomComparison via DuckDB's
    string_split / list_intersect / list_union array functions (see linkage.py).

    Relationship features require household inference to have run first.

    Returns an empty list if no census Person conclusions exist.
    """
    query = """
        SELECT
            p.person_id,
            s.source_id,
            pn.value                                     AS full_name,
            rp.age                                       AS age,
            r.date                                       AS census_date,
            r.place_as_recorded                          AS place_raw,
            pr2.place_id                                 AS place_id
        FROM person p
        -- Concluded person_name (birth_name preferred); required — persons
        -- without a name cannot be matched and are excluded.
        JOIN person_name pn ON pn.person_id = p.person_id
            AND pn.type = 'birth_name'
            AND pn.person_name_id = (
                SELECT MIN(pn2.person_name_id)
                FROM person_name pn2
                WHERE pn2.person_id = p.person_id AND pn2.type = 'birth_name'
            )
        -- Link to census records via person_record
        JOIN person_record pr ON pr.person_id = p.person_id
        JOIN record r         ON r.record_id  = pr.record_id
        JOIN source s         ON s.source_id  = r.source_id
                              AND s.source_id IN (3, 4, 5)
        -- Match THIS person's RecordedPerson row by name within the household
        -- record. Where two people share a name, LIMIT 1 picks the first
        -- occurrence — acceptable for Splink feature purposes.
        JOIN recorded_person rp ON rp.record_id = r.record_id
            AND rp.recorded_person_id = (
                SELECT rp2.recorded_person_id
                FROM recorded_person rp2
                WHERE rp2.record_id = r.record_id
                  AND rp2.name_as_recorded = pn.value
                ORDER BY rp2.recorded_person_id
                LIMIT 1
            )
        -- Resolved place
        LEFT JOIN place_record pr2 ON pr2.record_id = r.record_id
        ORDER BY p.person_id, s.source_id
    """

    rows = conn.execute(query).fetchall()

    records = []
    for row in rows:
        full_name = row["full_name"] or ""
        forename, surname = _split_name(full_name)

        place_raw = _normalise_name(row["place_raw"]) if row["place_raw"] else None
        place_id  = int(row["place_id"]) if row["place_id"] is not None else None

        person_id     = row["person_id"]
        children      = _child_names(conn, person_id)
        siblings      = _sibling_names(conn, person_id)

        records.append({
            "unique_id":         person_id,
            "person_id":         person_id,
            "source_id":         row["source_id"],
            "surname_norm":      surname,
            "forename_norm":     forename,
            "birth_year_est":    _birth_year_est(row["age"], row["census_date"]),
            "place_id":          place_id,
            "place_raw":         place_raw,
            "spouse_name_norm":  _spouse_name(conn, person_id),
            "child_names":       "|".join(sorted(children))   or None,
            "sibling_names":     "|".join(sorted(siblings))   or None,
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

    Child name matching uses forenames only (not full names). Within a
    confirmed same-surname household pair, the surname adds no discriminating
    value and would penalise cases where a child's surname is recorded with
    a variant spelling.

    Features:
        unique_id               int     — Splink required PK; equals record_id
        record_id               int     — GRA Record primary key
        source_id               int     — census source id
        head_surname_norm       str     — normalised head surname
        head_forename_norm      str     — normalised head forename
        head_birth_year_est     int     — estimated head birth year
        spouse_forename_norm    str     — normalised spouse forename; null if absent
        child_forenames_sorted  str     — pipe-joined sorted normalised child forenames;
                                          null if no sons or daughters present
        child_count             int     — count of son + daughter RecordedPersons
        household_size          int     — total RecordedPerson count
        place_id                int     — resolved place_id (blocking anchor)
        place_raw               str     — normalised place string (fallback)
    """
    head_surname       = None
    head_forename      = None
    head_birth_year    = None
    spouse_forename    = None
    child_forenames: list[str] = []
    household_size     = len(rp_rows)

    for rp in rp_rows:
        role      = rp["role"]
        name_raw  = rp["name_as_recorded"] or ""
        age       = rp["age"]

        if role in _HEAD_ROLES:
            forename, surname    = _split_name(name_raw)
            head_forename        = forename
            head_surname         = surname
            head_birth_year      = _birth_year_est(age, census_date)

        elif role in _SPOUSE_ROLES:
            spouse_forename = _forename_from_full(name_raw)

        elif role in _CHILD_ROLES:
            fn = _forename_from_full(name_raw)
            if fn:
                child_forenames.append(fn)

    child_forenames_sorted = "|".join(sorted(child_forenames)) or None

    return {
        "unique_id":              record_id,
        "record_id":              record_id,
        "source_id":              source_id,
        "head_surname_norm":      head_surname,
        "head_forename_norm":     head_forename,
        "head_birth_year_est":    head_birth_year,
        "spouse_forename_norm":   spouse_forename,
        "child_forenames_sorted": child_forenames_sorted,
        "child_count":            len(child_forenames),
        "household_size":         household_size,
        "place_id":               place_id,
        "place_raw":              place_raw,
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
    _extract_household_row(). Records with no head RecordedPerson are
    included but will have null head features — Splink's NullLevel will
    handle them gracefully (they will not match above threshold).

    Returns an empty list if no census Records exist.
    """
    # Fetch all census Records with their resolved place_id.
    # One row per record — place_record is LEFT JOIN so unresolved places
    # produce null place_id (NullLevel fires in blocking/comparison).
    record_rows = conn.execute(
        """
        SELECT
            r.record_id,
            r.source_id,
            r.date          AS census_date,
            r.place_as_recorded,
            pr.place_id
        FROM record r
        JOIN source s ON s.source_id = r.source_id
                      AND s.source_id IN (3, 4, 5)
        LEFT JOIN place_record pr ON pr.record_id = r.record_id
        ORDER BY r.source_id, r.record_id
        """,
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
    df["place_id"]           = df["place_id"].astype("Int64")
    df["head_birth_year_est"] = df["head_birth_year_est"].astype("Int64")
    df["child_count"]        = df["child_count"].astype("Int64")
    df["household_size"]     = df["household_size"].astype("Int64")

    # Replace empty strings with None so NullLevel fires correctly.
    for col in ("head_surname_norm", "head_forename_norm",
                "spouse_forename_norm", "child_forenames_sorted",
                "place_raw"):
        df[col] = df[col].replace("", None)

    # Split into one DataFrame per census source for Splink link_only.
    result: list[pd.DataFrame] = []
    for source_id in sorted(df["source_id"].unique()):
        result.append(df[df["source_id"] == source_id].reset_index(drop=True))
    return result
