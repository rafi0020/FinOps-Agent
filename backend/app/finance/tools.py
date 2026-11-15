"""The finance agent's tools. Each is a thin, typed wrapper over a module that does the real work."""

import json
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.tools import ToolContext, ToolError, ToolRegistry, ToolResult
from app.db import tenant_session
from app.finance.catalog import CATALOG, METRICS
from app.finance.charts import build_chart
from app.finance.compute import OPS, ComputeError, run_compute
from app.finance.grounding import EvidencePool, check_text
from app.finance.sqlexec import SQLFailed, execute_readonly, save_evidence
from app.finance.sqlguard import SQLRejected, validate_sql
from app.models.runs import Evidence, Step, new_handle

registry = ToolRegistry()
PREVIEW_ROWS = 20
MAX_QUESTIONS = 2
HANDLE_ATTEMPTS = 5


# ------------------------------------------------------------------ evidence helpers


async def _evidence(ctx: ToolContext, handles: list[str] | None = None) -> dict[str, Evidence]:
    """Evidence gathered by THIS run. A handle from any other run does not exist as far as a tool is concerned."""
    async with tenant_session(ctx.org_id) as db:
        stmt = select(Evidence).where(Evidence.run_id == ctx.run_id)
        if handles is not None:
            stmt = stmt.where(Evidence.id.in_(handles))
        return {e.id: e for e in (await db.execute(stmt)).scalars()}


async def _fresh_handle(ctx: ToolContext) -> str:
    """A handle no evidence row already uses. The model is shown the handle before the step is committed, so a
    clash found only at commit time would fail a result the model has already been told about."""
    for _ in range(HANDLE_ATTEMPTS):
        candidate = new_handle()
        async with tenant_session(ctx.org_id) as db:
            taken = (await db.execute(select(Evidence.id).where(Evidence.id == candidate))).first()
        if taken is None:
            return candidate
    raise ToolError("Could not allocate a result handle; try the query again.")


def _store(ctx: ToolContext, handle: str, kind: str, payload: dict, sql: str | None = None, rows: int = 0):
    """Database write applied together with the step record (see ToolResult.commit)."""

    async def commit(db) -> None:
        await save_evidence(db, ctx.org_id, ctx.run_id, kind, sql, payload, rows, handle=handle)

    return commit


def _as_table(evidence: Evidence) -> dict | None:
    payload = evidence.payload
    return payload if "columns" in payload and "rows" in payload else None


# ------------------------------------------------------------------ schema


class NoArgs(BaseModel):
    pass


class DescribeArgs(BaseModel):
    table: str = Field(description="Table name in schema analytics, e.g. order_lines")


@registry.tool("list_tables", "List the tables available in schema analytics and the business metric definitions.")
async def list_tables(ctx: ToolContext, args: NoArgs) -> ToolResult:
    tables = [{"name": t.name, "description": t.description} for t in CATALOG.values()]
    metrics = [{"name": k, **v} for k, v in METRICS.items()]
    return ToolResult(
        f"{len(tables)} tables, {len(metrics)} metric definitions.", data={"tables": tables, "metrics": metrics}
    )


@registry.tool("describe_table", "Show the columns of one table, with their types and meaning.")
async def describe_table(ctx: ToolContext, args: DescribeArgs) -> ToolResult:
    table = CATALOG.get(args.table.lower().removeprefix("analytics."))
    if table is None:
        raise ToolError(f"There is no table '{args.table}'. Tables: {', '.join(CATALOG)}.")
    return ToolResult(f"{table.name}: {len(table.columns)} columns.", data=table.as_dict())


# ------------------------------------------------------------------ query


class RunSqlArgs(BaseModel):
    sql: str = Field(description="One read-only PostgreSQL SELECT over schema analytics. Aggregate in SQL.")
    purpose: str = Field(description="One short sentence: what this query is meant to find out.", max_length=300)


@registry.tool(
    "run_sql",
    "Run one read-only SELECT against the analytics schema. Returns a handle (ev_...) for the full result and "
    f"a preview of up to {PREVIEW_ROWS} rows. Pass the handle to compute, chart and record_finding.",
    timeout_s=20,
)
async def run_sql(ctx: ToolContext, args: RunSqlArgs) -> ToolResult:
    try:
        validated = validate_sql(args.sql)
        result = await execute_readonly(ctx.org_id, validated, timeout_ms=10_000)
    except SQLRejected as exc:
        raise ToolError(f"[{exc.code}] {exc.message}") from exc
    except SQLFailed as exc:
        raise ToolError(f"[database_error] {exc}") from exc
    handle = await _fresh_handle(ctx)
    shown = result.rows[:PREVIEW_ROWS]
    summary = f"{result.row_count} row(s)" + (" (more rows exist; the result was capped)" if result.truncated else "")
    if result.row_count == 0:
        summary = "0 rows: no data matches this query."
    elif result.row_count > PREVIEW_ROWS:
        summary += f"; showing the first {PREVIEW_ROWS}. The handle refers to all of them."
    return ToolResult(
        summary,
        # Rows are database content, not instructions; the key name is what the system prompt refers to.
        data={"untrusted_data": {"columns": result.columns, "rows": shown}},
        handle=handle,
        commit=_store(
            ctx, handle, "query", result.payload() | {"purpose": args.purpose}, validated.sql, result.row_count
        ),
    )


