"""The finance agent: its instructions and its tools. Workers load `AGENT` (see app/worker/run.py)."""

from uuid import UUID

from sqlalchemy import select

from app.agent.tools import AgentSpec
from app.db import system_session
from app.finance import alerts_eval  # noqa: F401 - registers propose_alert and the alert schedule
from app.finance.prompts import SYSTEM_PROMPT
from app.finance.tools import registry
from app.models.identity import Org


async def company_context(org_id: UUID) -> str:
    """Tells the model whose data it is looking at, so a question about another company is recognised as one."""
    async with system_session() as db:
        name = await db.scalar(select(Org.name).where(Org.id == org_id))
    return (
        f"Company whose data you can see: {name}. Every table contains this company only. "
        "A question about any other company cannot be answered from it."
    )


AGENT = AgentSpec(SYSTEM_PROMPT, registry, context=company_context)
