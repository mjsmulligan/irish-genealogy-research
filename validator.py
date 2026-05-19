"""
Irish Genealogy Research — Schema Validator
Schema version: 1.2
Implements all 10 validation rules from Section 5 of genealogy_schema_v1.md

Usage:
    from validator import DataStore
    ds = DataStore()
    ds.load_all("data/")
    errors = ds.validate()
    for e in errors:
        print(e)
"""

import json
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Controlled vocabularies (Section 4)
# ---------------------------------------------------------------------------

SOURCE_TYPES = {
    "valuation",
    "census",
    "birth_registration",
    "death_registration",
    "marriage_registration",
    "parish_register",
    "manuscript",
    "gravestone",
    "directory",
}

RECORD_TYPES = {
    "valuation_entry",
    "census_return",
    "birth_registration",
    "death_registration",
    "marriage_registration",
    "baptism_entry",
    "marriage_entry",
    "burial_entry",
    "manuscript_entry",
}

DATE_QUALIFIERS = {
    "exact",
    "about",
    "before",
    "after",
    "between",
    "estimated",
    "calculated",
}

GENDER_VALUES = {"male", "female", "unknown"}

CONFIDENCE_URIS = {
    "http://gedcomx.org/High",
    "http://gedcomx.org/Medium",
    "http://gedcomx.org/Low",
}

RELATIONSHIP_TYPES = {
    "http://gedcomx.org/Couple",
    "http://gedcomx.org/ParentChild",
}

NAME_TYPES = {
    "http://gedcomx.org/BirthName",
    "http://gedcomx.org/MarriedName",
    "http://gedcomx.org/AlsoKnownAs",
    "http://gedcomx.org/Nickname",
}

FACT_TYPES = {
    "http://gedcomx.org/Birth",
    "http://gedcomx.org/Death",
    "http://gedcomx.org/Baptism",
    "http://gedcomx.org/Burial",
    "http://gedcomx.org/Marriage",
    "http://gedcomx.org/Residence",
    "http://gedcomx.org/Occupation",
    "http://gedcomx.org/Religion",
    "http://gedcomx.org/MaritalStatus",
    "http://gedcomx.org/Emigration",
}

EVENT_TYPES = {
    "http://gedcomx.org/Marriage",
    "http://gedcomx.org/Baptism",
    "http://gedcomx.org/Burial",
    "http://gedcomx.org/Census",
    "http://gedcomx.org/Emigration",
}

EVENT_ROLE_TYPES = {
    "http://gedcomx.org/Principal",
    "http://gedcomx.org/Witness",
    "http://gedcomx.org/Officiator",
    "http://gedcomx.org/Informant",
}

# ISO 8601 partial date patterns: YYYY, YYYY-MM, YYYY-MM-DD
DATE_PATTERN = re.compile(
    r"^\d{4}$"
    r"|^\d{4}-(0[1-9]|1[0-2])$"
    r"|^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"
)


# ---------------------------------------------------------------------------
# DataStore — loads all JSON files and exposes lookup indexes
# ---------------------------------------------------------------------------

