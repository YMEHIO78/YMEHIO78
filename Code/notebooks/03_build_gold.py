# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Gold — the tables the report and dashboard read
# MAGIC
# MAGIC Five tables, each answering one question:
# MAGIC
# MAGIC | Table | Question |
# MAGIC |---|---|
# MAGIC | `worker_skill_profile` | What does each person know, on what evidence, how stale? |
# MAGIC | `skill_coverage` | Which skills rest on too few people? |
# MAGIC | `cert_compliance` | Which certifications lapse next, and what do they cost? |
# MAGIC | `org_scorecard` | Which org's data can be trusted, and what is at risk there? |
# MAGIC | `kpi_snapshot` | The four numbers worth watching every week |
# MAGIC
# MAGIC Two rules matter here and are enforced in code, not convention:
# MAGIC
# MAGIC - **Depth needs a comparable scale.** An `H` translated onto 1-5 is an
# MAGIC   approximation. It can colour a heatmap; it cannot declare someone the expert
# MAGIC   a team depends on. Low-confidence ratings never establish depth.
# MAGIC - **A blank is not a zero.** An empty matrix cell means nobody filled it in.
# MAGIC   Only an explicit "no" counts as declared no exposure.

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

from skills_analysis import config as cfg, gold  # noqa: E402

S = f"{cfg.CATALOG}.{cfg.SILVER_SCHEMA}"
G = f"{cfg.CATALOG}.{cfg.GOLD_SCHEMA}"

# COMMAND ----------

workers = spark.table(f"{S}.worker").toPandas()
worker_skills = spark.table(f"{S}.worker_skill").toPandas()
matrix = spark.table(f"{S}.matrix_rating").toPandas()
certifications = spark.table(f"{S}.certification").toPandas()
learning = spark.table(f"{S}.learning_completion").toPandas()
issues = spark.table(f"{S}.data_quality_issue").toPandas()

# Spark returns timestamps; the analytics work in plain dates.
for frame, columns in (
    (workers, ["original_hire_date", "workday_hire_date"]),
    (worker_skills, ["last_updated"]),
    (certifications, ["expires_on"]),
    (learning, ["completed_on"]),
):
    for column in columns:
        if column in frame.columns:
            frame[column] = frame[column].map(lambda v: v.date() if hasattr(v, "date") else v)

# COMMAND ----------

# MAGIC %md ## Build

# COMMAND ----------

profile = gold.build_worker_skill_profile(worker_skills, matrix, workers)
coverage = gold.build_skill_coverage(profile, workers)
certs = gold.build_cert_compliance(certifications, workers)
scorecard = gold.build_org_scorecard(workers, profile, learning, certs)
kpis = gold.build_kpi_snapshot(workers, profile, coverage, learning, certs)
dq_summary = gold.build_data_quality_summary(issues)

for name, frame in [
    ("worker_skill_profile", profile), ("skill_coverage", coverage),
    ("cert_compliance", certs), ("org_scorecard", scorecard),
    ("kpi_snapshot", kpis), ("data_quality_summary", dq_summary),
]:
    print(f"  {name:24s} {len(frame):4d} rows")

# COMMAND ----------

# MAGIC %md ## Write gold

# COMMAND ----------

import pandas as pd

GOLD_TABLES = {
    "worker_skill_profile": (profile, "One row per worker per skill: best available evidence, its confidence, and how stale it is."),
    "skill_coverage": (coverage, "Per skill: who holds it, how deep it goes, and whether it is a single point of failure."),
    "cert_compliance": (certs, "Per certification: days to expiry, risk band and voucher cost."),
    "org_scorecard": (scorecard, "Per organisation: data trustworthiness and what is at risk."),
    "kpi_snapshot": (kpis, "The four headline metrics, one row each, for the dashboard counters."),
    "data_quality_summary": (dq_summary, "Data quality issue counts by source, type and severity."),
}

for name, (frame, comment) in GOLD_TABLES.items():
    table = f"{G}.{name}"
    out = frame.copy()
    for column in out.columns:
        if out[column].map(lambda v: hasattr(v, "isoformat")).any():
            out[column] = pd.to_datetime(out[column], errors="coerce")
    (spark.createDataFrame(out)
        .write.mode("overwrite").option("overwriteSchema", "true")
        .saveAsTable(table))
    spark.sql(f"COMMENT ON TABLE {table} IS '{comment}'")
    print(f"  wrote {table:50s} {len(out):4d} rows")

# COMMAND ----------

# MAGIC %md ## The four headline metrics

# COMMAND ----------

display(spark.sql(f"""
    SELECT metric_name, metric_value, metric_unit, target_value, direction, metric_detail
    FROM {G}.kpi_snapshot
    ORDER BY metric_key
"""))

# COMMAND ----------

# MAGIC %md ## Critical skills ordered by how exposed they are

# COMMAND ----------

display(spark.sql(f"""
    SELECT canonical_skill, people_with_skill, deep_practitioners, risk_band,
           deep_practitioner_names, criticality_rationale
    FROM {G}.skill_coverage
    WHERE is_critical_skill
    ORDER BY deep_practitioners, people_with_skill DESC
"""))
