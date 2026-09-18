# Databricks notebook source
# MAGIC %md
# MAGIC # 00 · Set up the lakehouse
# MAGIC
# MAGIC Creates the Unity Catalog objects the pipeline writes into, and lands the four
# MAGIC raw exports plus the reference tables in a managed Volume so bronze always has
# MAGIC an immutable copy of exactly what arrived.
# MAGIC
# MAGIC | Object | Purpose |
# MAGIC |---|---|
# MAGIC | `skills_analysis.bronze` | Verbatim copies of each export |
# MAGIC | `skills_analysis.silver` | Conformed, deduplicated, identity-resolved |
# MAGIC | `skills_analysis.gold` | Analytics tables behind the report and dashboard |
# MAGIC | `skills_analysis.bronze.raw_files` | Volume holding the source files and reference CSVs |
# MAGIC
# MAGIC Run this once per environment. It is idempotent.

# COMMAND ----------

# MAGIC %md ## Locate the repo and load shared configuration

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

from skills_analysis import config as cfg  # noqa: E402

print(f"Repo root      : {REPO_ROOT}")
print(f"Code root      : {CODE_ROOT}")
print(f"Catalog        : {cfg.CATALOG}")
print(f"Analysis as-of : {cfg.AS_OF_DATE}")

# COMMAND ----------

# MAGIC %md ## Create the catalog, schemas and volume

# COMMAND ----------

spark.sql(f"CREATE CATALOG IF NOT EXISTS {cfg.CATALOG}")
for schema in (cfg.BRONZE_SCHEMA, cfg.SILVER_SCHEMA, cfg.GOLD_SCHEMA):
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {cfg.CATALOG}.{schema}")

spark.sql(
    f"CREATE VOLUME IF NOT EXISTS {cfg.CATALOG}.{cfg.BRONZE_SCHEMA}.{cfg.RAW_VOLUME} "
    f"COMMENT 'Immutable copies of the source exports and the maintained reference tables'"
)

VOLUME_ROOT = f"/Volumes/{cfg.CATALOG}/{cfg.BRONZE_SCHEMA}/{cfg.RAW_VOLUME}"
print(f"Volume ready at {VOLUME_ROOT}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Land the source files
# MAGIC
# MAGIC The originals are copied byte for byte. Nothing downstream reads from the repo
# MAGIC at run time, so a re-run reproduces the same tables from the same bytes.

# COMMAND ----------

import shutil

dbutils.fs.mkdirs(f"{VOLUME_ROOT}/source")
dbutils.fs.mkdirs(f"{VOLUME_ROOT}/reference")

for source in cfg.SOURCE_FILES:
    src = REPO_ROOT / "Data" / "raw" / source.filename
    dst = f"{VOLUME_ROOT}/source/{source.filename}"
    shutil.copyfile(src, dst)
    print(f"  {source.system:22s} -> {source.filename}")

for name in cfg.REFERENCE_FILES:
    shutil.copyfile(REPO_ROOT / "Data" / "reference" / name, f"{VOLUME_ROOT}/reference/{name}")
    print(f"  reference              -> {name}")

# COMMAND ----------

display(dbutils.fs.ls(f"{VOLUME_ROOT}/source"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Register the reference tables
# MAGIC
# MAGIC These encode human judgement - which spellings are one skill, which identifiers
# MAGIC are one person, what an "H" rating means. They are queryable so a reviewer can
# MAGIC audit any mapping the pipeline applied, and editable without touching code.

# COMMAND ----------

import pandas as pd

for name in cfg.REFERENCE_FILES:
    table = f"{cfg.CATALOG}.{cfg.BRONZE_SCHEMA}.ref_{Path(name).stem}"
    pdf = pd.read_csv(f"{VOLUME_ROOT}/reference/{name}", dtype=str, keep_default_na=False)
    spark.createDataFrame(pdf).write.mode("overwrite").option(
        "overwriteSchema", "true"
    ).saveAsTable(table)
    print(f"  {table:60s} {len(pdf):4d} rows")

# COMMAND ----------

# MAGIC %md ## Verify

# COMMAND ----------

display(spark.sql(f"SHOW TABLES IN {cfg.CATALOG}.{cfg.BRONZE_SCHEMA}"))
