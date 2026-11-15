"""Builds the evaluation question sets, with reference answers computed from the database.

    python -m eval.build_questions        # writes eval/questions_dev.json and eval/questions_test.json

Reference answers are never typed by hand: each numeric question carries the SQL that produces its answer,
and that SQL is run here against the seeded data (seed 7, scale 1.0, which is what a fresh install loads).
The split is fixed: every third question, by position, is held out for the test set.
"""

import json
from pathlib import Path

import psycopg

from app.api.health import libpq_url
from app.config import get_settings
from seed.demo_users import HARBOR, NORTHWIND

QUARTERS = {
    "Q1 2026": ("2026-01-01", "2026-04-01"), "Q2 2026": ("2026-04-01", "2026-07-01"),
    "Q3 2026": ("2026-07-01", "2026-10-01"), "Q4 2025": ("2025-10-01", "2026-01-01"),
    "Q3 2025": ("2025-07-01", "2025-10-01"), "2025": ("2025-01-01", "2026-01-01"),
}  # fmt: skip
ORGS = {"northwind": NORTHWIND, "harbor": HARBOR}


def between(column: str, period: str) -> str:
    start, end = QUARTERS[period]
    return f"{column} >= '{start}' AND {column} < '{end}'"


def lookups() -> list[dict]:
    q = []

    def add(org, question, sql, tolerance=0.01, unit="number"):
        q.append(
            {
                "org": org,
                "kind": "lookup",
                "question": question,
                "reference_sql": sql,
                "tolerance": tolerance,
                "unit": unit,
            }
        )

    for period in ("Q3 2026", "Q2 2026", "2025"):
        add("northwind", f"What was total revenue in {period}?",
            f"SELECT sum(revenue_usd) FROM analytics.order_lines WHERE {between('order_date', period)}", unit="usd")  # fmt: skip
    for region, period in (("West", "Q3 2026"), ("East", "Q2 2026"), ("North", "Q1 2026"), ("South", "Q4 2025")):
        add("northwind", f"What was the gross margin in the {region} region in {period}?",
            f"SELECT sum(gross_profit_usd) / sum(revenue_usd) FROM analytics.order_lines WHERE region = '{region}' AND {between('order_date', period)}", unit="ratio")  # fmt: skip
    for segment, period in (("SMB", "Q2 2026"), ("Enterprise", "Q3 2026"), ("Mid-Market", "Q1 2026")):
        add("northwind", f"What was the average discount rate for {segment} customers in {period}?",
            f"SELECT sum(discount_usd) / sum(revenue_usd + discount_usd) FROM analytics.order_lines WHERE segment = '{segment}' AND {between('order_date', period)}", unit="ratio")  # fmt: skip
    for category, period in (("Metals", "Q3 2026"), ("Electronics", "2025")):
        add("northwind", f"How much revenue did the {category} category generate in {period}?",
            f"SELECT sum(revenue_usd) FROM analytics.order_lines WHERE category = '{category}' AND {between('order_date', period)}", unit="usd")  # fmt: skip
    add("northwind", "How many completed orders were placed in September 2026?",
        "SELECT count(*) FROM analytics.orders WHERE status = 'completed' AND order_date >= '2026-09-01' AND order_date < '2026-10-01'", 0.001)  # fmt: skip
    add("northwind", "How much did we spend on Marketing in 2025?",
        f"SELECT sum(amount_usd) FROM analytics.expenses WHERE category = 'Marketing' AND {between('expense_month', '2025')}", unit="usd")  # fmt: skip
    add("northwind", "What was the operating margin in Q3 2026?",
        f"""SELECT ((SELECT sum(gross_profit_usd) FROM analytics.order_lines WHERE {between("order_date", "Q3 2026")})
                    - (SELECT sum(amount_usd) FROM analytics.expenses WHERE {between("expense_month", "Q3 2026")}))
                   / (SELECT sum(revenue_usd) FROM analytics.order_lines WHERE {between("order_date", "Q3 2026")})""", unit="ratio")  # fmt: skip
    add("northwind", "How many units of Metals products were sold in the West region in Q2 2026?",
        f"SELECT sum(quantity) FROM analytics.order_lines WHERE category = 'Metals' AND region = 'West' AND {between('order_date', 'Q2 2026')}", 0.001)  # fmt: skip
    for period in ("Q3 2026", "Q1 2026"):
        add("harbor", f"What was total revenue in {period}?",
            f"SELECT sum(revenue_usd) FROM analytics.order_lines WHERE {between('order_date', period)}", unit="usd")  # fmt: skip
    add("harbor", "What was days sales outstanding for invoices paid in Q1 2026?",
        f"SELECT avg(p.paid_date - i.issued_date) FROM analytics.payments p JOIN analytics.invoices i ON i.id = p.invoice_id WHERE {between('p.paid_date', 'Q1 2026')}", 0.02, "days")  # fmt: skip
    add("harbor", "What is the total value of invoices issued in 2026 that have not been paid?",
        "SELECT sum(i.amount_usd) FROM analytics.invoices i LEFT JOIN analytics.payments p ON p.invoice_id = i.id WHERE p.id IS NULL AND i.issued_date >= '2026-01-01'", unit="usd")  # fmt: skip
    add("harbor", "What was the gross margin in the North region in Q3 2026?",
        f"SELECT sum(gross_profit_usd) / sum(revenue_usd) FROM analytics.order_lines WHERE region = 'North' AND {between('order_date', 'Q3 2026')}", unit="ratio")  # fmt: skip
    add("northwind", "What share of Q3 2026 revenue came from the West region?",
        f"""SELECT sum(revenue_usd) FILTER (WHERE region = 'West') / sum(revenue_usd) FROM analytics.order_lines WHERE {between("order_date", "Q3 2026")}""", unit="ratio")  # fmt: skip
    add("northwind", "What was the gross margin for the whole company in Q3 2026?",
        f"SELECT sum(gross_profit_usd) / sum(revenue_usd) FROM analytics.order_lines WHERE {between('order_date', 'Q3 2026')}", unit="ratio")  # fmt: skip
    add("northwind", "What was Enterprise segment revenue in Q3 2026?",
        f"SELECT sum(revenue_usd) FROM analytics.order_lines WHERE segment = 'Enterprise' AND {between('order_date', 'Q3 2026')}", unit="usd")  # fmt: skip
    return q


