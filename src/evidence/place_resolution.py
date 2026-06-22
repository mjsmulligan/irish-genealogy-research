"""
GRA — Place Resolution
Stage 2 of the reconstruction pipeline.

Reads all distinct place_as_recorded strings from the evidence layer,
normalises them, and matches each against the place_authority table using
Jaro-Winkler similarity on name_en. Matched strings are committed to
place_record. Unmatched strings are collected as unresolved flags.

Requires place_authority to be seeded before running:
    python -m src.db seed-places --file places.csv
or:
    python -m src.fetch_places --logainm-id 111482 --db genealogy.db

Entry point: run_place_resolution(conn) -> PlaceResolutionResult
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz.distance import JaroWinkler

SCORE_VERSION = "place_v2.0"

# Minimum Jaro-Winkler similarity to accept a match.
# Higher than person linkage (0.85) because false-positive place merges
# cause downstream damage to person linkage quality.
JW_THRESHOLD = 0.88

EXACT_SCORE = 1.0    # normalised token exactly matches authority name
FUZZY_SCORE = 0.90   # above threshold but not exact

_ABBREV = {
    r"\bco\b\.?":    "county",
    r"\bpar\b\.?":   "parish",
    r"\bbal\b\.?":   "bally",
    r"\btd\b\.?":    "townland",
}

_SUFFIXES = re.compile(
    r"\b(townland|civil parish|ded|barony|county|parish)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def _normalise(raw: str) -> str:
    s = raw.lower()

    # Handle compound "X or Y" place names by taking the primary (first) name only.
    # Historical census records often show "Tullyleague or Tullybrook" where
    # enumerators were uncertain about townland boundaries.
    if " or " in s:
        s = s.split(" or ")[0].strip()

    s = re.sub(r"[,.\-]", " ", s)
    for pattern, replacement in _ABBREV.items():
        s = re.sub(pattern, replacement, s, flags=re.IGNORECASE)
    s = _SUFFIXES.sub(" ", s)

    # Normalize double consonants to single for fuzzy matching.
    # Handles historical spelling variants like "Drummenny" vs "Drumenny".
    # Applied after tokenization to avoid affecting abbreviation expansion.
    s = re.sub(r"([bcdfghjklmnpqrstvwxyz])\1+", r"\1", s)

    s = " ".join(s.split())
    return s


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class PlaceMatch:
    place_as_recorded: str
    norm: str
    place_id: int
    name_en: str
    place_type: str
    score: float
    record_ids: list[int] = field(default_factory=list)


@dataclass
class UnresolvedPlace:
    place_as_recorded: str
    norm: str
    record_ids: list[int] = field(default_factory=list)
    best_candidate: str | None = None
    best_score: float = 0.0


@dataclass
class PlaceResolutionResult:
    matched: list[PlaceMatch] = field(default_factory=list)
    unresolved: list[UnresolvedPlace] = field(default_factory=list)
    records_linked: int = 0
    records_already_linked: int = 0
    skipped_blank: int = 0


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

def _load_authorities(conn: sqlite3.Connection) -> list[dict]:
    """
    Load all place_authority rows. For each row build a list of normalised
    name strings to match against: name_en is always included; any
    non-empty barony_name, civil_parish_name, ded_name are not used as
    match candidates (they are parent names, not this place's name).
    """
    with conn.cursor() as cur:
        cur.execute("SELECT place_id, name_en, place_type FROM place_authority")
        rows = cur.fetchall()

    authorities = []
    for row in rows:
        norms = [_normalise(row["name_en"])]
        authorities.append({
            "place_id":   row["place_id"],
            "name_en":    row["name_en"],
            "place_type": row["place_type"],
            "norms":      norms,
        })
    return authorities


def _collect_evidence_tokens(
    conn,  # psycopg2.extensions.connection
) -> tuple[dict[str, dict], int]:
    """
    Collect all distinct place_as_recorded strings from record,
    grouped by normalised token.
    Returns (token_map, blank_count).
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT record_id, place_as_recorded FROM record "
            "WHERE place_as_recorded IS NOT NULL AND trim(place_as_recorded) != ''"
        )
        rows = cur.fetchall()

        cur.execute(
            "SELECT COUNT(*) AS count FROM record "
            "WHERE place_as_recorded IS NULL OR trim(place_as_recorded) = ''"
        )
        blank_count = cur.fetchone()["count"]

    token_map: dict[str, dict] = {}
    for row in rows:
        norm = _normalise(row["place_as_recorded"])
        if not norm:
            blank_count += 1
            continue
        if norm not in token_map:
            token_map[norm] = {"raw": row["place_as_recorded"], "record_ids": []}
        token_map[norm]["record_ids"].append(row["record_id"])

    return token_map, blank_count


