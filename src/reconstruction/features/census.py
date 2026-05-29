"""
GRA — Census Feature Extractor
Builds a flat feature DataFrame for Splink from census Person conclusions.

One row per Person per census source. Features extracted from:
  - person_name (concluded names)
  - person_record → recorded_person (name_as_recorded, age, role)
  - person_record → recorded_event (date, place_as_recorded)
  - person_record → record → source (source_id)
  - place_record (resolved place_id)

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
    3. Expand standard abbreviations
    4. Normalise whitespace
    """
    if not raw:
        return None
    s = raw.lower().translate(_FADA)
    s = re.sub(r"['\-]", " ", s)          # strip apostrophes and hyphens
    s = " ".join(s.split())               # collapse whitespace
    # Expand abbreviations (whole-word match)
    tokens = s.split()
    tokens = [_FORENAME_ABBREV.get(t, t) for t in tokens]
    return " ".join(tokens)


def _split_name(full_name: str | None) -> tuple[str | None, str | None]:
    """
    Split a 'Firstname Surname' string into (forename, surname).
    Handles single-token names (surname only) gracefully.
    NAI census format is always 'firstname surname' from the ingest mapping.
    """
    if not full_name:
        return None, None
    parts = full_name.strip().split()
    if len(parts) == 1:
        return None, _normalise_name(parts[0])
    return _normalise_name(parts[0]), _normalise_name(" ".join(parts[1:]))


# Replace from line 77 to end

def build_census_features(conn: sqlite3.Connection) -> list[pd.DataFrame]:
    """
    Build feature DataFrames for all census Person conclusions, one DataFrame
    per census source.  Splink's link_and_dedupe mode requires a list of
    DataFrames so it can produce both within-source and cross-source candidate
    pairs.

    Each DataFrame has one row per person_id and the following columns:

        unique_id       int     — Splink required PK; equals person_id
        person_id       int     — GRA Person primary key
        source_id       int     — census source (3=1901, 4=1911, 5=1926)
        surname_norm    str     — normalised surname
        forename_norm   str     — normalised forename
        birth_year_est  int     — estimated birth year (census year - age)
        place_id        int     — resolved Place conclusion id (blocking anchor)
        place_raw       str     — normalised place string (fallback if unresolved)

    Returns an empty list if no census Person conclusions exist.
    """
    query = """
        SELECT
            p.person_id,
            s.source_id,
            -- Prefer concluded person_name, fall back to name_as_recorded
            COALESCE(pn.value, rp.name_as_recorded)     AS full_name,
            rp.age                                       AS age,
            re.date                                      AS census_date,
            re.place_as_recorded                         AS place_raw,
            pr2.place_id                                 AS place_id
        FROM person p
        -- Link to census records via person_record
        JOIN person_record pr ON pr.person_id = p.person_id
        JOIN record r         ON r.record_id  = pr.record_id
        JOIN source s         ON s.source_id  = r.source_id
                              AND s.source_id IN (3, 4, 5)
        -- RecordedPerson for this record (take the head/principal where possible)
        JOIN recorded_person rp ON rp.record_id = r.record_id
            AND rp.recorded_person_id = (
                SELECT rp2.recorded_person_id
                FROM recorded_person rp2
                WHERE rp2.record_id = r.record_id
                ORDER BY
                    CASE rp2.role
                        WHEN 'head'      THEN 0
                        WHEN 'spouse'    THEN 1
                        WHEN 'principal' THEN 2
                        ELSE 3
                    END,
                    rp2.recorded_person_id
                LIMIT 1
            )
        -- RecordedEvent for census date and place
        JOIN recorded_event re ON re.record_id = r.record_id
        -- Concluded person_name (birth_name preferred)
        LEFT JOIN person_name pn ON pn.person_id = p.person_id
            AND pn.type = 'birth_name'
            AND pn.person_name_id = (
                SELECT MIN(pn2.person_name_id)
                FROM person_name pn2
                WHERE pn2.person_id = p.person_id AND pn2.type = 'birth_name'
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

        # Estimate birth year from census date and age
        birth_year_est = None
        if row["age"] is not None and row["census_date"]:
            m = re.match(r"^(\d{4})", row["census_date"])
            if m:
                birth_year_est = int(m.group(1)) - int(row["age"])

        # Normalise raw place string as fallback
        place_raw = None
        if row["place_raw"]:
            place_raw = _normalise_name(row["place_raw"])

        records.append({
            "unique_id":      row["person_id"],   # Splink required PK
            "person_id":      row["person_id"],
            "source_id":      row["source_id"],
            "surname_norm":   surname,
            "forename_norm":  forename,
            "birth_year_est": birth_year_est,
            "place_id":       row["place_id"],
            "place_raw":      place_raw,
        })

    if not records:
        return []

    df = pd.DataFrame(records)

    # One row per person_id — take the first source record per person if there
    # are duplicates within a source (R42 will flag these; handle gracefully here)
    df = df.drop_duplicates(subset=["unique_id"], keep="first")

    # Split into one DataFrame per census source so Splink's link_and_dedupe
    # can distinguish within-source deduplication from cross-source linkage.
    # Sources present in the data may be a subset of {3, 4, 5}.
    result: list[pd.DataFrame] = []
    for source_id in sorted(df["source_id"].unique()):
        source_df = df[df["source_id"] == source_id].reset_index(drop=True)
        result.append(source_df)

    return result