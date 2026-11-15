"""Runs a validated query as the read-only analytics role. This is the real security boundary.

What the database enforces for every query here, whatever the SQL says:
  * role `finops_ro`: SELECT on schema `analytics` only; no access to schema public, no writes;
  * a read-only transaction;
  * the organisation set for the transaction, so row-level security returns only that organisation's rows.
    The role cannot change it: it has no right to call set_config, and the query is sent with a bound
    parameter, which makes PostgreSQL refuse more than one statement (so no trailing `SET ...`);
  * a statement timeout, and a row cap applied by wrapping the query.
"""

import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from psycopg import errors as pg_errors
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_engine
from app.finance.sqlguard import ValidatedSQL
from app.models.runs import Evidence, new_handle


class SQLFailed(Exception):
    """The database refused or could not run the query. The message is safe to show to the model."""


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list]
    row_count: int
    truncated: bool
    elapsed_ms: int

    def payload(self) -> dict:
        return {"columns": self.columns, "rows": self.rows, "truncated": self.truncated}


def _plain(value):
    """Database values as JSON-friendly Python values."""
    if isinstance(value, Decimal):
        return float(value) if value.is_finite() else None
    if isinstance(value, datetime | date):
        return value.isoformat()
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)


async def execute_readonly(
    org_id: UUID, v: ValidatedSQL, *, timeout_ms: int = 5000, max_rows: int = 5000
) -> QueryResult:
    # The bound LIMIT parameter is what forces a single statement; literal % signs are escaped for the driver.
    wrapped = "SELECT * FROM (" + v.sql.replace("%", "%%") + ") AS q LIMIT %s"  # noqa: S608
    started = time.perf_counter()
    try:
        async with get_engine("ro").connect() as conn:
            await conn.exec_driver_sql(f"SET LOCAL app.org_id = '{UUID(str(org_id))}'")
            await conn.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
            await conn.exec_driver_sql("SET LOCAL search_path = analytics")
            result = await conn.exec_driver_sql(wrapped, (max_rows + 1,))
            columns = list(result.keys())
            rows = [[_plain(value) for value in row] for row in result.fetchall()]
    except DBAPIError as exc:
        if isinstance(exc.orig, pg_errors.QueryCanceled):
            raise SQLFailed(f"The query was cancelled after {timeout_ms} ms. Make it narrower or simpler.") from exc
        primary = getattr(getattr(exc.orig, "diag", None), "message_primary", None) or str(exc.orig)
        raise SQLFailed(primary.splitlines()[0]) from exc
    truncated = len(rows) > max_rows
    return QueryResult(
        columns=columns,
        rows=rows[:max_rows],
        row_count=min(len(rows), max_rows),
        truncated=truncated,
        elapsed_ms=round((time.perf_counter() - started) * 1000),
    )


async def save_evidence(
    db: AsyncSession,
    org_id: UUID,
    run_id: UUID | None,
    kind: str,
    sql: str | None,
    payload: dict,
    row_count: int = 0,
    handle: str | None = None,
) -> str:
    """Store a query result or a calculation so a report can point at it. Returns its handle, e.g. ev_7f3a91c2d4b65e10."""
    handle = handle or new_handle()
    db.add(Evidence(id=handle, org_id=org_id, run_id=run_id, kind=kind, sql=sql, payload=payload, row_count=row_count))
    await db.flush()
    return handle


async def load_evidence(db: AsyncSession, handle: str) -> Evidence | None:
    return await db.get(Evidence, handle)
