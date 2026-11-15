"""Synthetic finance data for the two demo organisations.

Deterministic: the same seed and scale always produce the same rows. Three causes are planted on purpose so
that questions asked of the agent have answers that can be checked (see PLANTED).

    python -m seed.generate            # full size, about 300,000 rows
    python -m seed.generate --scale 0.2
"""

import argparse
import hashlib
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import psycopg

from app.api.health import libpq_url
from app.config import get_settings
from seed.demo_users import DEMO_ORGS, HARBOR, NORTHWIND

START, END = date(2024, 1, 1), date(2026, 9, 30)
REGIONS = ["North", "South", "East", "West"]
SEGMENTS = [("Enterprise", 0.12), ("Mid-Market", 0.33), ("SMB", 0.55)]
CATEGORIES = {  # category -> (supplier index, base cost as a share of list price, price range)
    "Metals": (0, 0.62, (120, 900)),
    "Plastics": (1, 0.60, (20, 260)),
    "Packaging": (2, 0.66, (8, 90)),
    "Electronics": (3, 0.64, (60, 700)),
    "Tools": (4, 0.58, (25, 420)),
    "Chemicals": (5, 0.68, (30, 380)),
}
SUPPLIERS = {
    NORTHWIND: ["Calder Metals", "Brightline Plastics", "Orchard Paper", "Vantage Electronics",
                "Kestrel Tools", "Summit Chemicals"],
    HARBOR: ["Ironbridge Alloys", "Polywave", "Fennel Packaging", "Lumen Circuits", "Anvil & Co",
             "Tidewater Chemicals"],
}  # fmt: skip
EXPENSE_SHARE = {"Salaries": 0.095, "Marketing": 0.03, "Logistics": 0.045, "Rent": 0.015, "Software": 0.012}
SEASON = [0.92, 0.94, 1.0, 1.0, 1.02, 1.03, 0.97, 0.98, 1.04, 1.06, 1.10, 1.08]
ORDERS_AT_FULL_SCALE = {NORTHWIND: 30_000, HARBOR: 24_000}
CUSTOMERS = {NORTHWIND: 420, HARBOR: 320}
ID_BLOCK = 100_000_000  # each organisation's ids live in their own block

# What was planted, for the evaluation set and the tests.
PLANTED = {
    "supplier_cost_rise": {
        "org": NORTHWIND, "supplier": "Calder Metals", "increase": 0.18, "from": date(2026, 7, 1),
        "hits_hardest": "West",
    },
    "smb_discount_spike": {
        "org": NORTHWIND, "segment": "SMB", "normal": 0.04, "spike": 0.11,
        "from": date(2026, 4, 1), "to": date(2026, 6, 30),
    },
    "late_payers": {"org": HARBOR, "region": "North", "customers": 14, "from": date(2026, 4, 1), "days_late": 45},
}  # fmt: skip


@dataclass
class SeedSummary:
    rows: dict[str, int] = field(default_factory=dict)
    checksum: str = ""

    @property
    def total(self) -> int:
        return sum(self.rows.values())


def month_starts() -> list[date]:
    out, d = [], START
    while d <= END:
        out.append(d)
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


def _money(x: float) -> Decimal:
    return Decimal(str(round(x, 2)))


