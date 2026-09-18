# Skills Analysis

Reconciles four disagreeing HR and learning exports into one set of Databricks
tables, an exploratory findings report, and an AI/BI dashboard of the four
metrics worth tracking every week.

The interesting problem here is not the analytics. It is that the four sources
describe the same 25 people and agree on almost nothing: who those people are,
how good they are, or what their certifications cost. Most of this repository is
the reconciliation, and every judgement it makes is recorded rather than assumed.

## What is in here

| Path | What it is |
|---|---|
| `notebooks/` | The Databricks pipeline: setup → bronze → silver → gold → report |
| `dashboards/skills_intelligence.lvdash.json` | AI/BI dashboard, four KPI tiles plus filters |
| `src/skills_analysis/` | Extraction, normalisation and transform logic shared by the notebooks, the local runner and the tests |
| `data/raw/` | The four source exports, unmodified |
| `data/reference/` | The maintained mapping tables — skill aliases, identity crosswalk, rating scales, criticality |
| `local/run_analysis.py` | Runs the whole pipeline on a laptop and writes CSVs plus the HTML report |
| `local/build_dashboard.py` | Generates the dashboard definition |
| `tests/` | 103 tests over the cleaning rules and the pipeline's decisions |
| `docs/` | [Findings](docs/FINDINGS.md) · [Data model](docs/DATA_MODEL.md) · [Deploying](docs/DEPLOY.md) |

## The four metrics on the dashboard

Chosen because each one is *leading* rather than lagging, and each has an owner
who can act on it this week.

| Metric | Now | Target | Why this one |
|---|---|---|---|
| **Skill profile freshness** | 48% | ≥ 90% | Every other number depends on it. Half the profiles are more than six months old, so half the capability picture is a guess. |
| **Certifications at risk** | 3 | 0 | Expired, expiring within 90 days, or with no expiry recorded. Each has a lead time, so finding out late is the whole cost. |
| **Critical skills with no backup** | 10 of 15 | 0 | Skills held deeply by one person or nobody. This is the number succession planning actually needs. |
| **Learning engagement** | 76% | ≥ 80% | The only forward-looking signal — whether identified gaps are being closed. |

Read them together. Engagement at 76% against freshness at 48% is the finding:
people are learning, and the system of record does not know about it.

## What the reconciliation found

Full write-up in [`docs/FINDINGS.md`](docs/FINDINGS.md). The short version:

- **25 people arrive as 28 identifiers.** Three are split identities — a truncated
  employee ID and two legacy Splunk worker IDs — each holding half of someone's
  history. Two acquired employees also carry the migration date as their hire
  date, understating their tenure by four to five years.
- **10 of 15 business-critical skills rest on one person or nobody.** NX-OS and
  VXLAN EVPN rest entirely on one engineer; Catalyst Center is claimed by nine
  people with nobody above intermediate.
- **The certification tracker's budget total is wrong by 3×.** It reads $2,071.
  The certifications on that sheet total $6,226. The stated figure is the exact
  sum of a stale FY25 pivot on a `DO NOT DELETE` tab — the total cell points at
  the wrong range.
- **28 data-quality issues, 15 of them high severity**, every one logged in
  `silver.data_quality_issue` with what was done about it.

## Running it

Locally, no Databricks needed — this produces every table as CSV plus the report:

```bash
pip install -r requirements.txt
python local/run_analysis.py          # -> build/*.csv and build/skills_report.html
python -m pytest tests/ -q            # 103 tests
```

On Databricks:

```bash
databricks bundle validate -t dev
databricks bundle deploy   -t dev --var="warehouse_id=<your-sql-warehouse-id>"
databricks bundle run skills_analysis_pipeline -t dev
```

See [`docs/DEPLOY.md`](docs/DEPLOY.md) for prerequisites and for importing the
dashboard without the bundle.

## Design decisions worth knowing

- **Bronze is verbatim.** Structural parsing only — find the header, drop the
  banner. No value is repaired there, so any cleaning decision can be traced back
  to what actually arrived and re-run differently without re-ingesting.
- **Human judgement lives in CSV, not code.** Which spellings are one skill, which
  identifiers are one person, what an "H" rating means, which skills are critical
  — all in `data/reference/`, reviewable by the people who own the answer.
- **Depth requires a comparable scale.** The matrix's legacy H/M/L ratings are
  translated onto 1–5 as an approximation, and approximations never establish that
  someone is deep in a skill. Letting them would have manufactured four false
  experts in a column that conflates two different skills.
- **A blank is not a zero.** An empty matrix cell means nobody filled it in, not
  that the person lacks the skill. Only an explicit "no" counts as no exposure.
- **Nothing is dropped silently.** Every repair, exclusion and unresolved conflict
  is a row in `silver.data_quality_issue` with its resolution.
- **The as-of date is pinned** (`2026-09-01`, the date of the Workday extract) so
  expiry and staleness figures are reproducible rather than drifting with the
  wall clock.

## Caveats

- 21 people in headcount. Percentages move about five points per person — read the
  counts, not the decimals.
- Skill criticality is a judgement in `data/reference/critical_skills.csv`, not
  something derived from the data. It is the input a reader should challenge first.
- Expiry dates recorded as fiscal shorthand ("Q1 FY28", "end of FY") are left null
  rather than guessed, so they cannot be alerted on until someone enters a real date.
- The source files are one-off exports. The job's schedule is paused until it
  points at a real feed.
