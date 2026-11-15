"""The database boundary, attacked directly: these tests hand the executor SQL the guard would have refused."""

import pytest

from app.db import tenant_session
from app.finance.sqlexec import SQLFailed, execute_readonly, load_evidence, save_evidence
from app.finance.sqlguard import ValidatedSQL, validate_sql


def unchecked(sql: str) -> ValidatedSQL:
    """Deliberately skip the guard."""
    return ValidatedSQL(sql=sql, tables=frozenset())


async def test_valid_query_returns_columns_and_plain_values(demo_orgs):
    northwind, _ = demo_orgs
    v = validate_sql(
        "SELECT region, sum(revenue_usd) AS revenue, min(order_date) AS first "
        "FROM order_lines GROUP BY region ORDER BY 1"
    )
    result = await execute_readonly(northwind, v)
    assert result.columns == ["region", "revenue", "first"]
    assert [r[0] for r in result.rows] == ["East", "North", "South", "West"]
    assert isinstance(result.rows[0][1], float) and result.rows[0][2].startswith("2024-01-")
    assert result.row_count == 4 and not result.truncated


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM analytics.orders RETURNING 1",
        "UPDATE analytics.customers SET name = 'x' RETURNING 1",
        "SELECT * FROM public.users",
        "SELECT * FROM public.orders",
        "SELECT * FROM public.sessions",
        "SELECT set_config('app.org_id', '22222222-2222-4222-8222-222222222222', true)",
    ],
)
async def test_database_refuses_writes_and_private_tables_even_without_the_guard(demo_orgs, sql):
    northwind, _ = demo_orgs
    with pytest.raises(SQLFailed, match="permission denied|syntax error|read-only"):
        await execute_readonly(northwind, unchecked(sql))


async def test_a_second_statement_cannot_be_smuggled_in(demo_orgs):
    northwind, harbor = demo_orgs
    attack = f"SELECT 1) AS q; SET LOCAL app.org_id = '{harbor}'; SELECT * FROM (SELECT count(*) FROM analytics.orders"
    with pytest.raises(SQLFailed, match="multiple commands|syntax error"):
        await execute_readonly(northwind, unchecked(attack))


async def test_one_org_never_receives_another_orgs_rows(demo_orgs):
    northwind, harbor = demo_orgs
    sql = unchecked("SELECT name FROM analytics.suppliers ORDER BY 1")
    ours = {r[0] for r in (await execute_readonly(northwind, sql)).rows}
    theirs = {r[0] for r in (await execute_readonly(harbor, sql)).rows}
    assert "Calder Metals" in ours and "Polywave" in theirs and not ours & theirs


async def test_long_running_query_is_cancelled(demo_orgs):
    northwind, _ = demo_orgs
    slow = unchecked("SELECT count(*) FROM analytics.order_lines a CROSS JOIN analytics.order_lines b")
    with pytest.raises(SQLFailed, match="cancelled after 300 ms"):
        await execute_readonly(northwind, slow, timeout_ms=300)


async def test_result_is_capped_and_marked_truncated(demo_orgs):
    northwind, _ = demo_orgs
    result = await execute_readonly(northwind, validate_sql("SELECT order_id FROM order_lines"), max_rows=50)
    assert result.row_count == 50 and len(result.rows) == 50 and result.truncated


async def test_zero_rows_and_null_aggregates_are_results_not_errors(demo_orgs):
    northwind, _ = demo_orgs
    empty = await execute_readonly(northwind, validate_sql("SELECT * FROM regions WHERE name = 'Atlantis'"))
    assert empty.row_count == 0 and empty.rows == [] and empty.columns == ["id", "name"]
    null = await execute_readonly(
        northwind, validate_sql("SELECT sum(revenue_usd) AS revenue FROM order_lines WHERE region = 'Atlantis'")
    )
    assert null.rows == [[None]]


async def test_percent_signs_in_the_query_survive(demo_orgs):
    northwind, _ = demo_orgs
    result = await execute_readonly(
        northwind, validate_sql("SELECT count(*) FROM suppliers WHERE name LIKE 'Calder%' AND 7 % 2 = 1")
    )
    assert result.rows == [[1]]


async def test_database_error_text_is_returned_for_the_model_to_fix(demo_orgs):
    northwind, _ = demo_orgs
    with pytest.raises(SQLFailed, match='column "revenu" does not exist'):
        await execute_readonly(northwind, validate_sql("SELECT revenu FROM order_lines"))


async def test_evidence_round_trips_and_is_private_to_its_org(demo_orgs):
    northwind, harbor = demo_orgs
    result = await execute_readonly(northwind, validate_sql("SELECT name FROM regions ORDER BY 1"))
    async with tenant_session(northwind) as db:
        handle = await save_evidence(db, northwind, None, "query", "SELECT ...", result.payload(), result.row_count)
    assert handle.startswith("ev_")
    async with tenant_session(northwind) as db:
        stored = await load_evidence(db, handle)
        assert stored.payload["rows"] == [["East"], ["North"], ["South"], ["West"]] and stored.row_count == 4
    async with tenant_session(harbor) as db:
        assert await load_evidence(db, handle) is None


async def test_other_sessions_query_text_is_not_readable(demo_orgs):
    """Found in review: every organisation's agent SQL runs as the same role, so pg_stat_activity would show it."""
    northwind, _ = demo_orgs
    with pytest.raises(SQLFailed, match="permission denied"):
        await execute_readonly(northwind, unchecked("SELECT query FROM pg_catalog.pg_stat_activity"))
