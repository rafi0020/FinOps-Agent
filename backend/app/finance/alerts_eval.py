"""Alert rules: proposing one (through the agent, with approval) and evaluating them on a schedule.

A rule compares one metric, for the latest complete month or quarter, with a threshold. When the comparison
holds, an event is recorded once for that period. Events are shown in the application; nothing is sent outside.
"""

import logging
from datetime import date, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from app.agent.tools import ToolContext, ToolResult
from app.db import system_session, tenant_session
from app.finance.tools import registry
from app.models.alerts import AlertEvent, AlertRule
from app.worker import scheduler

log = logging.getLogger("finops.alerts")

REGION = "(CAST(:region AS text) IS NULL OR {col} = :region)"
SALES = f"FROM analytics.order_lines WHERE order_date >= :start AND order_date < :end AND {REGION.format(col='region')}"
METRIC_SQL = {
    "revenue": f"SELECT sum(revenue_usd) {SALES}",
    "gross_margin": f"SELECT sum(gross_profit_usd) / nullif(sum(revenue_usd), 0) {SALES}",
    "discount_rate": f"SELECT sum(discount_usd) / nullif(sum(revenue_usd + discount_usd), 0) {SALES}",
    "operating_margin": f"""
        SELECT (s.gross_profit - coalesce(e.expenses, 0)) / nullif(s.revenue, 0)
        FROM (SELECT sum(revenue_usd) AS revenue, sum(gross_profit_usd) AS gross_profit {SALES}) s,
             (SELECT sum(x.amount_usd) AS expenses FROM analytics.expenses x JOIN analytics.regions r ON r.id = x.region_id
              WHERE x.expense_month >= :start AND x.expense_month < :end AND {REGION.format(col="r.name")}) e""",
    "dso": f"""
        SELECT avg(p.paid_date - i.issued_date) FROM analytics.payments p
        JOIN analytics.invoices i ON i.id = p.invoice_id JOIN analytics.customers c ON c.id = i.customer_id
        JOIN analytics.regions r ON r.id = c.region_id
        WHERE p.paid_date >= :start AND p.paid_date < :end AND {REGION.format(col="r.name")}""",
}
Metric = Literal["revenue", "gross_margin", "operating_margin", "discount_rate", "dso"]


class ProposeAlertArgs(BaseModel):
    metric: Metric
    comparison: Literal["<", ">"] = Field(description="Alert when the metric is below (<) or above (>) the threshold")
    threshold: float = Field(description="In the metric's own unit: USD for revenue, a ratio (0.25 = 25%) for margins "
                             "and discount_rate, days for dso")  # fmt: skip
    window: Literal["month", "quarter"]
    region: Literal["North", "South", "East", "West"] | None = Field(
        default=None, description="Omit for the whole company"
    )
    rationale: str = Field(description="Why this alert is useful, in one sentence.", max_length=300)


@registry.tool(
    "propose_alert",
    "Draft an alert rule on a metric. It takes effect only if an administrator approves it. "
    "Use only when the user asks to be alerted about, or to monitor, something.",
    level="needs_approval",
    idempotent=True,  # its only effect is a database row written together with the step record
)
async def propose_alert(ctx: ToolContext, args: ProposeAlertArgs) -> ToolResult:
    async def commit(db) -> None:
        await db.execute(
            insert(AlertRule)
            .values(
                org_id=ctx.org_id,
                metric=args.metric,
                comparison=args.comparison,
                threshold=args.threshold,
                window=args.window,
                region=args.region,
                rationale=args.rationale,
                run_id=ctx.run_id,
                step_idx=ctx.step_idx,
                created_by=ctx.user_id,
            )  # fmt: skip
            .on_conflict_do_nothing(index_elements=["run_id", "step_idx"])
        )

    where = f" in {args.region}" if args.region else ""
    return ToolResult(
        f"Approved. The alert is now active: {args.metric}{where} {args.comparison} {args.threshold:g} per {args.window}.",
        commit=commit,
    )


def _previous_period_start(start: date, window: str) -> date:
    months = 1 if window == "month" else 3
    index = start.year * 12 + start.month - 1 - months
    return date(index // 12, index % 12 + 1, 1)


def latest_complete_period(last_day: date, window: str) -> tuple[str, date, date]:
    """The most recent month or quarter that has fully passed as of `last_day`. Returns (label, start, end)."""
    day_after = last_day + timedelta(days=1)
    if window == "month":
        current = date(day_after.year, day_after.month, 1)
    else:
        current = date(day_after.year, 3 * ((day_after.month - 1) // 3) + 1, 1)
    start = _previous_period_start(current, window)
    label = f"{start.year}-{start.month:02d}" if window == "month" else f"{start.year}-Q{(start.month - 1) // 3 + 1}"
    return label, start, current


async def evaluate_rules(org_id: UUID) -> int:
    """Check every active rule of one organisation. Returns how many new events were raised."""
    raised = 0
    async with tenant_session(org_id) as db:
        rules = (await db.execute(select(AlertRule).where(AlertRule.status == "active"))).scalars().all()
        if not rules:
            return 0
        last_day = await db.scalar(text("SELECT max(order_date) FROM analytics.orders"))
        if last_day is None:
            return 0
        for rule in rules:
            label, start, end = latest_complete_period(last_day, rule.window)
            value = await db.scalar(text(METRIC_SQL[rule.metric]), {"start": start, "end": end, "region": rule.region})
            if value is None:
                continue  # no data for the period: nothing to compare
            breached = value < rule.threshold if rule.comparison == "<" else value > rule.threshold
            if not breached:
                continue
            created = await db.execute(
                insert(AlertEvent)
                .values(org_id=org_id, rule_id=rule.id, period=label, value=value)
                .on_conflict_do_nothing(index_elements=["rule_id", "period"])  # once per rule and period
                .returning(AlertEvent.id)
            )
            raised += len(created.all())
    return raised


@scheduler.every(900, name="evaluate_alerts")
async def evaluate_all() -> None:
    async with system_session() as db:
        org_ids = (await db.execute(text("SELECT id FROM orgs"))).scalars().all()
    for org_id in org_ids:
        try:
            if raised := await evaluate_rules(org_id):
                log.info("alerts raised", extra={"org_id": str(org_id), "count": raised})
        except Exception:  # noqa: BLE001 - one organisation's failure must not stop the rest
            log.exception("alert evaluation failed", extra={"org_id": str(org_id)})
