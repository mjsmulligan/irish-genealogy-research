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
    pytest tests/test_pipeline.py -v
    pytest tests/test_pipeline.py::test_schema_version  # single test
    pytest -k "evidence" -v                             # by pattern

Design:
  - One module-level fixture: ingest all three CSVs then run conclude once.
    All test functions query the resulting state; no test modifies the DB.
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

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import psycopg2
import psycopg2.extensions
import psycopg2.extras

# ---------------------------------------------------------------------------
# Path setup — allow running from repo root without install
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")

from src.db.db import open_db, init_db, check_version
from src.constants import SOURCE_ID_1901, SOURCE_ID_1911, SOURCE_ID_1926
from src.evidence.place_resolution import _normalise as normalize_place_name

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
    'Croaghnameal', 'Cuilly', 'Drumadoney', 'Drumcroagh', 'Drummenny Upper',
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
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_conn():
    """
    Module-level fixture: set up clean database, ingest Tullynaught fixtures,
    run full pipeline, capture metrics, then yield connection for all tests.

    This ensures all tests run against the same freshly-ingested golden dataset
    with known, fixed record and person counts (see METRICS_DEFINITIONS.md).

    Fixture setup:
      1. Clear evidence + conclusion layers (place_authority preserved)
      2. Verify clean state: person count = 0
      3. Ingest all three CSVs (1901, 1911, 1926)
      4. Run full evidence + conclusion pipeline
      5. Capture Phase 3 metrics and linkage statistics
      6. Yield connection for test queries
    """
    from src.db.db import open_db, check_version
    conn = open_db()
    check_version(conn)
    _setup_data(conn)
    yield conn
    conn.close()


