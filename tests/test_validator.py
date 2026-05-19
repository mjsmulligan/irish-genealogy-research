"""
Irish Genealogy Research — Validator Test Suite
Schema version: 1.2
Tests all 10 validation rules from Section 5 of genealogy_schema_v1.md

Run with:
    pytest tests/test_validator.py -v
"""

import copy
import pytest
from validator import DataStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_ds(
    sources=None,
    records=None,
    places=None,
    named_individuals=None,
    persons=None,
    relationships=None,
    facts=None,
    events=None,
) -> DataStore:
    """
    Build a DataStore directly from dicts, bypassing file I/O.
    Each argument is a list of objects; they are indexed by their primary key.
    """
    ds = DataStore()
    for src in sources or []:
        src = copy.deepcopy(src)
        ds.sources[src["source_id"]] = src
    for rec in records or []:
        rec = copy.deepcopy(rec)
        ds.records[rec["record_id"]] = rec
    for pl in places or []:
        pl = copy.deepcopy(pl)
        ds.places[pl["place_id"]] = pl
    for ni in named_individuals or []:
        ni = copy.deepcopy(ni)
        ds.named_individuals[ni["named_individual_id"]] = ni
    for p in persons or []:
        p = copy.deepcopy(p)
        ds.persons[p["person_id"]] = p
    for rel in relationships or []:
        rel = copy.deepcopy(rel)
        ds.relationships[rel["relationship_id"]] = rel
    for f in facts or []:
        f = copy.deepcopy(f)
        ds.facts[f["fact_id"]] = f
    for ev in events or []:
        ev = copy.deepcopy(ev)
        ds.events[ev["event_id"]] = ev
    return ds


def error_codes(errors: list[str]) -> list[str]:
    """Extract rule codes from error strings e.g. '[R01]' → 'R01'."""
    return [e[1:4] for e in errors if e.startswith("[")]


def has_error(errors: list[str], code: str, fragment: str = "") -> bool:
    """Return True if any error matches the given rule code and optional text fragment."""
    return any(
        e[1:4] == code and fragment in e
        for e in errors
    )


# ---------------------------------------------------------------------------
# Minimal valid fixtures — reused across tests
# ---------------------------------------------------------------------------

VALID_SOURCE = {
    "source_id": 1,
    "title": "Griffith's Valuation",
    "type": "valuation",
    "repository": "Askaboutireland.ie",
}

VALID_PLACE = {
    "place_id": 10,
    "name": "Straness",
}

VALID_RECORD = {
    "record_id": 100,
    "source_id": 1,
    "record_type": "valuation_entry",
    "verbatim": "John Mulligan, Straness, house and land",
}

VALID_NAMED_INDIVIDUAL = {
    "named_individual_id": 200,
    "record_id": 100,
    "label": "John Mulligan (Griffiths 1857)",
    "name_as_recorded": "John Mulligan",
}

VALID_PERSON = {
    "person_id": 42,
    "label": "John Mulligan of Straness",
    "named_individual_ids": [200],
    "fact_ids": [300],
    "relationship_ids": [400],
}

VALID_PERSON_2 = {
    "person_id": 43,
    "label": "Mary Mulligan of Straness",
    "named_individual_ids": [],
    "fact_ids": [301],
    "relationship_ids": [400],
}

VALID_RELATIONSHIP = {
    "relationship_id": 400,
    "relationship_type": "http://gedcomx.org/Couple",
    "person_id_1": 42,
    "person_id_2": 43,
    "fact_ids": [],
    "record_ids": [100],
}

VALID_FACT_PERSON = {
    "fact_id": 300,
    "person_id": 42,
    "relationship_id": None,
    "fact_type": "http://gedcomx.org/Residence",
    "record_ids": [100],
}

VALID_FACT_PERSON_2 = {
    "fact_id": 301,
    "person_id": 43,
    "relationship_id": None,
    "fact_type": "http://gedcomx.org/Residence",
    "record_ids": [100],
}

VALID_EVENT = {
    "event_id": 500,
    "event_type": "http://gedcomx.org/Marriage",
    "record_ids": [100],
    "fact_ids": [300],
    "relationship_ids": [400],
    "roles": [
        {"named_individual_id": 200, "role": "http://gedcomx.org/Principal"},
    ],
}


