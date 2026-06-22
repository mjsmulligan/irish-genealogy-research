"""
GRA — Evidence Layer Features: Census Person

Builds one Pandas DataFrame per active census source, suitable for use as
Splink input in run_person_similarity().

Each row represents one RecordedPerson.  Columns:

    unique_id           INTEGER  — recorded_person_id (Splink join key)
    source_id           INTEGER  — census source (3=1901, 4=1911, 5=1926)
    place_id            INTEGER  — resolved place_id from the parent Record, or NULL
    surname_norm        TEXT     — normalised surname (last token of name_as_recorded)
    forename_norm       TEXT     — normalised forenames (all tokens except last)
    name_norm           TEXT     — forename_norm + " " + surname_norm (full name for Splink comparison)
    birth_year_est      INTEGER  — census_year − age (NULL if age is NULL)
    sex_as_recorded     TEXT     — 'm' / 'f' / NULL

Normalisation:
    All name tokens are lowercased and stripped.

Entry point:
    build_census_person_features(conn) -> list[pd.DataFrame]
"""

from __future__ import annotations

import pandas as pd
import psycopg2.extensions

from src.constants import CENSUS_SOURCE_IDS

# Map source_id → approximate census year for birth_year_est calculation.
_SOURCE_YEAR: dict[int, int] = {3: 1901, 4: 1911, 5: 1926}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm(name: str | None) -> str:
    """Lowercase + strip; return '' for None."""
    return (name or "").lower().strip()


def _surname_from(name: str | None) -> str | None:
    """Last whitespace-delimited token of the name string."""
    parts = _norm(name).split()
    return parts[-1] if parts else None


def _forename_from(name: str | None) -> str | None:
    """Everything before the last token."""
    parts = _norm(name).split()
    if len(parts) >= 2:
        return " ".join(parts[:-1])
    return parts[0] if parts else None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_census_person_features(
    conn: psycopg2.extensions.connection,
) -> list[pd.DataFrame]:
    """
    Build one Pandas DataFrame per active census source for Splink
    person-level (RecordedPerson) similarity.

    Returns a list of DataFrames, one per source that has at least one
    RecordedPerson.  Sources with no RecordedPersons are omitted.

    Each DataFrame has Splink-required column 'unique_id' set to
    recorded_person_id.
    """
    result: list[pd.DataFrame] = []

    for source_id in CENSUS_SOURCE_IDS:
        census_year = _SOURCE_YEAR.get(source_id)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    rp.recorded_person_id,
                    rp.name_as_recorded,
                    rp.age,
                    rp.sex_as_recorded,
                    pr.place_id
                FROM recorded_person rp
                JOIN record r ON r.record_id = rp.record_id
                LEFT JOIN place_record pr ON pr.record_id = r.record_id
                WHERE r.source_id = %s
                ORDER BY rp.recorded_person_id
                """,
                (source_id,),
            )
            persons = cur.fetchall()

        if not persons:
            continue

        rows: list[dict] = []
        for p in persons:
            age = p["age"]
            birth_year_est = (census_year - int(age)) if (census_year and age is not None) else None

            surname = _surname_from(p["name_as_recorded"])
            forename = _forename_from(p["name_as_recorded"])
            name_norm = (
                f"{forename} {surname}".strip()
                if forename
                else surname
            ) or None

            rows.append(
                {
                    "unique_id": p["recorded_person_id"],
                    "source_id": source_id,
                    "place_id": p["place_id"],
                    "surname_norm": surname,
                    "forename_norm": forename,
                    "name_norm": name_norm,
                    "birth_year_est": birth_year_est,
                    "sex_as_recorded": _norm(p["sex_as_recorded"]) or None,
                }
            )

        df = pd.DataFrame(rows)
        df["unique_id"] = df["unique_id"].astype(int)
        df["source_id"] = df["source_id"].astype(int)
        result.append(df)

    return result
