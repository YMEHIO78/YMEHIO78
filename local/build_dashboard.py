#!/usr/bin/env python3
"""Generate the AI/BI dashboard definition (``.lvdash.json``).

Written as code rather than hand-edited JSON so the SQL stays readable, the
widget ids stay unique, and the catalog name comes from one place.

The four counters aggregate over per-worker and per-certification datasets
rather than reading a precomputed snapshot, so the organisation and skill-domain
filters actually move them. A tile that ignores its own filter is worse than no
tile at all.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from skills_analysis import config as cfg  # noqa: E402

S = f"{cfg.CATALOG}.{cfg.SILVER_SCHEMA}"
G = f"{cfg.CATALOG}.{cfg.GOLD_SCHEMA}"

GRID_WIDTH = 6  # AI/BI dashboards lay out on a six-column grid.


def q(sql: str) -> list[str]:
    return [line for line in sql.strip("\n").rstrip().split("\n")]


DATASETS = [
    {
        "name": "ds_worker_base",
        "displayName": "Worker profile and learning base",
        "queryLines": q(f"""
SELECT
  w.employee_id,
  w.worker_name,
  w.supervisory_org,
  w.location,
  w.worker_status,
  CASE WHEN fresh.employee_id IS NOT NULL THEN 1 ELSE 0 END AS has_current_profile,
  CASE WHEN learn.employee_id IS NOT NULL THEN 1 ELSE 0 END AS has_recent_learning
FROM {S}.worker w
LEFT JOIN (
  SELECT DISTINCT employee_id FROM {G}.worker_skill_profile WHERE is_current
) fresh ON fresh.employee_id = w.employee_id
LEFT JOIN (
  SELECT DISTINCT employee_id FROM {S}.learning_completion WHERE is_recent
) learn ON learn.employee_id = w.employee_id
WHERE w.in_headcount
"""),
    },
    {
        "name": "ds_cert_risk",
        "displayName": "Certification risk",
        "queryLines": q(f"""
SELECT
  worker_name,
  supervisory_org,
  certification,
  cert_status,
  expires_on,
  days_to_expiry,
  risk_band,
  coalesce(voucher_cost, 0) AS voucher_cost,
  on_approved_cert_list,
  CASE WHEN is_at_risk THEN 1 ELSE 0 END AS at_risk
FROM {G}.cert_compliance
WHERE in_headcount
"""),
    },
    {
        "name": "ds_critical_skills",
        "displayName": "Critical skill coverage",
        "queryLines": q(f"""
SELECT
  canonical_skill,
  skill_domain,
  people_with_skill,
  deep_practitioners,
  people_with_skill - deep_practitioners AS claim_without_depth,
  avg_proficiency,
  risk_band,
  deep_practitioner_names,
  criticality_rationale,
  CASE WHEN is_single_point_of_failure THEN 1 ELSE 0 END AS no_backup
FROM {G}.skill_coverage
WHERE is_critical_skill
"""),
    },
    {
        "name": "ds_org_scorecard",
        "displayName": "Organisation scorecard",
        "queryLines": q(f"""
SELECT
  supervisory_org,
  headcount,
  profile_freshness_pct,
  profile_coverage_pct,
  learning_engagement_pct,
  certs_at_risk,
  avg_days_since_skill_update
FROM {G}.org_scorecard
"""),
    },
    {
        "name": "ds_data_quality",
        "displayName": "Data quality issues",
        "queryLines": q(f"""
SELECT
  source_system,
  issue_type,
  severity,
  issue_count
