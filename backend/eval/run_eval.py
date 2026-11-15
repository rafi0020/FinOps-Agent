"""Runs a question set through the real agent with a real model and scores the answers.

    python -m eval.run_eval --split dev --model cx/gpt-6-luna
    python -m eval.run_eval --split test --model cc/claude-sonnet-5-5 --out eval/results/test-claude-sonnet.json

The model is reached through an OpenAI-compatible endpoint: NINEROUTER_BASE_URL / NINEROUTER_API_KEY, or
EVAL_BASE_URL / EVAL_API_KEY. It runs against the seeded demo database (make dev-up; python -m seed.generate).

How an answer is scored:
  lookup, compare (number)  a figure in the report matches the reference within the question's tolerance
  compare (name)            the reference name appears in the report
  root_cause                the planted cause is named (every `must` term and at least one `any_of` term)
  ambiguous                 the agent asked the user a question instead of guessing
  unanswerable              the agent finished with outcome "cannot_answer"
Numeric scoring accepts any matching figure in the report, so a report that lists many numbers can pass by
coincidence; the tolerance is tight (1-2%) to keep that unlikely.
"""

import argparse
import asyncio
import json
import os
import statistics
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from app.agent.runtime import advance
from app.config import get_settings
from app.db import dispose_engines, tenant_session
from app.finance.agent import AGENT
from app.finance.grounding import extract_numbers
from app.llm import factory
from app.llm.openai_compat import OpenAICompatProvider
from app.models.identity import User
from app.models.runs import Run, Step
from app.redis import close_redis
from eval.build_questions import ORGS

HERE = Path(__file__).parent
EVAL_WORKER = "evaluation"


def report_text(report: dict | None) -> str:
    if not report:
        return ""
    return " ".join([report.get("summary", ""), *[f["claim"] for f in report.get("findings", [])]])


def number_matches(text: str, expected: float, tolerance: float, unit: str) -> bool:
    targets = [expected]
    if unit in ("ratio", "points"):
        targets.append(expected * 100)  # 0.2047 may be written as 20.5% or as 20.5 points
    for mention in extract_numbers(text):
        for value, printed_precision in mention.candidates:
            for target in targets:
                if abs(abs(value) - abs(target)) <= max(printed_precision, tolerance * abs(target)):
                    return True
    return False


def score(question: dict, run: Run, steps: list[Step]) -> tuple[bool, str]:
    report = run.result or {}
    text = report_text(report).lower()
    kind = question["kind"]
    if kind == "ambiguous":
        asked = run.status == "waiting_user"
        return asked, "asked the user" if asked else f"did not ask; ended {run.status}"
    if kind == "unanswerable":
        declined = run.status == "completed" and report.get("outcome") == "cannot_answer"
        return (
            declined,
            "declined" if declined else f"did not decline (status {run.status}, outcome {report.get('outcome')})",
        )
    if run.status != "completed":
        return False, f"run ended {run.status}: {run.error or ''}"[:200]
    if report.get("outcome") != "answered":
        return False, "declined a question that has an answer"
    if kind == "root_cause":
        missing = [term for term in question["must"] if term not in text]
        any_ok = any(term in text for term in question["any_of"])
        return (
            not missing and any_ok
        ), "cause named" if not missing and any_ok else f"cause not named (missing {missing or question['any_of']})"
    if question.get("answer") == "name":
        ok = str(question["expected"]).lower() in text
        return ok, "named" if ok else f"expected '{question['expected']}'"
    ok = number_matches(
        report_text(report), question["expected"], question["tolerance"], question.get("unit", "number")
    )
    return ok, "figure matches" if ok else f"expected {question['expected']:.6g}"


async def run_question(question: dict, users: dict, gate: asyncio.Semaphore) -> dict:
    org_id = ORGS[question["org"]]
    async with gate:
        async with tenant_session(org_id) as db:
            run = Run(
                org_id=org_id,
                user_id=users[question["org"]],
                role="analyst",
                question=question["question"],
                status="running",
                # Held under a long lease so worker processes sharing this database leave the run alone.
                lease_owner=EVAL_WORKER,
                lease_expires_at=datetime.now(UTC) + timedelta(hours=2),
            )
            db.add(run)
            await db.flush()
            run_id = run.id
        started = time.perf_counter()
        try:
            await advance(run_id, AGENT, worker_id=EVAL_WORKER)
        except Exception as exc:  # noqa: BLE001 - one broken question must not stop the evaluation
            print(f"  {question['id']} crashed: {type(exc).__name__}: {exc}")
        elapsed = time.perf_counter() - started
    async with tenant_session(org_id) as db:
        run = (await db.execute(select(Run).where(Run.id == run_id))).scalar_one()
        steps = list((await db.execute(select(Step).where(Step.run_id == run_id).order_by(Step.idx))).scalars())
    passed, reason = score(question, run, steps)
    report = run.result or {}
    print(
        f"  {question['id']} {'PASS' if passed else 'FAIL'} [{question['kind']}] {question['question'][:60]} -> {reason}"
    )
    return {
        "id": question["id"], "kind": question["kind"], "question": question["question"], "passed": passed, "reason": reason,
        "status": run.status, "steps": run.steps_used, "tokens": run.tokens_used, "cost_usd": float(run.cost_usd),
        "latency_s": round(elapsed, 1), "unsupported": len(report.get("unsupported", [])),
        "tool_errors": sum(1 for s in steps if s.kind == "tool" and s.error),
        "answer": (report.get("summary") or run.error or (run.pending or {}).get("question") or "")[:400],
        "run_id": str(run_id),
    }  # fmt: skip


