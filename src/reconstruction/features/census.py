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
            pn.value                                     AS full_name,
            rp.age                                       AS age,
            re.date                                      AS census_date,
            re.place_as_recorded                         AS place_raw,
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
        -- RecordedEvent for census date and place
        JOIN recorded_event re ON re.record_id = r.record_id
        -- Match THIS person's RecordedPerson row by name within the household
        -- record. The previous implementation always took the household head's
        -- row, giving every household member the head's age and name. The
        -- correct approach matches name_as_recorded against the person's
        -- concluded name so each person gets their own features.
        --
        -- Where two people in the same household share a name (rare), LIMIT 1
        -- on recorded_person_id picks the first occurrence — acceptable for
        -- Splink feature purposes.
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

        records.append({
            "unique_id":      row["person_id"],   # Splink required PK
            "person_id":      row["person_id"],
            "source_id":      row["source_id"],
            "surname_norm":   surname,
            "forename_norm":  forename,
            "birth_year_est": birth_year_est,
            "place_id":       place_id,
            "place_raw":      place_raw,
        })

    if not records:
        return []

    df = pd.DataFrame(records)

    # Cast place_id to pandas Int64 (nullable integer) to prevent pandas from
    # coercing the column to float64 when NULLs are present. float64 place_ids
    # (5.0 instead of 5) can confuse DuckDB's blocking and ExactMatch logic.
    df["place_id"] = df["place_id"].astype("Int64")

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