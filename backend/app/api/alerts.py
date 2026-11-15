"""Alert rules and the events they have raised."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import audit, current_user, require_role
from app.db import tenant_session
from app.finance.alerts_eval import evaluate_rules
from app.models.alerts import AlertEvent, AlertRule
from app.models.identity import User
from app.security.ratelimit import rate_limit
from app.security.sessions import Principal

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


class RulePatch(BaseModel):
    status: Literal["active", "paused"]


def rule_out(rule: AlertRule, email: str | None = None) -> dict:
    return {
        "id": str(rule.id), "metric": rule.metric, "comparison": rule.comparison, "threshold": float(rule.threshold),
        "window": rule.window, "region": rule.region, "rationale": rule.rationale, "status": rule.status,
        "run_id": str(rule.run_id) if rule.run_id else None, "created_by": email,
        "created_at": rule.created_at.isoformat(),
    }  # fmt: skip


@router.get("/rules")
async def list_rules(user: Principal = Depends(current_user)) -> dict:
    stmt = (
        select(AlertRule, User.email)
        .outerjoin(User, User.id == AlertRule.created_by)
        .order_by(AlertRule.created_at.desc())
    )
    async with tenant_session(user.org_id) as db:
        rows = (await db.execute(stmt)).all()
    return {"rules": [rule_out(rule, email) for rule, email in rows]}


@router.patch("/rules/{rule_id}")
async def patch_rule(
    rule_id: UUID, body: RulePatch, request: Request, admin: Principal = Depends(require_role("admin"))
) -> dict:
    async with tenant_session(admin.org_id) as db:
        rule = (await db.execute(select(AlertRule).where(AlertRule.id == rule_id))).scalar_one_or_none()
        if rule is None:
            raise HTTPException(404, "Alert rule not found.")
        rule.status = body.status
        audit(db, admin, "alert.rule_updated", str(rule.id), {"status": body.status}, request)
        return rule_out(rule)


@router.get("/events")
async def list_events(
    user: Principal = Depends(current_user), open_only: bool = False, limit: int = Query(50, ge=1, le=200)
) -> dict:
    stmt = (
        select(AlertEvent, AlertRule)
        .join(AlertRule, AlertRule.id == AlertEvent.rule_id)
        .order_by(AlertEvent.created_at.desc())
        .limit(limit)
    )
    if open_only:
        stmt = stmt.where(AlertEvent.acknowledged_at.is_(None))
    async with tenant_session(user.org_id) as db:
        rows = (await db.execute(stmt)).all()
        unacknowledged = await db.scalar(
            select(func.count()).select_from(AlertEvent).where(AlertEvent.acknowledged_at.is_(None))
        )
    return {
        "unacknowledged": unacknowledged,
        "events": [
            {
                "id": str(e.id),
                "rule": rule_out(r),
                "period": e.period,
                "value": float(e.value),
                "created_at": e.created_at.isoformat(),
                "acknowledged": e.acknowledged_at is not None,
            }  # fmt: skip
            for e, r in rows
        ],
    }


@router.post("/events/{event_id}/ack")
async def acknowledge(
    event_id: UUID, request: Request, user: Principal = Depends(require_role("analyst", "admin"))
) -> dict:
    async with tenant_session(user.org_id) as db:
        event = (await db.execute(select(AlertEvent).where(AlertEvent.id == event_id))).scalar_one_or_none()
        if event is None:
            raise HTTPException(404, "Alert not found.")
        if event.acknowledged_at is None:
            event.acknowledged_by, event.acknowledged_at = user.id, func.now()
            audit(db, user, "alert.acknowledged", str(event.id), request=request)
    return {"acknowledged": True}


@router.post("/evaluate", dependencies=[Depends(rate_limit("alerts_evaluate", 6, 60))])
async def evaluate_now(admin: Principal = Depends(require_role("admin"))) -> dict:
    """Check the rules now instead of waiting for the schedule."""
    return {"raised": await evaluate_rules(admin.org_id)}