def valid_ds() -> DataStore:
    """A fully consistent minimal dataset that should produce zero errors."""
    return make_ds(
        sources=[VALID_SOURCE],
        places=[VALID_PLACE],
        records=[VALID_RECORD],
        named_individuals=[VALID_NAMED_INDIVIDUAL],
        persons=[VALID_PERSON, VALID_PERSON_2],
        relationships=[VALID_RELATIONSHIP],
        facts=[VALID_FACT_PERSON, VALID_FACT_PERSON_2],
        events=[VALID_EVENT],
    )


# ---------------------------------------------------------------------------
# Baseline — valid dataset produces no errors
# ---------------------------------------------------------------------------

class TestBaseline:
    def test_valid_dataset_produces_no_errors(self):
        errors = valid_ds().validate()
        assert errors == [], f"Expected no errors, got: {errors}"


# ---------------------------------------------------------------------------
# Rule 1 — Referential integrity
# ---------------------------------------------------------------------------

class TestRule01ReferentialIntegrity:

    def test_record_missing_source(self):
        ds = valid_ds()
        ds.records[100]["source_id"] = 999
        assert has_error(ds.validate(), "R01", "source_id=999")

    def test_record_missing_place(self):
        ds = valid_ds()
        ds.records[100]["place_id"] = 999
        assert has_error(ds.validate(), "R01", "place_id=999")

    def test_named_individual_missing_record(self):
        ds = valid_ds()
        ds.named_individuals[200]["record_id"] = 999
        assert has_error(ds.validate(), "R01", "record_id=999")

    def test_person_missing_named_individual(self):
        ds = valid_ds()
        ds.persons[42]["named_individual_ids"] = [999]
        assert has_error(ds.validate(), "R01", "named_individual_id=999")

    def test_person_missing_fact(self):
        ds = valid_ds()
        ds.persons[42]["fact_ids"] = [999]
        assert has_error(ds.validate(), "R01", "fact_id=999")

    def test_person_missing_relationship(self):
        ds = valid_ds()
        ds.persons[42]["relationship_ids"] = [999]
        assert has_error(ds.validate(), "R01", "relationship_id=999")

    def test_relationship_missing_person_1(self):
        ds = valid_ds()
        ds.relationships[400]["person_id_1"] = 999
        assert has_error(ds.validate(), "R01", "person_id_1=999")

    def test_relationship_missing_person_2(self):
        ds = valid_ds()
        ds.relationships[400]["person_id_2"] = 999
        assert has_error(ds.validate(), "R01", "person_id_2=999")

    def test_relationship_missing_fact(self):
        ds = valid_ds()
        ds.relationships[400]["fact_ids"] = [999]
        assert has_error(ds.validate(), "R01", "fact_id=999")

    def test_relationship_missing_record(self):
        ds = valid_ds()
        ds.relationships[400]["record_ids"] = [999]
        assert has_error(ds.validate(), "R01", "record_id=999")

    def test_fact_missing_person(self):
        ds = valid_ds()
        ds.facts[300]["person_id"] = 999
        assert has_error(ds.validate(), "R01", "person_id=999")

    def test_fact_missing_event(self):
        ds = valid_ds()
        ds.facts[300]["event_id"] = 999
        assert has_error(ds.validate(), "R01", "event_id=999")

    def test_fact_missing_place(self):
        ds = valid_ds()
        ds.facts[300]["place_id"] = 999
        assert has_error(ds.validate(), "R01", "place_id=999")

    def test_fact_missing_record(self):
        ds = valid_ds()
        ds.facts[300]["record_ids"] = [999]
        assert has_error(ds.validate(), "R01", "record_id=999")

    def test_event_missing_place(self):
        ds = valid_ds()
        ds.events[500]["place_id"] = 999
        assert has_error(ds.validate(), "R01", "place_id=999")

    def test_event_missing_record(self):
        ds = valid_ds()
        ds.events[500]["record_ids"] = [999]
        assert has_error(ds.validate(), "R01", "record_id=999")

    def test_event_missing_fact(self):
        ds = valid_ds()
        ds.events[500]["fact_ids"] = [999]
        assert has_error(ds.validate(), "R01", "fact_id=999")

    def test_event_missing_relationship(self):
        ds = valid_ds()
        ds.events[500]["relationship_ids"] = [999]
        assert has_error(ds.validate(), "R01", "relationship_id=999")

    def test_event_role_missing_named_individual(self):
        ds = valid_ds()
        ds.events[500]["roles"] = [{"named_individual_id": 999, "role": "http://gedcomx.org/Principal"}]
        assert has_error(ds.validate(), "R01", "named_individual_id=999")


