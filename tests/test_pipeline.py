"""End-to-end checks on the real exports.

These assert the decisions the pipeline makes about *this* data, so a change in
a cleaning rule that silently moves a headline number fails here first.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "local"))

from run_analysis import run  # noqa: E402


@pytest.fixture(scope="module")
def tables(tmp_path_factory):
    return run(tmp_path_factory.mktemp("build"))


class TestPopulation:
    def test_twenty_five_distinct_people_survive_identity_resolution(self, tables):
        # 69 Workday rows, 25 people, after merging three split identities.
        assert len(tables["silver_worker"]) == 25

    def test_headcount_excludes_contingent_interns_and_leavers(self, tables):
        workers = tables["silver_worker"]
        assert workers["in_headcount"].sum() == 21
        excluded = workers[~workers["in_headcount"]]
        assert set(excluded["worker_name"]) == {
            "Long Vo", "Patrick Fitzgerald", "Rosa Maldonado", "Tyler Hargrove"
        }

    def test_a_worker_on_leave_still_counts_in_headcount(self, tables):
        workers = tables["silver_worker"]
        loa = workers[workers["worker_status"] == "Leave of Absence"]
        assert len(loa) == 1 and bool(loa["in_headcount"].iloc[0])

    def test_acquisition_tenure_is_not_reset_by_the_migration_date(self, tables):
        workers = tables["silver_worker"].set_index("worker_name")
        marcus = workers.loc["Marcus Whitfield"]
        assert str(marcus["original_hire_date"]) == "2019-04-15"
        assert str(marcus["workday_hire_date"]) == "2024-03-18"
        assert marcus["is_acquired_employee"]

    def test_the_truncated_employee_id_does_not_create_a_second_person(self, tables):
        workers = tables["silver_worker"]
        chen = workers[workers["worker_name"] == "Wei-Lin Chen"]
        assert len(chen) == 1
        assert chen["legacy_worker_ids"].iloc[0] == "44102"


class TestDeduplication:
    def test_the_repeated_workday_skill_row_is_dropped(self, tables):
        skills = tables["silver_worker_skill"]
        yuki = skills[(skills["worker_name"] == "Yuki Nakamura") & (skills["canonical_skill"] == "Python")]
        assert len(yuki) == 1

    def test_a_manager_rating_beats_an_older_self_rating(self, tables):
        skills = tables["silver_worker_skill"].set_index(["worker_name", "canonical_skill"])
        row = skills.loc[("Emeka Okonkwo", "VXLAN EVPN")]
        assert row["proficiency"] == 5
        assert row["assessment_source"] == "Manager Assessment"

    def test_each_person_appears_once_per_certification(self, tables):
        certs = tables["silver_certification"]
        assert not certs.duplicated(subset=["employee_id", "certification"]).any()

    def test_a_status_consistent_expiry_beats_a_corrupted_one(self, tables):
        certs = tables["silver_certification"].set_index("worker_name")
        # Two rows for this CCNP: one expiry decoded from an Excel serial to
        # 2024-01-01 beside a status of "Expiring", the other 2026-10-15.
        assert str(certs.loc["Wei-Lin Chen", "expires_on"]) == "2026-10-15"

    def test_a_course_revision_is_not_a_second_completion(self, tables):
        learning = tables["silver_learning_completion"]
        vxlan = learning[learning["learning_item_key"].str.contains("vxlan", na=False)]
        assert len(vxlan[vxlan["employee_id"] == "1043915"]) == 1

    def test_the_duplicated_matrix_row_collapses_to_one_person(self, tables):
        matrix = tables["silver_matrix_rating"]
        rows = matrix[matrix["employee_id"] == "1043915"]["matrix_row"].nunique()
        assert rows == 1


class TestScopeExclusions:
    def test_external_partners_and_loaned_staff_never_reach_analytics(self, tables):
        names = set(tables["gold_worker_skill_profile"]["worker_name"].dropna())
        for outsider in {"R. Sandoval", "Jen Martin", "Jen Martin (temp)"}:
            assert outsider not in names
        assert tables["silver_certification"]["employee_id"].ne("").all()

    def test_exclusions_are_logged_rather_than_silently_dropped(self, tables):
        issues = tables["silver_data_quality_issue"]
        assert (issues["issue_type"] == "out_of_scope_person").sum() >= 4


class TestEvidenceRules:
    def test_a_blank_matrix_cell_creates_no_claim_of_skill(self, tables):
        matrix = tables["silver_matrix_rating"]
        assert matrix["raw_rating"].notna().all()

    def test_a_conflated_column_is_excluded_from_coverage(self, tables):
        coverage = tables["gold_skill_coverage"]
        conflated = coverage[coverage["canonical_skill"].str.contains("conflated")]
        assert conflated.empty or not conflated["is_critical_skill"].any()

    def test_a_low_confidence_rating_never_establishes_expertise(self, tables):
        profile = tables["gold_worker_skill_profile"]
        deep = profile[profile["is_deep"]]
        assert set(deep["proficiency_confidence"]) <= {"high", "medium"}

    def test_declared_no_exposure_does_not_count_as_holding_a_skill(self, tables):
        profile = tables["gold_worker_skill_profile"]
        assert not profile[profile["is_no_exposure"]]["has_skill"].any()


class TestHeadlineMetrics:
    def test_all_four_kpis_are_produced(self, tables):
        kpis = tables["gold_kpi_snapshot"]
        assert set(kpis["metric_key"]) == {
            "skill_profile_freshness_pct", "certifications_at_risk",
            "critical_skills_single_point_of_failure", "learning_engagement_pct",
        }
        assert kpis["metric_value"].notna().all()

    def test_at_risk_certifications_are_scoped_to_headcount(self, tables):
        certs = tables["gold_cert_compliance"]
        at_risk = certs[certs["is_at_risk"] & certs["in_headcount"].fillna(False)]
        kpi = tables["gold_kpi_snapshot"].set_index("metric_key")
        assert kpi.loc["certifications_at_risk", "metric_value"] == len(at_risk)

    def test_every_data_quality_issue_records_what_was_done_about_it(self, tables):
        issues = tables["silver_data_quality_issue"]
        assert not issues.empty
        assert issues["resolution"].str.len().gt(0).all()
        assert set(issues["severity"]) <= {"high", "medium", "low"}
