"""
GRA — Integration Test Suite
tests/test_pipeline.py

End-to-end pipeline tests using Tullynaught fixtures against a real Supabase
connection. Exercises all three layers (foundation, evidence, conclusion) and
asserts on structural invariants.

Requirements:
  - DATABASE_URL set in environment or .env (same Supabase project used for
    normal operation; tests clear and re-seed on every run)
  - place_authority must be seeded before running (tests skip place-dependent
    assertions gracefully if table is empty, but warn loudly)
  - Tullynaught fixtures at tests/tullynaught_{1901,1911,1926}.csv

Usage:
    python -m pytest tests/test_pipeline.py -v

    # Or without pytest:
    python tests/test_pipeline.py

Design:
  - One module-level fixture: ingest all three CSVs then run conclude once.
    All test functions query the resulting state; no test modifies the DB.
  - Tests are grouped by layer/concern using plain functions (pytest-compatible).
  - Counts derived from the fixed Tullynaught fixtures are asserted exactly
    (household counts, person counts, role relationship counts, place links,
    birth year bounds). These must only change if the fixture CSVs change.
  - Splink similarity and conclusion layer counts use floor assertions pending
    a first confirmed clean run, at which point they become exact too. Each
    such assertion carries a TODO comment.
  - Structural invariants (e.g. every Person has ≥1 RecordedPerson) are exact
    and must always hold regardless of parameter changes.
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import psycopg2
import psycopg2.extensions
import psycopg2.extras

# ---------------------------------------------------------------------------
# Path setup — allow running from repo root without install
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

LOG_DIR  = REPO_ROOT / "tests" / "logs"
LOG_FILE = LOG_DIR / f"test_run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.log"

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")

from src.db.db import open_db, init_db, check_version
from src.constants import SOURCE_ID_1901, SOURCE_ID_1911, SOURCE_ID_1926

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES = {
    SOURCE_ID_1901: REPO_ROOT / "tests" / "tullynaught_1901.csv",
    SOURCE_ID_1911: REPO_ROOT / "tests" / "tullynaught_1911.csv",
    SOURCE_ID_1926: REPO_ROOT / "tests" / "tullynaught_1926.csv",
}

# ---------------------------------------------------------------------------
# Exact Tullynaught counts — derived from fixed fixtures, not tunable.
#
# Ingest counts: directly countable from CSVs.
# Role relationships: derived by running role_relationships rules over fixtures.
# Place links: 100% match rate confirmed — all 31 townlands pass JW ≥ 0.88
#   against logainm canonical names (lowest scorer: 'Tullyleague or Tullybrook'
#   → 'Tullyleague' at 0.888). Requires place_authority to be seeded.
# Similarity / conclusion counts: Splink output and conclusion logic are
#   deterministic given fixed data, but sensitive to parameter changes.
#   These use exact values on first confirmed clean run; update them
#   deliberately (with a comment) when algorithm parameters change, not
#   to paper over bugs.
#
# Derivation (update comment if fixtures change):
#   Source 3 (1901): 263 households, 1193 persons
#   Source 4 (1911): 240 households, 1080 persons
#   Source 5 (1926): 212 households,  894 persons
#   Total:           715 households, 3167 persons
#
#   Role relationships by type:
#     couple: 347  parent_child: 2624  sibling: 2952  total: 5923
#
#   Place links: 715 (all households matched — 263 + 240 + 212)
#
#   Birth year plausibility window: 1807–1928
#     (oldest fixture age: 92 in 1901 → born 1809; ±2yr tolerance → floor 1807)
#     (youngest: age 0 in 1926 → born 1926; +2yr ceiling → 1928)
# ---------------------------------------------------------------------------

# Ingest (exact — derived directly from CSV row counts)
EXACT_RECORDS_1901      = 263
EXACT_RECORDS_1911      = 240
EXACT_RECORDS_1926      = 212
EXACT_RECORDS_TOTAL     = 715
EXACT_PERSONS_1901      = 1193
EXACT_PERSONS_1911      = 1080
EXACT_PERSONS_1926      = 894
EXACT_PERSONS_TOTAL     = 3167

# Role relationships (exact — deterministic from role mapping + rules)
EXACT_ROLE_RELS_COUPLE      = 347
EXACT_ROLE_RELS_PARENT_CHILD = 2624
EXACT_ROLE_RELS_SIBLING     = 2952
EXACT_ROLE_RELS_TOTAL       = 5923

# Place links (exact — 100% match rate confirmed for all 33 Tullynaught townlands)
# Croaghnakern and Rooney's Island are uninhabited (mountain/island); they appear
# in place_authority but have no households and therefore no place_record rows.
# 'Drummenny Upper' in fixtures matches logainm canonical 'Drumenny Upper' at JW=0.987.
EXACT_PLACE_LINKS       = 715

# Authoritative townland list for Tullynaught DED (33 townlands, from logainm via townlands.ie)
# logainm is authoritative; minor census spelling variants are expected and handled by JW matching.
# Croaghnakern (mountain, 941 acres) and Rooney's Island are confirmed uninhabited —
# present in place_authority but will never appear in place_record rows.
AUTHORITATIVE_TOWNLANDS = frozenset({
    'Aghlem', 'Ardnagassan', 'Barnesyneilly', 'Copany', 'Croaghnakern',
    'Croaghnameal', 'Cuilly', 'Drumadoney', 'Drumcroagh', 'Drumenny Upper',
    'Druminardagh', 'Drumlask', 'Drummenny Lower', 'Drummenny Middle',
    'Drumnahoul', 'Finnadoos', 'Legacurry', 'Leghawny', 'Loughcuill',
    'Loughkip', 'Meenadreen', 'Moyne', 'Mullans', "Rooney's Island",
    'Rossmore', 'Skreen', 'Straness', 'Tawnagh', 'Tullyearl', 'Tullyleague',
    'Tullyloskan', 'Tullymornin', 'Whitehill',
})
UNINHABITED_TOWNLANDS = frozenset({'Croaghnakern', "Rooney's Island"})

# Birth year bounds (derived from max ages in fixture data + ±2yr tolerance)
BIRTH_YEAR_MIN          = 1807
BIRTH_YEAR_MAX          = 1928

# Similarity and conclusion counts: floors pending first confirmed clean run.
# Replace with exact values after first successful pipeline execution.
FLOOR_RECORD_SIMS       = 50    # TODO: replace with exact after first run
FLOOR_PERSON_SIMS       = 100   # TODO: replace with exact after first run
FLOOR_PERSONS           = 50    # TODO: replace with exact after first run
FLOOR_RELATIONSHIPS     = 30    # TODO: replace with exact after first run
FLOOR_EVENTS            = 100   # TODO: replace with exact after first run

# ---------------------------------------------------------------------------
# Simple test runner (no pytest dependency required)
# ---------------------------------------------------------------------------

_tests: list[tuple[str, Callable]] = []
_results: dict[str, str] = {}
_timings: dict[str, float] = {}    # test name → elapsed seconds
_setup_timings: dict[str, float] = {}  # setup step label → elapsed seconds


def test(fn: Callable) -> Callable:
    """Decorator: register a test function."""
    _tests.append((fn.__name__, fn))
    return fn


# ---------------------------------------------------------------------------
# Logging — writes to stdout and to LOG_FILE simultaneously
# ---------------------------------------------------------------------------

_log_fh = None  # opened in __main__ once LOG_FILE path is known


def _log(line: str = "") -> None:
    """Print to stdout and append to log file."""
    print(line)
    if _log_fh is not None:
        _log_fh.write(line + "\n")
        _log_fh.flush()


def _run_all(conn: psycopg2.extensions.connection) -> bool:
    passed = failed = 0
    for name, fn in _tests:
        t0 = time.perf_counter()
        try:
            fn(conn)
            elapsed = time.perf_counter() - t0
            _results[name] = "PASS"
            _timings[name] = elapsed
            passed += 1
        except AssertionError as e:
            elapsed = time.perf_counter() - t0
            _results[name] = f"FAIL: {e}"
            _timings[name] = elapsed
            failed += 1
        except Exception as e:
            elapsed = time.perf_counter() - t0
            _results[name] = f"ERROR: {e}\n{traceback.format_exc()}"
            _timings[name] = elapsed
            failed += 1

    total_test_time = sum(_timings.values())

    _log()
    _log("=" * 72)
    _log("  GRA INTEGRATION TEST RESULTS")
    _log("=" * 72)
    for name, result in _results.items():
        icon    = "✓" if result == "PASS" else "✗"
        elapsed = _timings.get(name, 0.0)
        _log(f"  {icon}  {name:<55}  {elapsed:>6.2f}s")
        if result != "PASS":
            for line in result.splitlines():
                _log(f"       {line}")
    _log()
    _log(f"  {passed} passed  {failed} failed")
    _log(f"  Total test execution:  {total_test_time:>7.2f}s")
    _log()

    if _setup_timings:
        _log("  SETUP TIMINGS")
        _log("  " + "-" * 50)
        for step, elapsed in _setup_timings.items():
            _log(f"  {step:<40}  {elapsed:>7.2f}s")
        setup_total = sum(_setup_timings.values())
        _log(f"  {'Total setup':<40}  {setup_total:>7.2f}s")
        _log(f"  {'Grand total (setup + tests)':<40}  {setup_total + total_test_time:>7.2f}s")

    _log("=" * 72)
    if _log_fh is not None:
        _log(f"\n  Log written to: {LOG_FILE}")
    return failed == 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _q(conn: psycopg2.extensions.connection, sql: str, params: tuple = ()) -> int:
    """Execute a COUNT(*) query and return the integer result."""
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return list(row.values())[0]


def _rows(conn: psycopg2.extensions.connection, sql: str, params: tuple = ()) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _place_authority_seeded(conn: psycopg2.extensions.connection) -> bool:
    return _q(conn, "SELECT COUNT(*) FROM place_authority") > 0


# ---------------------------------------------------------------------------
# Setup: clear conclusions + evidence, re-ingest, re-conclude
# ---------------------------------------------------------------------------

def setup(conn: psycopg2.extensions.connection) -> None:
    """
    Wipe evidence + conclusion layers, ingest all three Tullynaught CSVs,
    then run the full conclusion pipeline.

    place_authority is preserved (must be seeded externally before running).
    """
    from src.evidence.census import ingest_census
    from src.evidence.role_relationships import assign_role_relationships
    from src.evidence.place_resolution import run_place_resolution
    from src.evidence.similarity import run_record_similarity, run_person_similarity
    from src.conclusion.person_resolution import run_person_resolution
    from src.conclusion.relationship_resolution import run_relationship_resolution
    from src.conclusion.event_resolution import run_event_resolution

    # --- Clear evidence + conclusion layers ---
    clear_tables = [
        "training_labels",
        "relationship_recorded_relationship",
        "person_recorded_person",
        "place_record",
        "event_record",
        "person_event",
        "record_similarity",
        "recorded_relationship",
        "event",
        "relationship",
        "person",
        "person_name",
        "recorded_person",
        "record",
    ]
    _log("\nSetup: clearing evidence + conclusion layers...")
    t0 = time.perf_counter()
    with conn:
        with conn.cursor() as cur:
            for table in clear_tables:
                cur.execute(f"DELETE FROM {table}")
    _setup_timings["clear tables"] = time.perf_counter() - t0
    _log(f"  cleared.  ({_setup_timings['clear tables']:.2f}s)")

    # --- Ingest all three sources ---
    for source_id, fixture_path in FIXTURES.items():
        if not fixture_path.exists():
            raise FileNotFoundError(f"Fixture not found: {fixture_path}")

        _log(f"  ingesting source {source_id} ({fixture_path.name})...")
        t0 = time.perf_counter()
        ingest_result = ingest_census(conn, str(fixture_path), source_id=source_id)

        # Fetch newly ingested record_ids (ingest_census commits its own transaction)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT record_id FROM record WHERE source_id = %s "
                "ORDER BY record_id DESC LIMIT %s",
                (source_id, ingest_result["records_committed"]),
            )
            record_ids = [row["record_id"] for row in cur.fetchall()]

        # Assign role relationships — one transaction per source, matching CLI behaviour
        with conn:
            for rid in record_ids:
                assign_role_relationships(conn, rid)
        elapsed = time.perf_counter() - t0
        _setup_timings[f"ingest + role_rels source {source_id}"] = elapsed
        _log(f"    {ingest_result['records_committed']} records, "
             f"{ingest_result['persons_committed']} persons  ({elapsed:.2f}s)")

    # --- Place resolution (once across all evidence) ---
    _log("  running place resolution...")
    t0 = time.perf_counter()
    run_place_resolution(conn)
    _setup_timings["place resolution"] = time.perf_counter() - t0
    _log(f"    ({_setup_timings['place resolution']:.2f}s)")

    # --- Similarity (once across all evidence) ---
    _log("  running record similarity...")
    t0 = time.perf_counter()
    run_record_similarity(conn)
    _setup_timings["record similarity (Splink)"] = time.perf_counter() - t0
    _log(f"    ({_setup_timings['record similarity (Splink)']:.2f}s)")

    _log("  running person similarity...")
    t0 = time.perf_counter()
    run_person_similarity(conn)
    _setup_timings["person similarity (Splink)"] = time.perf_counter() - t0
    _log(f"    ({_setup_timings['person similarity (Splink)']:.2f}s)")

    # --- Conclusion pipeline ---
    _log("  running person resolution...")
    t0 = time.perf_counter()
    run_person_resolution(conn)
    _setup_timings["person resolution"] = time.perf_counter() - t0
    _log(f"    ({_setup_timings['person resolution']:.2f}s)")

    _log("  running relationship resolution...")
    t0 = time.perf_counter()
    run_relationship_resolution(conn)
    _setup_timings["relationship resolution"] = time.perf_counter() - t0
    _log(f"    ({_setup_timings['relationship resolution']:.2f}s)")

    _log("  running event resolution...")
    t0 = time.perf_counter()
    run_event_resolution(conn)
    _setup_timings["event resolution"] = time.perf_counter() - t0
    _log(f"    ({_setup_timings['event resolution']:.2f}s)")

    _log("Setup complete.\n")


# ---------------------------------------------------------------------------
# FOUNDATION LAYER TESTS
# ---------------------------------------------------------------------------

@test
def test_schema_version(conn):
    """Schema version in gra_meta matches constants.SCHEMA_VERSION."""
    from src.constants import SCHEMA_VERSION
    with conn.cursor() as cur:
        cur.execute("SELECT value FROM gra_meta WHERE key = 'schema_version'")
        row = cur.fetchone()
    assert row is not None, "gra_meta has no schema_version row"
    assert int(row["value"]) == SCHEMA_VERSION, (
        f"Schema version mismatch: DB={row['value']}, code={SCHEMA_VERSION}"
    )


@test
def test_seed_data_repositories(conn):
    """At least 8 repository rows exist (from seed.sql)."""
    count = _q(conn, "SELECT COUNT(*) FROM repository")
    assert count >= 8, f"Expected ≥8 repositories, got {count}"


@test
def test_seed_data_sources(conn):
    """Census sources 3, 4, 5 and place authority source 13 exist."""
    rows = _rows(conn, "SELECT source_id FROM source WHERE source_id IN (3, 4, 5, 13)")
    ids = {r["source_id"] for r in rows}
    assert ids == {3, 4, 5, 13}, f"Missing expected source IDs: {ids}"


@test
def test_place_authority_warning(conn):
    """Warn if place_authority is empty (tests degrade gracefully but researcher should seed)."""
    count = _q(conn, "SELECT COUNT(*) FROM place_authority")
    assert count > 0, (
        "place_authority is empty — seed it with 'python -m src.cli seed-places' before "
        "running integration tests. Place-dependent assertions will be weak."
    )


# ---------------------------------------------------------------------------
# EVIDENCE LAYER TESTS — ingest
# ---------------------------------------------------------------------------

@test
def test_evidence_records_floor(conn):
    """Exactly 715 households ingested across all three sources (263+240+212)."""
    count = _q(conn, "SELECT COUNT(*) FROM record")
    assert count == EXACT_RECORDS_TOTAL, f"Expected {EXACT_RECORDS_TOTAL} records, got {count}"


@test
def test_evidence_records_per_source(conn):
    """Each census source has the exact expected household count."""
    expected = {
        SOURCE_ID_1901: EXACT_RECORDS_1901,
        SOURCE_ID_1911: EXACT_RECORDS_1911,
        SOURCE_ID_1926: EXACT_RECORDS_1926,
    }
    for source_id, expected_count in expected.items():
        count = _q(conn, "SELECT COUNT(*) FROM record WHERE source_id = %s", (source_id,))
        assert count == expected_count, (
            f"Source {source_id}: expected {expected_count} records, got {count}"
        )


@test
def test_evidence_recorded_persons_floor(conn):
    """Exactly 3167 recorded persons ingested across all sources (1193+1080+894)."""
    count = _q(conn, "SELECT COUNT(*) FROM recorded_person")
    assert count == EXACT_PERSONS_TOTAL, (
        f"Expected {EXACT_PERSONS_TOTAL} recorded_persons, got {count}"
    )


@test
def test_evidence_recorded_persons_per_source(conn):
    """Each census source has the exact expected recorded person count."""
    expected = {
        SOURCE_ID_1901: EXACT_PERSONS_1901,
        SOURCE_ID_1911: EXACT_PERSONS_1911,
        SOURCE_ID_1926: EXACT_PERSONS_1926,
    }
    for source_id, expected_count in expected.items():
        count = _q(conn, """
            SELECT COUNT(*) FROM recorded_person rp
            JOIN record r ON r.record_id = rp.record_id
            WHERE r.source_id = %s
        """, (source_id,))
        assert count == expected_count, (
            f"Source {source_id}: expected {expected_count} recorded_persons, got {count}"
        )


@test
def test_evidence_every_record_has_persons(conn):
    """Every record has at least one recorded_person (no orphan household records)."""
    orphans = _q(conn, """
        SELECT COUNT(*) FROM record r
        WHERE NOT EXISTS (
            SELECT 1 FROM recorded_person rp WHERE rp.record_id = r.record_id
        )
    """)
    assert orphans == 0, f"{orphans} records have no recorded_persons"


@test
def test_evidence_recorded_person_has_name(conn):
    """No recorded_person has a NULL or empty name_as_recorded."""
    bad = _q(conn, """
        SELECT COUNT(*) FROM recorded_person
        WHERE name_as_recorded IS NULL OR trim(name_as_recorded) = ''
    """)
    assert bad == 0, f"{bad} recorded_persons have blank/null name_as_recorded"


@test
def test_evidence_recorded_person_age_non_negative(conn):
    """All recorded_person ages are non-negative when present."""
    bad = _q(conn, "SELECT COUNT(*) FROM recorded_person WHERE age IS NOT NULL AND age < 0")
    assert bad == 0, f"{bad} recorded_persons have negative age"


@test
def test_evidence_record_dates_set(conn):
    """All census records have a non-null ISO date (1901-04-01, 1911-04-02, 1926-04-18)."""
    bad = _q(conn, "SELECT COUNT(*) FROM record WHERE date IS NULL")
    assert bad == 0, f"{bad} records have NULL date"


@test
def test_evidence_record_dates_valid_census_years(conn):
    """All census record dates fall in known census years (1901, 1911, 1926)."""
    bad = _q(conn, """
        SELECT COUNT(*) FROM record r
        JOIN source s ON s.source_id = r.source_id AND s.type = 'census'
        WHERE EXTRACT(YEAR FROM r.date::date) NOT IN (1901, 1911, 1926)
    """)
    assert bad == 0, f"{bad} census records have unexpected year in date field"


# ---------------------------------------------------------------------------
# EVIDENCE LAYER TESTS — role relationships
# ---------------------------------------------------------------------------

@test
def test_evidence_role_relationships_floor(conn):
    """Exactly 5923 role-pair relationships assigned (347 couple, 2624 parent_child, 2952 sibling)."""
    count = _q(conn, "SELECT COUNT(*) FROM recorded_relationship WHERE type != 'similarity'")
    assert count == EXACT_ROLE_RELS_TOTAL, (
        f"Expected {EXACT_ROLE_RELS_TOTAL} role relationships, got {count}"
    )


@test
def test_evidence_role_relationships_by_type(conn):
    """Exact role relationship counts by type match fixture-derived values."""
    expected = {
        "couple":       EXACT_ROLE_RELS_COUPLE,
        "parent_child": EXACT_ROLE_RELS_PARENT_CHILD,
        "sibling":      EXACT_ROLE_RELS_SIBLING,
    }
    for rel_type, expected_count in expected.items():
        count = _q(conn,
            "SELECT COUNT(*) FROM recorded_relationship WHERE type = %s",
            (rel_type,),
        )
        assert count == expected_count, (
            f"Type '{rel_type}': expected {expected_count}, got {count}"
        )


@test
def test_evidence_role_relationship_scores_not_null(conn):
    """All role-pair recorded_relationships have a non-null score."""
    bad = _q(conn, """
        SELECT COUNT(*) FROM recorded_relationship
        WHERE type != 'similarity' AND score IS NULL
    """)
    assert bad == 0, f"{bad} role-pair recorded_relationships have NULL score"


@test
def test_evidence_role_relationship_scores_in_range(conn):
    """Role-pair recorded_relationship scores are between 0.0 and 1.0."""
    bad = _q(conn, """
        SELECT COUNT(*) FROM recorded_relationship
        WHERE type != 'similarity'
          AND (score < 0.0 OR score > 1.0)
    """)
    assert bad == 0, f"{bad} role-pair recorded_relationships have out-of-range score"


@test
def test_evidence_role_relationship_types_valid(conn):
    """All role-pair recorded_relationships have a recognised type."""
    valid_types = ("couple", "parent_child", "sibling", "similarity")
    placeholders = ",".join(["%s"] * len(valid_types))
    bad = _q(
        conn,
        f"SELECT COUNT(*) FROM recorded_relationship WHERE type NOT IN ({placeholders})",
        valid_types,
    )
    assert bad == 0, f"{bad} recorded_relationships have invalid type"


# ---------------------------------------------------------------------------
# EVIDENCE LAYER TESTS — place resolution
# ---------------------------------------------------------------------------

@test
def test_evidence_place_links_exact(conn):
    """Exactly 715 place_record links — all households matched (100% match rate confirmed)."""
    if not _place_authority_seeded(conn):
        # Can't assert without place_authority — warn via a soft pass
        return
    count = _q(conn, "SELECT COUNT(*) FROM place_record")
    assert count == EXACT_PLACE_LINKS, (
        f"Expected {EXACT_PLACE_LINKS} place_record links, got {count}"
    )


@test
def test_evidence_place_links_valid_place_ids(conn):
    """All place_record rows reference a valid place_authority.place_id."""
    orphans = _q(conn, """
        SELECT COUNT(*) FROM place_record pr
        WHERE NOT EXISTS (
            SELECT 1 FROM place_authority pa WHERE pa.place_id = pr.place_id
        )
    """)
    assert orphans == 0, f"{orphans} place_record rows reference non-existent place_id"


@test
def test_evidence_place_links_valid_record_ids(conn):
    """All place_record rows reference a valid record.record_id."""
    orphans = _q(conn, """
        SELECT COUNT(*) FROM place_record pr
        WHERE NOT EXISTS (
            SELECT 1 FROM record r WHERE r.record_id = pr.record_id
        )
    """)
    assert orphans == 0, f"{orphans} place_record rows reference non-existent record_id"


@test
def test_evidence_place_authority_complete(conn):
    """place_authority contains all 33 authoritative Tullynaught townlands (logainm canonical names)."""
    if not _place_authority_seeded(conn):
        return
    rows = _rows(conn, "SELECT name_en FROM place_authority WHERE place_type = 'townland'")
    seeded = {r["name_en"] for r in rows}
    missing = AUTHORITATIVE_TOWNLANDS - seeded
    assert not missing, (
        f"Missing {len(missing)} authoritative townland(s) from place_authority: "
        f"{sorted(missing)}"
    )


@test
def test_evidence_place_authority_count(conn):
    """place_authority has exactly 34 rows: 1 DED + 33 townlands."""
    if not _place_authority_seeded(conn):
        return
    count = _q(conn, "SELECT COUNT(*) FROM place_authority")
    assert count == 34, (
        f"Expected 34 place_authority rows (1 DED + 33 townlands), got {count}"
    )


@test
def test_evidence_uninhabited_townlands_have_no_place_records(conn):
    """Croaghnakern and Rooney's Island are uninhabited — no place_record rows for them."""
    if not _place_authority_seeded(conn):
        return
    placeholders = ",".join(["%s"] * len(UNINHABITED_TOWNLANDS))
    count = _q(conn, f"""
        SELECT COUNT(*) FROM place_record pr
        JOIN place_authority pa ON pa.place_id = pr.place_id
        WHERE pa.name_en IN ({placeholders})
    """, tuple(UNINHABITED_TOWNLANDS))
    assert count == 0, (
        f"Expected 0 place_record rows for uninhabited townlands, got {count}"
    )


