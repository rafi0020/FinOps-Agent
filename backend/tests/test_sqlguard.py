"""Static checks on model-written SQL: what is refused, with which code, and what is let through."""

import pytest

from app.finance.sqlguard import SQLRejected, validate_sql


def rejected(sql: str) -> str:
    with pytest.raises(SQLRejected) as info:
        validate_sql(sql)
    return info.value.code


@pytest.mark.parametrize(
    ("sql", "code"),
    [
        ("", "parse_error"),
        ("   ", "parse_error"),
        ("SELEC region FRM order_lines", "parse_error"),
        ("SELECT (((", "parse_error"),
        ("SELECT 1; SELECT 2", "multiple_statements"),
        ("SELECT 1; DELETE FROM order_lines", "multiple_statements"),
        ("SELECT 1; /* note */ DROP TABLE orders", "multiple_statements"),
        ("DELETE FROM orders", "not_select"),
        ("UPDATE customers SET name = 'x'", "not_select"),
        ("INSERT INTO regions (name) VALUES ('x')", "not_select"),
        ("DROP TABLE orders", "not_select"),
        ("TRUNCATE orders", "not_select"),
        ("CREATE TABLE t AS SELECT * FROM orders", "not_select"),
        ("GRANT SELECT ON orders TO PUBLIC", "not_select"),
        ("SET app.org_id = '22222222-2222-4222-8222-222222222222'", "not_select"),
        ("COPY orders TO '/tmp/x'", "not_select"),
        ("WITH gone AS (DELETE FROM orders RETURNING *) SELECT count(*) FROM gone", "not_select"),
        ("WITH up AS (UPDATE customers SET name = 'x' RETURNING id) SELECT * FROM up", "not_select"),
        ("SELECT * INTO backup FROM orders", "forbidden_clause"),
        ("SELECT * FROM orders FOR UPDATE", "forbidden_clause"),
        ("SELECT * FROM users", "unknown_table"),
        ("SELECT * FROM public.users", "unknown_table"),
        ("SELECT * FROM public.orders", "unknown_table"),
        ("SELECT * FROM pg_catalog.pg_user", "unknown_table"),
        ("SELECT * FROM information_schema.tables", "unknown_table"),
        ("SELECT * FROM otherdb.analytics.orders", "unknown_table"),
        ("SELECT * FROM orders o JOIN sessions s ON true", "unknown_table"),
        ("SELECT (SELECT password_hash FROM users LIMIT 1) FROM orders", "unknown_table"),
        ("SELECT pg_sleep(10)", "forbidden_function"),
        ("SELECT pg_read_file('/etc/passwd')", "forbidden_function"),
        ("SELECT set_config('app.org_id', 'x', true)", "forbidden_function"),
        ("SELECT current_setting('app.org_id')", "forbidden_function"),
        ("SELECT region FROM order_lines WHERE pg_sleep(5) IS NULL", "forbidden_function"),
        ("SELECT dblink('host=x', 'select 1')", "forbidden_function"),
        ("SELECT some_unknown_function(1)", "forbidden_function"),
        ("SELECT version()", "forbidden_function"),
    ],
)
def test_refused_with_a_specific_code(sql, code):
    assert rejected(sql) == code


def test_query_longer_than_the_limit_is_refused():
    assert rejected("SELECT 1 " + "-- padding\n" * 2000) == "parse_error"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT region, sum(revenue_usd) AS revenue FROM order_lines GROUP BY region ORDER BY revenue DESC",
        "SELECT * FROM analytics.order_lines WHERE order_date >= '2026-07-01' LIMIT 5",
        """WITH q AS (
               SELECT date_trunc('quarter', order_date)::date AS quarter, region,
                      sum(gross_profit_usd) / nullif(sum(revenue_usd), 0) AS margin
               FROM order_lines GROUP BY 1, 2)
           SELECT quarter, region, margin, margin - lag(margin) OVER (PARTITION BY region ORDER BY quarter) AS change
           FROM q ORDER BY region, quarter""",
        """SELECT c.name, avg(p.paid_date - i.due_date) AS days_late
           FROM invoices i JOIN payments p ON p.invoice_id = i.id JOIN customers c ON c.id = i.customer_id
           GROUP BY c.name HAVING avg(p.paid_date - i.due_date) > 30""",
        "SELECT supplier, round(avg(unit_cost_usd), 2) FROM order_lines WHERE supplier LIKE 'Calder%' GROUP BY 1",
        "SELECT region FROM order_lines UNION SELECT name FROM regions",
        "SELECT extract(year FROM order_date) AS y, count(DISTINCT order_id) FROM order_lines GROUP BY 1",
        "SELECT coalesce(sum(amount_usd), 0), to_char(expense_month, 'YYYY-MM') FROM expenses GROUP BY 2",
        "SELECT m::date FROM generate_series('2026-01-01'::date, '2026-03-01'::date, interval '1 month') AS m",
        "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY revenue_usd) FROM order_lines",
        "SELECT CASE WHEN discount_pct > 0.1 THEN 'high' ELSE 'normal' END AS band, count(*) FROM order_lines GROUP BY 1",
    ],
)
def test_ordinary_analytical_queries_pass(sql):
    validated = validate_sql(sql)
    assert validated.sql.upper().lstrip().startswith(("SELECT", "WITH"))


def test_reports_the_tables_used_but_not_cte_names():
    v = validate_sql(
        "WITH t AS (SELECT * FROM analytics.orders) SELECT * FROM t JOIN customers c ON c.id = t.customer_id"
    )
    assert v.tables == {"orders", "customers"}


def test_comments_never_reach_the_database():
    v = validate_sql("SELECT 1 AS x -- ; DELETE FROM orders\n/* DROP TABLE orders */")
    assert "DELETE" not in v.sql.upper() and "DROP" not in v.sql.upper()


@pytest.mark.parametrize(
    "sql",
    [
        # a CTE declared inside a subquery must not make the same name acceptable outside it
        "SELECT usename, query FROM pg_stat_activity WHERE EXISTS (WITH pg_stat_activity AS (SELECT 1) SELECT 1 FROM pg_stat_activity)",
        "SELECT * FROM users WHERE 1 IN (WITH users AS (SELECT 1 AS x) SELECT x FROM users)",
        # a CTE cannot see the ones declared after it, so `users` here is the real table
        "WITH a AS (SELECT * FROM users), users AS (SELECT 1) SELECT * FROM a",
    ],
)
def test_a_cte_name_only_shadows_a_table_where_postgres_would_use_the_cte(sql):
    """Found in review: the first form passed the guard and read pg_stat_activity."""
    assert rejected(sql) in ("unknown_table", "forbidden_clause")


def test_ctes_that_refer_to_earlier_ctes_still_pass():
    v = validate_sql(
        "WITH q AS (SELECT region, sum(revenue_usd) AS r FROM order_lines GROUP BY 1), top AS (SELECT * FROM q ORDER BY r DESC LIMIT 2) "
        "SELECT * FROM top JOIN q USING (region)"
    )
    assert v.tables == {"order_lines"}
    assert (
        validate_sql(
            "WITH RECURSIVE n AS (SELECT 1 AS i UNION ALL SELECT i + 1 FROM n WHERE i < 3) SELECT * FROM n"
        ).tables
        == set()
    )
