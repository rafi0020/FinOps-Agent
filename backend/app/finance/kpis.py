"""Fixed, parameterised SQL behind the Overview screen. No model is involved in these numbers."""

import json
import re
from datetime import date
from uuid import UUID

from sqlalchemy import text

from app.db import tenant_session
from app.redis import get_redis

PERIOD = re.compile(r"^(\d{4})(?:-Q([1-4]))?$")
CACHE_SECONDS = 60


def period_bounds(period: str) -> tuple[date, date, date]:
    """(start, end exclusive, start of the previous period of the same length) for '2026-Q3' or '2026'."""
    m = PERIOD.match(period)
    if not m:
        raise ValueError("Period must look like 2026-Q3 or 2026.")
    year, quarter = int(m.group(1)), m.group(2)
    if quarter is None:
        return date(year, 1, 1), date(year + 1, 1, 1), date(year - 1, 1, 1)
    first = 3 * (int(quarter) - 1) + 1
    start = date(year, first, 1)
    end = date(year + (first == 10), (first + 3 - 1) % 12 + 1, 1)
    prev = date(year - (first == 1), (first - 4) % 12 + 1, 1)
    return start, end, prev


TOTALS = """
WITH sales AS (
    SELECT sum(revenue_usd) AS revenue, sum(gross_profit_usd) AS gross_profit
    FROM analytics.order_lines WHERE order_date >= :start AND order_date < :end
), opex AS (
    SELECT coalesce(sum(amount_usd), 0) AS expenses
    FROM analytics.expenses WHERE expense_month >= :start AND expense_month < :end
), collected AS (
    SELECT avg(p.paid_date - i.issued_date) AS dso
    FROM analytics.payments p JOIN analytics.invoices i ON i.id = p.invoice_id
    WHERE p.paid_date >= :start AND p.paid_date < :end
)
SELECT revenue, gross_profit / nullif(revenue, 0) AS gross_margin,
       (gross_profit - expenses) / nullif(revenue, 0) AS operating_margin, dso
FROM sales, opex, collected
"""

BY_MONTH = """
WITH months AS (
    SELECT generate_series(CAST(:end AS date) - interval '12 months', CAST(:end AS date) - interval '1 month',
                           interval '1 month')::date AS month
), sales AS (
    SELECT date_trunc('month', order_date)::date AS month, sum(revenue_usd) AS revenue
    FROM analytics.order_lines GROUP BY 1
), plan AS (
    SELECT budget_month AS month, sum(amount_usd) AS budget
    FROM analytics.budgets WHERE category = 'Revenue' GROUP BY 1
)
SELECT m.month, coalesce(s.revenue, 0) AS revenue, p.budget
FROM months m LEFT JOIN sales s USING (month) LEFT JOIN plan p USING (month) ORDER BY m.month
"""

BY_REGION = """
WITH sales AS (
    SELECT region, sum(revenue_usd) AS revenue, sum(gross_profit_usd) AS gross_profit
    FROM analytics.order_lines WHERE order_date >= :start AND order_date < :end GROUP BY region
), opex AS (
    SELECT r.name AS region, sum(e.amount_usd) AS expenses
    FROM analytics.expenses e JOIN analytics.regions r ON r.id = e.region_id
    WHERE e.expense_month >= :start AND e.expense_month < :end GROUP BY r.name
)
SELECT s.region, s.revenue, s.gross_profit / nullif(s.revenue, 0) AS gross_margin,
       (s.gross_profit - coalesce(o.expenses, 0)) / nullif(s.revenue, 0) AS operating_margin
FROM sales s LEFT JOIN opex o USING (region) ORDER BY s.revenue DESC
"""

TOP_CUSTOMERS = """
SELECT customer_name AS name, segment, region, sum(revenue_usd) AS revenue
FROM analytics.order_lines WHERE order_date >= :start AND order_date < :end
GROUP BY customer_id, customer_name, segment, region ORDER BY revenue DESC LIMIT 10
"""


def _num(value) -> float | None:
    return None if value is None else round(float(value), 4)


def _kpi(current, previous, *, relative: bool) -> dict:
    """`change` is a percentage change for money and a difference in points for ratios and days."""
    cur, prev = _num(current), _num(previous)
    if cur is None or prev is None or (relative and prev == 0):
        change = None
    else:
        change = round((cur - prev) / prev, 4) if relative else round(cur - prev, 4)
    return {"value": cur, "previous": prev, "change_vs_prev": change}


async def overview(org_id: UUID, period: str) -> dict:
    start, end, prev = period_bounds(period)
    cache_key = f"overview:{org_id}:{period}"  # the organisation is part of the key: caches are never shared
    redis = get_redis()
    if cached := await redis.get(cache_key):
        return json.loads(cached)
    async with tenant_session(org_id) as db:
        now = (await db.execute(text(TOTALS), {"start": start, "end": end})).one()
        before = (await db.execute(text(TOTALS), {"start": prev, "end": start})).one()
        months = (await db.execute(text(BY_MONTH), {"end": end})).all()
        regions = (await db.execute(text(BY_REGION), {"start": start, "end": end})).all()
        customers = (await db.execute(text(TOP_CUSTOMERS), {"start": start, "end": end})).all()
    result = {
        "period": period,
        "kpis": {
            "revenue": _kpi(now.revenue, before.revenue, relative=True),
            "gross_margin": _kpi(now.gross_margin, before.gross_margin, relative=False),
            "operating_margin": _kpi(now.operating_margin, before.operating_margin, relative=False),
            "dso": _kpi(now.dso, before.dso, relative=False),
        },
        "revenue_by_month": [
            {"month": m.month.isoformat(), "revenue": _num(m.revenue), "budget": _num(m.budget)} for m in months
        ],
        "margin_by_region": [
            {
                "region": r.region,
                "revenue": _num(r.revenue),
                "gross_margin": _num(r.gross_margin),
                "operating_margin": _num(r.operating_margin),
            }
            for r in regions
        ],
        "top_customers": [
            {"name": c.name, "segment": c.segment, "region": c.region, "revenue": _num(c.revenue)} for c in customers
        ],
    }
    await redis.set(cache_key, json.dumps(result), ex=CACHE_SECONDS)
    return result