# ---------------------------------------------------------------------------
# EVIDENCE LAYER TESTS — similarity
# ---------------------------------------------------------------------------

@test
def test_evidence_record_similarities_floor(conn):
    """At least FLOOR_RECORD_SIMS cross-census record similarity pairs."""
    count = _q(conn, "SELECT COUNT(*) FROM record_similarity")
    assert count >= FLOOR_RECORD_SIMS, (
        f"Expected ≥{FLOOR_RECORD_SIMS} record_similarity rows, got {count}"
    )


@test
def test_evidence_record_similarities_cross_census(conn):
    """All record_similarity pairs are cross-census (source_id_1 != source_id_2)."""
    same_source = _q(conn, """
        SELECT COUNT(*) FROM record_similarity rs
        JOIN record r1 ON r1.record_id = rs.record_id_1
        JOIN record r2 ON r2.record_id = rs.record_id_2
        WHERE r1.source_id = r2.source_id
    """)
    assert same_source == 0, (
        f"{same_source} record_similarity pairs are within the same source (should be cross-census only)"
    )


@test
def test_evidence_record_similarity_scores_in_range(conn):
    """All record_similarity scores are between 0.0 and 1.0."""
    bad = _q(conn, """
        SELECT COUNT(*) FROM record_similarity
        WHERE score < 0.0 OR score > 1.0
    """)
    assert bad == 0, f"{bad} record_similarity rows have out-of-range score"