FROM {G}.data_quality_summary
"""),
    },
]


def counter(name: str, dataset: str, field: str, expression: str, title: str,
            description: str) -> dict:
    return {
        "name": name,
        "queries": [{
            "name": "main_query",
            "query": {
                "datasetName": dataset,
                "fields": [{"name": field, "expression": expression}],
                "disaggregated": False,
            },
        }],
        "spec": {
            "version": 2,
            "widgetType": "counter",
            "encodings": {"value": {"fieldName": field, "displayName": description}},
            "frame": {"showTitle": True, "title": title, "showDescription": True,
                      "description": description},
        },
    }


def bar(name: str, dataset: str, category: str, category_label: str,
        value: str, value_expression: str, value_label: str, title: str,
        description: str, color_field: str | None = None,
        color_label: str | None = None) -> dict:
    fields = [
        {"name": category, "expression": f"`{category}`"},
        {"name": value, "expression": value_expression},
    ]
    encodings: dict = {
        "x": {"fieldName": value, "scale": {"type": "quantitative"},
              "displayName": value_label},
        "y": {"fieldName": category, "scale": {"type": "categorical"},
              "displayName": category_label},
    }
    if color_field:
        fields.append({"name": color_field, "expression": f"`{color_field}`"})
        encodings["color"] = {
            "fieldName": color_field,
            "scale": {"type": "categorical"},
            "displayName": color_label or color_field,
        }
    return {
        "name": name,
        "queries": [{
            "name": "main_query",
            "query": {"datasetName": dataset, "fields": fields, "disaggregated": False},
        }],
        "spec": {
            "version": 3,
            "widgetType": "bar",
            "encodings": encodings,
            "frame": {"showTitle": True, "title": title, "showDescription": True,
                      "description": description},
        },
    }


def table(name: str, dataset: str, columns: list[tuple[str, str]], title: str,
          description: str) -> dict:
    return {
        "name": name,
        "queries": [{
            "name": "main_query",
            "query": {
                "datasetName": dataset,
                "fields": [{"name": c, "expression": f"`{c}`"} for c, _ in columns],
                "disaggregated": True,
            },
        }],
        "spec": {
            "version": 1,
            "widgetType": "table",
            "encodings": {"columns": [
                {"fieldName": c, "displayName": label, "booleanValues": ["false", "true"],
                 "type": "string", "visible": True, "order": i}
                for i, (c, label) in enumerate(columns)
            ]},
            "frame": {"showTitle": True, "title": title, "showDescription": True,
                      "description": description},
        },
    }


def multi_filter(name: str, field: str, label: str, datasets: list[str]) -> dict:
    """One filter bound across several datasets, so it moves every tile that has the field."""
    return {
        "name": name,
        "queries": [
            {
                "name": f"filter_query_{i}",
                "query": {
                    "datasetName": dataset,
                    "fields": [
                        {"name": field, "expression": f"`{field}`"},
                        {"name": f"{field}_associativity",
                         "expression": "COUNT_IF(`associative_filter_predicate_group`)"},
                    ],
                    "disaggregated": False,
                },
            }
            for i, dataset in enumerate(datasets)
        ],
        "spec": {
            "version": 2,
            "widgetType": "filter-multi-select",
            "encodings": {"fields": [
                {"fieldName": field, "displayName": label, "queryName": f"filter_query_{i}"}
                for i, _ in enumerate(datasets)
            ]},
            "frame": {"showTitle": True, "title": label},
        },
    }


def markdown(name: str, text: str) -> dict:
    return {"name": name, "textbox_spec": text}


def place(widget: dict, x: int, y: int, width: int, height: int) -> dict:
    assert x + width <= GRID_WIDTH, f"{widget['name']} overflows the grid"
    return {"widget": widget, "position": {"x": x, "y": y, "width": width, "height": height}}


def build() -> dict:
    layout = []
    y = 0

    layout.append(place(markdown("header", (
        "# Skills Intelligence\n\n"
        "Four metrics worth watching every week, reconciled across Workday, Degreed, "
        "the recertification tracker and the team skills matrix. "
        "**Population:** employees with status Active or Leave of Absence — contingent "
        "workers, interns and leavers are excluded so a departure never looks like an "
        "improvement.\n\n"
        "Use the filters to narrow by organisation or skill domain; every tile below "
        "responds to them."
    )), 0, y, 6, 3))
    y += 3

    layout.append(place(multi_filter(
        "filter_org", "supervisory_org", "Organisation",
        ["ds_worker_base", "ds_cert_risk", "ds_org_scorecard"],
    ), 0, y, 3, 2))
    layout.append(place(multi_filter(
        "filter_domain", "skill_domain", "Skill domain", ["ds_critical_skills"],
    ), 3, y, 3, 2))
    y += 2

    # --- the four metrics ------------------------------------------------
    layout.append(place(counter(
        "kpi_freshness", "ds_worker_base", "profile_freshness_pct",
        "ROUND(100.0 * SUM(`has_current_profile`) / COUNT(`employee_id`), 0)",
        "Skill profile freshness %",
        f"Share of workers whose skill rating was updated in the last "
        f"{cfg.PROFILE_FRESHNESS_DAYS} days. Target 90%. Everything else on this "
        f"dashboard is only as good as this number.",
    ), 0, y, 3, 5))
    layout.append(place(counter(
        "kpi_certs", "ds_cert_risk", "certifications_at_risk", "SUM(`at_risk`)",
        "Certifications at risk",
        f"Expired, expiring within {cfg.CERT_EXPIRY_WARNING_DAYS} days, or with no "
        f"expiry recorded. Target 0. Each one has a lead time to fix.",
    ), 3, y, 3, 5))
    y += 5

    layout.append(place(counter(
        "kpi_no_backup", "ds_critical_skills", "critical_skills_without_backup",
        "SUM(`no_backup`)",
        "Critical skills with no backup",
        f"Critical skills held deeply by {cfg.BUS_FACTOR_THRESHOLD} person or fewer "
        f"(proficiency {cfg.EXPERT_THRESHOLD}+). Target 0. This is the metric "
        f"succession planning actually needs.",
    ), 0, y, 3, 5))
    layout.append(place(counter(
        "kpi_learning", "ds_worker_base", "learning_engagement_pct",
        "ROUND(100.0 * SUM(`has_recent_learning`) / COUNT(`employee_id`), 0)",
        "Learning engagement %",
        f"Share of workers who completed learning in the last "
        f"{cfg.LEARNING_LOOKBACK_DAYS} days. Target 80%. The only forward-looking "
        f"signal here — it shows whether identified gaps are being closed.",
    ), 3, y, 3, 5))
    y += 5

    # --- supporting detail ------------------------------------------------
    layout.append(place(bar(
        "chart_depth", "ds_critical_skills", "canonical_skill", "Critical skill",
        "deep_practitioners", "SUM(`deep_practitioners`)", "People at proficiency 4+",
        "Where capability is concentrated",
        "Bars at zero are skills nobody holds at depth. Bars at one are a single "
        "unplanned absence away from a gap.",
    ), 0, y, 6, 8))
    y += 8

    layout.append(place(bar(
        "chart_freshness", "ds_org_scorecard", "supervisory_org", "Organisation",
        "profile_freshness_pct", "AVG(`profile_freshness_pct`)", "Profile freshness %",
        "Which organisations can be trusted",
        "An organisation at 0% is not a low performer — it is one whose capability "
        "is simply unknown.",
    ), 0, y, 3, 8))
    layout.append(place(bar(
        "chart_dq", "ds_data_quality", "source_system", "Source system",
        "issue_count", "SUM(`issue_count`)", "Issues logged",
        "Where the data needs fixing at source",
        "Counts of repairs, exclusions and conflicts logged while reconciling each "
        "source. Split by severity.",
        color_field="severity", color_label="Severity",
    ), 3, y, 3, 8))
    y += 8

    layout.append(place(table(
        "table_certs", "ds_cert_risk",
        [("worker_name", "Worker"), ("certification", "Certification"),
         ("risk_band", "Risk"), ("expires_on", "Expires"),
         ("days_to_expiry", "Days to expiry"), ("voucher_cost", "Voucher $"),
         ("on_approved_cert_list", "On approved list")],
        "Certification pipeline",
        "Every tracked certification for the filtered population, soonest to lapse first.",
    ), 0, y, 6, 8))
    y += 8

    layout.append(place(table(
        "table_exposure", "ds_critical_skills",
        [("canonical_skill", "Skill"), ("risk_band", "Exposure"),
         ("deep_practitioner_names", "Who holds it"),
         ("people_with_skill", "Claim it"), ("deep_practitioners", "Hold it"),
         ("criticality_rationale", "Why it is critical")],
        "Critical skill exposure",
        "The gap between how many people claim a skill and how many hold it at depth.",
    ), 0, y, 6, 8))

    return {
        "datasets": DATASETS,
        "pages": [{
            "name": "skills_intelligence",
            "displayName": "Skills Intelligence",
            "layout": layout,
        }],
    }


def main() -> int:
    out = REPO_ROOT / "dashboards" / "skills_intelligence.lvdash.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    dashboard = build()
    out.write_text(json.dumps(dashboard, indent=2) + "\n", encoding="utf-8")

    widgets = dashboard["pages"][0]["layout"]
    print(f"Wrote {out.relative_to(REPO_ROOT)}")
    print(f"  {len(dashboard['datasets'])} datasets, {len(widgets)} widgets")
    names = [w["widget"]["name"] for w in widgets]
    assert len(names) == len(set(names)), "duplicate widget names"
    referenced = {
        wq["query"]["datasetName"]
        for w in widgets for wq in w["widget"].get("queries", [])
    }
    declared = {d["name"] for d in dashboard["datasets"]}
    assert referenced <= declared, f"undeclared datasets: {referenced - declared}"
    print(f"  every widget query resolves to a declared dataset")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
