"""
GRA — Conclusion Layer: Household Continuity Linking

Links RecordedPersons across adjacent census years (1901→1911, 1911→1926)
within the same household. This step runs BEFORE Splink (person_resolution)
and exploits the near-certain prior that named household members are the same
person across censuses, using age progression as a QA signal rather than an
identity signal.

Algorithm:
  1. For each household in year A, find candidate households in year B (same
     townland, head name similarity ≥ HEAD_NAME_THRESHOLD).
  2. Confirm the head pair: name similarity + age within ±HEAD_AGE_TOLERANCE.
  3. Walk other members: match by name similarity ≥ MEMBER_NAME_THRESHOLD and
     age within ±MEMBER_AGE_TOLERANCE of expected progression.
  4. Write person_recorded_person rows with SCORE_VERSION_HOUSEHOLD_CONTINUITY.
  5. Report which RecordedPerson IDs were resolved so person_resolution can
     skip them.

Entry point:
    run_household_continuity(repo) -> HouseholdContinuityResult
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from src.db.repository import Repository
from src.constants import (
    SOURCE_ID_1901,
    SOURCE_ID_1911,
    SOURCE_ID_1926,
    SCORE_VERSION_HOUSEHOLD_CONTINUITY,
)
from src.conclusion.household_utils import get_household_members
from src.conclusion.audit import AuditLog


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

HEAD_NAME_THRESHOLD: float = 0.80
MEMBER_NAME_THRESHOLD: float = 0.70
HEAD_AGE_TOLERANCE: int = 4
MEMBER_AGE_TOLERANCE: int = 5
# Widened tolerance used when role progression strongly corroborates the match
# despite an anomalous age.  Applies only when _role_consistent returns True.
MEMBER_AGE_TOLERANCE_ROLE_CORROBORATED: int = 60

SCORE_CONTINUITY_LINK: float = 0.88   # high-confidence prior; household context anchors it
SCORE_CONTINUITY_ROLE_CORROBORATED: float = 0.78  # lower confidence — age anomaly present

CENSUS_PAIRS: list[tuple[int, int]] = [
    (SOURCE_ID_1901, SOURCE_ID_1911),
    (SOURCE_ID_1911, SOURCE_ID_1926),
]
ELAPSED_YEARS: dict[tuple[int, int], int] = {
    (SOURCE_ID_1901, SOURCE_ID_1911): 10,
    (SOURCE_ID_1911, SOURCE_ID_1926): 15,
}


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class HouseholdContinuityResult:
    household_pairs_examined: int = 0
    household_pairs_confirmed: int = 0
    persons_created: int = 0
    linkages_created: int = 0
    resolved_rp_ids: set[int] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Name similarity
# ---------------------------------------------------------------------------

_FORENAME_VARIANTS: dict[str, str] = {
    "patrick": "patrick", "pat": "patrick", "padraig": "patrick", "paddy": "patrick",
    "michael": "michael", "mike": "michael", "micheal": "michael",
    "bridget": "bridget", "bridie": "bridget", "brigid": "bridget",
    "margaret": "margaret", "maggie": "margaret", "peggy": "margaret",
    "john": "john", "seán": "john", "sean": "john",
    "mary": "mary", "marie": "mary",
    "thomas": "thomas", "tom": "thomas", "thom": "thomas",
    "william": "william", "will": "william", "bill": "william", "wm": "william",
    "james": "james", "jim": "james",
    "catherine": "catherine", "kate": "catherine", "cathy": "catherine",
    "anne": "anne", "ann": "anne", "anna": "anne",
    "elizabeth": "elizabeth", "eliza": "elizabeth", "lizzie": "elizabeth", "betty": "elizabeth",
}


def _normalise(name: str) -> str:
    """Lower-case, strip punctuation, collapse whitespace."""
    name = name.lower().strip()
    name = re.sub(r"[^a-z\s]", "", name)
    name = re.sub(r"\s+", " ", name)
    return name


def _canonical_forename(name: str) -> str:
    """Map a normalised forename to its canonical form if known."""
    first = _normalise(name).split()[0] if _normalise(name) else ""
    return _FORENAME_VARIANTS.get(first, first)


def _name_similarity(a: str, b: str) -> float:
    """
    Similarity between two full recorded names.

    Uses the canonical forename of each name as the primary signal (exact
    canonical match → 0.95 floor), then falls back to SequenceMatcher on the
    full normalised string.
    """
    if not a or not b:
        return 0.0

    na, nb = _normalise(a), _normalise(b)
    if na == nb:
        return 1.0

    ca, cb = _canonical_forename(a), _canonical_forename(b)
    if ca and cb and ca == cb:
        # Same canonical forename — use surname component as a tiebreak
        parts_a = na.split()
        parts_b = nb.split()
        surname_a = " ".join(parts_a[1:]) if len(parts_a) > 1 else ""
        surname_b = " ".join(parts_b[1:]) if len(parts_b) > 1 else ""
        if not surname_a or not surname_b:
            return 0.92
        surname_sim = SequenceMatcher(None, surname_a, surname_b).ratio()
        return max(0.85, surname_sim)

    return SequenceMatcher(None, na, nb).ratio()


def _age_match(age_a: int | None, age_b: int | None, elapsed: int, tolerance: int) -> bool:
    """True if age_b is within tolerance of age_a + elapsed."""
    if age_a is None or age_b is None:
        return True   # no age data — don't reject on it
    expected = age_a + elapsed
    return abs(age_b - expected) <= tolerance


# ---------------------------------------------------------------------------
# Role progression by succession type
# ---------------------------------------------------------------------------

# Different household head successions create different plausible role dynamics.
# These are not certainties but genealogically defensible transitions that can
# corroborate weak age matches.
#
# SAME_HEAD: Head stays the same (same person across censuses, or same name).
#   - All members' roles relative to the head remain stable.
#   - Enumerator may reclassify (e.g., grandchild→son) but relationships unchanged.
#
# SPOUSE_BECOMES_HEAD: Widow inherits head role (patriarch dies before next census).
#   - Spouse→head (widow takes role).
#   - Other roles stay the same: son stays son, grandchild stays grandchild, etc.
#   - Everyone's relationship to the household is unchanged (still the same family).
#
# CHILD_BECOMES_HEAD: Adult son/daughter inherits head role (parent(s) die).
#   - Son/daughter→head (child inherits).
#   - Grandchild→son/daughter is plausible: could be the new head's own child,
#     or an enumerator reclassification as family structure changes.
#   - Son/daughter→sibling is plausible: former siblings of the new head.
#   - Other members' progressions: conservative (stay same role).

_ROLE_PROGRESSIONS_BY_SUCCESSION: dict[str, frozenset[tuple[str, str]]] = {
    "same_head": frozenset({
        ("head", "head"),
        ("spouse", "spouse"),
        ("son", "son"),
        ("daughter", "daughter"),
        ("grandchild", "grandchild"),
        ("sibling", "sibling"),
        ("in_law", "in_law"),
        ("boarder", "boarder"),
        ("servant", "servant"),
        ("visitor", "visitor"),
        ("cousin", "cousin"),
        ("niece_nephew", "niece_nephew"),
        ("aunt_uncle", "aunt_uncle"),
        ("grandchild", "son"),          # enumerator reclassification
        ("grandchild", "daughter"),
        ("sibling", "nephew"),          # informal adoption
        ("sibling", "niece"),
    }),
    "spouse_becomes_head": frozenset({
        ("spouse", "head"),             # widow inherits head role
        ("son", "son"),                 # son stays son to widow
        ("daughter", "daughter"),
        ("grandchild", "grandchild"),   # still grandchild to widow
        ("sibling", "sibling"),
        ("in_law", "in_law"),
        ("boarder", "boarder"),
        ("servant", "servant"),
        ("visitor", "visitor"),
    }),
    "child_becomes_head": frozenset({
        ("son", "head"),                # son inherits headship
        ("daughter", "head"),           # daughter inherits headship
        ("son", "sibling"),             # brother of new head
        ("daughter", "sibling"),        # sister of new head
        ("grandchild", "son"),          # plausible: new head's own child
        ("grandchild", "daughter"),
        ("sibling", "sibling"),         # siblings stay siblings
        ("boarder", "boarder"),         # unrelated members stay same
        ("servant", "servant"),
        ("visitor", "visitor"),
    }),
}


def _role_consistent(
    role_a: str | None,
    role_b: str | None,
    succession_type: str = "same_head",
) -> bool | None:
    """
    Returns True if the role transition is plausible under the given succession
    type, False if implausible, None if either role is missing or 'unknown'.

    A False return causes _match_member to skip the candidate.
    A True return widens age tolerance when age is the only failing signal.

    Args:
        role_a: Role in year A (e.g., 'son', 'grandchild')
        role_b: Role in year B
        succession_type: One of "same_head", "spouse_becomes_head", "child_becomes_head"
    """
    if not role_a or not role_b or role_a == "unknown" or role_b == "unknown":
        return None
    progressions = _ROLE_PROGRESSIONS_BY_SUCCESSION.get(succession_type, frozenset())
    return (role_a, role_b) in progressions


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_records_for_source(repo: Repository, source_id: int) -> list[dict]:
    """
    Return all census records that have a resolved place_id.
    Uses place_record join so downstream grouping is by canonical place authority.
    Records without a place_record row (unresolved places) are skipped — continuity
    cannot safely match them.
    """
    return repo.fetch_all(
        """
        SELECT r.record_id, pr.place_id
        FROM record r
        JOIN place_record pr ON pr.record_id = r.record_id
        WHERE r.source_id = %s
        ORDER BY r.record_id
        """,
        (source_id,),
    )


def _get_records_for_place_id(
    repo: Repository,
    place_id: int,
    source_id: int,
) -> list[dict]:
    """Return records sharing the canonical place_id for a given source."""
    return repo.fetch_all(
        """
        SELECT r.record_id, pr.place_id
        FROM record r
        JOIN place_record pr ON pr.record_id = r.record_id
        WHERE r.source_id = %s
          AND pr.place_id = %s
        ORDER BY r.record_id
        """,
        (source_id, place_id),
    )


def _head_of(members: list[dict]) -> dict | None:
    """Return the head member from a household member list, or None."""
    for m in members:
        if (m.get("role") or "").lower() == "head":
            return m
    return None


def _spouse_of(members: list[dict]) -> dict | None:
    """Return the spouse member from a household member list, or None."""
    for m in members:
        if (m.get("role") or "").lower() == "spouse":
            return m
    return None


# ---------------------------------------------------------------------------
# Person create / link helpers (mirrors household_resolution.py)
# ---------------------------------------------------------------------------

def _get_or_create_person(
    repo: Repository,
    rp: dict,
    score: float,
    change_group_id: str,
) -> int:
    """
    Return existing person_id if rp is already linked, otherwise create a new
    Person, link rp to it, and return the new person_id.
    """
    from src.dal.person_repo import create_person, link_person_to_recorded_person

    if rp.get("person_id"):
        return rp["person_id"]

    name = rp.get("name_as_recorded") or "Unknown"
    gender = None
    sex = rp.get("sex_as_recorded")
    if sex and sex.upper() in ("M", "F"):
        gender = "male" if sex.upper() == "M" else "female"

    place_row = repo.fetch_one(
        """
        SELECT place_as_recorded FROM record
        WHERE record_id = (
            SELECT record_id FROM recorded_person
            WHERE recorded_person_id = %s
        )
        """,
        (rp["recorded_person_id"],),
    )
    place = place_row["place_as_recorded"] if place_row else "Unknown"
    label = f"{name} ({place})"

    person_id = create_person(repo, label=label, gender=gender)

    AuditLog.log_create(
        repo,
        entity_type="person",
        entity_id=person_id,
        values={"label": label, "gender": gender or "unknown", "status": "active"},
        reason="Created via household continuity linking",
        change_group_id=change_group_id,
    )

    link_person_to_recorded_person(
        repo,
        person_id=person_id,
        recorded_person_id=rp["recorded_person_id"],
        score=score,
        score_version=SCORE_VERSION_HOUSEHOLD_CONTINUITY,
        verified=False,
    )

    AuditLog.log_create(
        repo,
        entity_type="person_recorded_person",
        entity_id=rp["recorded_person_id"],
        values={
            "person_id": person_id,
            "recorded_person_id": rp["recorded_person_id"],
            "score": score,
            "score_version": SCORE_VERSION_HOUSEHOLD_CONTINUITY,
        },
        reason="Linked via household continuity (year A)",
        change_group_id=change_group_id,
    )

    return person_id


def _link_to_existing_person(
    repo: Repository,
    person_id: int,
    rp: dict,
    score: float,
    change_group_id: str,
) -> None:
    """Link rp to an already-established person_id."""
    from src.dal.person_repo import link_person_to_recorded_person

    link_person_to_recorded_person(
        repo,
        person_id=person_id,
        recorded_person_id=rp["recorded_person_id"],
        score=score,
        score_version=SCORE_VERSION_HOUSEHOLD_CONTINUITY,
        verified=False,
    )

    AuditLog.log_create(
        repo,
        entity_type="person_recorded_person",
        entity_id=rp["recorded_person_id"],
        values={
            "person_id": person_id,
            "recorded_person_id": rp["recorded_person_id"],
            "score": score,
            "score_version": SCORE_VERSION_HOUSEHOLD_CONTINUITY,
        },
        reason="Linked via household continuity (year B)",
        change_group_id=change_group_id,
    )


def _already_linked(rp: dict) -> bool:
    return bool(rp.get("person_id"))


# ---------------------------------------------------------------------------
# Core matching
# ---------------------------------------------------------------------------

def _match_member(
    candidate: dict,
    pool: list[dict],
    elapsed: int,
    name_threshold: float,
    age_tolerance: int,
    exclude_rp_ids: set[int],
    succession_type: str = "same_head",
) -> tuple[dict | None, bool]:
    """
    Find the best match for `candidate` in `pool` by name similarity + age
    progression, with role progression as a corroborating signal.

    Returns (best_match, role_corroborated).

    Role logic (succession_type-aware):
    - Implausible role transition → skip candidate unconditionally.
    - Plausible role transition + age fails normal tolerance → retry with
      MEMBER_AGE_TOLERANCE_ROLE_CORROBORATED (wide tolerance for digit errors).
    - Role match is used as a tie-breaker: score += 0.05 bonus for consistent
      role, so a slightly lower name-sim but role-consistent member wins.
    - role_corroborated=True is returned when age only passed under the wide
      tolerance, flagging the link for age_progression_anomaly review.

    Args:
        succession_type: One of "same_head", "spouse_becomes_head", "child_becomes_head"
    """
    best_match: dict | None = None
    best_score: float = -1.0
    best_role_corroborated: bool = False

    for member in pool:
        if member["recorded_person_id"] in exclude_rp_ids:
            continue

        sim = _name_similarity(
            candidate.get("name_as_recorded", ""),
            member.get("name_as_recorded", ""),
        )
        if sim < name_threshold:
            continue

        role_consistent = _role_consistent(
            candidate.get("role"), member.get("role"), succession_type=succession_type
        )

        # Hard reject: implausible role transition
        if role_consistent is False:
            continue

        age_ok = _age_match(candidate.get("age"), member.get("age"), elapsed, age_tolerance)
        role_corroborated = False

        if not age_ok:
            # Age fails normal tolerance — try wide tolerance if role corroborates
            if role_consistent is True and _age_match(
                candidate.get("age"), member.get("age"),
                elapsed, MEMBER_AGE_TOLERANCE_ROLE_CORROBORATED
            ):
                age_ok = True
                role_corroborated = True
            else:
                continue

        # Role-consistent matches get a small score bonus as tie-breaker
        effective_score = sim + (0.05 if role_consistent is True else 0.0)

        if effective_score > best_score:
            best_score = effective_score
            best_match = member
            best_role_corroborated = role_corroborated

    return best_match, best_role_corroborated


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_household_continuity(repo: Repository) -> HouseholdContinuityResult:
    """
    Link RecordedPersons across adjacent census years within the same household.

    Runs BEFORE person_resolution so Splink only handles genuine cross-household
    uncertainty.
    """
    result = HouseholdContinuityResult()

    for source_a, source_b in CENSUS_PAIRS:
        elapsed = ELAPSED_YEARS[(source_a, source_b)]
        records_a = _get_records_for_source(repo, source_a)

        for rec_a in records_a:
            place_id = rec_a.get("place_id")
            if not place_id:
                continue

            # Find candidate households in the same canonical place in year B
            records_b = _get_records_for_place_id(repo, place_id, source_b)
            if not records_b:
                continue

            members_a = get_household_members(repo, rec_a["record_id"])
            head_a = _head_of(members_a)
            if not head_a:
                continue

            # Find the best matching household in year B by head name similarity
            best_rec_b: dict | None = None
            best_head_b: dict | None = None
            best_head_sim: float = -1.0

            for rec_b in records_b:
                members_b = get_household_members(repo, rec_b["record_id"])
                head_b = _head_of(members_b)
                if not head_b:
                    continue

                sim = _name_similarity(
                    head_a.get("name_as_recorded", ""),
                    head_b.get("name_as_recorded", ""),
                )
                if sim < HEAD_NAME_THRESHOLD:
                    continue
                if not _age_match(
                    head_a.get("age"), head_b.get("age"), elapsed, HEAD_AGE_TOLERANCE
                ):
                    continue

                result.household_pairs_examined += 1

                if sim > best_head_sim:
                    best_head_sim = sim
                    best_rec_b = rec_b
                    best_head_b = head_b

            if best_rec_b is None:
                # Spouse fallback: year-A spouse may have become year-B head
                # (widowhood succession — patriarch dies, widow takes head role).
                spouse_a = _spouse_of(members_a)
                if spouse_a:
                    for rec_b in records_b:
                        members_b_try = get_household_members(repo, rec_b["record_id"])
                        head_b_try = _head_of(members_b_try)
                        if not head_b_try:
                            continue
                        sim = _name_similarity(
                            spouse_a.get("name_as_recorded", ""),
                            head_b_try.get("name_as_recorded", ""),
                        )
                        if sim < HEAD_NAME_THRESHOLD:
                            continue
                        if not _age_match(
                            spouse_a.get("age"), head_b_try.get("age"), elapsed, HEAD_AGE_TOLERANCE
                        ):
                            continue
                        result.household_pairs_examined += 1
                        if sim > best_head_sim:
                            best_head_sim = sim
                            best_rec_b = rec_b
                            best_head_b = head_b_try

            if best_rec_b is None:
                # Child succession fallback: any year-A son/daughter may have
                # become year-B head (adult child inherits after parent(s) die).
                non_head_a = [m for m in members_a if m["recorded_person_id"] != head_a["recorded_person_id"]]
                for child_a in non_head_a:
                    if child_a.get("role") not in ("son", "daughter"):
                        continue
                    for rec_b in records_b:
                        members_b_try = get_household_members(repo, rec_b["record_id"])
                        head_b_try = _head_of(members_b_try)
                        if not head_b_try:
                            continue
                        sim = _name_similarity(
                            child_a.get("name_as_recorded", ""),
                            head_b_try.get("name_as_recorded", ""),
                        )
                        if sim < HEAD_NAME_THRESHOLD:
                            continue
                        if not _age_match(
                            child_a.get("age"), head_b_try.get("age"), elapsed, HEAD_AGE_TOLERANCE
                        ):
                            continue
                        result.household_pairs_examined += 1
                        if sim > best_head_sim:
                            best_head_sim = sim
                            best_rec_b = rec_b
                            best_head_b = head_b_try

            if best_rec_b is None:
                continue

            # Confirmed household pair
            result.household_pairs_confirmed += 1
            members_b = get_household_members(repo, best_rec_b["record_id"])
            change_group_id = str(uuid.uuid4())

            # Determine succession type based on how the household pair was confirmed
            if head_a["recorded_person_id"] == best_head_b["recorded_person_id"]:
                # Head-to-head match: same person remains head (both recorded as head)
                succession_type = "same_head"
            else:
                # Check which fallback matched by looking at year-A role that matched year-B head
                spouse_a = _spouse_of(members_a)
                if spouse_a and _name_similarity(
                    spouse_a.get("name_as_recorded", ""),
                    best_head_b.get("name_as_recorded", ""),
                ) >= HEAD_NAME_THRESHOLD:
                    # Spouse→head: name matches indicate widow became head
                    succession_type = "spouse_becomes_head"
                else:
                    # Child→head: adult child inherited headship
                    succession_type = "child_becomes_head"

            # Track which year-B members have been claimed this round
            claimed_b: set[int] = set()

            with repo:
                # --- Link the head(s) ---
                # In child succession, best_head_b is a child from year-A who became year-B head.
                # We need to establish a Person that encompasses both head_a and best_head_b.
                # In spouse succession or same_head, just link year-A head to year-B head.
                if succession_type == "child_becomes_head":
                    # Find the year-A member who became year-B head (should be in non_head_a)
                    child_who_became_head = None
                    for m in members_a:
                        sim = _name_similarity(
                            m.get("name_as_recorded", ""),
                            best_head_b.get("name_as_recorded", ""),
                        )
                        if sim >= HEAD_NAME_THRESHOLD and m["role"] in ("son", "daughter"):
                            child_who_became_head = m
                            break

                    if child_who_became_head and not _already_linked(child_who_became_head):
                        person_id = _get_or_create_person(
                            repo, child_who_became_head, SCORE_CONTINUITY_LINK, change_group_id
                        )
                        result.persons_created += 1
                        result.linkages_created += 1
                        result.resolved_rp_ids.add(child_who_became_head["recorded_person_id"])
                    elif child_who_became_head and _already_linked(child_who_became_head):
                        person_id = child_who_became_head["person_id"]
                    else:
                        # Fallback: create person from best_head_b
                        person_id = _get_or_create_person(
                            repo, best_head_b, SCORE_CONTINUITY_LINK, change_group_id
                        )
                        result.persons_created += 1
                        result.linkages_created += 1
                        result.resolved_rp_ids.add(best_head_b["recorded_person_id"])

                    # Link best_head_b to the same person
                    if not _already_linked(best_head_b):
                        _link_to_existing_person(
                            repo, person_id, best_head_b, SCORE_CONTINUITY_LINK, change_group_id
                        )
                        result.linkages_created += 1
                        result.resolved_rp_ids.add(best_head_b["recorded_person_id"])
                        claimed_b.add(best_head_b["recorded_person_id"])
                else:
                    # Same_head or spouse_becomes_head: normal head linking
                    # First check for conflict: both heads already linked to different Persons
                    head_a_person_id = head_a.get("person_id") if _already_linked(head_a) else None
                    head_b_person_id = best_head_b.get("person_id") if _already_linked(best_head_b) else None

                    if head_a_person_id and head_b_person_id and head_a_person_id != head_b_person_id:
                        # Conflict: heads already linked to different Persons
                        # Merge the two Persons: move all RecordedPersons from head_b_person to head_a_person
                        from src.dal.person_repo import merge_persons
                        AuditLog.log_merge(
                            repo,
                            keep_person_id=head_a_person_id,
                            merge_person_id=head_b_person_id,
                            reason="Household continuity merged split heads from same household pair",
                            change_group_id=change_group_id,
                        )
                        merge_persons(repo, head_a_person_id, head_b_person_id)
                        person_id = head_a_person_id
                        result.resolved_rp_ids.add(best_head_b["recorded_person_id"])
                    elif not _already_linked(head_a):
                        person_id = _get_or_create_person(
                            repo, head_a, SCORE_CONTINUITY_LINK, change_group_id
                        )
                        result.persons_created += 1
                        result.linkages_created += 1
                        result.resolved_rp_ids.add(head_a["recorded_person_id"])
                    else:
                        person_id = head_a["person_id"]

                    if not _already_linked(best_head_b):
                        _link_to_existing_person(
                            repo, person_id, best_head_b, SCORE_CONTINUITY_LINK, change_group_id
                        )
                        result.linkages_created += 1
                        result.resolved_rp_ids.add(best_head_b["recorded_person_id"])
                        claimed_b.add(best_head_b["recorded_person_id"])

                # --- Walk other members ---
                non_head_a = [m for m in members_a if m["recorded_person_id"] != head_a["recorded_person_id"]]
                non_head_b = [m for m in members_b if m["recorded_person_id"] != best_head_b["recorded_person_id"]]

                for member_a in non_head_a:
                    match_b, role_corroborated = _match_member(
                        member_a,
                        non_head_b,
                        elapsed,
                        name_threshold=MEMBER_NAME_THRESHOLD,
                        age_tolerance=MEMBER_AGE_TOLERANCE,
                        exclude_rp_ids=claimed_b,
                        succession_type=succession_type,
                    )
                    if match_b is None:
                        continue

                    claimed_b.add(match_b["recorded_person_id"])

                    # Role-corroborated links (age anomaly present) use lower score
                    link_score = (
                        SCORE_CONTINUITY_ROLE_CORROBORATED if role_corroborated
                        else SCORE_CONTINUITY_LINK
                    )

                    if not _already_linked(member_a):
                        pid = _get_or_create_person(
                            repo, member_a, link_score, change_group_id
                        )
                        result.persons_created += 1
                        result.linkages_created += 1
                        result.resolved_rp_ids.add(member_a["recorded_person_id"])
                    else:
                        pid = member_a["person_id"]

                    if not _already_linked(match_b):
                        _link_to_existing_person(
                            repo, pid, match_b, link_score, change_group_id
                        )
                        result.linkages_created += 1
                        result.resolved_rp_ids.add(match_b["recorded_person_id"])

    return result