@test
def test_evidence_person_similarities_floor(conn):
    """At least FLOOR_PERSON_SIMS person-level similarity pairs in recorded_relationship."""
    count = _q(conn, "SELECT COUNT(*) FROM recorded_relationship WHERE type = 'similarity'")
    assert count >= FLOOR_PERSON_SIMS, (
        f"Expected ≥{FLOOR_PERSON_SIMS} person similarity pairs, got {count}"
    )


@test
def test_evidence_person_similarity_scores_in_range(conn):
    """All person similarity scores are between 0.0 and 1.0."""
    bad = _q(conn, """
        SELECT COUNT(*) FROM recorded_relationship
        WHERE type = 'similarity'
          AND (score < 0.0 OR score > 1.0)
    """)
    assert bad == 0, f"{bad} person similarity rows have out-of-range score"


@test
def test_evidence_person_similarity_no_self_pairs(conn):
    """No person similarity pair links a recorded_person to itself."""
    self_pairs = _q(conn, """
        SELECT COUNT(*) FROM recorded_relationship
        WHERE type = 'similarity'
          AND recorded_person_id_1 = recorded_person_id_2
    """)
    assert self_pairs == 0, f"{self_pairs} person similarity self-pairs found"


@test
def test_evidence_person_similarity_cross_census(conn):
    """All person similarity pairs are cross-census."""
    same_source = _q(conn, """
        SELECT COUNT(*) FROM recorded_relationship rr
        JOIN recorded_person rp1 ON rp1.recorded_person_id = rr.recorded_person_id_1
        JOIN recorded_person rp2 ON rp2.recorded_person_id = rr.recorded_person_id_2
        JOIN record r1 ON r1.record_id = rp1.record_id
        JOIN record r2 ON r2.record_id = rp2.record_id
        WHERE rr.type = 'similarity'
          AND r1.source_id = r2.source_id
    """)
    assert same_source == 0, (
        f"{same_source} person similarity pairs are within the same source"
    )


