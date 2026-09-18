# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Silver — one person, one skill, one rating scale
# MAGIC
# MAGIC Silver is where the four sources stop disagreeing with each other. Three things
# MAGIC happen here, and every one of them is logged:
# MAGIC
# MAGIC 1. **Identity resolution** — the same person is written eight different ways
# MAGIC    across these files (legal name, preferred name, initials, username, email,
# MAGIC    legacy tenant ID, a truncated employee ID). All of it resolves to one
# MAGIC    Workday employee ID via the auditable crosswalk in `ref_identity_overrides`.
# MAGIC 2. **Conformance** — skill spellings collapse onto a taxonomy, four rating
# MAGIC    dialects collapse onto 1-5, and every date shape becomes a date.
# MAGIC 3. **Deduplication** — with conflicts resolved by an explicit precedence rule
# MAGIC    rather than by whichever row happened to be read first.
# MAGIC
# MAGIC Nothing is dropped silently. Every repair, exclusion and unresolved conflict
# MAGIC lands in `silver.data_quality_issue` with what was done about it.

# COMMAND ----------

import sys
from pathlib import Path


def repo_root() -> Path:
    ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
    return Path("/Workspace" + ctx.notebookPath().get()).resolve().parent.parent


ROOT = repo_root()
sys.path.insert(0, str(ROOT / "src"))

from skills_analysis import config as cfg, transform  # noqa: E402

B = f"{cfg.CATALOG}.{cfg.BRONZE_SCHEMA}"
S = f"{cfg.CATALOG}.{cfg.SILVER_SCHEMA}"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Read bronze
# MAGIC
# MAGIC The transforms are pandas. At a few hundred rows that is both faster and far
# MAGIC clearer than the equivalent Spark plan, and it keeps one implementation of every
# MAGIC cleaning rule shared with the local runner and the test suite. Outputs are
# MAGIC written back as Delta, so every consumer downstream is still reading a table.
# MAGIC If this population ever outgrows a single node, these calls are the seam to
# MAGIC swap for Spark DataFrame operations.

# COMMAND ----------

def bronze(name: str, columns: list[str]):
    """Read a bronze table back with its original header names restored."""
    pdf = spark.table(f"{B}.{name}").drop("_ingested_at", "_source_file").toPandas()
    pdf.columns = columns
    return pdf


workday_raw = bronze("workday_worker_skills", [
    "Employee ID", "Worker", "Business Title", "Job Profile", "Supervisory Organization",
    "Cost Center", "Location", "Worker Type", "Worker Status", "Hire Date", "Manager",
    "Skill", "Skill Category", "Proficiency Rating", "Years of Experience", "Skill Source",
    "Last Updated",
])
degreed_raw = bronze("degreed_completions", [
    "User Email", "Employee ID", "Name", "Group / Org", "Learning Item", "Provider",
    "Skill Tag", "Status", "Duration (hrs)", "Completion Date", "Expires", "Assigned By",
])
recert_raw = bronze("recert_tracker", [
    "Engineer", "Certification", "Cert Status", "Expires", "CE Credits Earned",
    "Exam / Path", "Voucher $", "Who's mentoring", "Notes", "_stray_comment",
])
catalogue_raw = bronze("cert_catalogue", ["certification", "vendor", "list_price"])
matrix_raw = bronze("skills_matrix", [
    "matrix_row", "matrix_section", "name", "team", "skill", "rating", "notes",
])

print(f"workday {len(workday_raw)}  degreed {len(degreed_raw)}  recert {len(recert_raw)}  "
      f"catalogue {len(catalogue_raw)}  matrix {len(matrix_raw)}")

# COMMAND ----------

# MAGIC %md ## Conform every source

# COMMAND ----------

dq = transform.DQLog()

workers = transform.build_worker_dim(workday_raw, dq)
worker_skills = transform.build_worker_skills(workday_raw, workers, dq)
matrix = transform.build_matrix_ratings(matrix_raw, dq)
certifications = transform.build_certifications(recert_raw, catalogue_raw, workers, dq)
learning = transform.build_learning(degreed_raw, workers, dq)
issues = dq.frame()

print(f"workers            {len(workers):4d}  ({int(workers['in_headcount'].sum())} in headcount)")
print(f"worker skills      {len(worker_skills):4d}")
print(f"matrix ratings     {len(matrix):4d}")
print(f"certifications     {len(certifications):4d}")
print(f"learning records   {len(learning):4d}")
print(f"data quality issues{len(issues):4d}")

# COMMAND ----------

# MAGIC %md ## Write silver

# COMMAND ----------

import pandas as pd

SILVER_TABLES = {
    "worker": (workers, "One row per person. Identity, tenure and population flags resolved."),
    "worker_skill": (worker_skills, "Workday skill ratings, conformed and deduplicated."),
    "matrix_rating": (matrix, "Manual skills matrix, unpivoted and identity-resolved."),
    "certification": (certifications, "Recertification tracker, cleaned and deduplicated."),
    "learning_completion": (learning, "Degreed completions, identity-resolved and deduplicated."),
    "data_quality_issue": (issues, "Every repair, exclusion and conflict, with its resolution."),
}

for name, (frame, comment) in SILVER_TABLES.items():
    table = f"{S}.{name}"
    out = frame.copy()
    # Dates carry through as real dates; pandas object columns need the nudge.
    for column in out.columns:
        if out[column].map(lambda v: hasattr(v, "isoformat")).any():
            out[column] = pd.to_datetime(out[column], errors="coerce")
    (spark.createDataFrame(out)
        .write.mode("overwrite").option("overwriteSchema", "true")
        .saveAsTable(table))
    spark.sql(f"COMMENT ON TABLE {table} IS '{comment}'")
    print(f"  wrote {table:52s} {len(out):4d} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## What the cleanup actually had to fix
# MAGIC
# MAGIC This table is the honest account of the pipeline. A high-severity row is
# MAGIC something a human should look at in the source system, not just a note.

# COMMAND ----------

display(spark.sql(f"""
    SELECT severity, source_system, issue_type, count(*) AS issues
    FROM {S}.data_quality_issue
    GROUP BY ALL
    ORDER BY CASE severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, issues DESC
"""))

# COMMAND ----------

display(spark.sql(f"""
    SELECT source_system, issue_type, entity, detail, resolution
    FROM {S}.data_quality_issue
    WHERE severity = 'high'
    ORDER BY source_system, issue_type
"""))