def _best_match(
    norm: str,
    authorities: list[dict],
) -> tuple[dict | None, float, dict | None]:
    """Return (matched_auth, score, best_candidate_auth).
    matched_auth is set only when score >= JW_THRESHOLD.
    best_candidate_auth is always the highest-scoring authority, for researcher hints.
    """
    best_auth = None
    best_score = 0.0
    for auth in authorities:
        for auth_norm in auth["norms"]:
            score = JaroWinkler.similarity(norm, auth_norm)
            if score > best_score:
                best_score = score
                best_auth = auth
    if best_score >= JW_THRESHOLD:
        return best_auth, best_score, best_auth
    return None, best_score, best_auth  # best_auth = hint even below threshold


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_place_resolution(conn: sqlite3.Connection) -> PlaceResolutionResult:
    """
    Match all unresolved place_as_recorded strings in the evidence layer
    against place_authority. Commits matched linkages to place_record.
    Collects unresolved strings for researcher attention.

    Safe to call incrementally — records already in place_record are skipped.
    Requires place_authority to be populated (run seed-places or fetch-places first).
    """
    result = PlaceResolutionResult()

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS count FROM place_authority")
        authority_count = cur.fetchone()["count"]
    if authority_count == 0:
        print(
            "  Place resolution: place_authority is empty.\n"
            "  Run 'python -m src.fetch_places' or 'python -m src.db seed-places' first."
        )
        return result

    authorities = _load_authorities(conn)
    token_map, blank_count = _collect_evidence_tokens(conn)
    result.skipped_blank = blank_count

    if not token_map:
        print("  Place resolution: no place strings found in evidence layer.")
        return result

    with conn.cursor() as cur:
        cur.execute("SELECT record_id FROM place_record")
        already_linked: set[int] = {row["record_id"] for row in cur.fetchall()}

    matches: list[PlaceMatch] = []
    unresolved: list[UnresolvedPlace] = []

    for norm, info in token_map.items():
        raw = info["raw"]
        record_ids = info["record_ids"]
        auth, score, hint_auth = _best_match(norm, authorities)

        if auth is not None:
            stored_score = EXACT_SCORE if score == 1.0 else FUZZY_SCORE
            matches.append(PlaceMatch(
                place_as_recorded=raw,
                norm=norm,
                place_id=auth["place_id"],
                name_en=auth["name_en"],
                place_type=auth["place_type"],
                score=stored_score,
                record_ids=record_ids,
            ))
        else:
            unresolved.append(UnresolvedPlace(
                place_as_recorded=raw,
                norm=norm,
                record_ids=record_ids,
                best_candidate=hint_auth["name_en"] if hint_auth else None,
                best_score=score,
            ))

    with conn:
        with conn.cursor() as cur:
            for match in matches:
                for record_id in match.record_ids:
                    if record_id in already_linked:
                        result.records_already_linked += 1
                        continue
                    cur.execute(
                        "INSERT INTO place_record "
                        "(place_id, record_id, score, score_version, verified) "
                        "VALUES (%s, %s, %s, %s, 0)",
                        (match.place_id, record_id, match.score, SCORE_VERSION),
                    )
                already_linked.add(record_id)
                result.records_linked += 1

    result.matched = matches
    result.unresolved = unresolved
    return result


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_place_resolution_report(result: PlaceResolutionResult) -> None:
    total_matched_records   = sum(len(m.record_ids) for m in result.matched)
    total_unresolved_records = sum(len(u.record_ids) for u in result.unresolved)

    print(f"\n  PLACE RESOLUTION  (authority-based, v2.0)")
    print(f"    Distinct tokens evaluated:   {len(result.matched) + len(result.unresolved):>4}")
    print(f"    Matched to authority:         {len(result.matched):>4}  tokens  ({total_matched_records} records)")
    print(f"    Unresolved:                   {len(result.unresolved):>4}  tokens  ({total_unresolved_records} records)")
    print(f"    Skipped (blank place):        {result.skipped_blank:>4}  records")
    if result.records_already_linked:
        print(f"    Already linked (skipped):    {result.records_already_linked:>4}  records")
    print(f"    Newly linked:                 {result.records_linked:>4}  records")

    if result.matched:
        print(f"\n  MATCHED ({len(result.matched)})")
        for m in sorted(result.matched, key=lambda x: x.name_en):
            score_label = "exact" if m.score == EXACT_SCORE else f"{m.score:.2f}"
            variant_note = (
                f"  ← '{m.place_as_recorded}'"
                if m.place_as_recorded.lower() != m.name_en.lower() else ""
            )
            print(
                f"    [{m.place_id:>5}] {m.name_en:<30} ({m.place_type:<14}) "
                f"{len(m.record_ids):>4} records  score={score_label}{variant_note}"
            )

    if result.unresolved:
        print(f"\n  UNRESOLVED ({len(result.unresolved)})  — researcher attention required")
        for u in sorted(result.unresolved, key=lambda x: -len(x.record_ids)):
            hint = (
                f"  closest: '{u.best_candidate}' ({u.best_score:.2f})"
                if u.best_candidate else "  no close match found"
            )
            print(f"    '{u.place_as_recorded}' ({len(u.record_ids)} records){hint}")
        print()
        print("    → Seed missing authorities: python -m src.fetch_places --logainm-id <ID> --db genealogy.db")
        print("    → Or assert manually via the service layer assert_linkage()")