# ---------------------------------------------------------------------------
# CONCLUSION LAYER TESTS — Person
# ---------------------------------------------------------------------------

@test
def test_conclusion_persons_floor(conn):
    """At least FLOOR_PERSONS Person conclusions created."""
    count = _q(conn, "SELECT COUNT(*) FROM person")
    assert count >= FLOOR_PERSONS, f"Expected ≥{FLOOR_PERSONS} persons, got {count}"


@test
def test_conclusion_every_person_has_recorded_person(conn):
    """Every Person is linked to at least one RecordedPerson (no ghost Persons)."""
    ghosts = _q(conn, """
        SELECT COUNT(*) FROM person p
        WHERE NOT EXISTS (
            SELECT 1 FROM person_recorded_person prp WHERE prp.person_id = p.person_id
        )
    """)
    assert ghosts == 0, f"{ghosts} Persons have no RecordedPerson link"


@test
def test_conclusion_every_person_has_label(conn):
    """Every Person has a non-null, non-empty label."""
    bad = _q(conn, "SELECT COUNT(*) FROM person WHERE label IS NULL OR trim(label) = ''")
    assert bad == 0, f"{bad} Persons have blank/null label"


@test
def test_conclusion_person_gender_valid(conn):
    """All Person gender values are male, female, or NULL."""
    bad = _q(conn, """
        SELECT COUNT(*) FROM person
        WHERE gender IS NOT NULL AND gender NOT IN ('male', 'female')
    """)
    assert bad == 0, f"{bad} Persons have invalid gender value"


