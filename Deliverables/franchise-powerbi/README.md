# Franchise Performance — Power BI dashboard

One semantic model, two pages, and row-level security, for a fictional bakery-café
chain. The chain has 30 locations in four US regions. 7 are corporate-owned and 23
belong to 10 franchisees.

| Page | For | Shows |
|---|---|---|
| **Corporate Overview** | Head office | Every location. Filter by date range, region, ownership, location and metric |
| **Franchisee View** | Each franchisee | Only the cafés that franchisee owns, enforced by the **Franchisee** security role |

## Open it

1. Unzip, then open `FranchisePerformance.pbip` in a recent Power BI Desktop.
2. *Transform data → Edit parameters → DataFolder*: set it to the full path of the
   `Data\franchise\` folder. A trailing backslash is optional.
3. **Refresh.**

## The filters

| Filter | Pages | Notes |
|---|---|---|
| **Date range** | both | Slider with a from–to date. Opens on all dates (1 Jan 2024 to 30 Sep 2026) |
| **Region**, **Ownership** | Corporate | Ownership is Corporate or Franchise |
| **Location** | both | Searchable list. On the Franchisee page it lists only that owner's cafés |
| **Metric** | both | Picks what the charts and the league table measure. The chart titles follow it |
| **Franchisee** | Franchisee View | Lets head office preview any owner's page. A signed-in franchisee sees only their own name here. **Clear it before you save or publish**: a saved selection applies to everyone, and a franchisee whose own name isn't selected would see a blank page |

The Metric picker offers eight metrics:

| Metric | Definition |
|---|---|
| Net Sales | Sales after discounts |
| Transactions | Guest checks |
| Avg Ticket | Net sales ÷ transactions |
| Avg Daily Sales | Net sales per location per trading day. Use this to compare owners with different numbers of cafés |
| Labor % | Labor cost ÷ net sales |
| Food Cost % | Food and paper cost ÷ net sales |
| Prime Cost % | Labor + food cost ÷ net sales. The industry rule of thumb is under 60% |
| Guest Satisfaction | Average post-visit survey score from 1 to 5, weighted by number of responses |

The **vs last year** column changes its unit with the metric:
- percentage change for money and counts
- percentage **points** for the cost ratios (Labor %, Food Cost %, Prime Cost %)
- score points for Guest Satisfaction

All "last year" figures go blank if the date range starts in 2024, and that
includes the default all-dates view. 2024 is the first year of data, so there is no
full prior year to compare against. Move the start date to 2025 or later to see growth.

## How franchisees only see their own data

The page alone is not the protection. The **Franchisee** role in the model is:

```
Franchisees[Owner Email] = USERPRINCIPALNAME()     (case-insensitive)
```

That filter flows from Franchisees to Locations to Sales. A franchisee's own
locations are therefore the only rows in every visual, card and total, on **both** pages,
and in Export data and Analyze in Excel. Corporate-owned cafés belong to the
"Corporate-owned" row, which no franchisee email matches.

### Test it in Desktop

1. *Modeling → View as*.
2. Tick **Other user** and enter `tomas.herrera@example.com`. Tick the **Franchisee** role, then **OK**.
   The yellow bar should name the email as well as the role. If it names only the role,
   Power BI is testing your own sign-in, which matches no franchisee, so every visual is blank.
3. Go to the **Franchisee View** page. The banner should read **Showing: Great Plains Bakehouse**,
   and the Location list should hold only **Omaha, NE** and **Kansas City, MO**.
4. Open **Corporate Overview** too. It shows the same two cafés and nothing else.
5. Click **Stop viewing** to go back.

Every owner's email is in `Data/franchise/franchisees.csv`. They are all `@example.com`,
which is reserved for documentation, so they match no one real.

### When you publish

1. Publish to a workspace. Then go to *Semantic model → Security* and add each
   franchisee (or a security group) to the **Franchisee** role. Add head-office
   viewers to **Corporate**.
2. Give franchisees **Viewer** access, or app access only. Workspace Admins, Members and
   Contributors bypass row-level security and would see everything.
3. To show franchisees only their page, publish through an **org app** with two
   audiences: Corporate gets both pages and Franchisees gets *Franchisee View*. Even if
   a franchisee reaches the Corporate page, the role still limits it to their own cafés.
4. Replace the sample emails in `franchisees.csv` with your owners' real sign-in
   addresses (UPNs).

## Check it after refresh

Set the Date range to **1/1/2026 – 9/30/2026**. Then, on the Corporate page with no other filters and Metric = Net Sales, you should see:

| Card | Expected |
|---|---|
| Net Sales | $58.16M |
| Net Sales YoY % | +9.2% |
| Avg Ticket | $15.74 |
| Prime Cost % | 58.9% |
| Guest Satisfaction | 4.23 |
| Active Locations | 30 |

Then switch Metric to **Avg Daily Sales**. The "by owner" chart should run from Copper
Kettle Group ($9,228) at the top to Great Plains Bakehouse ($4,883) at the bottom.

Viewing as Great Plains Bakehouse, with the same 2026 date range, the Franchisee View should show:

| Card | Expected |
|---|---|
| Net Sales | $2.67M |
| Net Sales YoY % | −2.6% |
| Labor % | 34.0% |
| Food Cost % | 33.0% |
| Guest Satisfaction | 3.84 |

## The data

Run `python Code/generate_franchise_data.py` to rebuild `Data/franchise/`. It uses
the standard library only and is seeded, so every run gives the same files.

| File | One row is |
|---|---|
| `franchisees.csv` | An owner and their sign-in email. Row 0 is "Corporate-owned" |
| `locations.csv` | A café: city, state, region, ownership, owner, open date |
| `daily_sales.csv` | One café on one day: net sales, transactions, labor cost, food cost, survey responses and total score |

The data runs from 1 Jan 2024 to 30 Sep 2026. Each owner was given an operating
character so there is something to find. Copper Kettle and Palmetto are growing fast
and running lean. Great Plains Bakehouse and Desert Bloom Dining are flat or shrinking,
with high labor and low guest scores.

## Files

```
FranchisePerformance.pbip              open this
FranchisePerformance.SemanticModel/    tables, measures, relationships, security roles (TMDL)
FranchisePerformance.Report/           two pages and their visuals (PBIR JSON)
```