def _setup_data(conn: psycopg2.extensions.connection) -> None:
    """
    Wipe evidence + conclusion layers, ingest all three Tullynaught CSVs,
    run the full conclusion pipeline, and capture metrics.

    place_authority is preserved (must be seeded externally before running).

    Uses the complete Tullynaught golden 3-census set (all 3,167 persons) to ensure
    consistent linkage measurements across all test runs. See METRICS_DEFINITIONS.md
    for linkage percentage calculations.
    """
    from src.evidence.census import ingest_census
    from src.evidence.role_relationships import assign_role_relationships
    from src.evidence.place_resolution import run_place_resolution
    from src.evidence.similarity import run_record_similarity, run_person_similarity
    from src.conclusion.person_resolution import run_person_resolution
    from src.conclusion.relationship_resolution import run_relationship_resolution
    from src.conclusion.event_resolution import run_event_resolution

    print("\nSetup: clearing evidence + conclusion layers...")
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
    with conn:
        with conn.cursor() as cur:
            for table in clear_tables:
                cur.execute(f"DELETE FROM {table}")

    # Verify clean state: ensure person table is empty before ingest
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) as count FROM person")
        person_count = cur.fetchone()["count"]
        if person_count > 0:
            raise AssertionError(
                f"Database not clean: {person_count} persons exist after clear. "
                "Run 'python -m src.cli clear-evidence' before tests."
            )

    print("  ingesting all sources...")
    for source_id, fixture_path in FIXTURES.items():
        if not fixture_path.exists():
            raise FileNotFoundError(f"Fixture not found: {fixture_path}")
        print(f"    source {source_id} ({fixture_path.name})...", end=" ", flush=True)
        t0 = time.perf_counter()
        ingest_result = ingest_census(conn, str(fixture_path), source_id=source_id)

        with conn.cursor() as cur:
            cur.execute(
                "SELECT record_id FROM record WHERE source_id = %s "
                "ORDER BY record_id DESC LIMIT %s",
                (source_id, ingest_result["records_committed"]),
            )
            record_ids = [row["record_id"] for row in cur.fetchall()]

        with conn:
            for rid in record_ids:
                assign_role_relationships(conn, rid)
        elapsed = time.perf_counter() - t0
        print(f"{ingest_result['records_committed']} records ({elapsed:.2f}s)")

    print("  running place resolution...", end=" ", flush=True)
    t0 = time.perf_counter()
    run_place_resolution(conn)
    print(f"({time.perf_counter() - t0:.2f}s)")

    print("  running record similarity...", end=" ", flush=True)
    t0 = time.perf_counter()
    run_record_similarity(conn)
    print(f"({time.perf_counter() - t0:.2f}s)")

    print("  running person similarity...", end=" ", flush=True)
    t0 = time.perf_counter()
    run_person_similarity(conn)
    print(f"({time.perf_counter() - t0:.2f}s)")

    print("  running person resolution...", end=" ", flush=True)
    t0 = time.perf_counter()
    run_person_resolution(conn)
    print(f"({time.perf_counter() - t0:.2f}s)")

    print("  running relationship resolution...", end=" ", flush=True)
    t0 = time.perf_counter()
    run_relationship_resolution(conn)
    print(f"({time.perf_counter() - t0:.2f}s)")

    print("  running event resolution...", end=" ", flush=True)
    t0 = time.perf_counter()
    run_event_resolution(conn)
    print(f"({time.perf_counter() - t0:.2f}s)")

    # METRICS CAPTURE: Three-Census Linkage and Pairwise Similarity
    # See tests/METRICS_DEFINITIONS.md for calculation definitions and regression detection rules.
    print("\n" + "="*80)
    print("LINKAGE METRICS — v1.1 Baseline (Phase 3 Removed)")
    print("="*80)

    with conn.cursor() as cur:
        # ===== Three-Census Linkage Percentage =====
        # Definition: Proportion of recorded persons linked into unified persons
        # Formula: 100 × (Linked Recorded Persons) / (Total Recorded Persons)
        # Numerator: COUNT(DISTINCT recorded_person_id) FROM person_recorded_person
        # Denominator: EXACT_PERSONS_TOTAL = 3,167 (fixed, from all three census fixtures)
        # Interpretation: % of all census persons that were merged via Splink + clustering

        cur.execute("""
            SELECT COUNT(DISTINCT recorded_person_id) as linked_rp
            FROM person_recorded_person
        """)
        linked_recorded_persons = cur.fetchone()["linked_rp"]
        linkage_pct = 100.0 * linked_recorded_persons / EXACT_PERSONS_TOTAL

        print(f"\nThree-Census Linkage (denominator: {EXACT_PERSONS_TOTAL} total persons)")
        print(f"  Linked recorded persons: {linked_recorded_persons}")
        print(f"  Linkage: {linkage_pct:.1f}%")

        # Verify fixture ingestion: total persons should match expected
        cur.execute("SELECT COUNT(DISTINCT person_id) FROM person")
        clustered_persons = cur.fetchone()["count"]
        print(f"  Clustered persons: {clustered_persons} (unique persons after merging)")
        print(f"  Merge ratio: {linked_recorded_persons / clustered_persons:.2f}x " +
              f"({linked_recorded_persons} recorded → {clustered_persons} clustered)")

        # ===== Pairwise Person Similarity Metrics =====
        # Definition: Distribution and quality of similarity scores across all recorded_person pairs
        # These scores come from Splink EM training and determine clustering at threshold=0.50
        # Formula: Score tiers as % of total similarity pairs evaluated
        # Interpretation: Concentration near threshold indicates good feature discrimination

        cur.execute("""
            SELECT
                COUNT(*) as total_pairs,
                AVG(score)::numeric(5,3) as avg_score,
                MIN(score)::numeric(5,3) as min_score,
                MAX(score)::numeric(5,3) as max_score,
                STDDEV(score)::numeric(5,3) as stddev_score,
                COUNT(CASE WHEN score >= 0.65 THEN 1 END) as tier_65,
                COUNT(CASE WHEN score >= 0.50 AND score < 0.65 THEN 1 END) as tier_50_65,
                COUNT(CASE WHEN score >= 0.45 AND score < 0.50 THEN 1 END) as tier_45_50,
                COUNT(CASE WHEN score < 0.45 THEN 1 END) as tier_below_45
            FROM recorded_relationship
            WHERE type = 'similarity'
        """)
        row = cur.fetchone()

        print(f"\nPairwise Person Similarity (person-level Splink scores)")
        if row and row['total_pairs']:
            total_pairs = row['total_pairs']
            print(f"  Total pairs: {total_pairs}")
            print(f"  Statistics:")
            print(f"    Mean: {row['avg_score']:.3f}")
            print(f"    Range: {row['min_score']:.3f} – {row['max_score']:.3f}")
            print(f"    Std Dev: {row['stddev_score']:.3f}")
            print(f"  Score distribution (tiers as % of total pairs):")
            pct_65 = 100*row['tier_65']/total_pairs
            pct_50_65 = 100*row['tier_50_65']/total_pairs
            pct_45_50 = 100*row['tier_45_50']/total_pairs
            pct_below_45 = 100*row['tier_below_45']/total_pairs

            print(f"    ≥0.65 (high):      {row['tier_65']:4d} ({pct_65:5.1f}%)")
            print(f"    0.50-0.65 (med):   {row['tier_50_65']:4d} ({pct_50_65:5.1f}%)")
            print(f"    0.45-0.50 (marg):  {row['tier_45_50']:4d} ({pct_45_50:5.1f}%)")
            print(f"    <0.45 (weak):      {row['tier_below_45']:4d} ({pct_below_45:5.1f}%)")

            pairs_above_threshold = row['tier_65'] + row['tier_50_65'] + row['tier_45_50']
            pct_above_threshold = 100*pairs_above_threshold/total_pairs
            print(f"  Pairs ≥0.45 (above clustering threshold): {pairs_above_threshold} ({pct_above_threshold:.1f}%)")
        else:
            print(f"  (No similarity pairs)")

        # ===== Regression Detection vs v1.1 Baseline =====
        # v1.1 baseline (Phase 3 removed): 20-23% linkage
        # Splink's EM training uses random sampling (estimate_u_using_random_sampling),
        # causing variance across runs even with fixed seeds. Observed range: 20.1-22.9%.
        # Target range: ≥20% (with Phase 3 removed and reproducible seeding).
        # If linkage drops below 20%, investigate whether seeds are being respected.

        MIN_LINKAGE = 20.0
        threshold_ok = linkage_pct >= MIN_LINKAGE

        print(f"\nRegression Detection vs v1.1 Baseline (Phase 3 Removed)")
        print(f"  Expected linkage range: ≥{MIN_LINKAGE:.1f}%")
        print(f"  Actual linkage: {linkage_pct:.1f}% ({linked_recorded_persons} persons)")
        if threshold_ok:
            print(f"  ✓ Within acceptable range")
        else:
            print(f"  ✗ Below threshold: {linkage_pct - MIN_LINKAGE:.1f}pp")

    print("="*80 + "\n")

    print("Setup complete.\n")


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
# FOUNDATION LAYER TESTS
# ---------------------------------------------------------------------------