class DataStore:
    """
    Loads all schema objects from the data/ directory tree and holds them
    in memory as dicts keyed by their primary key integer.
    """

    def __init__(self):
        self.sources: dict[int, dict] = {}
        self.records: dict[int, dict] = {}
        self.places: dict[int, dict] = {}
        self.named_individuals: dict[int, dict] = {}
        self.persons: dict[int, dict] = {}
        self.relationships: dict[int, dict] = {}
        self.facts: dict[int, dict] = {}
        self.events: dict[int, dict] = {}

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load_folder(self, folder: Path, store: dict, id_field: str) -> list[str]:
        """Load all JSON files in a folder into a dict keyed by id_field."""
        errors = []
        for path in sorted(folder.glob("*.json")):
            try:
                with open(path, encoding="utf-8") as f:
                    raw = json.load(f)
                # Accept either a single object or a list of objects
                items = raw if isinstance(raw, list) else [raw]
                for item in items:
                    pk = item.get(id_field)
                    if pk is None:
                        errors.append(f"[LOAD] {path.name}: missing '{id_field}' field")
                        continue
                    if pk in store:
                        errors.append(
                            f"[LOAD] {path.name}: duplicate {id_field}={pk}"
                        )
                    store[pk] = item
            except json.JSONDecodeError as exc:
                errors.append(f"[LOAD] {path.name}: JSON parse error — {exc}")
        return errors

    def load_all(self, data_dir: str = "data") -> list[str]:
        """
        Load all objects from the data/ directory tree.
        Returns a list of load errors (empty if all files parsed cleanly).
        """
        base = Path(data_dir)
        errors = []
        errors += self._load_folder(base / "sources", self.sources, "source_id")
        errors += self._load_folder(base / "records", self.records, "record_id")
        errors += self._load_folder(base / "places", self.places, "place_id")
        errors += self._load_folder(
            base / "named_individuals", self.named_individuals, "named_individual_id"
        )
        errors += self._load_folder(base / "persons", self.persons, "person_id")
        errors += self._load_folder(
            base / "relationships", self.relationships, "relationship_id"
        )
        errors += self._load_folder(base / "facts", self.facts, "fact_id")
        errors += self._load_folder(base / "events", self.events, "event_id")
        return errors

    # ------------------------------------------------------------------
    # Validation entry point
    # ------------------------------------------------------------------

    def validate(self) -> list[str]:
        """
        Run all 10 validation rules. Returns a list of error strings.
        An empty list means the dataset is valid.
        """
        errors = []
        errors += self._rule_01_referential_integrity()
        errors += self._rule_02_fact_subject_constraint()
        errors += self._rule_03_bidirectional_facts()
        errors += self._rule_04_bidirectional_named_individuals()
        errors += self._rule_05_verbatim_required()
        errors += self._rule_06_name_required_on_named_individual()
        errors += self._rule_07_record_ids_on_fact()
        errors += self._rule_08_event_role_references_named_individual()
        errors += self._rule_09_controlled_vocabulary()
        errors += self._rule_10_date_format()
        return errors

    # ------------------------------------------------------------------
    # Rule 1 — Referential integrity
    # ------------------------------------------------------------------

    def _rule_01_referential_integrity(self) -> list[str]:
        """Every foreign key must resolve to an existing object."""
        errors = []

        # Records → Sources, Places
        for rec_id, rec in self.records.items():
            if rec.get("source_id") not in self.sources:
                errors.append(
                    f"[R01] Record {rec_id}: source_id={rec.get('source_id')} not found in sources"
                )
            if (pid := rec.get("place_id")) is not None and pid not in self.places:
                errors.append(
                    f"[R01] Record {rec_id}: place_id={pid} not found in places"
                )

        # NamedIndividuals → Records
        for ni_id, ni in self.named_individuals.items():
            if ni.get("record_id") not in self.records:
                errors.append(
                    f"[R01] NamedIndividual {ni_id}: record_id={ni.get('record_id')} not found in records"
                )

        # Persons → NamedIndividuals, Facts, Relationships
        for p_id, person in self.persons.items():
            for ni_id in person.get("named_individual_ids") or []:
                if ni_id not in self.named_individuals:
                    errors.append(
                        f"[R01] Person {p_id}: named_individual_id={ni_id} not found in named_individuals"
                    )
            for f_id in person.get("fact_ids") or []:
                if f_id not in self.facts:
                    errors.append(
                        f"[R01] Person {p_id}: fact_id={f_id} not found in facts"
                    )
            for r_id in person.get("relationship_ids") or []:
                if r_id not in self.relationships:
                    errors.append(
                        f"[R01] Person {p_id}: relationship_id={r_id} not found in relationships"
                    )

        # Relationships → Persons, Facts, Records
        for rel_id, rel in self.relationships.items():
            for key in ("person_id_1", "person_id_2"):
                if rel.get(key) not in self.persons:
                    errors.append(
                        f"[R01] Relationship {rel_id}: {key}={rel.get(key)} not found in persons"
                    )
            for f_id in rel.get("fact_ids") or []:
                if f_id not in self.facts:
                    errors.append(
                        f"[R01] Relationship {rel_id}: fact_id={f_id} not found in facts"
                    )
            for rec_id in rel.get("record_ids") or []:
                if rec_id not in self.records:
                    errors.append(
                        f"[R01] Relationship {rel_id}: record_id={rec_id} not found in records"
                    )

        # Facts → Persons, Relationships, Events, Places, Records
        for f_id, fact in self.facts.items():
            if (p_id := fact.get("person_id")) is not None and p_id not in self.persons:
                errors.append(
                    f"[R01] Fact {f_id}: person_id={p_id} not found in persons"
                )
            if (r_id := fact.get("relationship_id")) is not None and r_id not in self.relationships:
                errors.append(
                    f"[R01] Fact {f_id}: relationship_id={r_id} not found in relationships"
                )
            if (e_id := fact.get("event_id")) is not None and e_id not in self.events:
                errors.append(
                    f"[R01] Fact {f_id}: event_id={e_id} not found in events"
                )
            if (pl_id := fact.get("place_id")) is not None and pl_id not in self.places:
                errors.append(
                    f"[R01] Fact {f_id}: place_id={pl_id} not found in places"
                )
            for rec_id in fact.get("record_ids") or []:
                if rec_id not in self.records:
                    errors.append(
                        f"[R01] Fact {f_id}: record_id={rec_id} not found in records"
                    )

        # Events → Places, Records, Facts, Relationships, NamedIndividuals (via roles)
        for e_id, event in self.events.items():
            if (pl_id := event.get("place_id")) is not None and pl_id not in self.places:
                errors.append(
                    f"[R01] Event {e_id}: place_id={pl_id} not found in places"
                )
            for rec_id in event.get("record_ids") or []:
                if rec_id not in self.records:
                    errors.append(
                        f"[R01] Event {e_id}: record_id={rec_id} not found in records"
                    )
            for f_id in event.get("fact_ids") or []:
                if f_id not in self.facts:
                    errors.append(
                        f"[R01] Event {e_id}: fact_id={f_id} not found in facts"
                    )
            for r_id in event.get("relationship_ids") or []:
                if r_id not in self.relationships:
                    errors.append(
                        f"[R01] Event {e_id}: relationship_id={r_id} not found in relationships"
                    )
            # FIX: check NamedIndividual references in event roles
            for i, role_entry in enumerate(event.get("roles") or []):
                ni_id = role_entry.get("named_individual_id")
                if ni_id is not None and ni_id not in self.named_individuals:
                    errors.append(
                        f"[R01] Event {e_id}, role[{i}]: named_individual_id={ni_id} not found in named_individuals"
                    )

        return errors

    # ------------------------------------------------------------------
    # Rule 2 — Fact subject constraint
    # ------------------------------------------------------------------

    def _rule_02_fact_subject_constraint(self) -> list[str]:
        """Exactly one of person_id or relationship_id must be non-null on every Fact."""
        errors = []
        for f_id, fact in self.facts.items():
            has_person = fact.get("person_id") is not None
            has_rel = fact.get("relationship_id") is not None
            if has_person and has_rel:
                errors.append(
                    f"[R02] Fact {f_id}: both person_id and relationship_id are set — exactly one must be non-null"
                )
            elif not has_person and not has_rel:
                errors.append(
                    f"[R02] Fact {f_id}: neither person_id nor relationship_id is set — exactly one must be non-null"
                )
        return errors

    # ------------------------------------------------------------------
    # Rule 3 — Bidirectional consistency: Facts
    # ------------------------------------------------------------------

    def _rule_03_bidirectional_facts(self) -> list[str]:
        """
        Bidirectional consistency for Facts in both directions:
        - If Person N lists fact_id F, then Fact F must have person_id=N.
        - If Relationship R lists fact_id F, then Fact F must have relationship_id=R.
        """
        errors = []

        # Person → Fact back-reference
        for p_id, person in self.persons.items():
            for f_id in person.get("fact_ids") or []:
                fact = self.facts.get(f_id)
                if fact is None:
                    continue  # already caught by R01
                if fact.get("person_id") != p_id:
                    errors.append(
                        f"[R03] Person {p_id} lists fact_id={f_id}, "
                        f"but Fact {f_id} has person_id={fact.get('person_id')}"
                    )

        # FIX: Relationship → Fact back-reference
        for rel_id, rel in self.relationships.items():
            for f_id in rel.get("fact_ids") or []:
                fact = self.facts.get(f_id)
                if fact is None:
                    continue  # already caught by R01
                if fact.get("relationship_id") != rel_id:
                    errors.append(
                        f"[R03] Relationship {rel_id} lists fact_id={f_id}, "
                        f"but Fact {f_id} has relationship_id={fact.get('relationship_id')}"
                    )

        return errors

    # ------------------------------------------------------------------
    # Rule 4 — Bidirectional consistency: NamedIndividuals
    # ------------------------------------------------------------------

    def _rule_04_bidirectional_named_individuals(self) -> list[str]:
        """No NamedIndividual may be claimed by more than one Person."""
        errors = []
        claimed: dict[int, int] = {}  # named_individual_id → person_id
        for p_id, person in self.persons.items():
            for ni_id in person.get("named_individual_ids") or []:
                if ni_id in claimed:
                    errors.append(
                        f"[R04] named_individual_id={ni_id} is claimed by both "
                        f"Person {claimed[ni_id]} and Person {p_id}"
                    )
                else:
                    claimed[ni_id] = p_id
        return errors

    # ------------------------------------------------------------------
    # Rule 5 — Verbatim required on Record
    # ------------------------------------------------------------------

    def _rule_05_verbatim_required(self) -> list[str]:
        """Every Record must have a non-empty verbatim field."""
        errors = []
        for rec_id, rec in self.records.items():
            v = rec.get("verbatim")
            if not v or not str(v).strip():
                errors.append(f"[R05] Record {rec_id}: verbatim field is missing or empty")
        return errors

    # ------------------------------------------------------------------
    # Rule 6 — Name required on NamedIndividual
    # ------------------------------------------------------------------

    def _rule_06_name_required_on_named_individual(self) -> list[str]:
        """Every NamedIndividual must have a non-empty name_as_recorded field."""
        errors = []
        for ni_id, ni in self.named_individuals.items():
            n = ni.get("name_as_recorded")
            if not n or not str(n).strip():
                errors.append(
                    f"[R06] NamedIndividual {ni_id}: name_as_recorded is missing or empty"
                )
        return errors

    # ------------------------------------------------------------------
    # Rule 7 — Record ids on Fact
    # ------------------------------------------------------------------

    def _rule_07_record_ids_on_fact(self) -> list[str]:
        """Every Fact must have at least one entry in record_ids."""
        errors = []
        for f_id, fact in self.facts.items():
            rec_ids = fact.get("record_ids")
            if not rec_ids:
                errors.append(
                    f"[R07] Fact {f_id}: record_ids is missing or empty — every Fact must cite at least one Record"
                )
        return errors

    # ------------------------------------------------------------------
    # Rule 8 — EventRole references NamedIndividual
    # ------------------------------------------------------------------

    def _rule_08_event_role_references_named_individual(self) -> list[str]:
        """
        Every role entry on Event must have a named_individual_id (not a person_id).
        Existence of the named_individual_id is checked in R01; this rule checks
        that the field is present and that no person_id has been mistakenly used.
        """
        errors = []
        for e_id, event in self.events.items():
            for i, role_entry in enumerate(event.get("roles") or []):
                ni_id = role_entry.get("named_individual_id")
                if ni_id is None:
                    errors.append(
                        f"[R08] Event {e_id}, role[{i}]: missing named_individual_id"
                    )
                # Flag accidental use of person_id in a role entry
                if role_entry.get("person_id") is not None:
                    errors.append(
                        f"[R08] Event {e_id}, role[{i}]: person_id must not appear in EventRole — "
                        f"use named_individual_id instead"
                    )
        return errors

    # ------------------------------------------------------------------
    # Rule 9 — Controlled vocabulary
    # ------------------------------------------------------------------

    def _rule_09_controlled_vocabulary(self) -> list[str]:
        """All vocabulary fields must use defined values. Required vocab fields are also checked for presence."""
        errors = []

        # Sources — type is required
        for src_id, src in self.sources.items():
            t = src.get("type")
            if not t:
                errors.append(f"[R09] Source {src_id}: missing required field 'type'")
            elif t not in SOURCE_TYPES:
                errors.append(f"[R09] Source {src_id}: invalid type='{t}'")

        # Records — record_type is required
        for rec_id, rec in self.records.items():
            t = rec.get("record_type")
            if not t:
                errors.append(f"[R09] Record {rec_id}: missing required field 'record_type'")
            elif t not in RECORD_TYPES:
                errors.append(f"[R09] Record {rec_id}: invalid record_type='{t}'")
            if (dq := rec.get("date_qualifier")) and dq not in DATE_QUALIFIERS:
                errors.append(f"[R09] Record {rec_id}: invalid date_qualifier='{dq}'")

        # Persons — gender is optional but must be valid if present
        for p_id, person in self.persons.items():
            if (g := person.get("gender")) and g not in GENDER_VALUES:
                errors.append(f"[R09] Person {p_id}: invalid gender='{g}'")
            # FIX: validate name type URIs
            for j, name_entry in enumerate(person.get("names") or []):
                nt = name_entry.get("type")
                if nt and nt not in NAME_TYPES:
                    errors.append(
                        f"[R09] Person {p_id}, names[{j}]: invalid name type='{nt}'"
                    )

        # Relationships — relationship_type is required
        for rel_id, rel in self.relationships.items():
            rt = rel.get("relationship_type")
            if not rt:
                errors.append(
                    f"[R09] Relationship {rel_id}: missing required field 'relationship_type'"
                )
            elif rt not in RELATIONSHIP_TYPES:
                errors.append(
                    f"[R09] Relationship {rel_id}: invalid relationship_type='{rt}'"
                )
            if (c := rel.get("confidence")) and c not in CONFIDENCE_URIS:
                errors.append(f"[R09] Relationship {rel_id}: invalid confidence='{c}'")

        # Facts — fact_type is required
        for f_id, fact in self.facts.items():
            ft = fact.get("fact_type")
            if not ft:
                errors.append(f"[R09] Fact {f_id}: missing required field 'fact_type'")
            elif ft not in FACT_TYPES:
                errors.append(f"[R09] Fact {f_id}: invalid fact_type='{ft}'")
            if (dq := fact.get("date_qualifier")) and dq not in DATE_QUALIFIERS:
                errors.append(f"[R09] Fact {f_id}: invalid date_qualifier='{dq}'")
            if (c := fact.get("confidence")) and c not in CONFIDENCE_URIS:
                errors.append(f"[R09] Fact {f_id}: invalid confidence='{c}'")

        # Events — event_type is required
        for e_id, event in self.events.items():
            et = event.get("event_type")
            if not et:
                errors.append(f"[R09] Event {e_id}: missing required field 'event_type'")
            elif et not in EVENT_TYPES:
                errors.append(f"[R09] Event {e_id}: invalid event_type='{et}'")
            if (dq := event.get("date_qualifier")) and dq not in DATE_QUALIFIERS:
                errors.append(f"[R09] Event {e_id}: invalid date_qualifier='{dq}'")
            for i, role_entry in enumerate(event.get("roles") or []):
                if (r := role_entry.get("role")) and r not in EVENT_ROLE_TYPES:
                    errors.append(
                        f"[R09] Event {e_id}, role[{i}]: invalid role='{r}'"
                    )

        return errors

    # ------------------------------------------------------------------
    # Rule 10 — Date format
    # ------------------------------------------------------------------

    def _rule_10_date_format(self) -> list[str]:
        """Date fields must match YYYY, YYYY-MM, or YYYY-MM-DD."""
        errors = []

        def check(obj_type: str, obj_id: int, date_val):
            if date_val is not None and not DATE_PATTERN.match(str(date_val)):
                errors.append(
                    f"[R10] {obj_type} {obj_id}: invalid date='{date_val}' "
                    f"(expected YYYY, YYYY-MM, or YYYY-MM-DD)"
                )

        for rec_id, rec in self.records.items():
            check("Record", rec_id, rec.get("date"))
        for f_id, fact in self.facts.items():
            check("Fact", f_id, fact.get("date"))
        for e_id, event in self.events.items():
            check("Event", e_id, event.get("date"))

        return errors


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    data_dir = sys.argv[1] if len(sys.argv) > 1 else "data"

    ds = DataStore()
    print(f"Loading data from '{data_dir}' ...")
    load_errors = ds.load_all(data_dir)

    if load_errors:
        print(f"\n{len(load_errors)} LOAD ERROR(S):")
        for e in load_errors:
            print(f"  {e}")

    print("\nRunning validation ...")
    val_errors = ds.validate()

    if not load_errors and not val_errors:
        print("OK — no errors found.")
        sys.exit(0)
    else:
        all_errors = load_errors + val_errors
        print(f"\n{len(all_errors)} ERROR(S) FOUND:")
        for e in all_errors:
            print(f"  {e}")
        sys.exit(1)
