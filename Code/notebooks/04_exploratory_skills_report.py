# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · Exploratory analysis → findings report
# MAGIC
# MAGIC This notebook is the working-out. It explores the gold tables question by
# MAGIC question, shows the evidence behind each answer, and ends by rendering the
# MAGIC findings as a standalone report page.
# MAGIC
# MAGIC The questions, in the order they have to be asked:
# MAGIC
# MAGIC 1. Who is actually in the population, once the four sources stop disagreeing?
# MAGIC 2. Can the ratings be compared at all?
# MAGIC 3. Which skills does the business depend on, and how few people hold them?
# MAGIC 4. How current is any of this?
# MAGIC 5. What lapses next, and what does it cost?
# MAGIC 6. Is learning activity turning into recorded capability?
# MAGIC
# MAGIC The report at the bottom is generated from the same tables, so it cannot drift
# MAGIC from what is shown here.

# COMMAND ----------

import sys
from pathlib import Path


def roots() -> tuple[Path, Path]:
    """(Code/, repository root), whether this runs from a Git folder or a bundle.

    This notebook lives at ``Code/notebooks/``, so the code root is two levels
    up and the repository root - which holds ``Data/`` and ``Deliverables/`` -
    is one above that.
    """
    ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
    here = Path("/Workspace" + ctx.notebookPath().get()).resolve()
    code_root = here.parent.parent
    return code_root, code_root.parent


CODE_ROOT, REPO_ROOT = roots()
sys.path.insert(0, str(CODE_ROOT / "src"))

from skills_analysis import config as cfg, report  # noqa: E402