def test_schema_version(db_conn):
    """Schema version in gra_meta matches constants.SCHEMA_VERSION."""
    from src.constants import SCHEMA_VERSION
    with db_conn.cursor() as cur:
        cur.execute("SELECT value FROM gra_meta WHERE key = 'schema_version'")
        row = cur.fetchone()
    assert row is not None, "gra_meta has no schema_version row"
    assert int(row["value"]) == SCHEMA_VERSION, (
        f"Schema version mismatch: DB={row['value']}, code={SCHEMA_VERSION}"
    )


def test_seed_data_repositories(db_conn):
    """At least 8 repository rows exist (from seed.sql)."""
    count = _q(db_conn, "SELECT COUNT(*) FROM repository")
    assert count >= 8, f"Expected ≥8 repositories, got {count}"


def test_seed_data_sources(db_conn):
    """Census sources 3, 4, 5 and place authority source 13 exist."""
    rows = _rows(db_conn, "SELECT source_id FROM source WHERE source_id IN (3, 4, 5, 13)")
    ids = {r["source_id"] for r in rows}
    assert ids == {3, 4, 5, 13}, f"Missing expected source IDs: {ids}"


def test_place_authority_warning(db_conn):
    """Warn if place_authority is empty (tests degrade gracefully but researcher should seed)."""
    count = _q(db_conn, "SELECT COUNT(*) FROM place_authority")
    assert count > 0, (
        "place_authority is empty — seed it with 'python -m src.cli seed-places' before "
        "running integration tests. Place-dependent assertions will be weak."
    )


# ---------------------------------------------------------------------------
# EVIDENCE LAYER TESTS — ingest
# ---------------------------------------------------------------------------

def test_evidence_records_floor(db_conn):
    """Exactly 715 households ingested across all three sources (263+240+212)."""
    count = _q(db_conn, "SELECT COUNT(*) FROM record")
    assert count == EXACT_RECORDS_TOTAL, f"Expected {EXACT_RECORDS_TOTAL} records, got {count}"


def test_evidence_records_per_source(db_conn):
    """Each census source has the exact expected household count."""
    expected = {
        SOURCE_ID_1901: EXACT_RECORDS_1901,
        SOURCE_ID_1911: EXACT_RECORDS_1911,
        SOURCE_ID_1926: EXACT_RECORDS_1926,
    }
    for source_id, expected_count in expected.items():
        count = _q(db_conn, "SELECT COUNT(*) FROM record WHERE source_id = %s", (source_id,))
        assert count == expected_count, (
            f"Source {source_id}: expected {expected_count} records, got {count}"
        )


