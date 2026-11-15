"""Every limit ends the run cleanly, keeping what it had gathered."""

import pytest
from sqlalchemy import update

from app.agent.runtime import advance
from app.config import get_settings
from app.db import tenant_session
from app.llm.stub import reply
from app.llm.types import ToolCall
from app.models.runs import Run
from tests.agent_helpers import TOY, call, done, get_run, get_steps, new_run


def endless():
    """A model that never finishes."""
    return lambda messages, tools: reply(tool_calls=[ToolCall(f"c{len(messages)}", "echo", {"text": "again"})])


async def test_step_limit(team, stub_llm, monkeypatch):
    monkeypatch.setattr(get_settings(), "run_max_steps", 3)
    stub_llm.responder = endless()
    run_id = await new_run(team)
    assert await advance(run_id, TOY) == "budget_exceeded"
    run = await get_run(team, run_id)
    assert run.steps_used == 3 and "limit of 3 model steps" in run.error
    assert len([s for s in await get_steps(team, run_id) if s.kind == "tool" and s.output]) == 3  # evidence kept


async def test_token_limit(team, stub_llm, monkeypatch):
    monkeypatch.setattr(get_settings(), "run_max_tokens", 200)  # each scripted turn uses 120
    stub_llm.responder = endless()
    run_id = await new_run(team)
    assert await advance(run_id, TOY) == "budget_exceeded"
    assert (await get_run(team, run_id)).steps_used == 2


async def test_cost_limit(team, stub_llm, monkeypatch):
    monkeypatch.setattr(get_settings(), "run_max_cost_usd", 0.001)  # one turn costs $0.0006 at default prices
    stub_llm.responder = endless()
    run_id = await new_run(team)
    assert await advance(run_id, TOY) == "budget_exceeded"
    run = await get_run(team, run_id)
    assert run.steps_used == 2 and float(run.cost_usd) == pytest.approx(0.0012) and "cost limit" in run.error


async def test_time_limit_counts_time_spent_working(team, stub_llm, monkeypatch):
    monkeypatch.setattr(get_settings(), "run_max_seconds", 5)
    stub_llm.script = [done()]
    run_id = await new_run(team)
    async with tenant_session(team.org_id) as db:
        await db.execute(update(Run).where(Run.id == run_id).values(active_ms=6000))
    assert await advance(run_id, TOY) == "budget_exceeded"
    assert "time limit of 5 seconds" in (await get_run(team, run_id)).error and stub_llm.calls == []


async def test_organisation_daily_limit_applies_across_runs(team, other_team, stub_llm, monkeypatch):
    monkeypatch.setattr(get_settings(), "org_daily_cost_usd", 0.0015)
    stub_llm.script = [call("echo", text="a"), call("echo", "c2", text="b"), done()]
    first = await new_run(team)
    assert await advance(first, TOY) == "completed"  # spends $0.0018 in total
    stub_llm.script = [done()]
    second = await new_run(team)
    assert await advance(second, TOY) == "budget_exceeded"
    assert "daily limit" in (await get_run(team, second)).error
    stub_llm.script = [done()]
    assert await advance(await new_run(other_team), TOY) == "completed"  # another organisation is unaffected