class OrgData:
    """Builds every row for one organisation in memory, then copies them to PostgreSQL."""

    def __init__(self, org_id, index: int, rng: random.Random, scale: float):
        self.org, self.rng, self.scale = org_id, rng, scale
        self.base = (index + 1) * ID_BLOCK
        self.tables: dict[str, list[tuple]] = {}
        self._next: dict[str, int] = {}

    def add(self, table: str, *values) -> int:
        self._next[table] = self._next.get(table, self.base) + 1
        self.tables.setdefault(table, []).append((self._next[table], str(self.org), *values))
        return self._next[table]

    def build(self) -> None:
        rng, months = self.rng, month_starts()
        region_ids = {name: self.add("regions", name) for name in REGIONS}
        supplier_ids = [self.add("suppliers", name) for name in SUPPLIERS[self.org]]

        # Currency rates by month
        fx: dict[tuple[str, date], float] = {}
        for currency, level in (("EUR", 1.08), ("GBP", 1.27)):
            for m in months:
                level *= 1 + rng.uniform(-0.012, 0.012)
                fx[currency, m] = round(level, 6)
                self.add("fx_rates", currency, m, Decimal(str(fx[currency, m])))

        # Products and their cost history
        products: list[dict] = []
        for category, (supplier_idx, cost_share, (low, high)) in CATEGORIES.items():
            for n in range(10):
                price = round(rng.uniform(low, high), 2)
                pid = self.add(
                    "products", f"{category[:3].upper()}-{n + 1:03d}", f"{category} item {n + 1}",
                    category, supplier_ids[supplier_idx], _money(price),
                )  # fmt: skip
                cost = price * cost_share * rng.uniform(0.96, 1.04)
                history = [(date(2024, 1, 1), cost), (date(2025, 1, 1), cost * 1.03)]
                rise = PLANTED["supplier_cost_rise"]
                if self.org == rise["org"] and supplier_idx == 0:
                    history.append((rise["from"], cost * 1.03 * (1 + rise["increase"])))
                for effective, value in history:
                    self.add("product_costs", pid, supplier_ids[supplier_idx], Decimal(str(round(value, 4))),
                             effective)  # fmt: skip
                products.append({"id": pid, "category": category, "price": price, "costs": history})
        by_category = {c: [p for p in products if p["category"] == c] for c in CATEGORIES}

        # Customers
        customers: list[dict] = []
        for n in range(CUSTOMERS[self.org]):
            segment = rng.choices([s for s, _ in SEGMENTS], [w for _, w in SEGMENTS])[0]
            region = rng.choices(REGIONS, [0.27, 0.22, 0.26, 0.25])[0]
            terms = rng.choice([30, 30, 45, 60] if segment != "SMB" else [15, 30, 30])
            cid = self.add("customers", f"{region} {segment} Customer {n + 1:04d}", segment, region_ids[region],
                           terms, START - timedelta(days=rng.randint(30, 900)))  # fmt: skip
            customers.append({"id": cid, "segment": segment, "region": region, "terms": terms, "late": False})
        late = PLANTED["late_payers"]
        if self.org == late["org"]:
            north = [c for c in customers if c["region"] == late["region"]]
            for c in rng.sample(north, late["customers"]):
                c["late"] = True
        weights = [{"Enterprise": 6.0, "Mid-Market": 2.5, "SMB": 1.0}[c["segment"]] for c in customers]

        # Orders, their items, invoices and payments
        total_orders = int(ORDERS_AT_FULL_SCALE[self.org] * self.scale)
        month_weight = [(1.012**i) * SEASON[m.month - 1] for i, m in enumerate(months)]
        revenue: dict[tuple[date, str], float] = {}
        spike = PLANTED["smb_discount_spike"]
        for i, m in enumerate(months):
            month_end = (months[i + 1] if i + 1 < len(months) else END + timedelta(days=1)) - timedelta(days=1)
            for _ in range(round(total_orders * month_weight[i] / sum(month_weight))):
                c = rng.choices(customers, weights)[0]
                day = m + timedelta(days=rng.randint(0, (month_end - m).days))
                status = rng.choices(["completed", "cancelled", "returned"], [0.96, 0.025, 0.015])[0]
                currency = rng.choices(["USD", "EUR", "GBP"], [0.88, 0.08, 0.04])[0]
                rate = 1.0 if currency == "USD" else fx[currency, m]
                oid = self.add("orders", c["id"], day, status, currency, Decimal(str(rate)))
                order_usd = 0.0
                for _ in range(rng.choices([1, 2, 3, 4], [0.25, 0.35, 0.25, 0.15])[0]):
                    metals = 0.66 if c["region"] == "West" else 0.12
                    others = [k for k in CATEGORIES if k != "Metals"]
                    category = "Metals" if rng.random() < metals else rng.choice(others)
                    p = rng.choice(by_category[category])
                    low, high = {"Enterprise": (20, 200), "Mid-Market": (5, 60), "SMB": (1, 15)}[c["segment"]]
                    quantity = rng.randint(low, high)
                    discount = {"Enterprise": 0.08, "Mid-Market": 0.05, "SMB": spike["normal"]}[c["segment"]]
                    if self.org == spike["org"] and c["segment"] == "SMB" and spike["from"] <= day <= spike["to"]:
                        discount = spike["spike"]
                    discount = max(0.0, round(discount + rng.uniform(-0.015, 0.015), 4))
                    price_usd = p["price"] * rng.uniform(0.98, 1.02)
                    cost = [value for effective, value in p["costs"] if effective <= day][-1]
                    self.add("order_items", oid, p["id"], quantity, _money(price_usd / rate),
                             Decimal(str(discount)), Decimal(str(round(cost, 4))))  # fmt: skip
                    order_usd += quantity * price_usd * (1 - discount)
                if status != "completed":
                    continue
                revenue[m, c["region"]] = revenue.get((m, c["region"]), 0.0) + order_usd
                issued = day + timedelta(days=rng.randint(1, 3))
                due = issued + timedelta(days=c["terms"])
                iid = self.add("invoices", oid, c["id"], issued, due, _money(order_usd))
                delay = round(rng.gauss(-2, 7))
                if c["late"] and issued >= late["from"]:
                    delay = rng.randint(late["days_late"], late["days_late"] + 30)
                paid = max(issued, due + timedelta(days=delay))
                if paid <= END:
                    self.add("payments", iid, paid, _money(order_usd))

        # Operating expenses and budgets, by month and region
        for i, m in enumerate(months):
            for region in REGIONS:
                typical = revenue.get((m, region), 0.0)
                smoothed = sum(revenue.get((x, region), 0.0) for x in months[max(0, i - 2) : i + 1]) / min(3, i + 1)
                for category, share in EXPENSE_SHARE.items():
                    amount = smoothed * share * rng.uniform(0.95, 1.05)
                    self.add("expenses", m, category, region_ids[region], _money(amount))
                    self.add("budgets", m, category, region_ids[region], _money(smoothed * share))
                self.add("budgets", m, "Revenue", region_ids[region], _money(typical * rng.uniform(0.97, 1.06)))