S = f"{cfg.CATALOG}.{cfg.SILVER_SCHEMA}"
G = f"{cfg.CATALOG}.{cfg.GOLD_SCHEMA}"
print(f"Analysis as-of {cfg.AS_OF_DATE}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1 · Who is in the population?
# MAGIC
# MAGIC Start here, because every later number divides by this one. Taken at face value
# MAGIC the sources describe 28 identifiers. They describe 25 people.

# COMMAND ----------

display(spark.sql(f"""
    SELECT worker_type, worker_status, count(*) AS workers,
           sum(CASE WHEN in_headcount THEN 1 ELSE 0 END) AS in_headcount
    FROM {S}.worker
    GROUP BY ALL
    ORDER BY workers DESC
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC Three people arrived under two identifiers each. Two of them are acquisition
# MAGIC transfers whose Workday hire date is the migration date, not the day they
# MAGIC started - which understates their tenure by years.

# COMMAND ----------

display(spark.sql(f"""
    SELECT worker_name, employee_id, legacy_worker_ids, supervisory_org,
           original_hire_date, workday_hire_date,
           datediff(workday_hire_date, original_hire_date) / 365.25 AS tenure_years_hidden
    FROM {S}.worker
    WHERE length(legacy_worker_ids) > 0
    ORDER BY tenure_years_hidden DESC
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2 · Can the ratings be compared?
# MAGIC
# MAGIC Four rating dialects appear across two systems. The confidence column records
# MAGIC how much of a translation each one needed - and low-confidence ratings are never
# MAGIC allowed to establish that someone is deep in a skill.

# COMMAND ----------

display(spark.sql(f"""
    SELECT proficiency_confidence, assessment_source, count(*) AS ratings,
           round(avg(proficiency), 2) AS avg_proficiency
    FROM {G}.worker_skill_profile
    WHERE proficiency IS NOT NULL
    GROUP BY ALL
    ORDER BY ratings DESC
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC Where both systems rate the same person on the same skill, do they agree?

# COMMAND ----------

display(spark.sql(f"""
    SELECT worker_name, canonical_skill, workday_proficiency, matrix_proficiency,
           abs(workday_proficiency - matrix_proficiency) AS gap, assessment_source
    FROM {G}.worker_skill_profile
    WHERE workday_proficiency IS NOT NULL AND matrix_proficiency IS NOT NULL
    ORDER BY gap DESC, worker_name
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3 · Where is capability concentrated?
# MAGIC
# MAGIC The bus-factor question. A skill claimed by many people but held deeply by none
# MAGIC is a different problem from one held deeply by exactly one person, and both are
# MAGIC different from genuine coverage.

# COMMAND ----------

display(spark.sql(f"""
    SELECT risk_band, count(*) AS skills,
           concat_ws(', ', collect_list(canonical_skill)) AS which
    FROM {G}.skill_coverage
    WHERE is_critical_skill
    GROUP BY risk_band
    ORDER BY CASE risk_band
        WHEN 'No coverage' THEN 1 WHEN 'No depth' THEN 2
        WHEN 'Single point of failure' THEN 3 WHEN 'Thin' THEN 4 ELSE 5 END
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC The widest gap between how many people *claim* a skill and how many actually
# MAGIC hold it. This is where breadth has been mistaken for capability.

# COMMAND ----------

display(spark.sql(f"""
    SELECT canonical_skill, people_with_skill, deep_practitioners,
           people_with_skill - deep_practitioners AS claim_without_depth,
           avg_proficiency, declared_no_exposure, risk_band
    FROM {G}.skill_coverage
    WHERE is_critical_skill
    ORDER BY claim_without_depth DESC, people_with_skill DESC
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC Who are the people a critical skill rests on entirely? These names are the
# MAGIC succession plan, whether or not anyone has written one.

# COMMAND ----------

display(spark.sql(f"""
    SELECT p.worker_name, p.supervisory_org,
           concat_ws(', ', collect_list(p.canonical_skill)) AS sole_owner_of,
           count(*) AS critical_skills_resting_on_them
    FROM {G}.worker_skill_profile p
    JOIN {G}.skill_coverage c USING (canonical_skill)
    WHERE p.is_deep AND c.is_single_point_of_failure AND p.in_headcount
    GROUP BY p.worker_name, p.supervisory_org
    ORDER BY critical_skills_resting_on_them DESC
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4 · How current is the data?
# MAGIC
# MAGIC Freshness is the constraint on everything above. An org at 0% is not a low
# MAGIC performer - it is an org whose capability is unknown.

# COMMAND ----------

display(spark.sql(f"""
    SELECT supervisory_org, headcount, profile_coverage_pct, profile_freshness_pct,
           avg_days_since_skill_update, learning_engagement_pct, certs_at_risk
    FROM {G}.org_scorecard
    ORDER BY profile_freshness_pct, avg_days_since_skill_update DESC
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5 · What lapses next?

# COMMAND ----------

display(spark.sql(f"""
    SELECT worker_name, certification, cert_status, expires_on, days_to_expiry,
           risk_band, voucher_cost, on_approved_cert_list, notes
    FROM {G}.cert_compliance
    WHERE in_headcount
    ORDER BY CASE WHEN days_to_expiry IS NULL THEN 0 ELSE 1 END, days_to_expiry
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC The tracker's own total says $2,071. That figure is the exact sum of a stale
# MAGIC FY25 pivot left on the `DO NOT DELETE` tab, so the total cell is pointed at the
# MAGIC wrong range.

# COMMAND ----------

display(spark.sql(f"""
    SELECT
        round(sum(voucher_cost), 0)                                        AS tracked_voucher_spend,
        2071                                                               AS stated_total_on_sheet,
        round(sum(voucher_cost) / 2071, 1)                                 AS understatement_factor,
        round(sum(CASE WHEN NOT on_approved_cert_list THEN voucher_cost END), 0)
                                                                           AS spend_outside_approved_list
    FROM {G}.cert_compliance
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6 · Is learning turning into recorded capability?
# MAGIC
# MAGIC Engagement is healthy and freshness is not, which means the gap is recording,
# MAGIC not effort. These people learned something in the last year and their skill
# MAGIC profile has not moved in six months.

# COMMAND ----------

display(spark.sql(f"""
    WITH recent_learners AS (
        SELECT DISTINCT employee_id FROM {S}.learning_completion WHERE is_recent
    ),
    current_profiles AS (
        SELECT DISTINCT employee_id FROM {G}.worker_skill_profile WHERE is_current
    )
    SELECT w.worker_name, w.supervisory_org,
           (SELECT count(*) FROM {S}.learning_completion l
             WHERE l.employee_id = w.employee_id AND l.is_recent) AS completions_last_year,
           (SELECT max(last_updated) FROM {G}.worker_skill_profile p
             WHERE p.employee_id = w.employee_id)                 AS profile_last_touched
    FROM {S}.worker w
    WHERE w.in_headcount
      AND w.employee_id IN (SELECT employee_id FROM recent_learners)
      AND w.employee_id NOT IN (SELECT employee_id FROM current_profiles)
    ORDER BY completions_last_year DESC, w.worker_name
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## The report
# MAGIC
# MAGIC Rendered from the gold tables above and written to the Volume so it can be
# MAGIC linked to, attached to a review, or served from anywhere with access.

# COMMAND ----------

tables = {
    "silver_worker": spark.table(f"{S}.worker").toPandas(),
    "silver_learning_completion": spark.table(f"{S}.learning_completion").toPandas(),
    "silver_data_quality_issue": spark.table(f"{S}.data_quality_issue").toPandas(),
    "gold_worker_skill_profile": spark.table(f"{G}.worker_skill_profile").toPandas(),
    "gold_skill_coverage": spark.table(f"{G}.skill_coverage").toPandas(),
    "gold_cert_compliance": spark.table(f"{G}.cert_compliance").toPandas(),
    "gold_org_scorecard": spark.table(f"{G}.org_scorecard").toPandas(),
    "gold_kpi_snapshot": spark.table(f"{G}.kpi_snapshot").toPandas(),
}

html_report = report.build_report(tables)

output_path = (
    f"/Volumes/{cfg.CATALOG}/{cfg.BRONZE_SCHEMA}/{cfg.RAW_VOLUME}/"
    f"reports/skills_report_{cfg.AS_OF_DATE.isoformat()}.html"
)
dbutils.fs.mkdirs(output_path.rsplit("/", 1)[0])
with open(output_path, "w", encoding="utf-8") as handle:
    handle.write(html_report)
print(f"Report written to {output_path}  ({len(html_report):,} bytes)")

# COMMAND ----------

displayHTML(html_report)
