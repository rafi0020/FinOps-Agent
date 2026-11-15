"""Opens many concurrent live-event connections and reports how many the server held.

    uv run python -m load.sse_connections --connections 2000 --hold 60 --host http://localhost:3100

Every connection follows the same run, which is parked waiting for an approval, so each stays open and
receives keep-alives. Measured: connections established, time to the first byte, and any that dropped.
"""

import argparse
import asyncio
import statistics
import time

import httpx


async def main(args: argparse.Namespace) -> None:
    limits = httpx.Limits(max_connections=args.connections + 50, max_keepalive_connections=0)
    async with httpx.AsyncClient(
        base_url=args.host, limits=limits, timeout=httpx.Timeout(30, read=args.hold + 30)
    ) as client:
        login = await client.post(
            "/api/auth/login", json={"email": "analyst@northwind.demo", "password": "Analyst#Demo2026"}
        )
        login.raise_for_status()
        client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        if args.run:
            run_id = args.run
        else:  # a run that stays open: with the built-in script, an alert request parks waiting for approval
            created = await client.post("/api/runs", json={"question": "Alert me about margin (live-connection test)"})
            created.raise_for_status()
            run_id = created.json()["id"]
        print(f"following run {run_id} with {args.connections} connections for {args.hold} s")

        first_byte: list[float] = []
        dropped = failed = 0
        gate = asyncio.Semaphore(200)  # open at most 200 at a time, like a browser fleet arriving over a few seconds

        async def follow() -> None:
            nonlocal dropped, failed
            started = time.perf_counter()
            try:
                async with gate:
                    stream = client.stream("GET", f"/api/runs/{run_id}/events")
                    response = await stream.__aenter__()
                if response.status_code != 200:
                    failed += 1
                    await stream.__aexit__(None, None, None)
                    return
                got_first = False
                deadline = started + args.hold
                async for _ in response.aiter_bytes():
                    if not got_first:
                        first_byte.append(time.perf_counter() - started)
                        got_first = True
                    if time.perf_counter() >= deadline:
                        break
                else:
                    dropped += 1  # the server closed the stream before the hold time was up
                await stream.__aexit__(None, None, None)
            except (httpx.HTTPError, OSError):
                failed += 1

        began = time.perf_counter()
        await asyncio.gather(*[follow() for _ in range(args.connections)])
        elapsed = time.perf_counter() - began
        first_byte.sort()
        print(
            f"established: {len(first_byte)} of {args.connections}; failed to connect: {failed}; closed early: {dropped}"
        )
        if first_byte:
            print(
                f"time to first byte: p50 {statistics.median(first_byte) * 1000:.0f} ms, "
                f"p95 {first_byte[int(len(first_byte) * 0.95)] * 1000:.0f} ms, max {first_byte[-1] * 1000:.0f} ms"
            )
        print(f"total wall time {elapsed:.0f} s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--connections", type=int, default=2000)
    parser.add_argument("--hold", type=int, default=60)
    parser.add_argument("--host", default="http://localhost:3100")
    parser.add_argument("--run", default="")
    asyncio.run(main(parser.parse_args()))