@test
def test_conclusion_recorded_person_not_double_linked(conn):
    """No RecordedPerson is linked to more than one Person."""
    double_linked = _q(conn, """
        SELECT COUNT(*) FROM (
            SELECT recorded_person_id
            FROM person_recorded_person
            GROUP BY recorded_person_id
            HAVING COUNT(DISTINCT person_id) > 1
        ) sub
    """)
    assert double_linked == 0, (
        f"{double_linked} RecordedPersons are linked to more than one Person"
    )


# ---------------------------------------------------------------------------
# CONCLUSION LAYER TESTS — Relationship
# ---------------------------------------------------------------------------

@test
def test_conclusion_relationships_floor(conn):
    """At least FLOOR_RELATIONSHIPS Relationship conclusions created."""
    count = _q(conn, "SELECT COUNT(*) FROM relationship")
    assert count >= FLOOR_RELATIONSHIPS, (
        f"Expected ≥{FLOOR_RELATIONSHIPS} relationships, got {count}"
    )


@test
def test_conclusion_relationship_types_valid(conn):
    """All Relationship types are couple, parent_child, or sibling."""
    bad = _q(conn, """
        SELECT COUNT(*) FROM relationship
        WHERE type NOT IN ('couple', 'parent_child', 'sibling')
    """)
    assert bad == 0, f"{bad} Relationships have invalid type"


