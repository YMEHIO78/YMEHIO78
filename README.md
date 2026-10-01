# Skills Analysis

Four CSVs describing a 30-person engineering organisation, one notebook that
analyses them, and a report that says what to do about it.

**→ [Read the findings](Deliverables/FINDINGS.md)**

## What is in here

```
Data/          employees · skills · certifications · learning
               sales/ — geography · products · sales · targets (Sales by Region dashboard)
               franchise/ — franchisees · locations · daily_sales (Franchise Performance dashboard)
Code/          skills_analysis.ipynb — the whole analysis
               generate_sales_data.py — builds Data/sales/
               generate_franchise_data.py — builds Data/franchise/
Deliverables/  FINDINGS.md, its charts, the Databricks dashboard, powerbi/ and franchise-powerbi/
```

### `Data/` — four tidy CSVs

| File | Rows | One row is |
|---|---:|---|
| `employees.csv` | 30 | a person: id, name, team, role, hire date |
| `skills.csv` | 90 | a person's rating in one skill, on a 1–5 scale |
| `certifications.csv` | 22 | a certification someone holds, with cost and expiry |
| `learning.csv` | 40 | a course someone completed, with hours and skill |

Synthetic data, generated to be plausible rather than drawn from any real
organisation.

### `Code/` — one notebook

[`skills_analysis.ipynb`](Code/skills_analysis.ipynb) reads the CSVs, derives two
tables (skill coverage, certification risk), draws three charts and writes the
report. It runs top to bottom with no arguments.

### `Deliverables/`

| File | What it is |
|---|---|
| [`FINDINGS.md`](Deliverables/FINDINGS.md) | The report — three findings, three courses of action, three charts |
| `charts/` | The charts, in light and dark variants so they read correctly either way |
| `skills_intelligence.lvdash.json` | Databricks AI/BI dashboard — four tracked metrics |
| [`powerbi/`](Deliverables/powerbi/README.md) | **Sales by Region** Power BI dashboard (`.pbip` project) over `Data/sales/` |
| [`franchise-powerbi/`](Deliverables/franchise-powerbi/README.md) | **Franchise Performance** Power BI dashboard: corporate view plus a franchisee view locked down by row-level security |

`FINDINGS.md` and the charts are **generated**. Re-running the notebook overwrites
them, so the prose cannot drift from the numbers.

## What it found

Three findings, and they all point the same way — the organisation is investing in
capability it already has, while the capability it depends on sits with one person
at a time.

1. **3 of 7 critical skills rest on one person or nobody.** Kubernetes is one
   person. Zero Trust is one person. Observability is held by 16 of 30 people and
   not one of them is above intermediate — breadth mistaken for depth.
2. **6 certifications are expired or lapse within 90 days**, covering $3,694 of a
   $10,657 certification budget. Renewals need lead time, so finding out late is
   the whole cost.
3. **Learning time is going where the capability already is.** Of 339 hours in the
   last year, 10 — about 3% — went to the three exposed skills. Python took 120 and
   already has seven people at depth.

## Running it

```bash
pip install pandas matplotlib
jupyter notebook Code/skills_analysis.ipynb     # or: jupyter lab
```

Run all cells. It rewrites `Deliverables/FINDINGS.md` and the six chart PNGs.

### On Databricks

Import `Code/skills_analysis.ipynb` (*Workspace → Import*) and run it. It detects
Databricks and additionally writes five tables to Unity Catalog under
`skills_analysis.main`:

```
employees   skills   certifications   learning   skill_coverage
```

Then import `Deliverables/skills_intelligence.lvdash.json`
(*Dashboards → Create dashboard → ⋮ → Import dashboard from file*) and point it at
a SQL warehouse. Its four tiles track: critical skills with no backup,
certifications at risk, the share of learning hours reaching exposed skills, and
total depth across the skills in view.

Off Databricks the table-writing cell prints a note and the analysis carries on
from the CSVs, so the notebook runs anywhere.

## Things to know before trusting it

- **Which skills are "critical" is a judgement**, set at the top of the notebook.
  It drives the headline finding, so it is the first thing to argue with.
- **Level 4+ means "can carry the skill without help."** That is what makes the
  bus-factor count meaningful rather than decorative.
- **30 people** — percentages move about three points per person. Read the counts.
- **The as-of date is pinned** to 2026-09-22, so figures are reproducible rather
  than drifting with the calendar.

## Sales by Region (Power BI)

A separate, self-contained dashboard. `Deliverables/powerbi/SalesByRegion.pbip`
opens in Power BI Desktop and shows net sales, growth, target attainment and
channel mix across five regions and 19 countries, from the synthetic CSVs in
`Data/sales/`. Set the `DataFolder` parameter to your copy of `Data\sales\`
and refresh. Details, measures and expected figures are in
[its README](Deliverables/powerbi/README.md).

## Franchise Performance (Power BI)

`Deliverables/franchise-powerbi/FranchisePerformance.pbip` has a corporate page
and a franchisee page. The corporate page filters by date range, region,
ownership, location and metric. On the franchisee page, a **Franchisee**
security role limits each owner to the cafés they own. The data is synthetic,
in `Data/franchise/`. Setup, security testing and expected figures are in
[its README](Deliverables/franchise-powerbi/README.md).