def aggregate(rows: list[dict]) -> tuple[dict, dict]:
    def rate(kinds: tuple[str, ...]) -> float | None:
        subset = [r for r in rows if r["kind"] in kinds]
        return round(sum(r["passed"] for r in subset) / len(subset), 4) if subset else None

    reports = [r for r in rows if r["status"] == "completed"]
    latencies = sorted(r["latency_s"] for r in rows)
    metrics = {
        "answer_accuracy": rate(("lookup", "compare")),
        "root_cause_rate": rate(("root_cause",)),
        "behaviour_rate": rate(("ambiguous", "unanswerable")),
        "overall_pass_rate": round(sum(r["passed"] for r in rows) / len(rows), 4),
        "completed_rate": round(len(reports) / len(rows), 4),
        "unsupported_numbers_per_report": round(sum(r["unsupported"] for r in reports) / max(1, len(reports)), 3),
        "mean_steps": round(statistics.mean(r["steps"] for r in rows), 2),
        "mean_tokens": round(statistics.mean(r["tokens"] for r in rows)),
        "mean_cost_usd": round(statistics.mean(r["cost_usd"] for r in rows), 4),
        "p50_latency_s": latencies[len(latencies) // 2],
        "p95_latency_s": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))],
    }
    by_kind = {
        kind: {"n": sum(r["kind"] == kind for r in rows), "passed": sum(r["passed"] for r in rows if r["kind"] == kind)}
        for kind in dict.fromkeys(r["kind"] for r in rows)
    }
    return metrics, by_kind


def configure_model(model: str) -> None:
    base = os.environ.get("EVAL_BASE_URL") or os.environ["NINEROUTER_BASE_URL"]
    key = os.environ.get("EVAL_API_KEY") or os.environ["NINEROUTER_API_KEY"]
    settings = get_settings()
    settings.llm_provider, settings.llm_model = "openai_compat", model
    settings.org_daily_cost_usd, settings.run_max_seconds = 10_000.0, 420
    factory.set_override(OpenAICompatProvider(base, key))

    async def evaluation_config(org_id):  # the model under test, whatever an organisation has saved
        return factory.environment_config()

    factory.load_config = evaluation_config


async def demo_analysts() -> dict[str, UUID]:
    users = {}
    for name, org_id in ORGS.items():
        async with tenant_session(org_id) as db:
            users[name] = (await db.execute(select(User.id).where(User.role == "analyst").limit(1))).scalar_one()
    return users


async def main(args: argparse.Namespace) -> None:
    questions = json.loads((HERE / f"questions_{args.split}.json").read_text())
    if args.only:
        questions = [q for q in questions if q["id"] in args.only.split(",") or q["kind"] in args.only.split(",")]
    configure_model(args.model)
    users = await demo_analysts()
    print(f"{len(questions)} questions, split={args.split}, model={args.model}, concurrency={args.concurrency}")
    gate = asyncio.Semaphore(args.concurrency)
    rows = await asyncio.gather(*[run_question(q, users, gate) for q in questions])
    metrics, by_kind = aggregate(rows)
    safe_model = args.model.replace("/", "-")
    result = {
        "name": f"{args.split}-{safe_model}", "model": args.model, "split": args.split, "n": len(rows),
        "at": datetime.now(UTC).isoformat(timespec="seconds"), "metrics": metrics, "by_kind": by_kind, "questions": rows,
    }  # fmt: skip
    out = Path(args.out) if args.out else HERE / "results" / f"{args.split}-{safe_model}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1))
    print(json.dumps(metrics, indent=1), "\n", by_kind, f"\nwritten to {out}")
    await close_redis()
    await dispose_engines()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate the agent on a question set")
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--model", required=True)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--only", default="", help="comma-separated question ids or kinds")
    parser.add_argument("--out", default="")
    asyncio.run(main(parser.parse_args()))
