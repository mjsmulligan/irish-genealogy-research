"""
GRA — Place Resolution
Stage 2 of the reconstruction pipeline.

Reads all distinct place_as_recorded strings from the evidence layer,
normalises them, clusters by Jaro-Winkler similarity, auto-commits each
cluster as a Place conclusion, and links every contributing Record via
place_record.

Entry point: run_place_resolution(conn) -> PlaceResolutionResult
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

import jellyfish

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCORE_VERSION = "place_v1.0"
JW_THRESHOLD = 0.88      # minimum similarity to merge two place tokens
EXACT_SCORE = 1.0        # score for records whose normalised token exactly matches the cluster canonical
AUTO_COMMIT_SCORE = 0.90 # default score stored on place_record for fuzzy (non-exact) matches

# Abbreviation expansions applied during normalisation
_ABBREV = {
    r"\bco\b\.?":    "county",
    r"\bpar\b\.?":   "parish",
    r"\bbal\b\.?":   "bally",
    r"\btd\b\.?":    "townland",
}

# Administrative suffixes stripped after abbreviation expansion
_SUFFIXES = re.compile(
    r"\b(townland|civil parish|ded|barony|county|parish)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def _normalise(raw: str) -> str:
    """
    Apply the townland normalisation pipeline from reconstruction_algorithms.md §2.3.
    Returns a normalised token suitable for Jaro-Winkler comparison.
    """
    s = raw.lower()
    # Strip punctuation (commas, full stops, hyphens-as-separators)
    s = re.sub(r"[,.\-]", " ", s)
    # Expand abbreviations
    for pattern, replacement in _ABBREV.items():
        s = re.sub(pattern, replacement, s, flags=re.IGNORECASE)
    # Strip administrative suffixes
    s = _SUFFIXES.sub(" ", s)
    # Collapse whitespace
    s = " ".join(s.split())
    return s


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class PlaceCluster:
    canonical_raw: str          # the most-common raw string in the cluster (used as Place.name)
    canonical_norm: str         # normalised form of canonical_raw
    records: list[int]          # record_ids in this cluster
    raw_variants: list[str]     # all distinct raw strings that mapped here
    place_id: int = 0           # assigned after insert


@dataclass
class PlaceResolutionResult:
    places_created: int = 0
    records_linked: int = 0
    clusters: list[PlaceCluster] = field(default_factory=list)
    skipped_blank: int = 0


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

def _collect_place_tokens(conn: sqlite3.Connection) -> dict[str, list[int]]:
    """
    Return a mapping of normalised place token → list of record_ids.
    Reads place_as_recorded from recorded_event (one per record).
    Skips null/blank values.
    """
    rows = conn.execute(
        "SELECT re.record_id, re.place_as_recorded "
        "FROM recorded_event re "
        "WHERE re.place_as_recorded IS NOT NULL AND trim(re.place_as_recorded) != ''"
    ).fetchall()

    token_to_records: dict[str, list[int]] = {}
    for row in rows:
        norm = _normalise(row["place_as_recorded"])
        if not norm:
            continue
        token_to_records.setdefault(norm, []).append(row["record_id"])
    return token_to_records


def _build_clusters(
    token_to_records: dict[str, list[int]],
    raw_lookup: dict[str, str],   # norm → most-common raw string
) -> list[PlaceCluster]:
    """
    Greedy single-linkage clustering of normalised place tokens by
    Jaro-Winkler similarity ≥ JW_THRESHOLD.

    Tokens are processed largest-first (most records) so the cluster
    canonical is drawn from the most-evidenced variant.
    """
    # Sort tokens by record count descending so high-frequency tokens
    # become cluster seeds first.
    tokens_sorted = sorted(
        token_to_records.keys(),
        key=lambda t: len(token_to_records[t]),
        reverse=True,
    )

    assigned: dict[str, int] = {}   # norm token → cluster index
    clusters: list[PlaceCluster] = []

    for token in tokens_sorted:
        if token in assigned:
            continue

        # Try to find an existing cluster whose canonical is similar enough
        best_idx = -1
        best_score = 0.0
        for idx, cluster in enumerate(clusters):
            score = jellyfish.jaro_winkler_similarity(token, cluster.canonical_norm)
            if score >= JW_THRESHOLD and score > best_score:
                best_score = score
                best_idx = idx

        if best_idx >= 0:
            # Merge into existing cluster
            cluster = clusters[best_idx]
            cluster.records.extend(token_to_records[token])
            raw = raw_lookup[token]
            if raw not in cluster.raw_variants:
                cluster.raw_variants.append(raw)
            assigned[token] = best_idx
        else:
            # Start a new cluster seeded by this token
            new_cluster = PlaceCluster(
                canonical_raw=raw_lookup[token],
                canonical_norm=token,
                records=list(token_to_records[token]),
                raw_variants=[raw_lookup[token]],
            )
            assigned[token] = len(clusters)
            clusters.append(new_cluster)

    return clusters


def _most_common_raw(conn: sqlite3.Connection, norm: str, records: list[int]) -> str:
    """
    Among all place_as_recorded values for the given record_ids that
    normalise to this token, return the most frequent raw string.
    Falls back to the normalised token itself if nothing resolves.
    """
    placeholders = ",".join("?" * len(records))
    rows = conn.execute(
        f"SELECT place_as_recorded FROM recorded_event "
        f"WHERE record_id IN ({placeholders}) AND place_as_recorded IS NOT NULL",
        records,
    ).fetchall()

    counts: dict[str, int] = {}
    for row in rows:
        raw = row["place_as_recorded"].strip()
        if raw:
            counts[raw] = counts.get(raw, 0) + 1

    if counts:
        return max(counts, key=lambda k: counts[k])
    return norm


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_place_resolution(conn: sqlite3.Connection) -> PlaceResolutionResult:
    """
    Run place resolution across all unresolved place strings in the
    evidence layer. Auto-commits all clusters as Place conclusions and
    links Records via place_record.

    Safe to call on a database that already has Place conclusions —
    existing places are loaded first and new tokens are matched against
    them before any new Place is created.
    """
    result = PlaceResolutionResult()

    # Count blanks for reporting
    blank_count = conn.execute(
        "SELECT COUNT(*) FROM recorded_event "
        "WHERE place_as_recorded IS NULL OR trim(place_as_recorded) = ''"
    ).fetchone()[0]
    result.skipped_blank = blank_count

    # Collect tokens
    token_to_records = _collect_place_tokens(conn)
    if not token_to_records:
        print("  Place resolution: no place strings found in evidence layer.")
        return result

    # For each token, find its most common raw form
    raw_lookup: dict[str, str] = {}
    for norm, records in token_to_records.items():
        raw_lookup[norm] = _most_common_raw(conn, norm, records)

    # Load any existing Place conclusions so we can match against them
    # before creating new ones (safe for incremental calls)
    existing = conn.execute(
        "SELECT place_id, name FROM place"
    ).fetchall()
    existing_clusters: list[PlaceCluster] = []
    for row in existing:
        norm = _normalise(row["name"])
        existing_clusters.append(PlaceCluster(
            canonical_raw=row["name"],
            canonical_norm=norm,
            records=[],
            raw_variants=[row["name"]],
            place_id=row["place_id"],
        ))

    # Determine next IDs
    max_place = conn.execute("SELECT COALESCE(MAX(place_id), 0) FROM place").fetchone()[0]
    next_place_id = max_place + 1

    # Build clusters from evidence tokens, seeded with existing places
    # by prepending them to the sorted token list as fixed seeds.
    # Simplest approach: run clustering on evidence tokens, then merge
    # with existing places via a second pass.
    new_clusters = _build_clusters(token_to_records, raw_lookup)

    # Match new clusters against existing Place conclusions
    committed_clusters: list[PlaceCluster] = []
    for nc in new_clusters:
        matched = False
        for ec in existing_clusters:
            score = jellyfish.jaro_winkler_similarity(nc.canonical_norm, ec.canonical_norm)
            if score >= JW_THRESHOLD:
                # Merge records into the existing place
                ec.records.extend(nc.records)
                for v in nc.raw_variants:
                    if v not in ec.raw_variants:
                        ec.raw_variants.append(v)
                committed_clusters.append(ec)
                matched = True
                break
        if not matched:
            nc.place_id = next_place_id
            next_place_id += 1
            committed_clusters.append(nc)
            existing_clusters.append(nc)

    # Determine which records are already linked to avoid duplicate junction rows
    already_linked: set[int] = set(
        row[0] for row in conn.execute("SELECT record_id FROM place_record").fetchall()
    )

    # Commit to database
    with conn:
        for cluster in committed_clusters:
            is_new = cluster.place_id > max_place

            if is_new:
                # Notes: record the variant spellings found
                notes = None
                if len(cluster.raw_variants) > 1:
                    others = [v for v in cluster.raw_variants if v != cluster.canonical_raw]
                    notes = "Variants: " + "; ".join(others)

                conn.execute(
                    "INSERT INTO place (place_id, name, notes) VALUES (?, ?, ?)",
                    (cluster.place_id, cluster.canonical_raw, notes),
                )
                result.places_created += 1

            # Link records not yet in place_record
            for record_id in cluster.records:
                if record_id in already_linked:
                    continue
                # Determine score: exact normalised match = EXACT_SCORE, else AUTO_COMMIT_SCORE
                raw_for_record = conn.execute(
                    "SELECT place_as_recorded FROM recorded_event WHERE record_id = ?",
                    (record_id,),
                ).fetchone()
                if raw_for_record:
                    rec_norm = _normalise(raw_for_record["place_as_recorded"] or "")
                    score = EXACT_SCORE if rec_norm == cluster.canonical_norm else AUTO_COMMIT_SCORE
                else:
                    score = AUTO_COMMIT_SCORE

                conn.execute(
                    "INSERT INTO place_record (place_id, record_id, score, score_version, verified) "
                    "VALUES (?, ?, ?, ?, 0)",
                    (cluster.place_id, record_id, score, SCORE_VERSION),
                )
                already_linked.add(record_id)
                result.records_linked += 1

            result.clusters.append(cluster)

    return result


def print_place_resolution_report(result: PlaceResolutionResult) -> None:
    """Print a human-readable summary of place resolution results."""
    print(f"\n  PLACE RESOLUTION")
    print(f"    Places created:        {result.places_created:>6}")
    print(f"    Records linked:        {result.records_linked:>6}")
    print(f"    Skipped (blank):       {result.skipped_blank:>6}")
    print(f"\n  PLACE CLUSTERS ({len(result.clusters)})")
    for cluster in sorted(result.clusters, key=lambda c: c.canonical_raw):
        variant_note = ""
        if len(cluster.raw_variants) > 1:
            others = [v for v in cluster.raw_variants if v != cluster.canonical_raw]
            variant_note = f"  [also: {'; '.join(others)}]"
        print(f"    [{cluster.place_id:>3}] {cluster.canonical_raw:<30} {len(cluster.records):>4} records{variant_note}")
