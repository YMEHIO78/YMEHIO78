"""Deployment-level names and the tuning knobs the analytics depend on."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date

# Unity Catalog target. Override per environment via the bundle or env vars.
CATALOG = os.environ.get("SKILLS_CATALOG", "skills_analysis")
BRONZE_SCHEMA = os.environ.get("SKILLS_BRONZE_SCHEMA", "bronze")
SILVER_SCHEMA = os.environ.get("SKILLS_SILVER_SCHEMA", "silver")
GOLD_SCHEMA = os.environ.get("SKILLS_GOLD_SCHEMA", "gold")
RAW_VOLUME = os.environ.get("SKILLS_RAW_VOLUME", "raw_files")

# "Today" for the analysis. The Workday extract is dated 2026-09-01 and every
# other export is from the same week, so the as-of date is pinned to keep
# expiry and staleness maths reproducible rather than drifting with wall clock.
AS_OF_DATE = date.fromisoformat(os.environ.get("SKILLS_AS_OF_DATE", "2026-09-01"))

# A skill profile is "current" if it was touched within this many days.
PROFILE_FRESHNESS_DAYS = 180

# A certification is "at risk" this many days before it expires.
CERT_EXPIRY_WARNING_DAYS = 90

# Proficiency at or above this level counts a worker as deep enough to be the
# person an org relies on for a skill.
EXPERT_THRESHOLD = 4

# A critical skill with this many or fewer deep practitioners is a single point
# of failure.
BUS_FACTOR_THRESHOLD = 1

# Learning engagement window.
LEARNING_LOOKBACK_DAYS = 365

# Worker populations. Headcount analytics cover employees only; contingent
# workers and interns are reported separately so they never inflate coverage.
HEADCOUNT_WORKER_TYPES = ("Employee",)
IN_SCOPE_WORKER_STATUSES = ("Active", "Leave of Absence")


@dataclass(frozen=True)
class SourceFile:
    """One raw export, as it lands in the volume."""

    key: str
    filename: str
    system: str
    description: str
    sheets: tuple[str, ...] = field(default=())


SOURCE_FILES: tuple[SourceFile, ...] = (
    SourceFile(
        key="workday",
        filename="workday_worker_skills_20260901.csv",
        system="Workday",
        description="Worker skills and experience extract - system of record for the roster",
    ),
    SourceFile(
        key="matrix",
        filename="skills_matrix_final_v3_1.xlsx",
        system="Manual spreadsheet",
        description="Team-maintained skills matrix used for FY27 headcount planning",
        sheets=("Matrix",),
    ),
    SourceFile(
        key="recert",
        filename="recert_tracker_draft.xlsx",
        system="Manual spreadsheet",
        description="Certification and recertification tracker with voucher spend",
        sheets=("Tracker", "Cert List"),
    ),
    SourceFile(
        key="degreed",
        filename="degreed_learning_completions_20260901.xlsx",
        system="Degreed",
        description="Learning completions and skill ratings detail export",
        sheets=("Report Data",),
    ),
)

REFERENCE_FILES = (
    "skill_aliases.csv",
    "identity_overrides.csv",
    "proficiency_scale.csv",
    "critical_skills.csv",
)


def fq(schema: str, table: str) -> str:
    """Fully qualified Unity Catalog name."""
    return f"{CATALOG}.{schema}.{table}"