LOAD_ORDER = ["regions", "suppliers", "fx_rates", "products", "product_costs", "customers", "orders",
              "order_items", "invoices", "payments", "expenses", "budgets"]  # fmt: skip


def generate(seed: int = 7, scale: float = 1.0) -> SeedSummary:
    """Replace the demo organisations' finance data. Runs as finops_owner."""
    summary, digest = SeedSummary(), hashlib.sha256()
    with psycopg.connect(libpq_url(get_settings().database_url_owner)) as conn:
        for index, (org_id, (name, _)) in enumerate(DEMO_ORGS.items()):
            data = OrgData(org_id, index, random.Random(seed * 1000 + index), scale)
            data.build()
            with conn.transaction():
                conn.execute("INSERT INTO orgs (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING", (org_id, name))
                # Row-level security applies to the owner too: the organisation must be set to write its rows.
                conn.execute("SELECT set_config('app.org_id', %s, true)", (str(org_id),))
                for table in reversed(LOAD_ORDER):
                    conn.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed table names; RLS limits to this org
                for table in LOAD_ORDER:
                    rows = data.tables.get(table, [])
                    # COPY cannot write straight into a table with row-level security, so rows are copied
                    # into a staging table and inserted from there, where the policy is checked.
                    conn.execute(f"CREATE TEMP TABLE _stage (LIKE {table}) ON COMMIT DROP")  # noqa: S608
                    with conn.cursor().copy("COPY _stage FROM STDIN") as copy:
                        for row in rows:
                            copy.write_row(row)
                            digest.update(repr(row).encode())
                    conn.execute(f"INSERT INTO {table} SELECT * FROM _stage")  # noqa: S608
                    conn.execute("DROP TABLE _stage")
                    summary.rows[table] = summary.rows.get(table, 0) + len(rows)
        conn.execute("ANALYZE")
    summary.checksum = digest.hexdigest()
    return summary


def has_data() -> bool:
    with psycopg.connect(libpq_url(get_settings().database_url_owner)) as conn, conn.transaction():
        conn.execute("SELECT set_config('app.org_id', %s, true)", (str(NORTHWIND),))
        return conn.execute("SELECT EXISTS (SELECT 1 FROM orders)").fetchone()[0]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--scale", type=float, default=1.0)
    args = parser.parse_args()
    result = generate(args.seed, args.scale)
    print(f"{result.total:,} rows  checksum {result.checksum[:12]}")
    for table, count in result.rows.items():
        print(f"  {table:<14}{count:>9,}")
