"""The generated data is reproducible, isolated per organisation, and contains the planted causes."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import get_engine
from seed.generate import generate

WEST_MARGIN = """
    SELECT round(sum(gross_profit_usd) / sum(revenue_usd), 4) FROM analytics.order_lines
    WHERE region = 'West' AND order_date >= :start AND order_date < :end
"""


async def ro_scalar(org, sql: str, **params):
    """Run a query exactly as the agent's SQL tool will: read-only role, organisation set for the transaction."""
    async with get_engine("ro").connect() as conn:
        await conn.execute(text(f"SET LOCAL app.org_id = '{org}'"))  # noqa: S608
        value = (await conn.execute(text(sql), params)).scalar_one()
        return float(value) if value is not None else None


def test_same_seed_gives_identical_data(seeded):
    again = generate(seed=7, scale=0.15)
    assert again.rows == seeded.rows and again.checksum == seeded.checksum
    assert generate(seed=8, scale=0.15).checksum != seeded.checksum
    assert generate(seed=7, scale=0.15).checksum == seeded.checksum  # leave the session data as it was


async def test_supplier_cost_rise_cuts_west_gross_margin_in_q3_2026(demo_orgs):
    northwind, _ = demo_orgs
    q2 = await ro_scalar(northwind, WEST_MARGIN, start="2026-04-01", end="2026-07-01")
    q3 = await ro_scalar(northwind, WEST_MARGIN, start="2026-07-01", end="2026-10-01")
    assert q2 - q3 >= 0.05


async def test_smb_discount_spikes_in_q2_2026(demo_orgs):
    northwind, _ = demo_orgs
    sql = """SELECT round(sum(discount_usd) / sum(revenue_usd + discount_usd), 3) FROM analytics.order_lines
             WHERE segment = 'SMB' AND order_date >= :start AND order_date < :end"""
    assert await ro_scalar(northwind, sql, start="2026-01-01", end="2026-04-01") == pytest.approx(0.04, abs=0.006)
    assert await ro_scalar(northwind, sql, start="2026-04-01", end="2026-07-01") == pytest.approx(0.11, abs=0.006)


async def test_a_cluster_of_north_customers_pays_late_from_april_2026(demo_orgs):
    _, harbor = demo_orgs
    sql = """SELECT count(*) FROM (
               SELECT i.customer_id FROM analytics.invoices i
               JOIN analytics.payments p ON p.invoice_id = i.id
               JOIN analytics.customers c ON c.id = i.customer_id
               JOIN analytics.regions r ON r.id = c.region_id
               WHERE r.name = 'North' AND i.issued_date >= '2026-04-01'
               GROUP BY i.customer_id HAVING avg(p.paid_date - i.due_date) >= 40) late"""
    assert 8 <= await ro_scalar(harbor, sql) <= 14


async def test_each_org_sees_only_its_own_data_through_the_views(demo_orgs):
    northwind, harbor = demo_orgs
    a = await ro_scalar(northwind, "SELECT count(*) FROM analytics.orders")
    b = await ro_scalar(harbor, "SELECT count(*) FROM analytics.orders")
    assert a > 0 and b > 0 and a != b
    assert await ro_scalar(northwind, "SELECT count(*) FROM analytics.suppliers WHERE name = 'Polywave'") == 0
    async with get_engine("ro").connect() as conn:  # no organisation set
        assert (await conn.execute(text("SELECT count(*) FROM analytics.orders"))).scalar_one() == 0


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM public.orders",
        "INSERT INTO analytics.regions (id, name) VALUES (1, 'x')",
        "UPDATE analytics.customers SET name = 'x'",
        "DELETE FROM analytics.payments",
        "CREATE TABLE analytics.t (x int)",
    ],
)
async def test_read_only_role_can_do_nothing_but_select_from_analytics(seeded, sql):
    async with get_engine("ro").connect() as conn:
        with pytest.raises(DBAPIError, match="permission denied|read-only transaction"):
            await conn.execute(text(sql))
