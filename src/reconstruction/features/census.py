"""
GRA — Census Feature Extractor
Builds a flat feature DataFrame for Splink from census Person conclusions.

One row per Person per census source. Features extracted from:
  - person_name (concluded names)
  - person_record → recorded_person (name_as_recorded, age, role)
  - person_record → record → source (source_id)
  - place_record (resolved place_id)
  - relationship graph (spouse, children, siblings from conclusion layer)

Relationship features require household inference to have run first.
They are null — not zero — for persons with no concluded relationships,
so Splink's NullLevel correctly treats absence-of-information differently
from confirmed non-overlap.

Called by src/reconstruction/linkage.py — not invoked directly.
"""

from __future__ import annotations

import re
import sqlite3

import pandas as pd

# Census source IDs
CENSUS_SOURCE_IDS = (3, 4, 5)

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


def _normalise_name(raw: str | None) -> str | None:
    """
    Apply name normalisation pipeline from reconstruction_algorithms.md §4.1:
    1. Lowercase
    2. Strip fada (diacritics)
    3. Normalise whitespace
    Note: abbreviation expansion is NOT applied here — it is applied to the
    forename token only in _split_name, to avoid corrupting surnames that
    happen to match abbreviation keys (Pat, Jas, Wm used as surnames).
    """
    if not raw:
        return None
    s = raw.lower().translate(_FADA)
    s = re.sub(r"['\-]", " ", s)          # strip apostrophes and hyphens
    s = " ".join(s.split())               # collapse whitespace
    return s


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
    Handles single-token names (surname only) gracefully.
    NAI census format is always 'firstname surname' from the ingest mapping.
    """
    if not full_name:
        return None, None
    parts = full_name.strip().split()
    if len(parts) == 1:
        return None, _normalise_name(parts[0])
    return _normalise_forename(parts[0]), _normalise_name(" ".join(parts[1:]))


# ---------------------------------------------------------------------------
# Relationship feature lookups (conclusion layer)
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

        # Estimate birth year from census date and age.
        # Clamped to 1750–1926: transcription errors in age (e.g. 999) would
        # otherwise produce implausible birth years that corrupt Splink scoring.
        birth_year_est = None
        if row["age"] is not None and row["census_date"]:
            m = re.match(r"^(\d{4})", row["census_date"])
            if m:
                raw_by = int(m.group(1)) - int(row["age"])
                if 1750 <= raw_by <= 1926:
                    birth_year_est = raw_by

        # Normalise raw place string as fallback for unresolved places.
        place_raw = None
        if row["place_raw"]:
            place_raw = _normalise_name(row["place_raw"])

        # place_id: keep as Python int or None. Pandas converts int columns
        # with None values to float64 (NaN), which can cause DuckDB to treat
        # place_id as DOUBLE. We handle this explicitly below with Int64.
        place_id = int(row["place_id"]) if row["place_id"] is not None else None

        person_id = row["person_id"]
        child_names   = _child_names(conn, person_id)
        sibling_names = _sibling_names(conn, person_id)

        records.append({
            "unique_id":         person_id,   # Splink required PK
            "person_id":         person_id,
            "source_id":         row["source_id"],
            "surname_norm":      surname,
            "forename_norm":     forename,
            "birth_year_est":    birth_year_est,
            "place_id":          place_id,
            "place_raw":         place_raw,
            # Spouse: scalar string for JaroWinkler comparison.
            # Null when no couple relationship concluded.
            "spouse_name_norm":  _spouse_name(conn, person_id),
            # Children and siblings: pipe-joined sorted name strings.
            # Empty string when no relationships concluded.
            # Jaccard overlap is computed inside Splink via SQL array functions
            # (see CustomComparison in linkage.py). Empty string → NullLevel fires.
            "child_names":       "|".join(sorted(child_names)),
            "sibling_names":     "|".join(sorted(sibling_names)),
        })

    if not records:
        return []

    df = pd.DataFrame(records)

    # Cast place_id to pandas Int64 (nullable integer) to prevent pandas from
    # coercing the column to float64 when NULLs are present. float64 place_ids
    # (5.0 instead of 5) can confuse DuckDB's blocking and ExactMatch logic.
    df["place_id"] = df["place_id"].astype("Int64")

    # spouse_name_norm: string or None — pandas object dtype is correct.
    # child_names / sibling_names: pipe-joined strings; empty string means
    # no concluded relationships. Replace empty strings with None so that
    # Splink's NullLevel fires rather than treating "" as a value to compare.
    df["child_names"]   = df["child_names"].replace("", None)
    df["sibling_names"] = df["sibling_names"].replace("", None)

    # One row per person_id per source. If a person somehow has two records
    # from the same source (R42 would flag this), take the first.
    df = df.drop_duplicates(subset=["unique_id", "source_id"], keep="first")

    # Split into one DataFrame per census source so Splink's link_and_dedupe
    # can distinguish within-source deduplication from cross-source linkage.
    # Sources present in the data may be a subset of {3, 4, 5}.
    result: list[pd.DataFrame] = []
    for source_id in sorted(df["source_id"].unique()):
        source_df = df[df["source_id"] == source_id].reset_index(drop=True)
        result.append(source_df)

    return result