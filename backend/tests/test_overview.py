"""Overview figures match an independent calculation and never cross organisations."""

import pytest

from tests.test_seed import ro_scalar

REVENUE = "SELECT sum(revenue_usd) FROM analytics.order_lines WHERE order_date >= :s AND order_date < :e"
EXPENSES = "SELECT sum(amount_usd) FROM analytics.expenses WHERE expense_month >= :s AND expense_month < :e"
PROFIT = "SELECT sum(gross_profit_usd) FROM analytics.order_lines WHERE order_date >= :s AND order_date < :e"
Q3, Q2 = {"s": "2026-07-01", "e": "2026-10-01"}, {"s": "2026-04-01", "e": "2026-07-01"}


async def test_kpis_equal_an_independent_calculation(demo):
    body = (await demo.northwind_viewer.get("/api/overview", params={"period": "2026-Q3"})).json()
    revenue, prev = await ro_scalar(demo.northwind_id, REVENUE, **Q3), await ro_scalar(demo.northwind_id, REVENUE, **Q2)
    profit, expenses = (
        await ro_scalar(demo.northwind_id, PROFIT, **Q3),
        await ro_scalar(demo.northwind_id, EXPENSES, **Q3),
    )
    kpis = body["kpis"]
    assert kpis["revenue"]["value"] == pytest.approx(revenue, abs=0.01)
    assert kpis["revenue"]["change_vs_prev"] == pytest.approx((revenue - prev) / prev, abs=1e-4)
    assert kpis["gross_margin"]["value"] == pytest.approx(profit / revenue, abs=1e-4)
    assert kpis["operating_margin"]["value"] == pytest.approx((profit - expenses) / revenue, abs=1e-4)
    assert kpis["gross_margin"]["change_vs_prev"] < -0.03  # the planted supplier cost rise
    assert 20 < kpis["dso"]["value"] < 70


async def test_breakdowns_are_complete_and_consistent(demo):
    body = (await demo.northwind_analyst.get("/api/overview", params={"period": "2026-Q3"})).json()
    assert {r["region"] for r in body["margin_by_region"]} == {"North", "South", "East", "West"}
    assert sum(r["revenue"] for r in body["margin_by_region"]) == pytest.approx(
        body["kpis"]["revenue"]["value"], rel=1e-6
    )
    months = [m["month"] for m in body["revenue_by_month"]]
    assert len(months) == 12 and months[0] == "2025-10-01" and months[-1] == "2026-09-01"
    assert len(body["top_customers"]) == 10
    assert body["top_customers"][0]["revenue"] >= body["top_customers"][-1]["revenue"]


async def test_organisations_get_their_own_figures_even_when_cached(demo):
    first = (await demo.northwind_analyst.get("/api/overview", params={"period": "2025"})).json()
    other = (await demo.harbor_analyst.get("/api/overview", params={"period": "2025"})).json()
    again = (await demo.northwind_analyst.get("/api/overview", params={"period": "2025"})).json()
    assert first == again
    assert first["kpis"]["revenue"]["value"] != other["kpis"]["revenue"]["value"]
    harbor_revenue = await ro_scalar(demo.harbor_id, REVENUE, s="2025-01-01", e="2026-01-01")
    assert other["kpis"]["revenue"]["value"] == pytest.approx(harbor_revenue, abs=0.01)


async def test_period_with_no_data_returns_nulls_not_errors(demo):
    body = (await demo.northwind_viewer.get("/api/overview", params={"period": "2031-Q1"})).json()
    assert body["kpis"]["revenue"] == {"value": None, "previous": None, "change_vs_prev": None}
    assert body["margin_by_region"] == [] and body["top_customers"] == []


@pytest.mark.parametrize("period", ["2026-Q5", "Q3", "2026-07", "'; --", ""])
async def test_invalid_period_is_rejected(demo, period):
    assert (await demo.northwind_viewer.get("/api/overview", params={"period": period})).status_code == 422


async def test_overview_requires_sign_in(client):
    assert (await client.get("/api/overview")).status_code == 401
