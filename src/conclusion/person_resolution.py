"""
GRA — Conclusion Layer: Person Resolution

Creates Person conclusions from RecordedPerson evidence using person-level
similarity scores. This is Step 1 of the conclusion pipeline.

Design:
  - Conservative clustering using similarity scores ≥ AUTO_COMMIT_THRESHOLD (0.85)
  - Connected components algorithm to handle transitive matches
  - Orphan RecordedPersons (no similarity matches) remain unlinked
  - No Person created for orphans in this step — they're handled by
    Relationship Resolution (Step 2) with additional context

Relationship Resolution (Step 2) will:
  - Use primary evidence (recorded roles, household structure) to refine the
    Person graph, including merging Persons when relationship patterns
    contradict the initial clustering
  - Link orphan RecordedPersons to existing Persons or create new Persons
    with relationship/household context

Entry point:
    run_person_resolution(conn) -> PersonResolutionResult
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from src.db.repository import Repository
from src.constants import PERSON_RESOLUTION_THRESHOLD
from src.genealogy import evaluate_pair, CENSUS_YEAR


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class PersonResolutionResult:
    persons_created: int = 0
    linkages_created: int = 0
    clusters_formed: int = 0
    orphans_count: int = 0
    largest_cluster_size: int = 0
    similarity_pairs_used: int = 0
    threshold: float = PERSON_RESOLUTION_THRESHOLD


# ---------------------------------------------------------------------------
# Connected Components (Union-Find)
# ---------------------------------------------------------------------------

class UnionFind:
    """
    Union-Find data structure for connected components clustering.

    Each RecordedPerson is a node. Similarity edges above threshold connect
    nodes. This finds all connected subgraphs (clusters).
    """

    def __init__(self):
        self.parent: dict[int, int] = {}
        self.rank: dict[int, int] = {}

    def add(self, node: int) -> None:
        """Add a node if it doesn't exist."""
        if node not in self.parent:
            self.parent[node] = node
            self.rank[node] = 0

    def find(self, node: int) -> int:
        """Find root of node's tree with path compression."""
        if self.parent[node] != node:
            self.parent[node] = self.find(self.parent[node])
        return self.parent[node]

    def union(self, node1: int, node2: int) -> None:
        """Merge two nodes' trees by rank."""
        root1 = self.find(node1)
        root2 = self.find(node2)

        if root1 == root2:
            return

        # Union by rank
        if self.rank[root1] < self.rank[root2]:
            self.parent[root1] = root2
        elif self.rank[root1] > self.rank[root2]:
            self.parent[root2] = root1
        else:
            self.parent[root2] = root1
            self.rank[root1] += 1

    def get_clusters(self) -> dict[int, list[int]]:
        """
        Return clusters as {root_id: [member_ids]}.
        Only includes nodes that were added via add() or union().
        """
        clusters: dict[int, list[int]] = defaultdict(list)
        for node in self.parent:
            root = self.find(node)
            clusters[root].append(node)
        return dict(clusters)


# ---------------------------------------------------------------------------
# Person label generation
# ---------------------------------------------------------------------------

def _generate_person_label(
    repo: Repository,
    recorded_person_ids: list[int],
) -> str:
    """
    Generate a human-readable label for a Person from its constituent
    RecordedPersons.

    Format: "Name (Townland)"

    Strategy:
      - Name: use the most common name variant across all RecordedPersons
      - Townland: use the most common place name

    Falls back to first RecordedPerson's values if aggregation unclear.
    """
    if not recorded_person_ids:
        return "Unknown Person"

    # Fetch all RecordedPersons in this cluster
    placeholders = ",".join(["%s"] * len(recorded_person_ids))
    rows = repo.fetch_all(
        f"""
        SELECT rp.name_as_recorded, r.place_as_recorded
        FROM recorded_person rp
        JOIN record r ON r.record_id = rp.record_id
        WHERE rp.recorded_person_id IN ({placeholders})
        """,
        tuple(recorded_person_ids),
    )

    if not rows:
        return "Unknown Person"

    # Pick most common name
    name_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        if row["name_as_recorded"]:
            name_counts[row["name_as_recorded"]] += 1

    if name_counts:
        most_common_name = max(name_counts.items(), key=lambda x: x[1])[0]
    else:
        most_common_name = "Unknown"

    # Pick most common place
    place_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        if row["place_as_recorded"]:
            place_counts[row["place_as_recorded"]] += 1

    if place_counts:
        most_common_place = max(place_counts.items(), key=lambda x: x[1])[0]
    else:
        most_common_place = "Unknown"

    return f"{most_common_name} ({most_common_place})"


