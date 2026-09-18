# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Bronze — land each export verbatim
# MAGIC
# MAGIC Bronze is a faithful copy: every value stays a string, exactly as the source
# MAGIC wrote it. The only judgement applied is structural — find the real header row,
# MAGIC drop the banner and footer notes, and unpivot the wide skills matrix into rows.
# MAGIC
# MAGIC Value-level repair is deliberately *not* done here. Keeping the mess intact
# MAGIC means any cleaning decision made in silver can be traced back to what actually
# MAGIC arrived, and re-run differently without re-ingesting.

# COMMAND ----------

# MAGIC %pip install openpyxl==3.1.5
# MAGIC %restart_python

# COMMAND ----------

import sys
from datetime import datetime
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

from skills_analysis import config as cfg, extract  # noqa: E402

VOLUME_ROOT = f"/Volumes/{cfg.CATALOG}/{cfg.BRONZE_SCHEMA}/{cfg.RAW_VOLUME}/source"
INGESTED_AT = datetime.utcnow().isoformat(timespec="seconds")
print(f"Reading from {VOLUME_ROOT}")

# COMMAND ----------

# MAGIC %md ## Read each source

# COMMAND ----------

frames = {
    "workday_worker_skills": extract.read_workday(
        f"{VOLUME_ROOT}/workday_worker_skills_20260901.csv"
    ),
    "degreed_completions": extract.read_degreed(
        f"{VOLUME_ROOT}/degreed_learning_completions_20260901.xlsx"
    ),
    "recert_tracker": extract.read_recert_tracker(
        f"{VOLUME_ROOT}/recert_tracker_draft.xlsx"
    ),
    "cert_catalogue": extract.read_cert_catalogue(
        f"{VOLUME_ROOT}/recert_tracker_draft.xlsx"
    ),
    "skills_matrix": extract.read_skills_matrix(
        f"{VOLUME_ROOT}/skills_matrix_final_v3_1.xlsx"
    ),
}

for name, frame in frames.items():
    print(f"  {name:26s} {len(frame):4d} rows x {len(frame.columns)} cols")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write the bronze tables
# MAGIC
# MAGIC Column names are made SQL-safe; the original header text is preserved in the
# MAGIC table comment so nothing about the source is lost.

# COMMAND ----------

import re


def sql_safe(name: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()
    return cleaned or "col"


for name, frame in frames.items():
    table = f"{cfg.CATALOG}.{cfg.BRONZE_SCHEMA}.{name}"
    out = frame.copy()
    original_columns = list(out.columns)
    out.columns = [sql_safe(c) for c in original_columns]
    out["_ingested_at"] = INGESTED_AT
    out["_source_file"] = name

    (spark.createDataFrame(out)
        .write.mode("overwrite").option("overwriteSchema", "true")
        .saveAsTable(table))

    header = ", ".join(original_columns).replace("'", "''")
    spark.sql(
        f"COMMENT ON TABLE {table} IS "
        f"'Verbatim ingest. Source header: {header}'"
    )
    print(f"  wrote {table:56s} {len(out):4d} rows")

# COMMAND ----------

# MAGIC %md ## Verify

# COMMAND ----------

display(spark.sql(f"""
    SELECT table_name, comment
    FROM {cfg.CATALOG}.information_schema.tables
    WHERE table_schema = '{cfg.BRONZE_SCHEMA}'
    ORDER BY table_name
"""))

# COMMAND ----------

display(spark.table(f"{cfg.CATALOG}.{cfg.BRONZE_SCHEMA}.workday_worker_skills").limit(10))
