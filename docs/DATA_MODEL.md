# Data model

Three layers, each with one job. The layer boundary is the point at which you can
stop and ask "is this still what arrived?" and get a yes.

```
data/raw/  ──▶  bronze  ──▶  silver  ──▶  gold  ──▶  report + dashboard
 4 exports      verbatim     conformed    analytics
```

## Bronze — what arrived

Every value stays a string, exactly as written. The only judgement applied is
structural: locate the real header row, drop the banner and footer notes, and
unpivot the wide skills matrix into rows.

| Table | Rows | Source |
|---|---:|---|
| `bronze.workday_worker_skills` | 69 | Workday skills and experience extract |
| `bronze.degreed_completions` | 43 | Degreed learning completions |
| `bronze.recert_tracker` | 25 | Recertification tracker, `Tracker` sheet |
| `bronze.cert_catalogue` | 11 | Recertification tracker, `Cert List` sheet |
| `bronze.skills_matrix` | 160 | Team skills matrix, unpivoted (20 people × 8 skills) |

Original header text is preserved in each table's comment. Reference tables are
registered alongside as `bronze.ref_*`.

**Why no cleaning here:** keeping the mess intact means every silver decision can
be traced to what actually arrived, and re-run differently without re-ingesting.

## Silver — one person, one skill, one scale

| Table | Rows | What it holds |
|---|---:|---|
| `silver.worker` | 25 | One row per person. Identity merged, tenure conflicts resolved, population flags set. |
| `silver.worker_skill` | 66 | Workday ratings, conformed and deduplicated. |
| `silver.matrix_rating` | 91 | Matrix ratings, identity-resolved. Blank cells create no row. |
| `silver.certification` | 20 | Tracker rows, deduplicated, dates parsed, columns un-swapped. |
| `silver.learning_completion` | 40 | Degreed rows, identity-resolved, revisions collapsed. |
| `silver.data_quality_issue` | 28 | Every repair, exclusion and conflict, with its resolution. |

### The rules silver applies

**Identity.** Each source's identifier resolves to a Workday employee ID through
`data/reference/identity_overrides.csv`. Resolution is tried in order: the
override table, a well-formed Workday ID, then the name with its order normalised
(so `Chen, Wei-Lin` and `Wei-Lin Chen` are one key). An override with an empty
employee ID means *reviewed and deliberately out of scope* — distinct from
*never seen*, which is logged as unresolved.

**Evidence precedence.** Manager assessment (3) > self assessment (2) >
unattributed Workday rating (1.5) > skills matrix (1). Within a tier, the most
recent rating wins. Conflicts are logged, never averaged.

**Duplicate certifications.** Ranked by whether an expiry exists (4), whether a
status exists (2), and whether the two are *consistent with each other* (1) — a
row reading "Expiring" beside a date two years past is a corrupted cell, not a
fact.

**Duplicate learning.** Course identity ignores revision markers, so
"X" and "X (Rev 2)" completed on the same day are one completion.

**Population.** `in_headcount` is worker type Employee and status Active or Leave
of Absence. Contingent workers, interns and leavers are kept in the tables and
excluded from every coverage metric.

## Gold — the questions

| Table | Rows | Question it answers |
|---|---:|---|
| `gold.worker_skill_profile` | 138 | What does each person know, on what evidence, how stale? |
| `gold.skill_coverage` | 38 | Which skills rest on too few people? |
| `gold.cert_compliance` | 20 | What lapses next, and what does it cost? |
| `gold.org_scorecard` | 11 | Whose data can be trusted, and what is at risk there? |
| `gold.kpi_snapshot` | 4 | The four numbers worth watching weekly. |
| `gold.data_quality_summary` | 18 | Where the data needs fixing at source. |

### Two rules enforced in code

**Depth requires a comparable scale.** `is_deep` is proficiency ≥ 4 *and*
confidence in {high, medium}. A legacy `H` translated onto 1–5 is an
approximation; it can colour a heatmap but cannot declare someone the expert a
team depends on. `is_deep_low_confidence` counts what this excludes, so the
exclusion is visible rather than silent.

**A blank is not a zero.** An empty matrix cell means nobody filled it in.
`has_skill` is false only where an explicit "no" was recorded, counted separately
as `declared_no_exposure`.

## Reference tables

Everything encoding a human judgement, in CSV so it can be reviewed and edited by
the people who own the answer.

| File | What it decides |
|---|---|
| `skill_aliases.csv` | Which spellings are the same skill, and its domain |
| `identity_overrides.csv` | Which identifiers are the same person, and why |
| `proficiency_scale.csv` | What each rating dialect means on 1–5, and how confidently |
| `critical_skills.csv` | Which skills the business depends on, and why |

A skill string absent from `skill_aliases.csv` is **not guessed at** — it is kept
verbatim, excluded from roll-ups, and logged as `unmapped_skill` for a human to
decide.

## Tuning knobs

All in `src/skills_analysis/config.py`, overridable by environment variable.

| Setting | Default | Meaning |
|---|---|---|
| `AS_OF_DATE` | `2026-09-01` | Pinned so expiry and staleness maths are reproducible |
| `PROFILE_FRESHNESS_DAYS` | 180 | A profile older than this is stale |
| `CERT_EXPIRY_WARNING_DAYS` | 90 | A certification inside this window is at risk |
| `EXPERT_THRESHOLD` | 4 | Proficiency at which someone counts as deep |
| `BUS_FACTOR_THRESHOLD` | 1 | Deep practitioners at or below which a skill is a single point of failure |
| `LEARNING_LOOKBACK_DAYS` | 365 | Window for learning engagement |

## Why pandas, not Spark

The whole population is a few hundred rows. At that size driver-side pandas is
faster and considerably clearer than the equivalent Spark plan, and it lets one
implementation of every cleaning rule be shared by the notebooks, the local runner
and the tests — so a rule fixed in one place is fixed everywhere.

Outputs are written as Delta tables in Unity Catalog, so every consumer downstream
(SQL, the dashboard, anything else) is still reading a governed table. The
`build_*` calls in notebooks `02` and `03` are the seam to swap for Spark
DataFrame operations if the population ever outgrows a single node.
