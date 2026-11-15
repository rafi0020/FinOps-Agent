"""Saved investigations: completed runs kept under a title so others can find and re-run them."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import audit, current_user, require_role
from app.api.runs import create_run
from app.db import tenant_session
from app.models.identity import User
from app.models.runs import Investigation, Run
from app.security.sessions import Principal

router = APIRouter(prefix="/api/investigations", tags=["investigations"])


class Save(BaseModel):
    run_id: UUID
    title: str = Field(min_length=1, max_length=160)


class Patch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    pinned: bool | None = None


def out(inv: Investigation, run: Run, email: str | None) -> dict:
    report = run.result or {}
    return {
        "id": str(inv.id), "run_id": str(inv.run_id), "title": inv.title, "pinned": inv.pinned,
        "question": run.question, "outcome": report.get("outcome"), "summary": (report.get("summary") or "")[:280],
        "created_by": email, "created_by_id": str(inv.created_by) if inv.created_by else None,
        "created_at": inv.created_at.isoformat(),
    }  # fmt: skip


@router.get("")
async def list_investigations(
    user: Principal = Depends(current_user),
    q: str | None = Query(None, max_length=100, description="Search titles and questions."),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    stmt = (
        select(Investigation, Run, User.email)
        .join(Run, Run.id == Investigation.run_id)
        .outerjoin(User, User.id == Investigation.created_by)
        .order_by(Investigation.pinned.desc(), Investigation.created_at.desc())
        .limit(limit)
    )
    if q and q.strip():
        term = q.strip()
        stmt = stmt.where(
            or_(Investigation.title.icontains(term, autoescape=True), Run.question.icontains(term, autoescape=True))
        )
    async with tenant_session(user.org_id) as db:
        rows = (await db.execute(stmt)).all()
    return {"investigations": [out(inv, run, email) for inv, run, email in rows]}


@router.post("", status_code=201)
async def save(body: Save, request: Request, user: Principal = Depends(require_role("analyst", "admin"))) -> dict:
    try:
        async with tenant_session(user.org_id) as db:
            run = (await db.execute(select(Run).where(Run.id == body.run_id))).scalar_one_or_none()
            if run is None:
                raise HTTPException(404, "Run not found.")
            if run.status != "completed":
                raise HTTPException(409, "Only a completed run can be saved.")
            inv = Investigation(org_id=user.org_id, run_id=run.id, title=body.title.strip(), created_by=user.id)
            db.add(inv)
            await db.flush()
            await db.refresh(inv)
            audit(db, user, "investigation.saved", str(inv.id), {"title": inv.title}, request)
            return out(inv, run, user.email)
    except IntegrityError as exc:
        raise HTTPException(409, "This run is already saved.") from exc


async def _own(db, investigation_id: UUID, user: Principal) -> Investigation:
    inv = (await db.execute(select(Investigation).where(Investigation.id == investigation_id))).scalar_one_or_none()
    if inv is None:
        raise HTTPException(404, "Investigation not found.")
    if user.role != "admin" and inv.created_by != user.id:
        raise HTTPException(403, "Only the person who saved it, or an administrator, can change it.")
    return inv


@router.patch("/{investigation_id}")
async def patch(
    investigation_id: UUID, body: Patch, request: Request, user: Principal = Depends(require_role("analyst", "admin"))
) -> dict:
    async with tenant_session(user.org_id) as db:
        inv = await _own(db, investigation_id, user)
        if body.title is not None:
            inv.title = body.title.strip()
        if body.pinned is not None:
            inv.pinned = body.pinned
        audit(db, user, "investigation.updated", str(inv.id), body.model_dump(exclude_none=True), request)
        return {"id": str(inv.id), "title": inv.title, "pinned": inv.pinned}


@router.delete("/{investigation_id}", status_code=204)
async def delete(
    investigation_id: UUID, request: Request, user: Principal = Depends(require_role("analyst", "admin"))
) -> None:
    async with tenant_session(user.org_id) as db:
        inv = await _own(db, investigation_id, user)
        audit(db, user, "investigation.deleted", str(inv.id), {"title": inv.title}, request)
        await db.delete(inv)


@router.post("/{investigation_id}/rerun", status_code=202)
async def rerun(
    investigation_id: UUID, request: Request, user: Principal = Depends(require_role("analyst", "admin"))
) -> dict:
    """Ask the same question again, as a new run against today's data."""
    async with tenant_session(user.org_id) as db:
        question = await db.scalar(
            select(Run.question)
            .join(Investigation, Investigation.run_id == Run.id)
            .where(Investigation.id == investigation_id)
        )
    if question is None:
        raise HTTPException(404, "Investigation not found.")
    return {"id": str(await create_run(user, question, request))}