def comparisons() -> list[dict]:
    q = []

    def named(org, question, sql):  # the answer is a name: the first column of the first row
        q.append({"org": org, "kind": "compare", "question": question, "reference_sql": sql, "answer": "name"})

    def number(org, question, sql, unit, tolerance=0.02):
        q.append(
            {
                "org": org,
                "kind": "compare",
                "question": question,
                "reference_sql": sql,
                "tolerance": tolerance,
                "unit": unit,
            }
        )

    named("northwind", "Which region had the highest revenue in Q3 2026?",
          f"SELECT region FROM analytics.order_lines WHERE {between('order_date', 'Q3 2026')} GROUP BY 1 ORDER BY sum(revenue_usd) DESC LIMIT 1")  # fmt: skip
    named("northwind", "Which region had the lowest gross margin in Q3 2026?",
          f"SELECT region FROM analytics.order_lines WHERE {between('order_date', 'Q3 2026')} GROUP BY 1 ORDER BY sum(gross_profit_usd) / sum(revenue_usd) LIMIT 1")  # fmt: skip
    named("northwind", "Which product category brought in the most revenue in 2025?",
          f"SELECT category FROM analytics.order_lines WHERE {between('order_date', '2025')} GROUP BY 1 ORDER BY sum(revenue_usd) DESC LIMIT 1")  # fmt: skip
    named("northwind", "Which customer segment had the highest average discount rate in Q2 2026?",
          f"SELECT segment FROM analytics.order_lines WHERE {between('order_date', 'Q2 2026')} GROUP BY 1 ORDER BY sum(discount_usd) / sum(revenue_usd + discount_usd) DESC LIMIT 1")  # fmt: skip
    named("northwind", "Which supplier accounted for the largest cost of goods sold in Q3 2026?",
          f"SELECT supplier FROM analytics.order_lines WHERE {between('order_date', 'Q3 2026')} GROUP BY 1 ORDER BY sum(cogs_usd) DESC LIMIT 1")  # fmt: skip
    named("northwind", "Who was our largest customer by revenue in Q3 2026?",
          f"SELECT customer_name FROM analytics.order_lines WHERE {between('order_date', 'Q3 2026')} GROUP BY 1 ORDER BY sum(revenue_usd) DESC LIMIT 1")  # fmt: skip
    named("harbor", "Which region had the highest revenue in 2025?",
          f"SELECT region FROM analytics.order_lines WHERE {between('order_date', '2025')} GROUP BY 1 ORDER BY sum(revenue_usd) DESC LIMIT 1")  # fmt: skip
    named("northwind", "Which expense category was the largest in 2025?",
          f"SELECT category FROM analytics.expenses WHERE {between('expense_month', '2025')} GROUP BY 1 ORDER BY sum(amount_usd) DESC LIMIT 1")  # fmt: skip

    def change(expr, table, period_a, period_b, where="true", date="order_date"):
        return (f"SELECT (SELECT {expr} FROM analytics.{table} WHERE {where} AND {between(date, period_b)}) - "
                f"(SELECT {expr} FROM analytics.{table} WHERE {where} AND {between(date, period_a)})")  # fmt: skip

    margin = "sum(gross_profit_usd) / sum(revenue_usd)"
    number("northwind", "By how many percentage points did West gross margin change from Q2 2026 to Q3 2026?",
           change(margin, "order_lines", "Q2 2026", "Q3 2026", "region = 'West'"), "points")  # fmt: skip
    number("northwind", "By how many percentage points did company gross margin change from Q2 2026 to Q3 2026?",
           change(margin, "order_lines", "Q2 2026", "Q3 2026"), "points")  # fmt: skip
    number("northwind", "How much did total revenue change in dollars from Q2 2026 to Q3 2026?",
           change("sum(revenue_usd)", "order_lines", "Q2 2026", "Q3 2026"), "usd")  # fmt: skip
    number("northwind", "How much higher was Q3 2026 revenue than Q3 2025 revenue, in dollars?",
           change("sum(revenue_usd)", "order_lines", "Q3 2025", "Q3 2026"), "usd")  # fmt: skip
    number("northwind", "By how many percentage points did the SMB discount rate change between Q1 2026 and Q2 2026?",
           change("sum(discount_usd) / sum(revenue_usd + discount_usd)", "order_lines", "Q1 2026", "Q2 2026", "segment = 'SMB'"), "points")  # fmt: skip
    number("harbor", "How much did total revenue change in dollars from Q2 2026 to Q3 2026?",
           change("sum(revenue_usd)", "order_lines", "Q2 2026", "Q3 2026"), "usd")  # fmt: skip
    return q


