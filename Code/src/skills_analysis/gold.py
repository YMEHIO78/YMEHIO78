"""Gold layer: the tables the report and the dashboard read.

Everything here is derived only from silver, so a correction to a cleaning rule
flows through without any table being edited by hand.
"""

from __future__ import annotations

import pandas as pd

from . import config as cfg
from .reference import critical_skill_rationale, critical_skills

# Evidence precedence. Workday is the system of record, so even an unattributed
# rating there outranks the hand-maintained spreadsheet; within Workday, a
# manager's assessment outranks a self rating.
_SOURCE_PRECEDENCE = {
    "Manager Assessment": 3.0,
    "Self-Assessment": 2.0,
    "Unspecified": 1.5,
    "Skills Matrix": 1.0,
}


def build_worker_skill_profile(worker_skills: pd.DataFrame, matrix: pd.DataFrame,
                               workers: pd.DataFrame) -> pd.DataFrame:
    """One row per worker per skill, best available evidence, conflicts flagged."""
    frames = []
    if not worker_skills.empty:
        frames.append(worker_skills.assign(evidence_system="Workday", is_no_exposure=False)[[
            "employee_id", "canonical_skill", "skill_domain", "proficiency",
            "proficiency_confidence", "assessment_source", "last_updated", "evidence_system",
            "is_no_exposure",
        ]])
    if not matrix.empty:
        frames.append(matrix.assign(evidence_system="Skills Matrix", last_updated=pd.NaT)[[
            "employee_id", "canonical_skill", "skill_domain", "proficiency",
            "proficiency_confidence", "assessment_source", "last_updated", "evidence_system",
            "is_no_exposure",
        ]])
    evidence = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if evidence.empty:
        return evidence

    evidence["_rank"] = evidence["assessment_source"].map(lambda s: _SOURCE_PRECEDENCE.get(s, 0))
    rows = []
    for (emp_id, skill), grp in evidence.groupby(["employee_id", "canonical_skill"], sort=False):
        rated = grp[grp["proficiency"].notna()]
        best = (rated if not rated.empty else grp).sort_values("_rank", ascending=False).iloc[0]
        levels = {int(p) for p in rated["proficiency"]} if not rated.empty else set()
        workday_level = _first_level(rated[rated["evidence_system"] == "Workday"])
        matrix_level = _first_level(rated[rated["evidence_system"] == "Skills Matrix"])
        rows.append({
            "employee_id": emp_id,
            "canonical_skill": skill,
            "skill_domain": best["skill_domain"],
            "proficiency": int(best["proficiency"]) if pd.notna(best["proficiency"]) else None,
            "proficiency_confidence": best["proficiency_confidence"],
            "assessment_source": best["assessment_source"],
            "last_updated": best["last_updated"] if pd.notna(best["last_updated"]) else None,
            "evidence_systems": ";".join(sorted(set(grp["evidence_system"]))),
            "evidence_count": int(len(grp)),
            "workday_proficiency": workday_level,
            "matrix_proficiency": matrix_level,
            "has_source_conflict": bool(
                workday_level is not None and matrix_level is not None
                and abs(workday_level - matrix_level) >= 2
            ),
            "proficiency_spread": (max(levels) - min(levels)) if len(levels) > 1 else 0,
            # True only when every piece of evidence says the person has no exposure.
            "is_no_exposure": bool(grp["is_no_exposure"].all()),
        })

    profile = pd.DataFrame(rows)
    profile["is_critical_skill"] = profile["canonical_skill"].map(
        lambda s: critical_skills().get(s, False)
    )
    # An H/M/L rating translated onto a 1-5 scale is an approximation. It is good
    # enough to show on a heatmap, but not to claim someone is the expert a team
    # can depend on, so low-confidence ratings never establish depth.
    profile["is_deep"] = profile.apply(
        lambda r: bool(r["proficiency"] is not None and r["proficiency"] >= cfg.EXPERT_THRESHOLD
                       and r["proficiency_confidence"] in {"high", "medium"}),
        axis=1,
    )
    profile["is_deep_low_confidence"] = profile.apply(
        lambda r: bool(r["proficiency"] is not None and r["proficiency"] >= cfg.EXPERT_THRESHOLD
                       and r["proficiency_confidence"] not in {"high", "medium"}),
        axis=1,
    )
    profile["has_skill"] = ~profile["is_no_exposure"]
    profile["days_since_update"] = profile["last_updated"].map(
        lambda d: (cfg.AS_OF_DATE - d).days if d is not None else None
    )
    profile["is_current"] = profile["days_since_update"].map(
        lambda d: bool(d is not None and d <= cfg.PROFILE_FRESHNESS_DAYS)
    )
    return profile.merge(
        workers[["employee_id", "worker_name", "supervisory_org", "worker_type",
                 "worker_status", "in_headcount", "location"]],
        on="employee_id", how="left",
    ).sort_values(["worker_name", "canonical_skill"]).reset_index(drop=True)