def test_evidence_recorded_persons_floor(db_conn):
    """Exactly 3167 recorded persons ingested across all sources (1193+1080+894)."""
    count = _q(db_conn, "SELECT COUNT(*) FROM recorded_person")
    assert count == EXACT_PERSONS_TOTAL, (
        f"Expected {EXACT_PERSONS_TOTAL} recorded_persons, got {count}"
    )


def test_evidence_recorded_persons_per_source(db_conn):
    """Each census source has the exact expected recorded person count."""
    expected = {
        SOURCE_ID_1901: EXACT_PERSONS_1901,
        SOURCE_ID_1911: EXACT_PERSONS_1911,
        SOURCE_ID_1926: EXACT_PERSONS_1926,
    }
    for source_id, expected_count in expected.items():
        count = _q(db_conn, """
            SELECT COUNT(*) FROM recorded_person rp
            JOIN record r ON r.record_id = rp.record_id
            WHERE r.source_id = %s
        """, (source_id,))
        assert count == expected_count, (
            f"Source {source_id}: expected {expected_count} recorded_persons, got {count}"
        )


def test_evidence_every_record_has_persons(db_conn):
    """Every record has at least one recorded_person (no orphan household records)."""
    orphans = _q(db_conn, """
        SELECT COUNT(*) FROM record r
        WHERE NOT EXISTS (
            SELECT 1 FROM recorded_person rp WHERE rp.record_id = r.record_id
        )
    """)
    assert orphans == 0, f"{orphans} records have no recorded_persons"


def test_evidence_recorded_person_has_name(db_conn):
    """No recorded_person has a NULL or empty name_as_recorded."""
    bad = _q(db_conn, """
        SELECT COUNT(*) FROM recorded_person
        WHERE name_as_recorded IS NULL OR trim(name_as_recorded) = ''
    """)
    assert bad == 0, f"{bad} recorded_persons have blank/null name_as_recorded"


def test_evidence_recorded_person_age_non_negative(db_conn):
    """All recorded_person ages are non-negative when present."""
    bad = _q(db_conn, "SELECT COUNT(*) FROM recorded_person WHERE age IS NOT NULL AND age < 0")
    assert bad == 0, f"{bad} recorded_persons have negative age"


def test_evidence_record_dates_set(db_conn):
    """All census records have a non-null ISO date (1901-04-01, 1911-04-02, 1926-04-18)."""
    bad = _q(db_conn, "SELECT COUNT(*) FROM record WHERE date IS NULL")
    assert bad == 0, f"{bad} records have NULL date"


def test_evidence_record_dates_valid_census_years(db_conn):
    """All census record dates fall in known census years (1901, 1911, 1926)."""
    bad = _q(db_conn, """
        SELECT COUNT(*) FROM record r
        JOIN source s ON s.source_id = r.source_id AND s.type = 'census'
        WHERE EXTRACT(YEAR FROM r.date::date) NOT IN (1901, 1911, 1926)
    """)
    assert bad == 0, f"{bad} census records have unexpected year in date field"


# ---------------------------------------------------------------------------
# EVIDENCE LAYER TESTS — role relationships
# ---------------------------------------------------------------------------

def test_evidence_role_relationships_floor(db_conn):
    """Exactly 5923 role-pair relationships assigned (347 couple, 2624 parent_child, 2952 sibling)."""
    count = _q(db_conn, "SELECT COUNT(*) FROM recorded_relationship WHERE type != 'similarity'")
    assert count == EXACT_ROLE_RELS_TOTAL, (
        f"Expected {EXACT_ROLE_RELS_TOTAL} role relationships, got {count}"
    )


def test_evidence_role_relationships_by_type(db_conn):
    """Exact role relationship counts by type match fixture-derived values."""
    expected = {
        "couple":       EXACT_ROLE_RELS_COUPLE,
        "parent_child": EXACT_ROLE_RELS_PARENT_CHILD,
        "sibling":      EXACT_ROLE_RELS_SIBLING,
    }
    for rel_type, expected_count in expected.items():
        count = _q(db_conn,
            "SELECT COUNT(*) FROM recorded_relationship WHERE type = %s",
            (rel_type,),
        )
        assert count == expected_count, (
            f"Type '{rel_type}': expected {expected_count}, got {count}"
        )


def test_evidence_role_relationship_scores_not_null(db_conn):
    """All role-pair recorded_relationships have a non-null score."""
    bad = _q(db_conn, """
        SELECT COUNT(*) FROM recorded_relationship
        WHERE type != 'similarity' AND score IS NULL
    """)
    assert bad == 0, f"{bad} role-pair recorded_relationships have NULL score"