# ---------------------------------------------------------------------------
# Gender resolution
# ---------------------------------------------------------------------------

def _resolve_gender(
    repo: Repository,
    recorded_person_ids: list[int],
) -> str | None:
    """
    Resolve gender for a Person from its RecordedPersons using majority vote.

    Returns 'male', 'female', or None if no consensus or all NULL.
    """
    placeholders = ",".join(["%s"] * len(recorded_person_ids))
    rows = repo.fetch_all(
        f"""
        SELECT sex_as_recorded
        FROM recorded_person
        WHERE recorded_person_id IN ({placeholders})
          AND sex_as_recorded IS NOT NULL
        """,
        tuple(recorded_person_ids),
    )
    sex_values = [row["sex_as_recorded"] for row in rows]

    if not sex_values:
        return None

    # Map to canonical values
    sex_map = {"M": "male", "F": "female", "m": "male", "f": "female"}
    canonical = [sex_map.get(s) for s in sex_values]
    canonical = [s for s in canonical if s]  # Remove None

    if not canonical:
        return None

    # Majority vote
    male_count = canonical.count("male")
    female_count = canonical.count("female")

    if male_count > female_count:
        return "male"
    elif female_count > male_count:
        return "female"
    else:
        # Tie or all unknown
        return None


# ---------------------------------------------------------------------------
# Validation filtering (Option 2)
# ---------------------------------------------------------------------------