@test
def test_conclusion_relationship_persons_exist(conn):
    """All Relationships reference valid Person IDs for both endpoints."""
    bad = _q(conn, """
        SELECT COUNT(*) FROM relationship r
        WHERE NOT EXISTS (SELECT 1 FROM person p WHERE p.person_id = r.person_id_1)
           OR NOT EXISTS (SELECT 1 FROM person p WHERE p.person_id = r.person_id_2)
    """)
    assert bad == 0, f"{bad} Relationships reference non-existent Person IDs"


@test
def test_conclusion_no_self_relationships(conn):
    """No Relationship links a Person to itself."""
    self_rels = _q(conn, "SELECT COUNT(*) FROM relationship WHERE person_id_1 = person_id_2")
    assert self_rels == 0, f"{self_rels} self-referencing Relationships found"


@test
def test_conclusion_no_duplicate_relationships(conn):
    """No duplicate Relationships exist for the same Person pair and type."""
    # Relationship is undirected: (A, B, type) == (B, A, type)
    duplicates = _q(conn, """
        SELECT COUNT(*) FROM (
            SELECT
                LEAST(person_id_1, person_id_2)  AS p_lo,
                GREATEST(person_id_1, person_id_2) AS p_hi,
                type,
                COUNT(*) AS n
            FROM relationship
            GROUP BY p_lo, p_hi, type
            HAVING COUNT(*) > 1
        ) sub
    """)
    assert duplicates == 0, f"{duplicates} duplicate Relationship (person-pair, type) groups found"


