"""Measures how many runs per minute the workers complete when the model itself costs nothing.

    uv run python -m load.throughput --runs 400

It queues runs for the two demo organisations and waits until the workers (already running, with
LLM_PROVIDER=stub) have finished them. Each stub run does what a real one does around the model: claims the
run, records eight steps, runs a guarded SQL query and a calculation, stores evidence, checks the report and
publishes events. The result is the platform's ceiling; with a real model, the model's latency dominates.
"""

import argparse
import asyncio
import time

from sqlalchemy import func, select, text

from app.db import dispose_engines, system_session, tenant_session
from app.models.identity import User
from app.models.runs import Run
from app.redis import close_redis
from app.worker.run import wake_workers
from seed.demo_users import HARBOR, NORTHWIND


async def main(args: argparse.Namespace) -> None:
    tag = f"load-test {int(time.time())}"
    for i, org_id in enumerate((NORTHWIND, HARBOR)):
        async with tenant_session(org_id) as db:
            user_id = (await db.execute(select(User.id).where(User.role == "analyst").limit(1))).scalar_one()
            share = args.runs // 2 + (args.runs % 2 if i == 0 else 0)
            db.add_all(
                [
                    Run(org_id=org_id, user_id=user_id, role="analyst", question=tag, status="queued")
                    for _ in range(share)
                ]
            )
    started = time.perf_counter()
    await wake_workers()
    while True:
        async with system_session() as db:
            rows = dict(
                (
                    await db.execute(select(Run.status, func.count()).where(Run.question == tag).group_by(Run.status))
                ).all()
            )
        done = sum(count for status, count in rows.items() if status not in ("queued", "running"))
        if done >= args.runs:
            break
        if time.perf_counter() - started > args.timeout:
            print("timed out", rows)
            break
        await asyncio.sleep(0.5)
    elapsed = time.perf_counter() - started
    async with system_session() as db:
        latency = (
            await db.execute(
                text(
                    "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM finished_at - started_at)), "
                    "percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM finished_at - started_at)), "
                    "percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM started_at - created_at)) "
                    "FROM runs WHERE question = :tag AND status = 'completed'"
                ),
                {"tag": tag},
            )
        ).one()
    print(f"statuses: {rows}")
    print(f"{args.runs} runs in {elapsed:.1f} s = {args.runs / elapsed * 60:.0f} runs/minute")
    print(f"run duration p50 {latency[0]:.2f} s, p95 {latency[1]:.2f} s; time waiting in queue p95 {latency[2]:.1f} s")
    await close_redis()
    await dispose_engines()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=400)
    parser.add_argument("--timeout", type=int, default=600)
    asyncio.run(main(parser.parse_args()))
