# Scale: what was measured

Everything here was measured on one laptop on 2026-11-14, with the load generator running on the same
machine as the system under test. It shows how the system behaves and where it stops on this hardware. It
is not a capacity claim for a production deployment.

**Machine:** 16 logical cores, 31 GB RAM, Linux, Docker 29. PostgreSQL 16 (`shared_buffers` 512 MB), PgBouncer
in transaction mode (pool of 40), Redis 7, nginx 1.29. Data: 284,000 finance rows; during the tests the run
tables grew to 3,283 runs and 14,463 steps.

**How to repeat:** `docker compose -f docker-compose.yml -f docker-compose.load.yml up -d --build --scale api=4`,
then the commands in `backend/load/`. The override uses the built-in script instead of a model and lifts the
per-user and per-organisation limits, so the platform is measured rather than its own throttles.

## 1. Reading: people browsing dashboards and opening results

Locust, `backend/load/locustfile.py`: each simulated person signs in, then requests the overview, a run, the
investigations list, alerts, the catalogue and their own session, with 1–3 s between requests. Figures are
steady state, after everyone has signed in.

| API containers | People | Requests/s | p50 | p95 | p99 | Errors |
|---|---|---|---|---|---|---|
| 1 | 1,000 | 449 | 6 ms | 220 ms | 890 ms | 0 |
| 4 | 1,000 | 461 | 3 ms | 8 ms | 130 ms | 0 |
| 4 | 3,000 | 974 | 17 ms | 9.5 s | 21 s | 0.03% (HTTP 500) |
| 8 | 3,000 | 877 | 6 ms | 12 s | 20 s | 0.003% (HTTP 500) |

What this says:

- **1,000 concurrent people are served comfortably**, by one API container at a push and by four with a
  large margin.
- **At 3,000 people this machine is saturated**, at roughly 900–1,000 requests per second. Median latency
  stays low but a tail of requests queues for seconds. Going from four API containers to eight did not help,
  so the limit is not the API tier. With the load generator, eight API processes, PostgreSQL, PgBouncer,
  Redis and nginx sharing 16 cores, the most likely cause is the machine itself; **the bottleneck was not
  isolated**, and doing so needs the load generator on separate hardware.
- **The handful of HTTP 500 responses at 3,000 people were not diagnosed.** No exception was found in the
  API logs for them.

## 2. Signing in

Sign-in is deliberately expensive: verifying a password costs about 0.1 s of CPU (scrypt, memory-hard). When
1,000 people signed in within ten seconds, sign-in took a median of 5.3 s on one API container and 2.6 s on
four; with 3,000 at once, 17 s. Nothing failed, but people waited. A sudden mass sign-in is therefore the
weakest point for concurrency. Sessions last 12 hours, so in normal use sign-ins are spread out.

## 3. Live connections

`backend/load/sse_connections.py`: 2,000 browsers following one run over Server-Sent Events for 45 s,
through nginx, on four API containers.

| | |
|---|---|
| Connections established | 2,000 of 2,000 |
| Dropped before the end | 0 |
| Time to first byte | p50 1.8 s, p95 4.1 s (2,000 connections opened within a few seconds) |
| API CPU while held | 50–70% of one core per container, about 2.3 cores in total |
| API memory | about 165 MB per container |
| Redis | 9% of one core, 49 MB |

The CPU cost comes from the design choice in `backend/app/api/events.py`: each connection polls its run's
event stream every 0.4 s instead of holding a blocking Redis read. That keeps Redis connections few, at
about one core per 900 idle connections. For tens of thousands of open tabs, one reader per API process
fanning events out to its connections would be the next step.

## 4. Runs: throughput of the agent machinery

`backend/load/throughput.py`: 600 runs queued at once, executed with the built-in script in place of a
model. Each run still does everything around the model: claim under a lease, eight recorded steps, a guarded
SQL query, a calculation, stored evidence, the grounding check and published events.

| Worker containers (4 concurrent runs each) | Runs per minute | Run duration p50 |
|---|---|---|
| 1 | 940 | 0.23 s |
| 4 | 2,645 | 0.33 s |
| 8 | 3,379 | 0.50 s |

Throughput scales with workers, less than linearly at eight as each run slows down, which points at the
shared database. **With a real model these numbers do not apply:** a run takes 10–60 s, almost all of it
waiting for the model, so the number of concurrent runs is set by the provider's rate limits and by
`WORKER_CONCURRENCY`, not by this code. What the table shows is that the machinery around the model is not
the constraint.

## 5. Query plans

`python -m load.explain`, at the table sizes above. No request-path query scans a large table.

| Query | Time |
|---|---|
| Session look-up, run by id, steps of a run, evidence of a run | 0.01–0.03 ms |
| Claim a run | 0.10 ms |
| Recent runs of an organisation | 1.7 ms |
| Spend today (budget check) | 2.1 ms |
| Overview aggregates (three queries over a quarter) | 14–23 ms each, cached for 60 s |

"Spend today" and "recent runs" will grow with the number of runs per organisation per day; at the sizes
tested they are index scans.

## A defect the load test found

With one API container at about 450 requests per second, 1.2% of requests failed with HTTP 502. nginx was
opening a new connection to the API for every request and ran out of local ports
(`connect() failed (99: Address not available)`). The proxy now uses an upstream block with keep-alive
connections and DNS re-resolution (`frontend/nginx.conf`); the same test then ran with no errors.

## Not tested

- Any load with a real model, beyond the 100 or so runs of the evaluation.
- More than one machine; network latency between tiers; a managed database.
- Many organisations at once (two were used), or a large number of users per organisation.
- Sustained load over hours, memory growth, or behaviour while PostgreSQL or Redis restarts.
- Tables in the millions of rows. Partitioning `steps` and `evidence` by time and a retention policy would
  be needed before then.