@test
def test_conclusion_couples_have_two_distinct_persons(conn):
    """All couple Relationships link two distinct Persons."""
    bad = _q(conn, """
        SELECT COUNT(*) FROM relationship
        WHERE type = 'couple' AND person_id_1 = person_id_2
    """)
    assert bad == 0, f"{bad} couple Relationships have identical person IDs"


# ---------------------------------------------------------------------------
# CONCLUSION LAYER TESTS — Event
# ---------------------------------------------------------------------------

@test
def test_conclusion_events_floor(conn):
    """At least FLOOR_EVENTS Event conclusions created."""
    count = _q(conn, "SELECT COUNT(*) FROM event")
    assert count >= FLOOR_EVENTS, f"Expected ≥{FLOOR_EVENTS} events, got {count}"


@test
def test_conclusion_census_events_exist(conn):
    """At least one census Event exists."""
    count = _q(conn, "SELECT COUNT(*) FROM event WHERE type = 'census'")
    assert count >= 1, "No census Events created"


@test
def test_conclusion_birth_events_exist(conn):
    """At least one birth Event exists."""
    count = _q(conn, "SELECT COUNT(*) FROM event WHERE type = 'birth'")
    assert count >= 1, "No birth Events created"


@test
def test_conclusion_event_types_valid(conn):
    """All Event types are in the known vocabulary."""
    valid_types = (
        "birth", "baptism", "marriage", "death", "burial",
        "census", "residence", "emigration",
        "valuation", "tithe", "military_service", "pension", "folklore",
    )
    placeholders = ",".join(["%s"] * len(valid_types))
    bad = _q(conn, f"SELECT COUNT(*) FROM event WHERE type NOT IN ({placeholders})", valid_types)
    assert bad == 0, f"{bad} Events have invalid type"


@test
def test_conclusion_every_event_has_person_link(conn):
    """Every Event is linked to at least one Person via person_event."""
    orphan_events = _q(conn, """
        SELECT COUNT(*) FROM event e
        WHERE NOT EXISTS (
            SELECT 1 FROM person_event pe WHERE pe.event_id = e.event_id
        )
    """)
    assert orphan_events == 0, f"{orphan_events} Events have no person_event link"


@test
def test_conclusion_person_event_persons_exist(conn):
    """All person_event rows reference valid Person IDs."""
    bad = _q(conn, """
        SELECT COUNT(*) FROM person_event pe
        WHERE NOT EXISTS (SELECT 1 FROM person p WHERE p.person_id = pe.person_id)
    """)
    assert bad == 0, f"{bad} person_event rows reference non-existent Person IDs"


@test
def test_conclusion_person_event_events_exist(conn):
    """All person_event rows reference valid Event IDs."""
    bad = _q(conn, """
        SELECT COUNT(*) FROM person_event pe
        WHERE NOT EXISTS (SELECT 1 FROM event e WHERE e.event_id = pe.event_id)
    """)
    assert bad == 0, f"{bad} person_event rows reference non-existent Event IDs"


@test
def test_conclusion_birth_event_dates_calculated(conn):
    """All birth Events from census inference have date_qualifier='calculated'."""
    bad = _q(conn, """
        SELECT COUNT(*) FROM event
        WHERE type = 'birth'
          AND (date_qualifier IS NULL OR date_qualifier != 'calculated')
    """)
    assert bad == 0, (
        f"{bad} birth Events are missing date_qualifier='calculated' "
        "(BMD birth events should use a different ingest path)"
    )


@test
def test_conclusion_birth_event_dates_plausible(conn):
    """All calculated birth Events have a date year within fixture-derived plausible range."""
    bad = _q(conn, """
        SELECT COUNT(*) FROM event
        WHERE type = 'birth'
          AND date_qualifier = 'calculated'
          AND date IS NOT NULL
          AND (
              EXTRACT(YEAR FROM date::date) < %s
              OR EXTRACT(YEAR FROM date::date) > %s
          )
    """, (BIRTH_YEAR_MIN, BIRTH_YEAR_MAX))
    assert bad == 0, (
        f"{bad} birth Events have year outside plausible range "
        f"({BIRTH_YEAR_MIN}–{BIRTH_YEAR_MAX})"
    )


@test
def test_conclusion_one_primary_birth_event_per_person(conn):
    """Every Person has at most one is_primary birth Event."""
    bad = _q(conn, """
        SELECT COUNT(*) FROM (
            SELECT pe.person_id
            FROM person_event pe
            JOIN event e ON e.event_id = pe.event_id
            WHERE e.type = 'birth' AND e.is_primary = 1
            GROUP BY pe.person_id
            HAVING COUNT(*) > 1
        ) sub
    """)
    assert bad == 0, f"{bad} Persons have more than one is_primary birth Event"


@test
def test_conclusion_census_events_all_primary(conn):
    """All census Events are is_primary=1 (each census appearance is a distinct moment)."""
    bad = _q(conn, "SELECT COUNT(*) FROM event WHERE type = 'census' AND is_primary != 1")
    assert bad == 0, f"{bad} census Events have is_primary != 1"


@test
def test_conclusion_marriage_events_have_relationship(conn):
    """All marriage Events reference a Relationship (relationship_id is not NULL)."""
    bad = _q(conn, "SELECT COUNT(*) FROM event WHERE type = 'marriage' AND relationship_id IS NULL")
    assert bad == 0, f"{bad} marriage Events have NULL relationship_id"


