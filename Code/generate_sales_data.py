"""Generate the synthetic sales data behind the Sales by Region Power BI dashboard.

Writes four CSVs to Data/sales/:

    geography.csv   one row per country, with the region it rolls up to
    products.csv    one row per product, with category and list price
    sales.csv       one row per order line, Jan 2024 to the as-of date
    targets.csv     monthly sales target per country

Each region is given its own growth rate so the dashboard has a story to tell:
Asia Pacific grows fastest, Europe is flat, Latin America softens. Targets are
set from the prior year's actuals plus a planned uplift, so some regions beat
plan and some miss.

Standard library only. Seeded, so re-running produces identical files.
"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 20260930
START = date(2024, 1, 1)
AS_OF = date(2026, 9, 30)
OUT = Path(__file__).resolve().parent.parent / "Data" / "sales"

# region -> (annual growth, planned uplift used for targets, countries with relative size)
REGIONS = {
    "North America": (0.08, 0.10, {"United States": 10, "Canada": 2.2, "Mexico": 1.4}),
    "Latin America": (-0.04, 0.06, {"Brazil": 2.6, "Argentina": 1.0, "Chile": 0.8, "Colombia": 0.9}),
    "Europe": (0.01, 0.05, {"Germany": 3.4, "United Kingdom": 3.1, "France": 2.5, "Spain": 1.4, "Netherlands": 1.2}),
    "Middle East & Africa": (0.12, 0.10, {"United Arab Emirates": 1.3, "Saudi Arabia": 1.1, "South Africa": 0.9}),
    "Asia Pacific": (0.22, 0.15, {"Japan": 3.0, "Australia": 2.1, "India": 1.8, "Singapore": 1.0}),
}

# category -> [(product, list price, unit cost)]
PRODUCTS = {
    "Laptops": [("Aero 14", 1299, 910), ("Aero 16 Pro", 1899, 1290), ("Flex 13", 849, 640)],
    "Monitors": [("View 27 QHD", 379, 250), ("View 32 4K", 649, 420), ("View 24", 199, 138)],
    "Accessories": [("Dock Pro", 229, 120), ("Wireless Keyboard", 89, 41), ("Precision Mouse", 59, 24)],
    "Services": [("Extended Warranty", 149, 35), ("Onsite Setup", 199, 90), ("Care Plus", 299, 95)],
}
CATEGORY_WEIGHT = {"Laptops": 3, "Monitors": 3, "Accessories": 5, "Services": 2}
CHANNELS = [("Online", 5), ("Retail", 3), ("Partner", 2)]
# Q4 is the busy season; January the quietest.
SEASON = [0.80, 0.85, 0.95, 0.95, 1.00, 0.98, 0.95, 0.97, 1.02, 1.08, 1.22, 1.35]
BASE_ORDERS_PER_DAY_PER_UNIT_SIZE = 0.55


def daterange(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def main():
    rng = random.Random(SEED)
    OUT.mkdir(parents=True, exist_ok=True)

    geography, country_id = [], {}
    for r_idx, (region, (_, _, countries)) in enumerate(REGIONS.items(), start=1):
        for c_idx, country in enumerate(countries, start=1):
            cid = r_idx * 100 + c_idx
            country_id[country] = cid
            geography.append({"country_id": cid, "country": country, "region": region})

    products, product_rows = [], []
    pid = 1
    for category, items in PRODUCTS.items():
        for name, price, cost in items:
            products.append({"product_id": pid, "product": name, "category": category,
                             "list_price": price, "unit_cost": cost})
            product_rows.append((pid, category, price, cost))
            pid += 1
    cat_weights = [CATEGORY_WEIGHT[c] for _, c, _, _ in product_rows]

    sales, order_id = [], 100000
    # monthly actuals per country, used to set next year's targets
    actual = {}
    for day in daterange(START, AS_OF):
        years_in = (day - START).days / 365.25
        weekday_factor = 0.7 if day.weekday() >= 5 else 1.0
        for region, (growth, _, countries) in REGIONS.items():
            trend = (1 + growth) ** years_in
            for country, size in countries.items():
                lam = BASE_ORDERS_PER_DAY_PER_UNIT_SIZE * size * trend * SEASON[day.month - 1] * weekday_factor
                n = int(lam) + (1 if rng.random() < lam - int(lam) else 0)
                for _ in range(n):
                    order_id += 1
                    channel = rng.choices([c for c, _ in CHANNELS], [w for _, w in CHANNELS])[0]
                    lines = 1 if rng.random() < 0.7 else 2
                    for p in rng.choices(product_rows, cat_weights, k=lines):
                        p_id, category, price, cost = p
                        units = rng.choices([1, 2, 3, 5, 10], [60, 20, 10, 6, 4])[0]
                        if channel == "Partner":
                            units *= 2
                        discount = rng.choice([0, 0, 0, 0.05, 0.10, 0.15]) + (0.05 if channel == "Partner" else 0)
                        revenue = round(units * price * (1 - discount), 2)
                        line_cost = round(units * cost, 2)
                        sales.append({
                            "order_id": order_id, "order_date": day.isoformat(),
                            "country_id": country_id[country], "product_id": p_id,
                            "channel": channel, "units": units,
                            "revenue": f"{revenue:.2f}", "cost": f"{line_cost:.2f}",
                        })
                        key = (country_id[country], day.year, day.month)
                        actual[key] = actual.get(key, 0) + revenue

    # Targets: 2024 is planned flat against a smoothed estimate of itself; later years
    # are prior-year actual for the same month plus the region's planned uplift.
    targets = []
    for region, (_, uplift, countries) in REGIONS.items():
        for country in countries:
            cid = country_id[country]
            for year in range(START.year, AS_OF.year + 1):
                last_month = 12 if year < AS_OF.year else AS_OF.month
                for month in range(1, last_month + 1):
                    if year == START.year:
                        base = actual.get((cid, year, month), 0) * rng.uniform(0.95, 1.08)
                    else:
                        base = actual.get((cid, year - 1, month), 0) * (1 + uplift)
                    targets.append({"country_id": cid, "month": date(year, month, 1).isoformat(),
                                    "target": int(round(base, -2))})

    write(OUT / "geography.csv", geography)
    write(OUT / "products.csv", products)
    write(OUT / "sales.csv", sales)
    write(OUT / "targets.csv", targets)
    print(f"{len(sales):,} sales lines, {len(geography)} countries, {len(products)} products, "
          f"{len(targets)} target rows -> {OUT}")


def write(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
