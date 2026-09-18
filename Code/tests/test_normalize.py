"""Rules that must keep holding as the cleaning logic changes."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # Code/src

from skills_analysis.normalize import (  # noqa: E402
    canonical_skill,
    clean_text,
    date_is_fiscal_shorthand,
    normalize_cert_status,
    normalize_learning_status,
    normalize_location,
    normalize_org,
    normalize_person_name,
    normalize_proficiency,
    parse_date,
    parse_duration_hours,
    parse_money,
    parse_number,
    resolve_employee_id,
)


@pytest.mark.parametrize("raw,expected", [
    ("2026-01-14", date(2026, 1, 14)),
    ("3/4/2026", date(2026, 3, 4)),
    ("14-Jan-26", date(2026, 1, 14)),
    ("2026-01-14 00:00:00", date(2026, 1, 14)),
    (45292, date(2024, 1, 1)),           # Excel serial that lost its formatting
    ("45777", date(2025, 4, 30)),        # serial that arrived as text
    ("2024-01@08", date(2024, 1, 8)),    # mistyped separator
    (date(2025, 5, 1), date(2025, 5, 1)),
])
def test_parse_date_handles_every_shape_in_the_exports(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize("raw", ["Q1 FY28", "end of FY", "TBD", "?", "ASAP", "", None])
def test_parse_date_refuses_to_invent_a_date(raw):
    assert parse_date(raw) is None


def test_fiscal_shorthand_is_recognised_so_it_can_be_reported_not_guessed():
    assert date_is_fiscal_shorthand("Q1 FY28")
    assert date_is_fiscal_shorthand("end of FY")
    assert not date_is_fiscal_shorthand("2026-10-15")


@pytest.mark.parametrize("raw,level,confidence", [
    ("5 - Expert", 5, "high"),
    ("4 - Advanced", 4, "high"),
    ("3", 3, "high"),
    ("advanced", 4, "medium"),
    ("expert!!", 5, "medium"),
    ("3 (was 2)", 3, "medium"),
    ("H", 4, "low"),
    ("no", 1, "low"),
])
def test_every_rating_dialect_maps_onto_one_scale(raw, level, confidence):
    assert normalize_proficiency(raw) == (level, confidence)


@pytest.mark.parametrize("raw", ["Not Rated", "x", "?", "-", "n/a", "", None])
def test_unrated_values_stay_unrated(raw):
    assert normalize_proficiency(raw)[0] is None


@pytest.mark.parametrize("raw,expected", [
    ("Python", "Python"), ("Python (Programming Language)", "Python"), ("python 3", "Python"),
    ("DNAC", "Catalyst Center"), ("Cisco DNA Center", "Catalyst Center"),
    ("Catalyst  Center", "Catalyst Center"),          # doubled internal space
    ("1000 Eyes", "ThousandEyes"), ("Thousand Eyes", "ThousandEyes"),
    ("Firepower", "Cisco Secure Firewall"),
    ("Stealthwatch", "Secure Network Analytics"),
    ("SD-WAN (Viptela)", "SD-WAN"), ("Catalyst SD-WAN", "SD-WAN"), ("sd-wan", "SD-WAN"),
    ("Kubernetes (K8s)", "Kubernetes"),
])
def test_skill_spellings_collapse_onto_the_taxonomy(raw, expected):
    assert canonical_skill(raw)[0] == expected


def test_a_column_covering_two_skills_is_not_attributed_to_either():
    assert canonical_skill("ACI / NX-OS")[0] == "ACI / NX-OS (conflated)"


def test_unknown_skills_are_reported_rather_than_guessed():
    assert canonical_skill("Quantum Networking")[0] is None


@pytest.mark.parametrize("raw,expected", [
    ("Completed", "Completed"), ("COMPLETE", "Completed"), ("Done", "Completed"),
    ("C", "Completed"), ("Y", "Completed"), ("completed ", "Completed"),
    ("In Progress", "In Progress"), ("In progress", "In Progress"), ("Started", "In Progress"),
    ("Not started", "Not Started"), ("Withdrawn", "Withdrawn"),
])
def test_learning_statuses_collapse(raw, expected):
    assert normalize_learning_status(raw) == expected


def test_cert_status_reads_free_text_but_rejects_a_date():
    assert normalize_cert_status("Active ✔") == "Active"
    assert normalize_cert_status("active - recert in progress") == "Active"
    assert normalize_cert_status("expiring soon") == "Expiring"
    assert normalize_cert_status("lapsed, Dana wants her recertified") == "Expired"
    # One row has the expiry date typed into the status column.
    assert normalize_cert_status("2027-05-11 00:00:00") is None


@pytest.mark.parametrize("raw,expected", [
    ("$1,600", 1600.0), ("1600", 1600.0), ("800.00", 800.0),
    ("~$300?", 300.0), ("free", 0.0), ("0", 0.0), ("$70.50", 70.5),
])
def test_money_parses_through_symbols_and_free_text(raw, expected):
    assert parse_money(raw) == expected


def test_duration_handles_the_one_row_recorded_in_minutes():
    assert parse_duration_hours("90 min") == 1.5
    assert parse_duration_hours("6") == 6.0
    assert parse_duration_hours("") is None


def test_ce_credits_read_through_a_parenthetical():
    assert parse_number("40 (need 80)") == 40.0


@pytest.mark.parametrize("raw,expected", [
    ("Okonkwo, Emeka ", "Emeka Okonkwo"),
    ("OKONKWO, EMEKA", "Emeka Okonkwo"),
    ("O'Leary, Daniel P.", "Daniel P. O'Leary"),
    ("Baptiste, Marie-Claire", "Marie-Claire Baptiste"),
])
def test_names_normalise_to_one_form(raw, expected):
    assert normalize_person_name(raw) == expected


def test_mojibake_is_repaired():
    assert clean_text("Delgado, JosÃ© R.") == "Delgado, José R."


def test_site_codes_and_full_names_become_one_location():
    assert normalize_location("SJC") == normalize_location("San Jose, CA") == "San Jose, CA"
    assert normalize_location("RTP") == "Research Triangle Park, NC"


def test_org_names_lose_the_manager_suffix_and_shouting():
    assert normalize_org("PARTNER ENABLEMENT APJC (Joost Vandermeer)") == "Partner Enablement Apjc"
    assert normalize_org("Partner Enablement APJC (Joost Vandermeer)") == "Partner Enablement APJC"


class TestIdentityResolution:
    def test_truncated_employee_id_maps_to_the_real_worker(self):
        assert resolve_employee_id("workday", "44102")[0] == "1044102"

    def test_legacy_acquisition_ids_map_to_the_current_worker(self):
        assert resolve_employee_id("workday", "SPLK-0227")[0] == "1048893"
        assert resolve_employee_id("workday", "SPLK-0314")[0] == "1041555"

    def test_name_order_does_not_matter(self):
        assert resolve_employee_id("recert", "Wei-Lin Chen")[0] == "1044102"
        assert resolve_employee_id("recert", "Chen, Wei-Lin")[0] == "1044102"

    def test_preferred_names_resolve_to_the_legal_record(self):
        assert resolve_employee_id("recert", "Okonkwo, Mike")[0] == "1043915"
        assert resolve_employee_id("matrix", "Jazz Carter")[0] == "1051004"
        assert resolve_employee_id("recert", "Vo, Alex")[0] == "1053771"

    def test_windows_account_and_email_resolve_to_the_same_person(self):
        assert resolve_employee_id("degreed", "CISCO\\delgadj")[0] == "1045620"
        assert resolve_employee_id("degreed", "delgadj@cisco.com")[0] == "1045620"

    def test_split_identities_across_tenants_merge(self):
        assert resolve_employee_id("degreed", "mwhitfield@splunk.com")[0] == "1048893"
        assert resolve_employee_id("degreed", "whitfim@cisco.com")[0] == "1048893"

    def test_people_outside_the_population_resolve_to_a_deliberate_exclusion(self):
        # An empty string means "reviewed and out of scope", not "unknown".
        assert resolve_employee_id("recert", "partner SE (NW Systems)")[0] == ""
        assert resolve_employee_id("degreed", "rsandoval@partner-nwsystems.com")[0] == ""

    def test_a_genuinely_unknown_person_is_not_guessed_at(self):
        assert resolve_employee_id("recert", "Nobody, Real")[0] is None
