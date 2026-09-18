# Deploying to Databricks

## Prerequisites

- A Databricks workspace with **Unity Catalog** enabled.
- Permission to create a catalog, or an existing catalog you can write to (see
  [using an existing catalog](#using-an-existing-catalog)).
- A **SQL warehouse** — the AI/BI dashboard needs one to run its queries.
- The [Databricks CLI](https://docs.databricks.com/dev-tools/cli/) v0.218 or
  later, authenticated: `databricks auth login --host https://<workspace>`

## Deploy with the bundle

```bash
databricks bundle validate -t dev
databricks bundle deploy   -t dev --var="warehouse_id=<your-sql-warehouse-id>"
databricks bundle run skills_analysis_pipeline -t dev
```

Find a warehouse id with `databricks warehouses list`.

This deploys the notebooks, the five-task job that chains them, and the
dashboard. The `dev` target writes to `skills_analysis_dev`; `prod` writes to
`skills_analysis`.

The run takes a few minutes and produces:

- `skills_analysis_dev.bronze` — five verbatim tables plus the reference tables
- `skills_analysis_dev.silver` — six conformed tables including the data-quality log
- `skills_analysis_dev.gold` — six analytics tables
- the report at
  `/Volumes/skills_analysis_dev/bronze/raw_files/reports/skills_report_2026-09-01.html`
- the **Skills Intelligence** dashboard, ready to open

### Compute

Tasks run on **serverless** compute, which needs no configuration. To use classic
compute instead, add a `job_clusters` block to
`Code/resources/skills_analysis_job.yml` and give each task a `job_cluster_key`:

```yaml
      job_clusters:
        - job_cluster_key: pipeline
          new_cluster:
            spark_version: "15.4.x-scala2.12"
            node_type_id: "i3.xlarge"
            num_workers: 0
            data_security_mode: SINGLE_USER
```

A single node is ample — the whole dataset is a few hundred rows.

## Without the bundle

Two manual paths, if you would rather not use the CLI.

**Notebooks.** Clone this repository as a Git folder
(*Workspace → Create → Git folder*), then run `Code/notebooks/00` through `04` in
order. They locate the repository root from their own path, so no configuration
is needed.

**Dashboard.** *Dashboards → Create dashboard → ⋮ → Import dashboard from file*,
and choose `Deliverables/skills_intelligence.lvdash.json`. Then set its warehouse
and, if you changed the catalog name, update the five dataset queries.

## Using an existing catalog

Set the catalog name and skip creation:

```bash
databricks bundle deploy -t dev \
  --var="catalog=my_existing_catalog" \
  --var="warehouse_id=<id>"
```

`CREATE CATALOG IF NOT EXISTS` in notebook `00` is a no-op when the catalog
exists, but you still need `CREATE SCHEMA` and `CREATE VOLUME` on it.

You can also override the catalog outside the bundle with the `SKILLS_CATALOG`
environment variable; see `Code/src/skills_analysis/config.py` for the full list.

## Refreshing the data

The source exports are one-off files in `Data/raw/`, so the job's schedule ships
**paused**. To refresh:

1. Drop new exports into `Data/raw/` with the same filenames, or change the
   filenames in `SOURCE_FILES` in `Code/src/skills_analysis/config.py`.
2. Update `as_of_date` in `databricks.yml` to the new extract date.
3. Re-run the job.

To point at real feeds instead, replace the readers in
`Code/src/skills_analysis/extract.py`. Everything downstream is unchanged as long as
they return the same columns.

Before promoting a refresh, run `python -m pytest Code/tests/ -q` locally. The
pipeline tests assert the decisions made about this population, so a new extract
that changes a headline number fails there first — which is the point.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `PERMISSION_DENIED` on `CREATE CATALOG` | Use an existing catalog, as above |
| Dashboard opens empty | Its warehouse is unset, or it is pointed at a catalog the pipeline has not written to yet |
| Notebook `01` fails on `openpyxl` | The `%pip install` cell at the top did not run; run it and then `%restart_python` |
| `repo_root()` resolves wrongly | The notebooks expect to sit one directory below the repository root |