def root_causes() -> list[dict]:
    def cause(org, question, must, any_of):
        return {"org": org, "kind": "root_cause", "question": question, "must": must, "any_of": any_of}

    supplier = (["calder"], ["cost", "price", "supplier"])
    discount = (["smb"], ["discount"])
    late = (["north"], ["late", "overdue", "slow", "delay"])
    return [
        cause("northwind", "Why did gross margin fall in the West region in Q3 2026?", *supplier),
        cause("northwind", "Gross margin dropped sharply last quarter. What caused it?", *supplier),
        cause(
            "northwind", "Operating margin was much lower in Q3 2026 than in Q2 2026. Find the main driver.", *supplier
        ),
        cause("northwind", "Metals profitability got worse in the third quarter of 2026. Why?", *supplier),
        cause("northwind", "Why was the average discount rate higher in Q2 2026 than in Q1 2026?", *discount),
        cause(
            "northwind", "Discounts given jumped in the second quarter of 2026. Which customers drove that?", *discount
        ),
        cause(
            "northwind", "Was the Q2 2026 rise in discounting spread across all segments or concentrated?", *discount
        ),
        cause("harbor", "Are customers paying later than they used to in 2026? If so, where is the problem?", *late),
        cause("harbor", "Collections seem to have slowed since April 2026. Which region is responsible?", *late),
        cause("harbor", "Which group of customers started paying well after the due date in 2026?", *late),
    ]


def behaviours() -> list[dict]:
    ask = [
        "Compare it with the other one.",
        "Is that number good?",
        "Show me the figures for the one we discussed.",
        "What is the margin for that customer?",
        "How does this period compare?",
        "Break it down the usual way.",
    ]
    decline = [
        "How many employees do we have in each region?",
        "What is our market share compared with our competitors?",
        "What was revenue in 2019?",
        "What is our customer satisfaction score?",
        "Show me Harbor Trade's revenue by region for 2025.",
        "What is the current cash balance in our bank accounts?",
    ]
    return [{"org": "northwind", "kind": "ambiguous", "question": q, "behaviour": "ask_user"} for q in ask] + [
        {"org": "northwind", "kind": "unanswerable", "question": q, "behaviour": "decline"} for q in decline
    ]


def main() -> None:
    questions = lookups() + comparisons() + root_causes() + behaviours()
    with psycopg.connect(libpq_url(get_settings().database_url_ro)) as conn:
        for item in questions:
            if "reference_sql" not in item:
                continue
            with conn.transaction():
                conn.execute(f"SET LOCAL app.org_id = '{ORGS[item['org']]}'")
                value = conn.execute(item["reference_sql"]).fetchone()[0]
            if value is None:
                raise SystemExit(f"reference query returned NULL: {item['question']}")
            item["expected"] = value if item.get("answer") == "name" else float(value)
    here = Path(__file__).parent
    for number, item in enumerate(questions, start=1):
        item["id"] = f"q{number:02d}"
    test = [q for i, q in enumerate(questions) if i % 3 == 2]
    dev = [q for i, q in enumerate(questions) if i % 3 != 2]
    (here / "questions_dev.json").write_text(json.dumps(dev, indent=1))
    (here / "questions_test.json").write_text(json.dumps(test, indent=1))
    kinds = {
        k: sum(q["kind"] == k for q in questions)
        for k in ("lookup", "compare", "root_cause", "ambiguous", "unanswerable")
    }
    print(f"{len(questions)} questions ({kinds}); dev {len(dev)}, test {len(test)}")


if __name__ == "__main__":
    main()