# ---------------------------------------------------------------------------
# Rule 2 — Fact subject constraint
# ---------------------------------------------------------------------------

class TestRule02FactSubjectConstraint:

    def test_both_person_and_relationship_set(self):
        ds = valid_ds()
        ds.facts[300]["relationship_id"] = 400
        assert has_error(ds.validate(), "R02", "both person_id and relationship_id")

    def test_neither_person_nor_relationship_set(self):
        ds = valid_ds()
        ds.facts[300]["person_id"] = None
        ds.facts[300]["relationship_id"] = None
        assert has_error(ds.validate(), "R02", "neither person_id nor relationship_id")

    def test_only_person_id_is_valid(self):
        errors = valid_ds().validate()
        assert not any("R02" in e for e in errors)

    def test_only_relationship_id_is_valid(self):
        ds = valid_ds()
        # Create a fact that belongs to a relationship, not a person
        ds.facts[302] = {
            "fact_id": 302,
            "person_id": None,
            "relationship_id": 400,
            "fact_type": "http://gedcomx.org/Marriage",
            "record_ids": [100],
        }
        ds.relationships[400]["fact_ids"] = [302]
        errors = ds.validate()
        assert not any("R02" in e and "302" in e for e in errors)


# ---------------------------------------------------------------------------
# Rule 3 — Bidirectional consistency: Facts
# ---------------------------------------------------------------------------

class TestRule03BidirectionalFacts:

    def test_person_lists_fact_but_fact_points_elsewhere(self):
        ds = valid_ds()
        ds.facts[300]["person_id"] = 43  # points to person 43, not 42
        assert has_error(ds.validate(), "R03", "Person 42")

    def test_relationship_lists_fact_but_fact_points_elsewhere(self):
        ds = valid_ds()
        # Add a relationship-owned fact but wire it incorrectly
        ds.facts[302] = {
            "fact_id": 302,
            "person_id": None,
            "relationship_id": 999,  # wrong — relationship 400 claims it
            "fact_type": "http://gedcomx.org/Marriage",
            "record_ids": [100],
        }
        ds.relationships[400]["fact_ids"] = [302]
        errors = ds.validate()
        assert has_error(errors, "R03", "Relationship 400")

    def test_correct_bidirectional_wiring_produces_no_r03(self):
        errors = valid_ds().validate()
        assert not any("R03" in e for e in errors)


# ---------------------------------------------------------------------------
# Rule 4 — Bidirectional consistency: NamedIndividuals
# ---------------------------------------------------------------------------

class TestRule04BidirectionalNamedIndividuals:

    def test_named_individual_claimed_by_two_persons(self):
        ds = valid_ds()
        ds.persons[43]["named_individual_ids"] = [200]  # 200 already claimed by person 42
        assert has_error(ds.validate(), "R04", "named_individual_id=200")

    def test_unique_claims_produce_no_r04(self):
        errors = valid_ds().validate()
        assert not any("R04" in e for e in errors)


# ---------------------------------------------------------------------------
# Rule 5 — Verbatim required on Record
# ---------------------------------------------------------------------------

class TestRule05VerbatimRequired:

    def test_missing_verbatim(self):
        ds = valid_ds()
        del ds.records[100]["verbatim"]
        assert has_error(ds.validate(), "R05", "Record 100")

    def test_empty_verbatim(self):
        ds = valid_ds()
        ds.records[100]["verbatim"] = ""
        assert has_error(ds.validate(), "R05", "Record 100")

    def test_whitespace_only_verbatim(self):
        ds = valid_ds()
        ds.records[100]["verbatim"] = "   "
        assert has_error(ds.validate(), "R05", "Record 100")

    def test_null_verbatim(self):
        ds = valid_ds()
        ds.records[100]["verbatim"] = None
        assert has_error(ds.validate(), "R05", "Record 100")

    def test_valid_verbatim_produces_no_r05(self):
        errors = valid_ds().validate()
        assert not any("R05" in e for e in errors)


# ---------------------------------------------------------------------------
# Rule 6 — Name required on NamedIndividual
# ---------------------------------------------------------------------------

