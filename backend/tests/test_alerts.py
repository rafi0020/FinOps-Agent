"""Alerts: proposed by the agent, created only on approval, raised once per period, private to the organisation."""

from datetime import date

from app.finance.agent import AGENT
from app.finance.alerts_eval import evaluate_rules, latest_complete_period
from tests.agent_helpers import work
from tests.test_finance_tools import call
from tests.test_runs_api import ask
from tests.test_seed import ro_scalar

WEST_MARGIN_BELOW_25 = dict(
    metric="gross_margin", comparison="<", threshold=0.25, window="quarter", region="West",
    rationale="West margin fell after the supplier cost rise.",
)  # fmt: skip


async def propose(demo, stub_llm, **args) -> tuple[str, str]:
    stub_llm.script = [call("propose_alert", **args)]
    run_id = await ask(demo.northwind_analyst, "Alert me if West gross margin drops below 25%.")
    await work(AGENT)
    approval = next(
        a for a in (await demo.northwind_admin.get("/api/approvals")).json()["approvals"] if a["run_id"] == run_id
    )
    return run_id, approval["id"]


async def rules(client) -> list[dict]:
    return (await client.get("/api/alerts/rules")).json()["rules"]


def test_latest_complete_period():
    assert latest_complete_period(date(2026, 9, 30), "quarter") == ("2026-Q3", date(2026, 7, 1), date(2026, 10, 1))
    assert latest_complete_period(date(2026, 9, 30), "month") == ("2026-09", date(2026, 9, 1), date(2026, 10, 1))
    assert latest_complete_period(date(2026, 9, 29), "quarter") == ("2026-Q2", date(2026, 4, 1), date(2026, 7, 1))
    assert latest_complete_period(date(2026, 1, 15), "month") == ("2025-12", date(2025, 12, 1), date(2026, 1, 1))


async def test_approved_proposal_becomes_exactly_one_rule(empty_queue, demo, stub_llm):
    before = len(await rules(demo.northwind_admin))
    run_id, approval = await propose(demo, stub_llm, **WEST_MARGIN_BELOW_25)
    assert len(await rules(demo.northwind_admin)) == before  # nothing exists until it is approved
    stub_llm.script = [call("finish", summary="The alert is set.")]
    assert (
        await demo.northwind_admin.post(f"/api/approvals/{approval}/decide", json={"decision": "approved"})
    ).status_code == 200
    assert (
        await demo.northwind_admin.post(f"/api/approvals/{approval}/decide", json={"decision": "approved"})
    ).status_code == 409
    await work(AGENT)
    await work(AGENT)
    created = [r for r in await rules(demo.northwind_admin) if r["run_id"] == run_id]
    assert len(created) == 1
    assert created[0] | {"id": 0, "created_at": 0} == {
        "id": 0, "metric": "gross_margin", "comparison": "<", "threshold": 0.25, "window": "quarter", "region": "West",
        "rationale": "West margin fell after the supplier cost rise.", "status": "active", "run_id": run_id,
        "created_by": "analyst@northwind.demo", "created_at": 0,
    }  # fmt: skip
    assert (await demo.northwind_analyst.get(f"/api/runs/{run_id}")).json()["status"] == "completed"


async def test_rejected_proposal_creates_nothing(empty_queue, demo, stub_llm):
    run_id, approval = await propose(demo, stub_llm, **WEST_MARGIN_BELOW_25 | {"threshold": 0.1})
    stub_llm.script = [call("finish", summary="Not set.")]
    await demo.northwind_admin.post(f"/api/approvals/{approval}/decide", json={"decision": "rejected", "reason": "no"})
    await work(AGENT)
    assert [r for r in await rules(demo.northwind_admin) if r["run_id"] == run_id] == []