def test_evidence_role_relationship_scores_in_range(db_conn):
    """Role-pair recorded_relationship scores are between 0.0 and 1.0."""
    bad = _q(db_conn, """
        SELECT COUNT(*) FROM recorded_relationship
        WHERE type != 'similarity'
          AND (score < 0.0 OR score > 1.0)
    """)
    assert bad == 0, f"{bad} role-pair recorded_relationships have out-of-range score"


def test_evidence_role_relationship_types_valid(db_conn):
    """All role-pair recorded_relationships have a recognised type."""
    valid_types = ("couple", "parent_child", "sibling", "similarity")
    placeholders = ",".join(["%s"] * len(valid_types))
    bad = _q(
        db_conn,
        f"SELECT COUNT(*) FROM recorded_relationship WHERE type NOT IN ({placeholders})",
        valid_types,
    )
    assert bad == 0, f"{bad} recorded_relationships have invalid type"


# ---------------------------------------------------------------------------
# EVIDENCE LAYER TESTS — place resolution
# ---------------------------------------------------------------------------

def test_evidence_place_links_exact(db_conn):
    """Exactly 715 place_record links — all households matched (100% match rate confirmed)."""
    if not _place_authority_seeded(db_conn):
        # Can't assert without place_authority — warn via a soft pass
        return
    count = _q(db_conn, "SELECT COUNT(*) FROM place_record")
    assert count == EXACT_PLACE_LINKS, (
        f"Expected {EXACT_PLACE_LINKS} place_record links, got {count}"
    )


def test_evidence_place_links_valid_place_ids(db_conn):
    """All place_record rows reference a valid place_authority.place_id."""
    orphans = _q(db_conn, """
        SELECT COUNT(*) FROM place_record pr
        WHERE NOT EXISTS (
            SELECT 1 FROM place_authority pa WHERE pa.place_id = pr.place_id
        )
    """)
    assert orphans == 0, f"{orphans} place_record rows reference non-existent place_id"


def test_evidence_place_links_valid_record_ids(db_conn):
    """All place_record rows reference a valid record.record_id."""
    orphans = _q(db_conn, """
        SELECT COUNT(*) FROM place_record pr
        WHERE NOT EXISTS (
            SELECT 1 FROM record r WHERE r.record_id = pr.record_id
        )
    """)
    assert orphans == 0, f"{orphans} place_record rows reference non-existent record_id"


def test_evidence_place_authority_complete(db_conn):
    """place_authority contains all 33 authoritative Tullynaught townlands (via normalized matching)."""
    if not _place_authority_seeded(db_conn):
        return
    rows = _rows(db_conn, "SELECT name_en FROM place_authority WHERE place_type = 'townland'")

    # Build normalized lookup from seeded authority names
    seeded_normalized = {normalize_place_name(r["name_en"]): r["name_en"] for r in rows}

    # Check if each expected townland can be resolved via normalization
    missing = []
    for expected in AUTHORITATIVE_TOWNLANDS:
        normalized_expected = normalize_place_name(expected)
        if normalized_expected not in seeded_normalized:
            missing.append(expected)

    assert not missing, (
        f"Missing {len(missing)} authoritative townland(s) that cannot be resolved via normalization: "
        f"{sorted(missing)}"
    )


def test_evidence_place_authority_count(db_conn):
    """place_authority has exactly 34 rows: 1 DED + 33 townlands."""
    if not _place_authority_seeded(db_conn):
        return
    count = _q(db_conn, "SELECT COUNT(*) FROM place_authority")
    assert count == 34, (
        f"Expected 34 place_authority rows (1 DED + 33 townlands), got {count}"
    )


