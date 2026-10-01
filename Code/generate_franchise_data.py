"""Generate the synthetic data behind the Franchise Performance Power BI dashboard.

Writes three CSVs to Data/franchise/:

    franchisees.csv   one row per franchisee, with the owner's sign-in email.
                      Row 0 is "Corporate-owned", for the locations the brand runs itself.
    locations.csv     one row per café, with region, city, ownership and franchisee
    daily_sales.csv   one row per location per day, Jan 2024 to the as-of date

The brand, people and emails are invented. The emails use example.com, which is
reserved for documentation, so they can be typed into Power BI's "View as" dialog
to test row-level security without matching anyone real.

Standard library only. Seeded, so re-running produces identical files.
"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 20261001
START = date(2024, 1, 1)
AS_OF = date(2026, 9, 30)
OUT = Path(__file__).resolve().parent.parent / "Data" / "franchise"

# franchisee_id, name, owner email
FRANCHISEES = [
    (0, "Corporate-owned", "corporate.ops@example.com"),
    (1, "Harborline Hospitality", "dana.reyes@example.com"),
    (2, "Copper Kettle Group", "sam.whitfield@example.com"),
    (3, "Bluebonnet Eats LLC", "priya.natarajan@example.com"),
    (4, "Lakeshore Cafés Inc.", "marcus.bell@example.com"),
    (5, "Summit Street Foods", "elena.kowalski@example.com"),
    (6, "Palmetto Morning Co.", "jordan.akers@example.com"),
    (7, "Great Plains Bakehouse", "tomas.herrera@example.com"),
    (8, "Cascade Table Partners", "aisha.mensah@example.com"),
    (9, "Granite State Kitchens", "ben.okafor@example.com"),
    (10, "Desert Bloom Dining", "lucia.fontaine@example.com"),
]

# city, state, region, franchisee_id (0 = corporate-owned), open date, size factor
LOCATIONS = [
    ("Boston", "MA", "Northeast", 0, "2016-03-01", 1.25),
    ("Cambridge", "MA", "Northeast", 0, "2018-06-15", 1.05),
    ("Portland", "ME", "Northeast", 9, "2019-04-01", 0.80),
    ("Manchester", "NH", "Northeast", 9, "2020-09-01", 0.75),
    ("Providence", "RI", "Northeast", 1, "2017-11-01", 0.95),
    ("Hartford", "CT", "Northeast", 1, "2021-02-01", 0.85),
    ("New Haven", "CT", "Northeast", 1, "2022-05-01", 0.90),
    ("Atlanta", "GA", "Southeast", 0, "2017-01-15", 1.20),
    ("Charleston", "SC", "Southeast", 6, "2019-08-01", 0.95),
    ("Savannah", "GA", "Southeast", 6, "2023-03-01", 0.80),
    ("Charlotte", "NC", "Southeast", 2, "2018-10-01", 1.05),
    ("Raleigh", "NC", "Southeast", 3, "2020-01-15", 0.95),
    ("Nashville", "TN", "Southeast", 2, "2021-07-01", 1.10),
    ("Tampa", "FL", "Southeast", 3, "2024-06-01", 0.85),
    ("Chicago", "IL", "Midwest", 0, "2015-05-01", 1.30),
    ("Evanston", "IL", "Midwest", 4, "2019-02-01", 0.85),
    ("Milwaukee", "WI", "Midwest", 4, "2020-04-01", 0.80),
    ("Madison", "WI", "Midwest", 4, "2022-09-01", 0.75),
    ("Omaha", "NE", "Midwest", 7, "2018-03-01", 0.80),
    ("Kansas City", "MO", "Midwest", 7, "2021-10-01", 0.90),
    ("Minneapolis", "MN", "Midwest", 0, "2019-12-01", 1.00),
    ("Seattle", "WA", "West", 0, "2016-09-01", 1.25),
    ("Tacoma", "WA", "West", 8, "2020-06-01", 0.80),
    ("Portland", "OR", "West", 8, "2018-08-01", 1.00),
    ("Boise", "ID", "West", 5, "2021-04-01", 0.75),
    ("Denver", "CO", "West", 5, "2017-07-01", 1.10),
    ("Boulder", "CO", "West", 5, "2023-01-15", 0.80),
    ("Phoenix", "AZ", "West", 10, "2019-05-01", 0.95),
    ("Tucson", "AZ", "West", 10, "2022-02-01", 0.75),
    ("San Diego", "CA", "West", 0, "2018-01-15", 1.15),
]

# Per-franchisee operating character: (sales growth per year, labor % centre,
# food cost % centre, guest satisfaction centre). Corporate runs a tight ship;
# a couple of franchisees are visibly struggling so the dashboard has something to find.
CHARACTER = {
    0: (0.05, 0.27, 0.29, 4.45),
    1: (0.07, 0.29, 0.30, 4.30),
    2: (0.11, 0.28, 0.29, 4.50),
    3: (0.04, 0.30, 0.31, 4.20),
    4: (0.03, 0.31, 0.31, 4.15),
    5: (0.09, 0.28, 0.30, 4.40),
    6: (0.13, 0.28, 0.29, 4.35),
    7: (-0.06, 0.34, 0.33, 3.85),
    8: (0.06, 0.29, 0.30, 4.25),
    9: (0.02, 0.30, 0.32, 4.10),
    10: (-0.03, 0.33, 0.32, 3.95),
}

AVG_TICKET = 14.50                 # dollars, 2024
TICKET_INFLATION = 0.035           # per year
BASE_TRANSACTIONS = 420            # per day for a size-1.0 café
WEEKDAY = [0.92, 0.95, 0.97, 1.00, 1.12, 1.22, 1.05]  # Mon..Sun
SEASON = [0.88, 0.90, 0.97, 1.00, 1.03, 1.02, 0.98, 0.97, 1.01, 1.03, 1.06, 1.15]


def main():
    rng = random.Random(SEED)
    OUT.mkdir(parents=True, exist_ok=True)

    write(OUT / "franchisees.csv", [
        {"franchisee_id": fid, "franchisee": name, "owner_email": email}
        for fid, name, email in FRANCHISEES])

    locations = []
    for i, (city, state, region, fid, opened, size) in enumerate(LOCATIONS, start=1):
        locations.append({
            "location_id": i,
            "location": f"{city}, {state}",
            "city": city, "state": state, "region": region,
            "ownership": "Corporate" if fid == 0 else "Franchise",
            "franchisee_id": fid, "open_date": opened,
        })
    write(OUT / "locations.csv", locations)

    rows = []
    day = START
    while day <= AS_OF:
        years_in = (day - START).days / 365.25
        for loc, (_, _, _, fid, opened, size) in zip(locations, LOCATIONS):
            if day < date.fromisoformat(opened):
                continue
            growth, labor_c, food_c, csat_c = CHARACTER[fid]
            # a new café ramps up over its first six months
            age_days = (day - date.fromisoformat(opened)).days
            ramp = min(1.0, 0.6 + 0.4 * age_days / 180)
            mean_tx = (BASE_TRANSACTIONS * size * ramp * (1 + growth) ** years_in
                       * WEEKDAY[day.weekday()] * SEASON[day.month - 1])
            tx = max(0, round(rng.gauss(mean_tx, mean_tx * 0.08)))
            ticket = AVG_TICKET * (1 + TICKET_INFLATION) ** years_in * rng.gauss(1.0, 0.03)
            sales = round(tx * ticket, 2)
            # weak days carry fixed labour, so labor % rises when traffic falls
            labor_pct = labor_c * (mean_tx / max(tx, 1)) ** 0.35 * rng.gauss(1.0, 0.03)
            food_pct = food_c * rng.gauss(1.0, 0.025)
            surveys = rng.randint(3, 14)
            score = sum(min(5, max(1, round(rng.gauss(csat_c, 0.7)))) for _ in range(surveys))
            rows.append({
                "date": day.isoformat(), "location_id": loc["location_id"],
                "net_sales": f"{sales:.2f}", "transactions": tx,
                "labor_cost": f"{sales * labor_pct:.2f}", "food_cost": f"{sales * food_pct:.2f}",
                "survey_responses": surveys, "survey_score_total": score,
            })
        day += timedelta(days=1)
    write(OUT / "daily_sales.csv", rows)
    print(f"{len(rows):,} daily rows, {len(locations)} locations, "
          f"{len(FRANCHISEES) - 1} franchisees -> {OUT}")


def write(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