@test
def test_conclusion_marriage_relationship_ids_valid(conn):
    """All marriage Event relationship_ids reference existing Relationships."""
    bad = _q(conn, """
        SELECT COUNT(*) FROM event e
        WHERE e.type = 'marriage'
          AND e.relationship_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM relationship r WHERE r.relationship_id = e.relationship_id
          )
    """)
    assert bad == 0, f"{bad} marriage Events reference non-existent relationship_id"


@test
def test_conclusion_event_record_links_valid(conn):
    """All event_record rows reference valid event_id and record_id."""
    bad_event = _q(conn, """
        SELECT COUNT(*) FROM event_record er
        WHERE NOT EXISTS (SELECT 1 FROM event e WHERE e.event_id = er.event_id)
    """)
    bad_record = _q(conn, """
        SELECT COUNT(*) FROM event_record er
        WHERE NOT EXISTS (SELECT 1 FROM record r WHERE r.record_id = er.record_id)
    """)
    assert bad_event == 0, f"{bad_event} event_record rows reference non-existent event_id"
    assert bad_record == 0, f"{bad_record} event_record rows reference non-existent record_id"


# ---------------------------------------------------------------------------
# CROSS-LAYER INVARIANTS
# ---------------------------------------------------------------------------

@test
def test_invariant_person_recorded_person_fk(conn):
    """All person_recorded_person rows have valid person_id and recorded_person_id FKs."""
    bad_person = _q(conn, """
        SELECT COUNT(*) FROM person_recorded_person prp
        WHERE NOT EXISTS (SELECT 1 FROM person p WHERE p.person_id = prp.person_id)
    """)
    bad_rp = _q(conn, """
        SELECT COUNT(*) FROM person_recorded_person prp
        WHERE NOT EXISTS (
            SELECT 1 FROM recorded_person rp WHERE rp.recorded_person_id = prp.recorded_person_id
        )
    """)
    assert bad_person == 0, f"{bad_person} person_recorded_person rows have invalid person_id"
    assert bad_rp == 0, f"{bad_rp} person_recorded_person rows have invalid recorded_person_id"


@test
def test_invariant_recorded_relationship_fk(conn):
    """All recorded_relationship rows reference valid recorded_person IDs."""
    bad_1 = _q(conn, """
        SELECT COUNT(*) FROM recorded_relationship rr
        WHERE NOT EXISTS (
            SELECT 1 FROM recorded_person rp WHERE rp.recorded_person_id = rr.recorded_person_id_1
        )
    """)
    bad_2 = _q(conn, """
        SELECT COUNT(*) FROM recorded_relationship rr
        WHERE NOT EXISTS (
            SELECT 1 FROM recorded_person rp WHERE rp.recorded_person_id = rr.recorded_person_id_2
        )
    """)
    assert bad_1 == 0, f"{bad_1} recorded_relationship rows have invalid recorded_person_id_1"
    assert bad_2 == 0, f"{bad_2} recorded_relationship rows have invalid recorded_person_id_2"


@test
def test_invariant_no_conclusion_points_to_conclusion(conn):
    """
    Evidence-conclusion separation: no RecordedPerson or RecordedRelationship
    references a conclusion-layer ID (Person, Relationship, Event).
    This is a schema-level property but worth asserting explicitly.
    """
    # RecordedPerson has no person_id FK by design — verified by absence of column
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'recorded_person'
              AND column_name IN ('person_id', 'relationship_id', 'event_id')
        """)
        bad_columns = [row["column_name"] for row in cur.fetchall()]
    assert bad_columns == [], (
        f"recorded_person has unexpected conclusion-layer FK columns: {bad_columns}"
    )


# ---------------------------------------------------------------------------
# Entry point (also works with pytest)
# ---------------------------------------------------------------------------

# Module-level connection used by both pytest fixtures and standalone runner
_conn: psycopg2.extensions.connection | None = None


def get_conn() -> psycopg2.extensions.connection:
    global _conn
    if _conn is None:
        _conn = open_db()
        check_version(_conn)
    return _conn


# pytest compatibility
try:
    import pytest

    @pytest.fixture(scope="module")
    def db_conn():
        conn = get_conn()
        setup(conn)
        yield conn
        conn.close()

    # Re-export each test function for pytest discovery with the conn fixture
    # pytest will call these; the standalone runner calls them directly.
    def pytest_generate_tests(metafunc):
        pass

    # Wrap registered tests as pytest functions
    import types
    _module = sys.modules[__name__]
    for _name, _fn in _tests:
        def _make_pytest_fn(fn):
            def _pytest_fn(db_conn):
                fn(db_conn)
            _pytest_fn.__name__ = fn.__name__
            return _pytest_fn
        setattr(_module, f"pytest_{_name}", _make_pytest_fn(_fn))

except ImportError:
    pass  # pytest not installed; standalone runner only


if __name__ == "__main__":
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _log_fh = LOG_FILE.open("w", encoding="utf-8")

    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    _log(f"GRA Integration Test Suite")
    _log(f"Run started: {run_ts}")
    _log(f"Log file:    {LOG_FILE}")
    _log()

    _log("Connecting to database...")
    try:
        conn = get_conn()
    except Exception as e:
        _log(f"ERROR: Could not connect: {e}")
        _log_fh.close()
        sys.exit(1)

    try:
        setup(conn)
    except Exception as e:
        _log(f"ERROR during setup: {e}")
        _log(traceback.format_exc())
        conn.close()
        _log_fh.close()
        sys.exit(1)

    ok = _run_all(conn)
    conn.close()
    _log_fh.close()
    sys.exit(0 if ok else 1)