def test_evidence_uninhabited_townlands_have_no_place_records(db_conn):
    """Croaghnakern and Rooney's Island are uninhabited — no place_record rows for them."""
    if not _place_authority_seeded(db_conn):
        return
    placeholders = ",".join(["%s"] * len(UNINHABITED_TOWNLANDS))
    count = _q(db_conn, f"""
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

def test_evidence_record_similarities_floor(db_conn):
    """At least FLOOR_RECORD_SIMS cross-census record similarity pairs."""
    count = _q(db_conn, "SELECT COUNT(*) FROM record_similarity")
    assert count >= FLOOR_RECORD_SIMS, (
        f"Expected ≥{FLOOR_RECORD_SIMS} record_similarity rows, got {count}"
    )


def test_evidence_record_similarities_cross_census(db_conn):
    """All record_similarity pairs are cross-census (source_id_1 != source_id_2)."""
    same_source = _q(db_conn, """
        SELECT COUNT(*) FROM record_similarity rs
        JOIN record r1 ON r1.record_id = rs.record_id_1
        JOIN record r2 ON r2.record_id = rs.record_id_2
        WHERE r1.source_id = r2.source_id
    """)
    assert same_source == 0, (
        f"{same_source} record_similarity pairs are within the same source (should be cross-census only)"
    )


def test_evidence_record_similarity_scores_in_range(db_conn):
    """All record_similarity scores are between 0.0 and 1.0."""
    bad = _q(db_conn, """
        SELECT COUNT(*) FROM record_similarity
        WHERE score < 0.0 OR score > 1.0
    """)
    assert bad == 0, f"{bad} record_similarity rows have out-of-range score"


def test_evidence_person_similarities_floor(db_conn):
    """At least FLOOR_PERSON_SIMS person-level similarity pairs in recorded_relationship."""
    count = _q(db_conn, "SELECT COUNT(*) FROM recorded_relationship WHERE type = 'similarity'")
    assert count >= FLOOR_PERSON_SIMS, (
        f"Expected ≥{FLOOR_PERSON_SIMS} person similarity pairs, got {count}"
    )


def test_evidence_person_similarity_scores_in_range(db_conn):
    """All person similarity scores are between 0.0 and 1.0."""
    bad = _q(db_conn, """
        SELECT COUNT(*) FROM recorded_relationship
        WHERE type = 'similarity'
          AND (score < 0.0 OR score > 1.0)
    """)
    assert bad == 0, f"{bad} person similarity rows have out-of-range score"


def test_evidence_person_similarity_no_self_pairs(db_conn):
    """No person similarity pair links a recorded_person to itself."""
    self_pairs = _q(db_conn, """
        SELECT COUNT(*) FROM recorded_relationship
        WHERE type = 'similarity'
          AND recorded_person_id_1 = recorded_person_id_2
    """)
    assert self_pairs == 0, f"{self_pairs} person similarity self-pairs found"


def test_evidence_person_similarity_cross_census(db_conn):
    """All person similarity pairs are cross-census."""
    same_source = _q(db_conn, """
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

def test_conclusion_persons_floor(db_conn):
    """At least FLOOR_PERSONS Person conclusions created."""
    count = _q(db_conn, "SELECT COUNT(*) FROM person")
    assert count >= FLOOR_PERSONS, f"Expected ≥{FLOOR_PERSONS} persons, got {count}"


def test_conclusion_every_person_has_recorded_person(db_conn):
    """Every Person is linked to at least one RecordedPerson (no ghost Persons)."""
    ghosts = _q(db_conn, """
        SELECT COUNT(*) FROM person p
        WHERE NOT EXISTS (
            SELECT 1 FROM person_recorded_person prp WHERE prp.person_id = p.person_id
        )
    """)
    assert ghosts == 0, f"{ghosts} Persons have no RecordedPerson link"


def test_conclusion_every_person_has_label(db_conn):
    """Every Person has a non-null, non-empty label."""
    bad = _q(db_conn, "SELECT COUNT(*) FROM person WHERE label IS NULL OR trim(label) = ''")
    assert bad == 0, f"{bad} Persons have blank/null label"


def test_conclusion_person_gender_valid(db_conn):
    """All Person gender values are male, female, or NULL."""
    bad = _q(db_conn, """
        SELECT COUNT(*) FROM person
        WHERE gender IS NOT NULL AND gender NOT IN ('male', 'female')
    """)
    assert bad == 0, f"{bad} Persons have invalid gender value"


def test_conclusion_recorded_person_not_double_linked(db_conn):
    """No RecordedPerson is linked to more than one Person."""
    double_linked = _q(db_conn, """
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

def test_conclusion_relationships_floor(db_conn):
    """At least FLOOR_RELATIONSHIPS Relationship conclusions created."""
    count = _q(db_conn, "SELECT COUNT(*) FROM relationship")
    assert count >= FLOOR_RELATIONSHIPS, (
        f"Expected ≥{FLOOR_RELATIONSHIPS} relationships, got {count}"
    )


def test_conclusion_relationship_types_valid(db_conn):
    """All Relationship types are couple, parent_child, or sibling."""
    bad = _q(db_conn, """
        SELECT COUNT(*) FROM relationship
        WHERE type NOT IN ('couple', 'parent_child', 'sibling')
    """)
    assert bad == 0, f"{bad} Relationships have invalid type"


def test_conclusion_relationship_persons_exist(db_conn):
    """All Relationships reference valid Person IDs for both endpoints."""
    bad = _q(db_conn, """
        SELECT COUNT(*) FROM relationship r
        WHERE NOT EXISTS (SELECT 1 FROM person p WHERE p.person_id = r.person_id_1)
           OR NOT EXISTS (SELECT 1 FROM person p WHERE p.person_id = r.person_id_2)
    """)
    assert bad == 0, f"{bad} Relationships reference non-existent Person IDs"


def test_conclusion_no_self_relationships(db_conn):
    """No Relationship links a Person to itself."""
    self_rels = _q(db_conn, "SELECT COUNT(*) FROM relationship WHERE person_id_1 = person_id_2")
    assert self_rels == 0, f"{self_rels} self-referencing Relationships found"


def test_conclusion_no_duplicate_relationships(db_conn):
    """No duplicate Relationships exist for the same Person pair and type."""
    # Relationship is undirected: (A, B, type) == (B, A, type)
    duplicates = _q(db_conn, """
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


def test_conclusion_couples_have_two_distinct_persons(db_conn):
    """All couple Relationships link two distinct Persons."""
    bad = _q(db_conn, """
        SELECT COUNT(*) FROM relationship
        WHERE type = 'couple' AND person_id_1 = person_id_2
    """)
    assert bad == 0, f"{bad} couple Relationships have identical person IDs"


# ---------------------------------------------------------------------------
# CONCLUSION LAYER TESTS — Event
# ---------------------------------------------------------------------------

def test_conclusion_events_floor(db_conn):
    """At least FLOOR_EVENTS Event conclusions created."""
    count = _q(db_conn, "SELECT COUNT(*) FROM event")
    assert count >= FLOOR_EVENTS, f"Expected ≥{FLOOR_EVENTS} events, got {count}"


def test_conclusion_census_events_exist(db_conn):
    """At least one census Event exists."""
    count = _q(db_conn, "SELECT COUNT(*) FROM event WHERE type = 'census'")
    assert count >= 1, "No census Events created"


def test_conclusion_birth_events_exist(db_conn):
    """At least one birth Event exists."""
    count = _q(db_conn, "SELECT COUNT(*) FROM event WHERE type = 'birth'")
    assert count >= 1, "No birth Events created"


def test_conclusion_event_types_valid(db_conn):
    """All Event types are in the known vocabulary."""
    valid_types = (
        "birth", "baptism", "marriage", "death", "burial",
        "census", "residence", "emigration",
        "valuation", "tithe", "military_service", "pension", "folklore",
    )
    placeholders = ",".join(["%s"] * len(valid_types))
    bad = _q(db_conn, f"SELECT COUNT(*) FROM event WHERE type NOT IN ({placeholders})", valid_types)
    assert bad == 0, f"{bad} Events have invalid type"


def test_conclusion_every_event_has_person_link(db_conn):
    """Every Event is linked to at least one Person via person_event."""
    orphan_events = _q(db_conn, """
        SELECT COUNT(*) FROM event e
        WHERE NOT EXISTS (
            SELECT 1 FROM person_event pe WHERE pe.event_id = e.event_id
        )
    """)
    assert orphan_events == 0, f"{orphan_events} Events have no person_event link"


def test_conclusion_person_event_persons_exist(db_conn):
    """All person_event rows reference valid Person IDs."""
    bad = _q(db_conn, """
        SELECT COUNT(*) FROM person_event pe
        WHERE NOT EXISTS (SELECT 1 FROM person p WHERE p.person_id = pe.person_id)
    """)
    assert bad == 0, f"{bad} person_event rows reference non-existent Person IDs"


def test_conclusion_person_event_events_exist(db_conn):
    """All person_event rows reference valid Event IDs."""
    bad = _q(db_conn, """
        SELECT COUNT(*) FROM person_event pe
        WHERE NOT EXISTS (SELECT 1 FROM event e WHERE e.event_id = pe.event_id)
    """)
    assert bad == 0, f"{bad} person_event rows reference non-existent Event IDs"


def test_conclusion_birth_event_dates_calculated(db_conn):
    """All birth Events from census inference have date_qualifier='calculated'."""
    bad = _q(db_conn, """
        SELECT COUNT(*) FROM event
        WHERE type = 'birth'
          AND (date_qualifier IS NULL OR date_qualifier != 'calculated')
    """)
    assert bad == 0, (
        f"{bad} birth Events are missing date_qualifier='calculated' "
        "(BMD birth events should use a different ingest path)"
    )


def test_conclusion_birth_event_dates_plausible(db_conn):
    """All calculated birth Events have a date year within fixture-derived plausible range."""
    bad = _q(db_conn, """
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


def test_conclusion_one_primary_birth_event_per_person(db_conn):
    """Every Person has at most one is_primary birth Event."""
    bad = _q(db_conn, """
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


def test_conclusion_census_events_all_primary(db_conn):
    """All census Events are is_primary=1 (each census appearance is a distinct moment)."""
    bad = _q(db_conn, "SELECT COUNT(*) FROM event WHERE type = 'census' AND is_primary != 1")
    assert bad == 0, f"{bad} census Events have is_primary != 1"


def test_conclusion_marriage_events_have_relationship(db_conn):
    """All marriage Events reference a Relationship (relationship_id is not NULL)."""
    bad = _q(db_conn, "SELECT COUNT(*) FROM event WHERE type = 'marriage' AND relationship_id IS NULL")
    assert bad == 0, f"{bad} marriage Events have NULL relationship_id"


def test_conclusion_marriage_relationship_ids_valid(db_conn):
    """All marriage Event relationship_ids reference existing Relationships."""
    bad = _q(db_conn, """
        SELECT COUNT(*) FROM event e
        WHERE e.type = 'marriage'
          AND e.relationship_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM relationship r WHERE r.relationship_id = e.relationship_id
          )
    """)
    assert bad == 0, f"{bad} marriage Events reference non-existent relationship_id"


def test_conclusion_event_record_links_valid(db_conn):
    """All event_record rows reference valid event_id and record_id."""
    bad_event = _q(db_conn, """
        SELECT COUNT(*) FROM event_record er
        WHERE NOT EXISTS (SELECT 1 FROM event e WHERE e.event_id = er.event_id)
    """)
    bad_record = _q(db_conn, """
        SELECT COUNT(*) FROM event_record er
        WHERE NOT EXISTS (SELECT 1 FROM record r WHERE r.record_id = er.record_id)
    """)
    assert bad_event == 0, f"{bad_event} event_record rows reference non-existent event_id"
    assert bad_record == 0, f"{bad_record} event_record rows reference non-existent record_id"


# ---------------------------------------------------------------------------
# CROSS-LAYER INVARIANTS
# ---------------------------------------------------------------------------

def test_invariant_person_recorded_person_fk(db_conn):
    """All person_recorded_person rows have valid person_id and recorded_person_id FKs."""
    bad_person = _q(db_conn, """
        SELECT COUNT(*) FROM person_recorded_person prp
        WHERE NOT EXISTS (SELECT 1 FROM person p WHERE p.person_id = prp.person_id)
    """)
    bad_rp = _q(db_conn, """
        SELECT COUNT(*) FROM person_recorded_person prp
        WHERE NOT EXISTS (
            SELECT 1 FROM recorded_person rp WHERE rp.recorded_person_id = prp.recorded_person_id
        )
    """)
    assert bad_person == 0, f"{bad_person} person_recorded_person rows have invalid person_id"
    assert bad_rp == 0, f"{bad_rp} person_recorded_person rows have invalid recorded_person_id"


def test_invariant_recorded_relationship_fk(db_conn):
    """All recorded_relationship rows reference valid recorded_person IDs."""
    bad_1 = _q(db_conn, """
        SELECT COUNT(*) FROM recorded_relationship rr
        WHERE NOT EXISTS (
            SELECT 1 FROM recorded_person rp WHERE rp.recorded_person_id = rr.recorded_person_id_1
        )
    """)
    bad_2 = _q(db_conn, """
        SELECT COUNT(*) FROM recorded_relationship rr
        WHERE NOT EXISTS (
            SELECT 1 FROM recorded_person rp WHERE rp.recorded_person_id = rr.recorded_person_id_2
        )
    """)
    assert bad_1 == 0, f"{bad_1} recorded_relationship rows have invalid recorded_person_id_1"
    assert bad_2 == 0, f"{bad_2} recorded_relationship rows have invalid recorded_person_id_2"


def test_invariant_no_conclusion_points_to_conclusion(db_conn):
    """
    Evidence-conclusion separation: no RecordedPerson or RecordedRelationship
    references a conclusion-layer ID (Person, Relationship, Event).
    This is a schema-level property but worth asserting explicitly.
    """
    # RecordedPerson has no person_id FK by design — verified by absence of column
    with db_conn.cursor() as cur:
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