class TestRule06NameRequired:

    def test_missing_name_as_recorded(self):
        ds = valid_ds()
        del ds.named_individuals[200]["name_as_recorded"]
        assert has_error(ds.validate(), "R06", "NamedIndividual 200")

    def test_empty_name_as_recorded(self):
        ds = valid_ds()
        ds.named_individuals[200]["name_as_recorded"] = ""
        assert has_error(ds.validate(), "R06", "NamedIndividual 200")

    def test_whitespace_only_name(self):
        ds = valid_ds()
        ds.named_individuals[200]["name_as_recorded"] = "   "
        assert has_error(ds.validate(), "R06", "NamedIndividual 200")

    def test_valid_name_produces_no_r06(self):
        errors = valid_ds().validate()
        assert not any("R06" in e for e in errors)


# ---------------------------------------------------------------------------
# Rule 7 — Record ids on Fact
# ---------------------------------------------------------------------------

class TestRule07RecordIdsOnFact:

    def test_missing_record_ids(self):
        ds = valid_ds()
        del ds.facts[300]["record_ids"]
        assert has_error(ds.validate(), "R07", "Fact 300")

    def test_empty_record_ids(self):
        ds = valid_ds()
        ds.facts[300]["record_ids"] = []
        assert has_error(ds.validate(), "R07", "Fact 300")

    def test_null_record_ids(self):
        ds = valid_ds()
        ds.facts[300]["record_ids"] = None
        assert has_error(ds.validate(), "R07", "Fact 300")

    def test_valid_record_ids_produces_no_r07(self):
        errors = valid_ds().validate()
        assert not any("R07" in e for e in errors)


# ---------------------------------------------------------------------------
# Rule 8 — EventRole references NamedIndividual
# ---------------------------------------------------------------------------

class TestRule08EventRoleReferencesNamedIndividual:

    def test_role_missing_named_individual_id(self):
        ds = valid_ds()
        ds.events[500]["roles"] = [{"role": "http://gedcomx.org/Principal"}]
        assert has_error(ds.validate(), "R08", "missing named_individual_id")

    def test_role_has_person_id_instead(self):
        ds = valid_ds()
        ds.events[500]["roles"] = [
            {"named_individual_id": 200, "person_id": 42, "role": "http://gedcomx.org/Principal"}
        ]
        assert has_error(ds.validate(), "R08", "person_id must not appear")

    def test_valid_role_produces_no_r08(self):
        errors = valid_ds().validate()
        assert not any("R08" in e for e in errors)


# ---------------------------------------------------------------------------
# Rule 9 — Controlled vocabulary
# ---------------------------------------------------------------------------