def _filter_invalid_pairs(
    repo: Repository,
    pairs: list[dict],
) -> list[dict]:
    """
    Filter out linkage pairs that fail genealogical constraints before clustering.

    Delegates all constraint logic to src.genealogy.evaluate_pair(), which is
    the single authoritative gate for pairwise RecordedPerson evaluation.

    Returns subset of pairs that pass all constraints.
    """
    valid_pairs = []

    for pair in pairs:
        rp_id_1 = pair["recorded_person_id_1"]
        rp_id_2 = pair["recorded_person_id_2"]

        rows = repo.fetch_all(
            """
            SELECT rp.age, r.source_id, rp.name_as_recorded
            FROM recorded_person rp
            JOIN record r ON r.record_id = rp.record_id
            WHERE rp.recorded_person_id IN (%s, %s)
            ORDER BY rp.recorded_person_id
            """,
            (rp_id_1, rp_id_2),
        )

        if len(rows) != 2:
            continue

        p1, p2 = rows[0], rows[1]

        # Hard constraint: same-census pairs are always rejected
        if p1["source_id"] == p2["source_id"]:
            continue

        evaluation = evaluate_pair(
            name1=p1["name_as_recorded"],
            age1=float(p1["age"]) if p1["age"] is not None else None,
            source_id_1=p1["source_id"],
            name2=p2["name_as_recorded"],
            age2=float(p2["age"]) if p2["age"] is not None else None,
            source_id_2=p2["source_id"],
        )

        if evaluation.passes:
            valid_pairs.append(pair)

    return valid_pairs


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_person_resolution(
    repo: Repository,
    threshold: float = PERSON_RESOLUTION_THRESHOLD,
) -> PersonResolutionResult:
    """
    Run Person Resolution: cluster RecordedPersons using person-level
    similarity scores and create Person conclusions.

    Algorithm:
      1. Fetch all person similarity pairs ≥ threshold
      2. Build connected components (clusters) using Union-Find
      3. Create one Person per cluster
      4. Link each RecordedPerson to its Person via person_recorded_person
      5. Orphans (RecordedPersons with no similarity matches) remain unlinked

    Relationship Resolution (Step 2) will handle orphans with additional
    context from household structure and semantic relationships.

    Returns PersonResolutionResult with counts and statistics.
    """
    result = PersonResolutionResult(threshold=threshold)

    # Step 1: Fetch similarity pairs above threshold
    similarity_pairs = repo.fetch_all(
        """
        SELECT recorded_person_id_1, recorded_person_id_2, score
        FROM recorded_relationship
        WHERE type = 'similarity'
          AND score >= %s
        ORDER BY score DESC
        """,
        (threshold,),
    )

    result.similarity_pairs_used = len(similarity_pairs)

    if not similarity_pairs:
        # No similarities above threshold — all RecordedPersons are orphans
        count_row = repo.fetch_one("SELECT COUNT(*) as count FROM recorded_person")
        result.orphans_count = count_row["count"]
        return result

    # Step 1b: Filter out invalid pairs (Option 2 pre-clustering validation)
    similarity_pairs = _filter_invalid_pairs(repo, similarity_pairs)

    if not similarity_pairs:
        # All pairs filtered out by validation — all RecordedPersons are orphans
        count_row = repo.fetch_one("SELECT COUNT(*) as count FROM recorded_person")
        result.orphans_count = count_row["count"]
        return result

    # Step 2: Build connected components
    uf = UnionFind()

    for pair in similarity_pairs:
        rp1 = pair["recorded_person_id_1"]
        rp2 = pair["recorded_person_id_2"]
        uf.add(rp1)
        uf.add(rp2)
        uf.union(rp1, rp2)

    clusters = uf.get_clusters()
    result.clusters_formed = len(clusters)

    if clusters:
        result.largest_cluster_size = max(len(members) for members in clusters.values())

    # Step 3: Create one Person per cluster
    from src.dal.person_repo import create_person, link_person_to_recorded_person

    for root, members in clusters.items():
        # Validate cluster: remove any members that share a census source with another member
        # This catches transitive same-census linkages (A→B cross-census, B→C cross-census, but A and C same-census)
        valid_members = []
        member_sources: dict[int, int] = {}  # rp_id -> source_id

        # Get source_id for each member
        member_source_rows = repo.fetch_all(
            "SELECT rp.recorded_person_id, r.source_id "
            "FROM recorded_person rp "
            "JOIN record r ON rp.record_id = r.record_id "
            "WHERE rp.recorded_person_id = ANY(%s)",
            (members,),
        )
        for row in member_source_rows:
            member_sources[row["recorded_person_id"]] = row["source_id"]

        # Keep only members that don't share source_id with any other member
        for rp_id in members:
            source_id = member_sources.get(rp_id)
            # Check if any other member has the same source_id
            if not any(other_id != rp_id and member_sources.get(other_id) == source_id for other_id in members):
                valid_members.append(rp_id)

        if not valid_members:
            # Cluster invalid; skip it
            continue

        # Generate label and resolve gender
        label = _generate_person_label(repo, valid_members)
        gender = _resolve_gender(repo, valid_members)

        # Create Person
        person_id = create_person(repo, label=label, gender=gender)
        result.persons_created += 1

        # Link all RecordedPersons to this Person
        for rp_id in valid_members:
            link_person_to_recorded_person(
                repo,
                person_id=person_id,
                recorded_person_id=rp_id,
                score=None,  # No score for clustering-based linkage
                score_version=None,
                verified=False,
            )
            result.linkages_created += 1

    # Step 4: Count orphans (RecordedPersons not in any cluster)
    total_rp_row = repo.fetch_one("SELECT COUNT(*) as count FROM recorded_person")
    total_rp = total_rp_row["count"]

    result.orphans_count = total_rp - result.linkages_created

    return result


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

def print_person_resolution_report(result: PersonResolutionResult) -> None:
    print("\n  PERSON RESOLUTION")
    print(f"    Threshold:               {result.threshold:.2f}")
    print(f"    Similarity pairs used:   {result.similarity_pairs_used:>6}")
    print(f"    Clusters formed:         {result.clusters_formed:>6}")
    print(f"    Largest cluster size:    {result.largest_cluster_size:>6}")
    print(f"    Persons created:         {result.persons_created:>6}")
    print(f"    Linkages created:        {result.linkages_created:>6}")
    print(f"    Orphans (unlinked):      {result.orphans_count:>6}")
