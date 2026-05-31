"""
Tests for place authority (flat schema), fetch_places CSV loading,
seed_places, place_resolution, and hierarchy queries.
"""

import csv
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.db import open_db, init_db
from src.fetch_places import (
    PlaceRow, load_from_csv, write_to_db, write_to_csv,
    VALID_PLACE_TYPES, _API_TYPE_MAP,
)
from src.seed_places import seed_places
from src.reconstruction.place_resolution import (
    run_place_resolution, _normalise,
    EXACT_SCORE, FUZZY_SCORE, JW_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_db(tmp: str) -> sqlite3.Connection:
    return init_db(os.path.join(tmp, "test.db"))


def write_csv(path: str, rows: list[dict], fieldnames: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


FIELDNAMES = [
    "place_id", "logainm_id", "name_en", "place_type",
    "parent_name", "parent_id", "parent_type",
    "ded_name", "ded_id", "county_name", "county_id",
    "barony_name", "barony_id", "civil_parish_name", "civil_parish_id",
    "latitude", "longitude", "logainm_url", "notes",
]

TULLYNAUGHT_ROW = {
    "place_id": "1", "logainm_id": "111482", "name_en": "Tullynaught",
    "place_type": "ded", "parent_name": "Tullynaught", "parent_id": "111482",
    "parent_type": "ded", "ded_name": "", "ded_id": "",
    "county_name": "Donegal", "county_id": "100013",
    "barony_name": "", "barony_id": "", "civil_parish_name": "", "civil_parish_id": "",
    "latitude": "54.6455", "longitude": "-8.0435",
    "logainm_url": "https://www.logainm.ie/en/111482", "notes": "",
}

STRANESS_ROW = {
    "place_id": "2", "logainm_id": "14300", "name_en": "Straness",
    "place_type": "townland", "parent_name": "Tullynaught", "parent_id": "111482",
    "parent_type": "ded", "ded_name": "Tullynaught", "ded_id": "111482",
    "county_name": "Donegal", "county_id": "100013",
    "barony_name": "Tirhugh", "barony_id": "52",
    "civil_parish_name": "Drumhome", "civil_parish_id": "785",
    "latitude": "54.6638", "longitude": "-7.9794",
    "logainm_url": "https://www.logainm.ie/en/14300", "notes": "",
}

KILBARRON_ROW = {
    "place_id": "3", "logainm_id": "", "name_en": "Kilbarron",
    "place_type": "church_parish", "parent_name": "", "parent_id": "",
    "parent_type": "", "ded_name": "", "ded_id": "",
    "county_name": "Donegal", "county_id": "100013",
    "barony_name": "", "barony_id": "", "civil_parish_name": "", "civil_parish_id": "",
    "latitude": "", "longitude": "",
    "logainm_url": "", "notes": "Not in logainm; manually added",
}

DRUMHOME_ROW = {
    "place_id": "4", "logainm_id": "785", "name_en": "Drumhome",
    "place_type": "civil_parish", "parent_name": "", "parent_id": "",
    "parent_type": "", "ded_name": "", "ded_id": "",
    "county_name": "Donegal", "county_id": "100013",
    "barony_name": "Tirhugh", "barony_id": "52",
    "civil_parish_name": "", "civil_parish_id": "",
    "latitude": "", "longitude": "",
    "logainm_url": "https://www.logainm.ie/en/785", "notes": "",
}


def _write_standard_csv(tmp: str, rows: list[dict] | None = None) -> str:
    rows = rows or [TULLYNAUGHT_ROW, STRANESS_ROW, KILBARRON_ROW]
    path = os.path.join(tmp, "places.csv")
    write_csv(path, rows, FIELDNAMES)
    return path


def _seed_standard(conn, tmp: str) -> dict:
    path = _write_standard_csv(tmp)
    return seed_places(conn, path)


def insert_record_with_place(conn, record_id: int, place_str: str) -> None:
    conn.execute(
        "INSERT INTO record (record_id, source_id, raw_text) VALUES (?, 3, ?)",
        (record_id, f"raw,{place_str}"),
    )
    conn.execute(
        "INSERT INTO recorded_event (recorded_event_id, record_id, type, place_as_recorded) "
        "VALUES (?, ?, 'census', ?)",
        (record_id, record_id, place_str),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def test_normalise_basic():
    assert _normalise("Straness") == "straness"

def test_normalise_strips_hyphens():
    assert _normalise("Tully-naught") == "tully naught"

def test_normalise_strips_suffix():
    result = _normalise("Straness Townland")
    assert "townland" not in result
    assert "straness" in result

def test_normalise_collapses_whitespace():
    assert _normalise("  Stra  ness  ") == "stra  ness".replace("  ", " ")


# ---------------------------------------------------------------------------
# API type mapping
# ---------------------------------------------------------------------------

def test_api_type_map_electoral_division():
    assert _API_TYPE_MAP["electoral division"] == "ded"

def test_api_type_map_townland():
    assert _API_TYPE_MAP["townland"] == "townland"

def test_api_type_map_civil_parish():
    assert _API_TYPE_MAP["civil parish"] == "civil_parish"


# ---------------------------------------------------------------------------
# load_from_csv validation
# ---------------------------------------------------------------------------

def test_load_csv_rejects_missing_name_en(tmp_path):
    rows = [{**TULLYNAUGHT_ROW, "name_en": ""}]
    path = os.path.join(tmp_path, "p.csv")
    write_csv(path, rows, FIELDNAMES)
    try:
        load_from_csv(path)
        assert False, "Should have raised"
    except ValueError as e:
        assert "name_en" in str(e)

def test_load_csv_rejects_invalid_place_type(tmp_path):
    rows = [{**TULLYNAUGHT_ROW, "place_type": "ocean"}]
    path = os.path.join(tmp_path, "p.csv")
    write_csv(path, rows, FIELDNAMES)
    try:
        load_from_csv(path)
        assert False, "Should have raised"
    except ValueError as e:
        assert "place_type" in str(e)

def test_load_csv_maps_api_type_strings(tmp_path):
    rows = [{**TULLYNAUGHT_ROW, "place_type": "electoral division"}]
    path = os.path.join(tmp_path, "p.csv")
    write_csv(path, rows, FIELDNAMES)
    loaded = load_from_csv(path)
    assert loaded[0].place_type == "ded"

def test_load_csv_null_logainm_for_manual_entry(tmp_path):
    path = _write_standard_csv(tmp_path, [KILBARRON_ROW])
    loaded = load_from_csv(path)
    assert loaded[0].logainm_id is None

def test_load_csv_parses_hierarchy_columns(tmp_path):
    path = _write_standard_csv(tmp_path, [STRANESS_ROW])
    loaded = load_from_csv(path)
    row = loaded[0]
    assert row.barony_name == "Tirhugh"
    assert row.barony_id == 52
    assert row.civil_parish_name == "Drumhome"
    assert row.civil_parish_id == 785
    assert row.ded_name == "Tullynaught"
    assert row.ded_id == 111482

def test_load_csv_parses_coordinates(tmp_path):
    path = _write_standard_csv(tmp_path, [STRANESS_ROW])
    loaded = load_from_csv(path)
    assert abs(loaded[0].latitude - 54.6638) < 0.001
    assert abs(loaded[0].longitude - (-7.9794)) < 0.001

def test_load_csv_blank_optional_columns_become_none(tmp_path):
    path = _write_standard_csv(tmp_path, [TULLYNAUGHT_ROW])
    loaded = load_from_csv(path)
    assert loaded[0].barony_id is None
    assert loaded[0].civil_parish_id is None
    assert loaded[0].latitude is not None   # has coords


# ---------------------------------------------------------------------------
# write_to_db / seed_places
# ---------------------------------------------------------------------------

def test_seed_places_inserts_rows(tmp_path):
    conn = make_db(tmp_path)
    result = _seed_standard(conn, tmp_path)
    assert result["ok"], result.get("errors")
    assert result["inserted"] == 3
    count = conn.execute("SELECT COUNT(*) FROM place_authority").fetchone()[0]
    assert count == 3

def test_seed_places_idempotent(tmp_path):
    conn = make_db(tmp_path)
    _seed_standard(conn, tmp_path)
    r2 = _seed_standard(conn, tmp_path)
    assert r2["inserted"] == 0
    assert r2["skipped"] == 3   # all 3 rows skipped: 2 by logainm_id, 1 by (name_en, place_type)
    count = conn.execute("SELECT COUNT(*) FROM place_authority").fetchone()[0]
    assert count == 3

def test_seed_places_null_logainm_stored(tmp_path):
    conn = make_db(tmp_path)
    _seed_standard(conn, tmp_path)
    row = conn.execute(
        "SELECT logainm_id FROM place_authority WHERE name_en='Kilbarron'"
    ).fetchone()
    assert row is not None
    assert row["logainm_id"] is None

def test_seed_places_hierarchy_stored(tmp_path):
    conn = make_db(tmp_path)
    path = _write_standard_csv(tmp_path, [STRANESS_ROW])
    seed_places(conn, path)
    row = conn.execute(
        "SELECT * FROM place_authority WHERE logainm_id=14300"
    ).fetchone()
    assert row["barony_name"] == "Tirhugh"
    assert row["barony_id"] == 52
    assert row["civil_parish_name"] == "Drumhome"
    assert row["civil_parish_id"] == 785
    assert row["county_name"] == "Donegal"
    assert row["county_id"] == 100013

def test_seed_places_coordinates_stored(tmp_path):
    conn = make_db(tmp_path)
    path = _write_standard_csv(tmp_path, [STRANESS_ROW])
    seed_places(conn, path)
    row = conn.execute(
        "SELECT latitude, longitude FROM place_authority WHERE logainm_id=14300"
    ).fetchone()
    assert abs(row["latitude"] - 54.6638) < 0.001
    assert abs(row["longitude"] - (-7.9794)) < 0.001


# ---------------------------------------------------------------------------
# CSV round-trip (fetch_places write_to_csv → load_from_csv)
# ---------------------------------------------------------------------------

def test_csv_roundtrip(tmp_path):
    rows = [
        PlaceRow(
            place_id=1, logainm_id=111482, name_en="Tullynaught",
            place_type="ded", parent_name="Tullynaught", parent_id=111482,
            parent_type="ded", ded_name="", ded_id=None,
            county_name="Donegal", county_id=100013,
            barony_name="", barony_id=None,
            civil_parish_name="", civil_parish_id=None,
            latitude=54.6455, longitude=-8.0435,
            logainm_url="https://www.logainm.ie/en/111482",
        ),
        PlaceRow(
            place_id=2, logainm_id=14300, name_en="Straness",
            place_type="townland", parent_name="Tullynaught", parent_id=111482,
            parent_type="ded", ded_name="Tullynaught", ded_id=111482,
            county_name="Donegal", county_id=100013,
            barony_name="Tirhugh", barony_id=52,
            civil_parish_name="Drumhome", civil_parish_id=785,
            latitude=54.6638, longitude=-7.9794,
            logainm_url="https://www.logainm.ie/en/14300",
        ),
    ]
    csv_path = os.path.join(tmp_path, "out.csv")
    write_to_csv(rows, csv_path)
    reloaded = load_from_csv(csv_path)
    assert len(reloaded) == 2
    assert reloaded[1].name_en == "Straness"
    assert reloaded[1].barony_id == 52
    assert reloaded[1].civil_parish_id == 785


# ---------------------------------------------------------------------------
# Place resolution
# ---------------------------------------------------------------------------

def _seed_for_resolution(conn, tmp: str) -> None:
    rows = [TULLYNAUGHT_ROW, STRANESS_ROW, KILBARRON_ROW, DRUMHOME_ROW]
    path = _write_standard_csv(tmp, rows)
    seed_places(conn, path)


def test_resolution_exact_match(tmp_path):
    conn = make_db(tmp_path)
    _seed_for_resolution(conn, tmp_path)
    insert_record_with_place(conn, 1, "Straness")
    result = run_place_resolution(conn)
    assert result.records_linked == 1
    assert len(result.unresolved) == 0
    row = conn.execute("SELECT score FROM place_record WHERE record_id=1").fetchone()
    assert row["score"] == EXACT_SCORE

def test_resolution_fuzzy_variant(tmp_path):
    """'Straniss' should fuzzy-match Straness."""
    conn = make_db(tmp_path)
    _seed_for_resolution(conn, tmp_path)
    insert_record_with_place(conn, 1, "Straniss")
    result = run_place_resolution(conn)
    assert result.records_linked == 1
    assert len(result.unresolved) == 0
    row = conn.execute("SELECT score FROM place_record WHERE record_id=1").fetchone()
    assert row["score"] == FUZZY_SCORE

def test_resolution_unresolved_flagged(tmp_path):
    conn = make_db(tmp_path)
    _seed_for_resolution(conn, tmp_path)
    insert_record_with_place(conn, 1, "Ballymacnab")
    result = run_place_resolution(conn)
    assert result.records_linked == 0
    assert len(result.unresolved) == 1
    assert result.unresolved[0].place_as_recorded == "Ballymacnab"

def test_resolution_multiple_variants_same_authority(tmp_path):
    conn = make_db(tmp_path)
    _seed_for_resolution(conn, tmp_path)
    for rid, spelling in enumerate(["Straness", "Straniss", "Strandness"], start=1):
        insert_record_with_place(conn, rid, spelling)
    result = run_place_resolution(conn)
    assert result.records_linked == 3
    place_ids = {
        row[0] for row in
        conn.execute("SELECT DISTINCT place_id FROM place_record").fetchall()
    }
    assert len(place_ids) == 1

def test_resolution_idempotent(tmp_path):
    conn = make_db(tmp_path)
    _seed_for_resolution(conn, tmp_path)
    insert_record_with_place(conn, 1, "Straness")
    run_place_resolution(conn)
    run_place_resolution(conn)
    count = conn.execute("SELECT COUNT(*) FROM place_record").fetchone()[0]
    assert count == 1

def test_resolution_empty_authority_graceful(tmp_path):
    conn = make_db(tmp_path)
    insert_record_with_place(conn, 1, "Straness")
    result = run_place_resolution(conn)
    assert result.records_linked == 0

def test_resolution_blank_place_counted(tmp_path):
    conn = make_db(tmp_path)
    _seed_for_resolution(conn, tmp_path)
    conn.execute("INSERT INTO record (record_id, source_id, raw_text) VALUES (1, 3, 'x')")
    conn.execute(
        "INSERT INTO recorded_event (recorded_event_id, record_id, type, place_as_recorded) "
        "VALUES (1, 1, 'census', '')"
    )
    conn.commit()
    result = run_place_resolution(conn)
    assert result.skipped_blank >= 1


# ---------------------------------------------------------------------------
# Hierarchy queries (flat schema — WHERE clauses, no joins)
# ---------------------------------------------------------------------------

def test_hierarchy_all_townlands_in_civil_parish(tmp_path):
    """All townlands in Drumhome civil parish (civil_parish_id=785)."""
    conn = make_db(tmp_path)
    rows_data = [TULLYNAUGHT_ROW, STRANESS_ROW, KILBARRON_ROW, DRUMHOME_ROW]
    # Add a second townland in Drumhome for a richer test
    extra = {**STRANESS_ROW, "place_id": "5", "logainm_id": "14301",
             "name_en": "Tullyearl", "civil_parish_id": "785"}
    rows_data.append(extra)
    path = _write_standard_csv(tmp_path, rows_data)
    seed_places(conn, path)

    townlands = conn.execute(
        "SELECT name_en FROM place_authority "
        "WHERE civil_parish_id = 785 AND place_type = 'townland' "
        "ORDER BY name_en"
    ).fetchall()
    names = [r["name_en"] for r in townlands]
    assert "Straness" in names
    assert "Tullyearl" in names

def test_hierarchy_all_records_in_ded(tmp_path):
    """Records in Tullynaught DED via place_record + place_authority."""
    conn = make_db(tmp_path)
    rows_data = [TULLYNAUGHT_ROW, STRANESS_ROW]
    path = _write_standard_csv(tmp_path, rows_data)
    seed_places(conn, path)

    insert_record_with_place(conn, 1, "Straness")
    insert_record_with_place(conn, 2, "Straness")
    run_place_resolution(conn)

    records_in_ded = conn.execute(
        """
        SELECT r.record_id
        FROM record r
        JOIN place_record pr ON pr.record_id = r.record_id
        JOIN place_authority pa ON pa.place_id = pr.place_id
        WHERE pa.ded_id = 111482
        """
    ).fetchall()
    assert len(records_in_ded) == 2

def test_hierarchy_townlands_missing_barony_stored_as_null(tmp_path):
    """Townlands without barony data in logainm are stored with NULL barony_id."""
    conn = make_db(tmp_path)
    no_barony = {**TULLYNAUGHT_ROW, "place_id": "1", "logainm_id": "14271",
                 "name_en": "Aghlem", "place_type": "townland",
                 "barony_name": "", "barony_id": "", "civil_parish_name": "", "civil_parish_id": ""}
    path = _write_standard_csv(tmp_path, [no_barony])
    seed_places(conn, path)
    row = conn.execute("SELECT barony_id FROM place_authority WHERE logainm_id=14271").fetchone()
    assert row["barony_id"] is None

def test_hierarchy_county_query(tmp_path):
    """All place_authority rows for Donegal."""
    conn = make_db(tmp_path)
    rows_data = [TULLYNAUGHT_ROW, STRANESS_ROW, KILBARRON_ROW]
    path = _write_standard_csv(tmp_path, rows_data)
    seed_places(conn, path)
    donegal = conn.execute(
        "SELECT COUNT(*) FROM place_authority WHERE county_id = 100013"
    ).fetchone()[0]
    assert donegal == 3

def test_real_csv_loads_correctly(tmp_path):
    """Load the actual Tullynaught CSV produced by getplaces.py."""
    real_csv = "/mnt/user-data/uploads/Tullynaught_electoral_division_townlands.csv"
    if not os.path.exists(real_csv):
        print("  SKIP — real CSV not available")
        return
    rows = load_from_csv(real_csv)
    assert len(rows) == 34   # 1 DED + 33 townlands
    # Check DED row
    ded = next(r for r in rows if r.place_type == "ded")
    assert ded.logainm_id == 111482
    assert ded.name_en == "Tullynaught"
    assert ded.county_name == "Donegal"
    # Check a townland with full hierarchy
    straness = next(r for r in rows if r.logainm_id == 14300)
    assert straness.barony_name == "Tirhugh"
    assert straness.civil_parish_name == "Drumhome"
    assert straness.civil_parish_id == 785
    # Check townlands missing barony
    aghlem = next(r for r in rows if r.logainm_id == 14271)
    assert aghlem.barony_id is None

def test_real_csv_db_insert(tmp_path):
    """Insert the real Tullynaught CSV into a fresh DB."""
    real_csv = "/mnt/user-data/uploads/Tullynaught_electoral_division_townlands.csv"
    if not os.path.exists(real_csv):
        print("  SKIP — real CSV not available")
        return
    conn = make_db(tmp_path)
    result = seed_places(conn, real_csv)
    assert result["ok"], result.get("errors")
    assert result["inserted"] == 34
    # Verify hierarchy indexes work
    drumhome_townlands = conn.execute(
        "SELECT COUNT(*) FROM place_authority WHERE civil_parish_id=785 AND place_type='townland'"
    ).fetchone()[0]
    assert drumhome_townlands == 16   # 16 townlands have Drumhome as civil parish


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    no_arg = [
        test_normalise_basic, test_normalise_strips_hyphens,
        test_normalise_strips_suffix, test_normalise_collapses_whitespace,
        test_api_type_map_electoral_division, test_api_type_map_townland,
        test_api_type_map_civil_parish,
    ]
    with_arg = [
        test_load_csv_rejects_missing_name_en,
        test_load_csv_rejects_invalid_place_type,
        test_load_csv_maps_api_type_strings,
        test_load_csv_null_logainm_for_manual_entry,
        test_load_csv_parses_hierarchy_columns,
        test_load_csv_parses_coordinates,
        test_load_csv_blank_optional_columns_become_none,
        test_seed_places_inserts_rows,
        test_seed_places_idempotent,
        test_seed_places_null_logainm_stored,
        test_seed_places_hierarchy_stored,
        test_seed_places_coordinates_stored,
        test_csv_roundtrip,
        test_resolution_exact_match,
        test_resolution_fuzzy_variant,
        test_resolution_unresolved_flagged,
        test_resolution_multiple_variants_same_authority,
        test_resolution_idempotent,
        test_resolution_empty_authority_graceful,
        test_resolution_blank_place_counted,
        test_hierarchy_all_townlands_in_civil_parish,
        test_hierarchy_all_records_in_ded,
        test_hierarchy_townlands_missing_barony_stored_as_null,
        test_hierarchy_county_query,
        test_real_csv_loads_correctly,
        test_real_csv_db_insert,
    ]

    passed = failed = 0

    for fn in no_arg:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {fn.__name__}: {e}")
            failed += 1

    import traceback
    for fn in with_arg:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                fn(tmp)
                print(f"  PASS  {fn.__name__}")
                passed += 1
            except Exception as e:
                print(f"  FAIL  {fn.__name__}: {e}")
                traceback.print_exc()
                failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