def _first_level(frame: pd.DataFrame) -> int | None:
    if frame.empty:
        return None
    value = frame.sort_values("_rank", ascending=False)["proficiency"].iloc[0]
    return int(value) if pd.notna(value) else None


def build_skill_coverage(profile: pd.DataFrame, workers: pd.DataFrame) -> pd.DataFrame:
    """Per skill: who has it, how deep it goes, and whether it is a single point of failure."""
    pop = profile[profile["in_headcount"].fillna(False) & profile["has_skill"]]
    no_exposure = profile[profile["in_headcount"].fillna(False) & ~profile["has_skill"]]
    rows = []
    for skill, grp in pop.groupby("canonical_skill", sort=False):
        rated = grp[grp["proficiency"].notna()]
        deep = grp[grp["is_deep"]]
        rows.append({
            "canonical_skill": skill,
            "skill_domain": grp["skill_domain"].iloc[0],
            "is_critical_skill": bool(critical_skills().get(skill, False)),
            "criticality_rationale": critical_skill_rationale().get(skill, ""),
            "people_with_skill": int(grp["employee_id"].nunique()),
            "people_rated": int(rated["employee_id"].nunique()),
            "deep_practitioners": int(deep["employee_id"].nunique()),
            "avg_proficiency": round(float(rated["proficiency"].mean()), 2) if not rated.empty else None,
            "max_proficiency": int(rated["proficiency"].max()) if not rated.empty else None,
            "orgs_covered": int(grp["supervisory_org"].nunique()),
            "deep_practitioner_names": ", ".join(sorted(deep["worker_name"].dropna().unique())),
            "deep_low_confidence_only": int(grp[grp["is_deep_low_confidence"]]["employee_id"].nunique()),
            "declared_no_exposure": int(
                no_exposure[no_exposure["canonical_skill"] == skill]["employee_id"].nunique()
            ),
            "stale_profiles": int((~grp["is_current"]).sum()),
        })

    coverage = pd.DataFrame(rows)
    if coverage.empty:
        return coverage
    coverage["is_single_point_of_failure"] = (
        coverage["is_critical_skill"] & (coverage["deep_practitioners"] <= cfg.BUS_FACTOR_THRESHOLD)
    )
    coverage["risk_band"] = coverage.apply(_coverage_band, axis=1)

    # Critical skills nobody in the population holds at all.
    covered = set(coverage["canonical_skill"])
    missing = [s for s, is_crit in critical_skills().items() if is_crit and s not in covered]
    if missing:
        gaps = pd.DataFrame([{
            "canonical_skill": s,
            "skill_domain": "",
            "is_critical_skill": True,
            "criticality_rationale": critical_skill_rationale().get(s, ""),
            "people_with_skill": 0, "people_rated": 0, "deep_practitioners": 0,
            "avg_proficiency": None, "max_proficiency": None, "orgs_covered": 0,
            "deep_practitioner_names": "", "deep_low_confidence_only": 0,
            "declared_no_exposure": 0, "stale_profiles": 0,
            "is_single_point_of_failure": True, "risk_band": "No coverage",
        } for s in missing])
        coverage = pd.concat([coverage, gaps], ignore_index=True)

    return coverage.sort_values(
        ["is_critical_skill", "deep_practitioners", "canonical_skill"],
        ascending=[False, True, True],
    ).reset_index(drop=True)


def _coverage_band(row: pd.Series) -> str:
    if not row["is_critical_skill"]:
        return "Not critical"
    if row["deep_practitioners"] == 0:
        return "No depth"
    if row["deep_practitioners"] <= cfg.BUS_FACTOR_THRESHOLD:
        return "Single point of failure"
    if row["deep_practitioners"] <= 2:
        return "Thin"
    return "Covered"