# ------------------------------------------------------------------ calculation and charts


class ComputeArgs(BaseModel):
    op: Literal["growth", "share", "margin", "variance_decomposition", "zscore_anomalies", "seasonal_forecast"]
    args: dict[str, Any] = Field(
        description="Always includes 'handle' (an ev_... result) and column names from that result. "
        "growth: value, order_by, [group_by]. share: value, label. margin: revenue, cost or profit, [group_by]. "
        "variance_decomposition: item, period, quantity, value, base_period, compare_period. "
        "zscore_anomalies: value, [label], [threshold]. seasonal_forecast: value, order_by, [periods], [season_length]."
    )


@registry.tool(
    "compute",
    "Do a calculation over a stored result. Use this for every derived figure; never calculate yourself. "
    "Operations: " + ", ".join(OPS) + ". The output gets its own handle.",
)
async def compute(ctx: ToolContext, args: ComputeArgs) -> ToolResult:
    source = args.args.get("handle")
    tables = {h: _as_table(e) for h, e in (await _evidence(ctx, [source] if isinstance(source, str) else [])).items()}
    try:
        result = run_compute(args.op, args.args, tables.get)
    except ComputeError as exc:
        raise ToolError(f"[{exc.code}] {exc.message}") from exc
    handle = await _fresh_handle(ctx)
    payload = result.as_dict() | {"source": source}
    if result.table:  # stored in table form as well, so a chart or another calculation can use it
        columns = list(result.table[0])
        payload |= {"columns": columns, "rows": [[row.get(c) for c in columns] for row in result.table]}
    shown = {"values": result.values, "table": (result.table or [])[:PREVIEW_ROWS], "notes": result.notes}
    return ToolResult(
        f"{args.op} calculated" + (f"; notes: {' '.join(result.notes)}" if result.notes else "."),
        data=shown,
        handle=handle,
        commit=_store(ctx, handle, "compute", payload, rows=len(result.table or [])),
    )


class ChartArgs(BaseModel):
    kind: Literal["line", "bar", "waterfall"]
    handle: str = Field(description="The ev_... result to draw")
    x: str = Field(description="Column for the horizontal axis")
    y: list[str] = Field(description="One or more numeric columns", min_length=1, max_length=4)
    title: str = Field(max_length=120)


@registry.tool("chart", "Create a chart from a stored result, to include in the report.")
async def chart(ctx: ToolContext, args: ChartArgs) -> ToolResult:
    tables = {h: _as_table(e) for h, e in (await _evidence(ctx, [args.handle])).items()}
    try:
        spec = build_chart(args.kind, args.handle, args.x, args.y, args.title, tables.get)
    except ComputeError as exc:
        raise ToolError(f"[{exc.code}] {exc.message}") from exc
    handle = await _fresh_handle(ctx)
    return ToolResult(f"Chart '{spec['title']}' created.", handle=handle, commit=_store(ctx, handle, "chart", spec))


# ------------------------------------------------------------------ findings, questions, report


class FindingArgs(BaseModel):
    claim: str = Field(description="One conclusion, in one or two sentences, with its figures.", max_length=600)
    evidence: list[str] = Field(
        description="Handles (ev_...) of the results that support it", min_length=1, max_length=8
    )


async def _findings(ctx: ToolContext) -> list[Step]:
    async with tenant_session(ctx.org_id) as db:
        stmt = (
            select(Step)
            .where(Step.run_id == ctx.run_id, Step.name == "record_finding", Step.state == "done", Step.error.is_(None))
            .order_by(Step.idx)
        )
        return list((await db.execute(stmt)).scalars())


@registry.tool("record_finding", "Record one conclusion together with the evidence that supports it.")
async def record_finding(ctx: ToolContext, args: FindingArgs) -> ToolResult:
    known = await _evidence(ctx, args.evidence)
    if missing := [h for h in args.evidence if h not in known]:
        raise ToolError(f"Unknown evidence handle(s): {', '.join(missing)}. Use handles returned in this run.")
    number = len(await _findings(ctx)) + 1
    return ToolResult(f"Finding {number} recorded.", data={"number": number})


