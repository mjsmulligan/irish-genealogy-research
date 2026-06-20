"""
GRA — Census Person Feature Extractor (Evidence Layer)

Builds person-level feature DataFrames for Splink from census evidence.

build_census_person_features()
    One row per RecordedPerson per census source (person-level).
    Used by the evidence-layer person similarity step (src/evidence/similarity.py).
    Features drawn exclusively from the evidence layer (recorded_person rows).
    Does NOT require any conclusion layer to exist — operates on raw evidence.

    Person features for cross-census matching:
      name_normalized      — full name, lowercased, fada-stripped
      surname_norm         — surname token only
      forename_norm        — forename token only
      birth_year_est       — derived from age + census year
      sex_as_recorded      — M/F/null
      place_id             — resolved place authority ID (from place_record)
      place_raw            — normalized place_as_recorded string
      record_id            — household Record this person belongs to (for household score lookup)

Called by src/evidence/similarity.py for person-level Splink matching.
"""

from __future__ import annotations

import pandas as pd
import psycopg2.extensions

from src.constants import CENSUS_SOURCE_IDS
from src.pipeline.features.census import (
    _birth_year_est,
    _normalise_name,
    _split_name,
)


def build_census_person_features(
    conn: psycopg2.extensions.connection,
) -> list[pd.DataFrame]:
    """
    Build person-level feature DataFrames for all census RecordedPersons present
    in the database. One DataFrame per census source, ordered by source_id.

    Features are extracted entirely from the evidence layer — recorded_person
    rows, record event fields, and place_record. Does NOT require any conclusion
    layer objects to exist; operates on raw evidence only.

    Used by:
      - src/evidence/similarity.py  (evidence-layer person Splink → RecordedRelationship)

    Splink's link_only mode receives the list of DataFrames and generates
    cross-source person candidate pairs only — never within-source.

    Returns an empty list if no census RecordedPersons exist.

    Row schema (one row per RecordedPerson):
      unique_id            — recorded_person_id (Splink ID)
      source_id            — census source (3=1901, 4=1911, 5=1926)
      record_id            — household Record this person belongs to
      name_normalized      — full name, lowercased, fada-stripped
      surname_norm         — surname token only
      forename_norm        — forename token only
      birth_year_est       — derived from age + census year
      sex_as_recorded      — M/F/null
      place_id             — resolved place authority ID (from place_record)
      place_raw            — normalized place_as_recorded string
      age                  — age as integer
    """
    placeholders = ",".join(["%s"] * len(CENSUS_SOURCE_IDS))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                rp.recorded_person_id,
                r.source_id,
                r.record_id,
                rp.name_as_recorded,
                rp.age,
                rp.sex_as_recorded,
                r.date              AS census_date,
                r.place_as_recorded,
                pr.place_id
            FROM recorded_person rp
            JOIN record r ON r.record_id = rp.record_id
            JOIN source s ON s.source_id = r.source_id
                          AND s.source_id IN ({placeholders})
            LEFT JOIN place_record pr ON pr.record_id = r.record_id
            ORDER BY r.source_id, rp.recorded_person_id
            """,
            CENSUS_SOURCE_IDS,
        )
        rows = cur.fetchall()

    if not rows:
        return []

    rows_out = []
    for row in rows:
        forename_norm, surname_norm = _split_name(row["name_as_recorded"])
        name_normalized = _normalise_name(row["name_as_recorded"])
        birth_year_est = _birth_year_est(row["age"], row["census_date"])
        place_id = int(row["place_id"]) if row["place_id"] is not None else None
        place_raw = _normalise_name(row["place_as_recorded"]) if row["place_as_recorded"] else None

        rows_out.append({
            "unique_id": row["recorded_person_id"],
            "source_id": row["source_id"],
            "record_id": row["record_id"],
            "name_normalized": name_normalized or "",
            "surname_norm": surname_norm or "",
            "forename_norm": forename_norm or "",
            "birth_year_est": birth_year_est,
            "sex_as_recorded": row["sex_as_recorded"],
            "place_id": place_id,
            "place_raw": place_raw or "",
            "age": row["age"],
        })

    if not rows_out:
        return []

    df = pd.DataFrame(rows_out)
    df["place_id"] = df["place_id"].astype("Int64")
    df["birth_year_est"] = df["birth_year_est"].astype("Int64")
    df["age"] = df["age"].astype("Int64")

    for col in ("name_normalized", "surname_norm", "forename_norm", "place_raw", "sex_as_recorded"):
        df[col] = df[col].replace("", None)

    result: list[pd.DataFrame] = []
    for source_id in sorted(df["source_id"].unique()):
        result.append(df[df["source_id"] == source_id].reset_index(drop=True))
    return result