async def test_invalid_proposals_never_reach_an_administrator(empty_queue, demo, stub_llm):
    stub_llm.script = [
        call("propose_alert", **WEST_MARGIN_BELOW_25 | {"metric": "headcount"}),
        call("finish", summary="x"),
    ]
    run_id = await ask(demo.northwind_analyst, "alert")
    await work(AGENT)
    run = (await demo.northwind_analyst.get(f"/api/runs/{run_id}")).json()
    assert run["status"] == "completed" and "invalid_call" in run["steps"][1]["error"]


async def test_rule_fires_once_per_period_with_the_measured_value(empty_queue, demo, stub_llm):
    run_id, approval = await propose(demo, stub_llm, **WEST_MARGIN_BELOW_25 | {"rationale": "fires"})
    stub_llm.script = [call("finish", summary="set")]
    await demo.northwind_admin.post(f"/api/approvals/{approval}/decide", json={"decision": "approved"})
    await work(AGENT)
    rule = next(r for r in await rules(demo.northwind_admin) if r["run_id"] == run_id)

    assert (await demo.northwind_admin.post("/api/alerts/evaluate")).json()["raised"] >= 1
    assert await evaluate_rules(demo.northwind_id) == 0  # the same period does not raise it again
    listed = (await demo.northwind_viewer.get("/api/alerts/events", params={"open_only": True})).json()
    event = next(e for e in listed["events"] if e["rule"]["id"] == rule["id"])
    expected = await ro_scalar(
        demo.northwind_id,
        "SELECT sum(gross_profit_usd) / sum(revenue_usd) FROM analytics.order_lines "
        "WHERE region = 'West' AND order_date >= '2026-07-01' AND order_date < '2026-10-01'",
    )
    assert event["period"] == "2026-Q3" and abs(event["value"] - expected) < 1e-6 and event["value"] < 0.25
    assert listed["unacknowledged"] >= 1

    assert (await demo.northwind_viewer.post(f"/api/alerts/events/{event['id']}/ack")).status_code == 403
    assert (await demo.northwind_analyst.post(f"/api/alerts/events/{event['id']}/ack")).json() == {"acknowledged": True}
    still_open = (await demo.northwind_viewer.get("/api/alerts/events", params={"open_only": True})).json()["events"]
    assert event["id"] not in {e["id"] for e in still_open}

    # a paused rule is not evaluated; only an administrator can pause it
    assert (
        await demo.northwind_analyst.patch(f"/api/alerts/rules/{rule['id']}", json={"status": "paused"})
    ).status_code == 403
    assert (await demo.northwind_admin.patch(f"/api/alerts/rules/{rule['id']}", json={"status": "paused"})).json()[
        "status"
    ] == "paused"


async def test_rule_that_is_not_breached_raises_nothing(empty_queue, demo, stub_llm):
    args = dict(metric="revenue", comparison="<", threshold=1.0, window="month", rationale="never true")
    run_id, approval = await propose(demo, stub_llm, **args)
    stub_llm.script = [call("finish", summary="set")]
    await demo.northwind_admin.post(f"/api/approvals/{approval}/decide", json={"decision": "approved"})
    await work(AGENT)
    rule = next(r for r in await rules(demo.northwind_admin) if r["run_id"] == run_id)
    await evaluate_rules(demo.northwind_id)
    events = (await demo.northwind_admin.get("/api/alerts/events")).json()["events"]
    assert rule["id"] not in {e["rule"]["id"] for e in events}


async def test_rules_and_events_are_private_to_the_organisation(empty_queue, demo, stub_llm):
    await evaluate_rules(demo.northwind_id)
    ours = {r["id"] for r in await rules(demo.northwind_admin)}
    theirs = {r["id"] for r in await rules(demo.harbor_admin)}
    assert ours and not ours & theirs
    harbor_events = (await demo.harbor_admin.get("/api/alerts/events")).json()
    assert harbor_events["events"] == [] and harbor_events["unacknowledged"] == 0
    rule_id = next(iter(ours))
    assert (await demo.harbor_admin.patch(f"/api/alerts/rules/{rule_id}", json={"status": "paused"})).status_code == 404
