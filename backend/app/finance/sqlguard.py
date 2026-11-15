"""Static checks on SQL written by the model, before it reaches the database.

This is the second line of defence, not the first. The first is the database itself: the query runs as a role
that can only SELECT from schema `analytics`, in a read-only transaction, with row-level security and a time
limit (see sqlexec.py). The guard exists to give the model a precise, immediate reason when it writes
something it should not, and to keep obviously wrong statements away from the database altogether.

The SQL that is executed is regenerated from the parsed tree, so comments and anything the parser did not
understand never reach PostgreSQL.
"""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from app.finance.catalog import CATALOG

MAX_SQL_LENGTH = 8000

# Statement kinds and clauses that are never acceptable anywhere in the tree.
FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter, exp.TruncateTable,
    exp.Command, exp.Set, exp.Copy, exp.Grant, exp.Transaction, exp.Commit, exp.Rollback, exp.Into, exp.Lock,
    exp.Use, exp.Pragma,
)  # fmt: skip

# Functions sqlglot does not model are refused unless listed here.
EXTRA_FUNCTIONS = {
    "date_part", "to_char", "age", "width_bucket", "percentile_cont", "percentile_disc", "mode", "regr_slope",
    "regr_intercept", "corr", "stddev_samp", "stddev_pop", "var_samp", "var_pop", "make_date", "justify_days",
    "nullif", "greatest", "least", "round", "trunc", "abs", "ceil", "floor", "power", "sqrt", "ln", "log", "exp",
    "string_agg", "array_agg", "bool_and", "bool_or", "lag", "lead", "first_value", "last_value", "nth_value",
    "ntile", "rank", "dense_rank", "row_number", "percent_rank", "cume_dist", "generate_series", "initcap",
    "to_date", "date", "left", "right", "split_part", "concat_ws", "format", "sign", "mod", "div",
}  # fmt: skip

# Refused even if a future parser version starts to recognise them.
DENIED_FUNCTIONS = {"set_config", "current_setting", "version", "current_version", "current_catalog", "current_role", "current_user", "session_user", "current_database",
                    "current_schema", "query_to_xml", "dblink", "lo_import", "lo_export"}  # fmt: skip


class SQLRejected(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class ValidatedSQL:
    sql: str
    tables: frozenset[str]


def _function_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.this).lower()
    return node.sql_name().lower()


def validate_sql(sql: str) -> ValidatedSQL:
    """Return the statement to execute, or raise SQLRejected with a code the model can act on."""
    if not sql or not sql.strip():
        raise SQLRejected("parse_error", "The query is empty.")
    if len(sql) > MAX_SQL_LENGTH:
        raise SQLRejected("parse_error", f"The query is longer than {MAX_SQL_LENGTH} characters.")
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except SqlglotError as exc:
        raise SQLRejected("parse_error", f"The query could not be parsed: {str(exc).splitlines()[0]}") from exc
    if not statements:
        raise SQLRejected("parse_error", "The query is empty.")
    if len(statements) > 1:
        raise SQLRejected("multiple_statements", "Send exactly one statement.")
    tree = statements[0]

    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise SQLRejected(
                "forbidden_clause" if isinstance(node, exp.Into | exp.Lock) else "not_select",
                f"{type(node).__name__.upper()} is not allowed. Only read-only SELECT queries can be run.",
            )
    if not isinstance(tree, exp.Select | exp.SetOperation):
        raise SQLRejected("not_select", "Only a single SELECT (optionally with WITH) can be run.")

    # A CTE name stands for the CTE only where PostgreSQL itself would resolve it that way: after its own
    # declaration, in the query's single top-level WITH. A WITH nested in a subquery is refused outright,
    # because a name declared there would otherwise look acceptable outside it, where it is the real table.
    top_with = tree.args.get("with_")
    if any(node is not top_with for node in tree.find_all(exp.With)):
        raise SQLRejected("forbidden_clause", "WITH is only allowed once, at the start of the query.")
    ctes = list(top_with.expressions) if top_with else []
    cte_names = [cte.alias_or_name.lower() for cte in ctes]
    recursive = bool(top_with and top_with.args.get("recursive"))

    def visible_ctes(node: exp.Expression) -> set[str]:
        while node.parent is not None:
            if isinstance(node, exp.CTE) and node.parent is top_with:
                position = next(i for i, cte in enumerate(ctes) if cte is node)
                return set(cte_names[: position + (1 if recursive else 0)])  # earlier ones, and itself if recursive
            node = node.parent
        return set(cte_names)

    tables: set[str] = set()
    for table in tree.find_all(exp.Table):
        name, schema = table.name.lower(), (table.db or "").lower()
        if not name:  # a set-returning function in FROM, e.g. generate_series(...); checked as a function below
            continue
        if not schema and name in visible_ctes(table):
            continue
        if table.catalog or schema not in ("", "analytics") or name not in CATALOG:
            shown = ".".join(p for p in (table.catalog, table.db, table.name) if p)
            raise SQLRejected(
                "unknown_table",
                f"Table '{shown}' is not available. Use list_tables to see the tables in schema analytics.",
            )
        tables.add(name)

    for func in tree.find_all(exp.Func):
        name = _function_name(func)
        unknown = isinstance(func, exp.Anonymous) and name not in EXTRA_FUNCTIONS
        if unknown or name in DENIED_FUNCTIONS or name.startswith(("pg_", "lo_", "dblink")):
            raise SQLRejected("forbidden_function", f"Function '{name}' is not allowed.")

    return ValidatedSQL(sql=tree.sql(dialect="postgres", comments=False), tables=frozenset(tables))
