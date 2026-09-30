# Sales by Region — Power BI dashboard

A one-page Power BI report of net sales across five regions and 19 countries,
saved as a **Power BI Project** (`.pbip`). The project is plain text (TMDL for the model, JSON for
the report), so changes show up as readable diffs in git.

## Open it

1. Power BI Desktop, recent build (2025 or later). The report uses the PBIR folder
   format. If Desktop says it can't read it, turn on
   *File → Options → Preview features → Power BI Project (.pbip) save option* and
   *Store reports using enhanced metadata format (PBIR)*, then restart.
2. Open `SalesByRegion.pbip`.
3. Point the model at the data: *Transform data → Edit parameters → DataFolder*,
   set it to the full path of this repo's `Data\sales\` folder **with a trailing
   backslash**, e.g. `C:\src\YMEHIO78\Data\sales\`.
4. **Refresh**. The project holds no data, so every visual is blank until you refresh.

## What's on the page

| Area | Visual | Notes |
|---|---|---|
| Top right | Year, Region, Channel slicers | Year is single-select and opens on **2026** |
| KPI row | Total Sales · Sales YoY % · Target Attainment % · Gross Margin % · Avg Order Value | |
| Left | Sales by region | Bar chart, sorted high to low |
| Right | Monthly sales by region | One line per region. It **ignores the Year slicer**, so the full history stays visible |
| Bottom left | Region and country detail | Matrix. Expand a region to see its countries: sales, prior year, YoY, target, variance, attainment, margin, share |
| Bottom right | Channel mix by region | 100% stacked bar: Online / Retail / Partner |

Click a bar or a region row to cross-filter the rest of the page.

## Check it after refresh

With Year = 2026 (Jan to Sep; the data ends 30 Sep 2026), you should see:

| Region | Sales | YoY | Attainment | Margin |
|---|---:|---:|---:|---:|
| **All** | **$9,151,259** | **+8.5%** | **99.3%** | **30.5%** |
| North America | $3,044,423 | +12.2% | 102.0% | 30.3% |
| Asia Pacific | $2,248,113 | +25.8% | 109.3% | 30.5% |
| Europe | $2,191,541 | +6.8% | 101.7% | 31.0% |
| Middle East & Africa | $845,072 | +6.7% | 97.0% | 30.7% |
| Latin America | $822,110 | −24.3% | 71.4% | 30.3% |

Avg Order Value for all regions is $1,425. If your numbers differ, the refresh
probably read the wrong folder.

## The model

```
            Geography (Region › Country)       Products (Category, Product)
                 │            │                        │
   Targets ──────┘            └──── Sales (fact) ──────┘
  (country × month)                    │
                 └───────── Calendar ──┘
```

- **Sales**: one row per order line; holds all the measures.
- **Targets**: a monthly target per country, so the target rolls up to region and
  year the same way sales do.
- **Calendar**: a DAX table running from 1 Jan of the first order year **to the last
  order date**. Because it stops there, `Sales PY` for a part-year (2026) is compared
  with the same months of 2025, not the whole year.

Measures, grouped into display folders:

| Folder | Measures |
|---|---|
| Sales | Total Sales, Total Cost, Orders, Units Sold, Avg Order Value, Region Share % |
| Profitability | Gross Profit, Gross Margin % |
| Growth | Sales PY, Sales YoY % |
| Target | Sales Target, Variance to Target, Target Attainment % |

## Using your own data

Replace the four CSVs in `Data/sales/` with your own files. Keep the same file
names and column headers, then refresh. Region is simply a column on
`geography.csv`, so any grouping works: sales territories, states, or districts.

To regenerate the synthetic data: `python Code/generate_sales_data.py`
(standard library only, seeded, so the output is identical each run).

## Files

```
SalesByRegion.pbip                    open this
SalesByRegion.SemanticModel/          model: tables, measures, relationships (TMDL)
SalesByRegion.Report/                 report: page, visuals, theme (PBIR JSON)
```

Power BI Desktop writes `.pbi/localSettings.json` and `.pbi/cache.abf` next to
these files when you open the project. Both are ignored in git.

The chart colours come from a custom theme, `StaticResources/RegisteredResources/SalesByRegionTheme.json`.
If it doesn't load, the report falls back to the default Power BI theme; nothing else changes.