class AskArgs(BaseModel):
    question: str = Field(description="One specific question whose answer changes what you will do.", max_length=300)


@registry.tool("ask_user", "Ask the user one clarifying question and wait for the answer. Use sparingly.")
async def ask_user(ctx: ToolContext, args: AskArgs) -> ToolResult:
    async with tenant_session(ctx.org_id) as db:
        asked = await db.scalar(
            select(Step.id).where(Step.run_id == ctx.run_id, Step.name == "ask_user", Step.state == "done").limit(MAX_QUESTIONS).offset(MAX_QUESTIONS - 1)
        )  # fmt: skip
    if asked:
        raise ToolError("You have already asked the user twice. State your assumption and continue.")
    return ToolResult(args.question, signal="wait_user")


class FinishArgs(BaseModel):
    outcome: Literal["answered", "cannot_answer"] = "answered"
    summary: str = Field(
        description="The answer, then the cause, then what it is based on. A sentence may end with the handle "
        "(ev_...) its figures come from; those figures are then checked against that result only.",
        max_length=3000,
    )
    findings: list[int] = Field(default_factory=list, description="Numbers of the recorded findings to include")
    recommendations: list[str] = Field(default_factory=list, max_length=6)
    charts: list[str] = Field(default_factory=list, description="Handles of charts to include", max_length=6)


GROUNDING_REFUSAL = "These statements contain numbers that are not in the cited evidence"


@registry.tool(
    "finish",
    "Submit the final report. Every number in the summary and findings is checked against the evidence.",
)
async def finish(ctx: ToolContext, args: FinishArgs) -> ToolResult:
    recorded = {n: step for n, step in enumerate(await _findings(ctx), start=1)}
    if unknown := [n for n in args.findings if n not in recorded]:
        raise ToolError(f"There is no finding number {unknown[0]}. Recorded findings: {sorted(recorded) or 'none'}.")
    evidence = await _evidence(ctx)
    if bad := [h for h in args.charts if h not in evidence or evidence[h].kind != "chart"]:
        raise ToolError(f"'{bad[0]}' is not a chart created in this run.")
    chosen = [recorded[n] for n in args.findings]
    cited = {h for step in chosen for h in step.input["evidence"]}
    # Figures are checked against the evidence the findings cite, plus every calculation made in the run.
    pool = EvidencePool(
        [(h, e.payload) for h, e in evidence.items() if h in cited or e.kind == "compute" or not chosen]
    )

    every_result = EvidencePool([(h, e.payload) for h, e in evidence.items()])
    summary = check_text(args.summary, pool, every_result)
    findings, unsupported = [], list(summary.unsupported)
    for number, step in zip(args.findings, chosen, strict=True):
        checked = check_text(step.input["claim"], pool, every_result)
        unsupported += checked.unsupported
        if checked.cleaned:
            findings.append(
                {"number": number, "claim": checked.cleaned, "evidence": step.input["evidence"],
                 "numbers": [{"text": r.text, "handle": r.handle} for r in checked.supported]}
            )  # fmt: skip

    async with tenant_session(ctx.org_id) as db:
        earlier_attempts = await db.scalar(
            select(Step.id)
            .where(Step.run_id == ctx.run_id, Step.name == "finish", Step.error.startswith(GROUNDING_REFUSAL))
            .limit(1)
        )
    if unsupported and not earlier_attempts:
        # One chance to repair: usually the model did a subtraction itself or forgot to cite a query.
        raise ToolError(
            GROUNDING_REFUSAL
            + ":\n- "
            + "\n- ".join(unsupported[:6])
            + "\nGet each figure from run_sql or compute and cite it in a finding, or remove it, then call finish "
            "again. If you call finish again without fixing them they will be removed from the report."
        )

    report = {
        "outcome": args.outcome,
        "summary": summary.cleaned,
        "summary_numbers": [{"text": r.text, "handle": r.handle} for r in summary.supported],
        "findings": findings,
        "recommendations": [r.strip() for r in args.recommendations if r.strip()],
        "charts": [evidence[h].payload | {"chart_handle": h} for h in args.charts],
        "unsupported": unsupported,
        "evidence": [
            {"handle": h, "kind": e.kind, "purpose": e.payload.get("purpose") or e.payload.get("op") or e.payload.get("title"),
             "sql": e.sql, "row_count": e.row_count}
            for h, e in sorted(evidence.items(), key=lambda item: item[1].created_at)
        ],
    }  # fmt: skip
    return ToolResult(
        json.dumps({"outcome": args.outcome, "unsupported_removed": len(unsupported)}), data=report, signal="finish"
    )
