"""The whole agent with a real model through 9Router, on the planted supplier cost rise."""

import os

import pytest

from app.agent.runtime import advance
from app.config import get_settings
from app.finance.agent import AGENT
from app.llm import factory
from app.llm.openai_compat import OpenAICompatProvider
from tests.agent_helpers import get_run, get_steps, new_run

pytestmark = pytest.mark.live


# What each model is held to. Claude Sonnet named the supplier in every run observed. GPT-6 Luna names it in
# most runs but sometimes stops one level up, at the product category (see docs/EVALUATION.md: 3 of 4 root
# causes on the held-out set), so for it this test requires the right direction rather than the full answer.
@pytest.mark.parametrize(("model", "must_name"), [("cx/gpt-6-luna", "metals"), ("cc/claude-sonnet-5-5", "calder")])
async def test_agent_finds_the_planted_cause_of_the_west_margin_drop(demo, monkeypatch, model, must_name):
    monkeypatch.setattr(get_settings(), "llm_model", model)
    monkeypatch.setattr(get_settings(), "run_max_seconds", 600)
    factory.set_override(OpenAICompatProvider(os.environ["NINEROUTER_BASE_URL"], os.environ["NINEROUTER_API_KEY"]))
    try:
        run_id = await new_run(demo.northwind, question="Why did gross margin fall in the West region in Q3 2026?")
        status = await advance(run_id, AGENT)
    finally:
        factory.set_override(None)
    run = await get_run(demo.northwind, run_id)
    steps = await get_steps(demo.northwind, run_id)
    print(f"\n[{model}] status={status} steps={run.steps_used} tokens={run.tokens_used} cost=${run.cost_usd}")
    print("tools:", [s.name for s in steps if s.kind == "tool"])
    print("errors:", [s.error[:120] for s in steps if s.error])
    print(
        "summary:",
        (run.result or {}).get("summary"),
        "| unsupported:",
        (run.result or {}).get("unsupported"),
        "| error:",
        run.error,
    )
    assert status == "completed", run.error
    report = run.result
    text = (report["summary"] + " " + " ".join(f["claim"] for f in report["findings"])).lower()
    assert must_name in text
    assert report["unsupported"] == []
    assert len({h for f in report["findings"] for h in f["evidence"]}) >= 2
