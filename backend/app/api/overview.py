"""Headline figures for the Overview screen."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import current_user
from app.finance.kpis import overview
from app.security.sessions import Principal

router = APIRouter(prefix="/api/overview", tags=["overview"])


@router.get("")
async def get_overview(
    period: str = Query("2026-Q3", max_length=7, description="A quarter (2026-Q3) or a year (2026)."),
    user: Principal = Depends(current_user),
) -> dict:
    try:
        return await overview(user.org_id, period)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