class TestRule09ControlledVocabulary:

    # Source type
    def test_invalid_source_type(self):
        ds = valid_ds()
        ds.sources[1]["type"] = "newspaper"
        assert has_error(ds.validate(), "R09", "Source 1")

    def test_missing_source_type(self):
        ds = valid_ds()
        del ds.sources[1]["type"]
        assert has_error(ds.validate(), "R09", "Source 1")

    # Record type
    def test_invalid_record_type(self):
        ds = valid_ds()
        ds.records[100]["record_type"] = "unknown_type"
        assert has_error(ds.validate(), "R09", "Record 100")

    def test_missing_record_type(self):
        ds = valid_ds()
        del ds.records[100]["record_type"]
        assert has_error(ds.validate(), "R09", "Record 100")

    def test_invalid_record_date_qualifier(self):
        ds = valid_ds()
        ds.records[100]["date_qualifier"] = "circa"
        assert has_error(ds.validate(), "R09", "Record 100")

    # Person gender and name types
    def test_invalid_gender(self):
        ds = valid_ds()
        ds.persons[42]["gender"] = "M"
        assert has_error(ds.validate(), "R09", "Person 42")

    def test_invalid_name_type(self):
        ds = valid_ds()
        ds.persons[42]["names"] = [{"value": "John", "type": "http://gedcomx.org/Unknown"}]
        assert has_error(ds.validate(), "R09", "Person 42")

    def test_valid_name_type_produces_no_r09(self):
        ds = valid_ds()
        ds.persons[42]["names"] = [
            {"value": "John Mulligan", "type": "http://gedcomx.org/BirthName"}
        ]
        errors = ds.validate()
        assert not any("R09" in e and "Person 42" in e for e in errors)

    # Relationship type
    def test_invalid_relationship_type(self):
        ds = valid_ds()
        ds.relationships[400]["relationship_type"] = "http://gedcomx.org/Sibling"
        assert has_error(ds.validate(), "R09", "Relationship 400")

    def test_missing_relationship_type(self):
        ds = valid_ds()
        del ds.relationships[400]["relationship_type"]
        assert has_error(ds.validate(), "R09", "Relationship 400")

    def test_invalid_relationship_confidence(self):
        ds = valid_ds()
        ds.relationships[400]["confidence"] = "http://gedcomx.org/Certain"
        assert has_error(ds.validate(), "R09", "Relationship 400")

    # Fact type
    def test_invalid_fact_type(self):
        ds = valid_ds()
        ds.facts[300]["fact_type"] = "http://gedcomx.org/Unknown"
        assert has_error(ds.validate(), "R09", "Fact 300")

    def test_missing_fact_type(self):
        ds = valid_ds()
        del ds.facts[300]["fact_type"]
        assert has_error(ds.validate(), "R09", "Fact 300")

    def test_invalid_fact_confidence(self):
        ds = valid_ds()
        ds.facts[300]["confidence"] = "certain"
        assert has_error(ds.validate(), "R09", "Fact 300")

    def test_invalid_fact_date_qualifier(self):
        ds = valid_ds()
        ds.facts[300]["date_qualifier"] = "circa"
        assert has_error(ds.validate(), "R09", "Fact 300")

    # Event type and roles
    def test_invalid_event_type(self):
        ds = valid_ds()
        ds.events[500]["event_type"] = "http://gedcomx.org/Unknown"
        assert has_error(ds.validate(), "R09", "Event 500")

    def test_missing_event_type(self):
        ds = valid_ds()
        del ds.events[500]["event_type"]
        assert has_error(ds.validate(), "R09", "Event 500")

    def test_invalid_event_role_type(self):
        ds = valid_ds()
        ds.events[500]["roles"] = [
            {"named_individual_id": 200, "role": "http://gedcomx.org/Subject"}
        ]
        assert has_error(ds.validate(), "R09", "Event 500")

    def test_invalid_event_date_qualifier(self):
        ds = valid_ds()
        ds.events[500]["date_qualifier"] = "circa"
        assert has_error(ds.validate(), "R09", "Event 500")

    def test_valid_dataset_produces_no_r09(self):
        errors = valid_ds().validate()
        assert not any("R09" in e for e in errors)


# ---------------------------------------------------------------------------
# Rule 10 — Date format
# ---------------------------------------------------------------------------

class TestRule10DateFormat:

    @pytest.mark.parametrize("valid_date", [
        "1857",
        "1901-04",
        "1901-04-01",
        "1800-01-01",
        "2001-12-31",
    ])
    def test_valid_dates_pass(self, valid_date):
        ds = valid_ds()
        ds.records[100]["date"] = valid_date
        errors = ds.validate()
        assert not any("R10" in e and "Record 100" in e for e in errors)

    @pytest.mark.parametrize("invalid_date", [
        "57",           # two-digit year
        "01-04-1901",   # wrong order
        "1901/04/01",   # wrong separator
        "April 1901",   # text
        "c.1857",       # circa prefix
        "1901-13",      # invalid month
        "1901-00",      # zero month
        "1901-04-00",   # zero day
        "1901-04-32",   # day out of range
    ])
    def test_invalid_dates_fail(self, invalid_date):
        ds = valid_ds()
        ds.records[100]["date"] = invalid_date
        assert has_error(ds.validate(), "R10", "Record 100")

    def test_fact_date_validated(self):
        ds = valid_ds()
        ds.facts[300]["date"] = "April 1890"
        assert has_error(ds.validate(), "R10", "Fact 300")

    def test_event_date_validated(self):
        ds = valid_ds()
        ds.events[500]["date"] = "1890/01/10"
        assert has_error(ds.validate(), "R10", "Event 500")

    def test_null_date_passes(self):
        ds = valid_ds()
        ds.records[100]["date"] = None
        errors = ds.validate()
        assert not any("R10" in e and "Record 100" in e for e in errors)

    def test_valid_dataset_produces_no_r10(self):
        errors = valid_ds().validate()
        assert not any("R10" in e for e in errors)