def build_cert_compliance(certs: pd.DataFrame, workers: pd.DataFrame) -> pd.DataFrame:
    """Certification records with days-to-expiry and a risk band."""
    if certs.empty:
        return certs
    out = certs.merge(
        workers[["employee_id", "supervisory_org", "worker_type", "worker_status", "in_headcount"]],
        on="employee_id", how="left",
    )
    out["days_to_expiry"] = out["expires_on"].map(
        lambda d: (d - cfg.AS_OF_DATE).days if d is not None else None
    )
    out["risk_band"] = out.apply(_cert_band, axis=1)
    out["is_at_risk"] = out["risk_band"].isin(
        ["Expired", f"Expiring within {cfg.CERT_EXPIRY_WARNING_DAYS} days", "No expiry recorded"]
    )
    # A zero voucher means a no-cost path (CE credits, internal exam credits), not
    # an underspend, so price variance is only meaningful on rows that were paid for.
    out["is_zero_cost_path"] = out["voucher_cost"].map(lambda v: bool(v is not None and not pd.isna(v) and v == 0))
    out["on_approved_cert_list"] = out["list_price"].notna()
    out["voucher_vs_list"] = out.apply(
        lambda r: None if (pd.isna(r["voucher_cost"]) or pd.isna(r["list_price"]) or r["voucher_cost"] == 0)
        else round(float(r["voucher_cost"]) - float(r["list_price"]), 2), axis=1
    )
    return out.sort_values(["risk_band", "days_to_expiry"]).reset_index(drop=True)


def _cert_band(row: pd.Series) -> str:
    status = row["cert_status"]
    days = row["days_to_expiry"]
    if status in {"Not Started", "In Progress"}:
        return f"{status} (no certification yet)"
    if days is None or pd.isna(days):
        return "No expiry recorded"
    if days < 0:
        return "Expired"
    if days <= cfg.CERT_EXPIRY_WARNING_DAYS:
        return f"Expiring within {cfg.CERT_EXPIRY_WARNING_DAYS} days"
    if days <= 365:
        return "Expiring within 12 months"
    return "Current"


def build_org_scorecard(workers: pd.DataFrame, profile: pd.DataFrame,
                        learning: pd.DataFrame, certs: pd.DataFrame) -> pd.DataFrame:
    """Per supervisory organisation: are the inputs trustworthy, and what is at risk."""
    pop = workers[workers["in_headcount"]]
    rows = []
    for org, grp in pop.groupby("supervisory_org", sort=False):
        ids = set(grp["employee_id"])
        org_profile = profile[profile["employee_id"].isin(ids)]
        with_profile = set(org_profile[org_profile["proficiency"].notna()]["employee_id"])
        current = set(org_profile[org_profile["is_current"]]["employee_id"])
        recent_learners = set(
            learning[learning["employee_id"].isin(ids) & learning["is_recent"]]["employee_id"]
        ) if not learning.empty else set()
        org_certs = certs[certs["employee_id"].isin(ids)] if not certs.empty else certs
        rows.append({
            "supervisory_org": org,
            "headcount": int(len(ids)),
            "workers_with_rated_skill": len(with_profile),
            "profile_coverage_pct": _pct(len(with_profile), len(ids)),
            "workers_with_current_profile": len(current),
            "profile_freshness_pct": _pct(len(current), len(ids)),
            "recent_learners": len(recent_learners),
            "learning_engagement_pct": _pct(len(recent_learners), len(ids)),
            "certs_tracked": int(len(org_certs)) if not org_certs.empty else 0,
            "certs_at_risk": int(org_certs["is_at_risk"].sum()) if not org_certs.empty else 0,
            "avg_days_since_skill_update": (
                round(float(org_profile["days_since_update"].dropna().mean()), 0)
                if org_profile["days_since_update"].notna().any() else None
            ),
        })
    return pd.DataFrame(rows).sort_values("profile_freshness_pct").reset_index(drop=True)


def _pct(numerator: int, denominator: int) -> float | None:
    return round(100.0 * numerator / denominator, 1) if denominator else None


def build_kpi_snapshot(workers: pd.DataFrame, profile: pd.DataFrame, coverage: pd.DataFrame,
                       learning: pd.DataFrame, certs: pd.DataFrame) -> pd.DataFrame:
    """The four headline metrics, one row each, ready for the dashboard counters."""
    pop_ids = set(workers[workers["in_headcount"]]["employee_id"])
    headcount = len(pop_ids)

    current_ids = set(profile[profile["employee_id"].isin(pop_ids) & profile["is_current"]]["employee_id"])
    freshness_pct = _pct(len(current_ids), headcount) or 0.0

    at_risk = certs[certs["is_at_risk"] & certs["in_headcount"].fillna(False)] if not certs.empty else certs
    at_risk_count = int(len(at_risk)) if not at_risk.empty else 0
    at_risk_spend = float(at_risk["voucher_cost"].fillna(0).sum()) if not at_risk.empty else 0.0

    spof = coverage[coverage["is_single_point_of_failure"]] if not coverage.empty else coverage
    spof_count = int(len(spof)) if not spof.empty else 0
    critical_total = int(coverage["is_critical_skill"].sum()) if not coverage.empty else 0

    learner_ids = set(
        learning[learning["employee_id"].isin(pop_ids) & learning["is_recent"]]["employee_id"]
    ) if not learning.empty else set()
    engagement_pct = _pct(len(learner_ids), headcount) or 0.0

    return pd.DataFrame([
        {
            "metric_key": "skill_profile_freshness_pct",
            "metric_name": "Skill profile freshness",
            "metric_value": freshness_pct,
            "metric_unit": "percent",
            "metric_detail": f"{len(current_ids)} of {headcount} in-headcount workers have a skill "
                             f"rating updated in the last {cfg.PROFILE_FRESHNESS_DAYS} days",
            "target_value": 90.0,
            "direction": "higher_is_better",
            "why_it_matters": "Every other skills metric is only as good as the profiles feeding it. "
                              "This is the leading indicator of whether the data can be trusted.",
        },
        {
            "metric_key": "certifications_at_risk",
            "metric_name": "Certifications at risk",
            "metric_value": float(at_risk_count),
            "metric_unit": "count",
            "metric_detail": f"Expired, expiring within {cfg.CERT_EXPIRY_WARNING_DAYS} days, or with "
                             f"no expiry recorded; ${at_risk_spend:,.0f} of voucher spend attached",
            "target_value": 0.0,
            "direction": "lower_is_better",
            "why_it_matters": "Lapsed certifications put partner tier status and customer "
                              "commitments at risk, and each one has a lead time to fix.",
        },
        {
            "metric_key": "critical_skills_single_point_of_failure",
            "metric_name": "Critical skills with no backup",
            "metric_value": float(spof_count),
            "metric_unit": "count",
            "metric_detail": f"{spof_count} of {critical_total} critical skills have "
                             f"{cfg.BUS_FACTOR_THRESHOLD} or fewer people at proficiency "
                             f"{cfg.EXPERT_THRESHOLD}+",
            "target_value": 0.0,
            "direction": "lower_is_better",
            "why_it_matters": "A critical skill resting on one person is an unplanned-absence "
                              "outage waiting to happen, and it is the metric succession planning "
                              "actually needs.",
        },
        {
            "metric_key": "learning_engagement_pct",
            "metric_name": "Learning engagement",
            "metric_value": engagement_pct,
            "metric_unit": "percent",
            "metric_detail": f"{len(learner_ids)} of {headcount} in-headcount workers completed "
                             f"learning in the last {cfg.LEARNING_LOOKBACK_DAYS} days",
            "target_value": 80.0,
            "direction": "higher_is_better",
            "why_it_matters": "Learning activity is the only forward-looking signal here - it "
                              "shows whether the skill gaps identified are actually being closed.",
        },
    ])


def build_data_quality_summary(dq_frame: pd.DataFrame) -> pd.DataFrame:
    if dq_frame.empty:
        return dq_frame
    summary = (
        dq_frame.groupby(["source_system", "issue_type", "severity"])
        .size().reset_index(name="issue_count")
    )
    order = {"high": 0, "medium": 1, "low": 2}
    summary["_o"] = summary["severity"].map(order).fillna(3)
    return summary.sort_values(["_o", "issue_count"], ascending=[True, False]).drop(columns="_o").reset_index(drop=True)
