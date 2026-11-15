"""Checks the query plans of the hot paths.

    uv run python -m load.explain

Request-path queries (sessions, runs, steps, the claim) must not scan a large table from end to end; if one
does, this exits non-zero and names it. The analytical queries behind the Overview screen read a whole quarter
by design, so for those the time is reported rather than the plan judged; their results are cached for 60 s.
"""

import json
import sys
import uuid

import psycopg

from app.api.health import libpq_url
from app.config import get_settings
from app.finance import kpis
from app.worker.run import CLAIM
from seed.demo_users import NORTHWIND

BIG = 10_000
ORG = str(NORTHWIND)
RANDOM = str(uuid.uuid4())

REQUEST_PATH = {
    "session lookup": ("SELECT s.id, u.id FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = %s", ("x" * 64,)),
    "run by id": ("SELECT * FROM runs WHERE id = %s", (RANDOM,)),
    "steps of a run": ("SELECT * FROM steps WHERE run_id = %s ORDER BY idx", (RANDOM,)),
    "evidence of a run": ("SELECT * FROM evidence WHERE run_id = %s", (RANDOM,)),
    "recent runs of an organisation": ("SELECT * FROM runs ORDER BY created_at DESC LIMIT 30", ()),
    "active runs of an organisation": ("SELECT count(*) FROM runs WHERE status IN ('queued', 'running')", ()),
    "spend today": ("SELECT coalesce(sum(cost_usd), 0) FROM runs WHERE created_at >= date_trunc('day', now())", ()),
    "pending approvals": ("SELECT * FROM approvals WHERE status = 'pending' ORDER BY created_at DESC LIMIT 50", ()),
    "audit log page": ("SELECT * FROM audit_log ORDER BY id DESC LIMIT 51", ()),
    "claim a run": (str(CLAIM).replace(":worker", "%(worker)s").replace(":lease", "%(lease)s").replace(":per_org", "%(per_org)s"),
                    {"worker": "explain", "lease": 30, "per_org": 5}),
}  # fmt: skip
ANALYTICAL = {
    "overview totals": kpis.TOTALS,
    "overview by region": kpis.BY_REGION,
    "overview top customers": kpis.TOP_CUSTOMERS,
}


def seq_scans(node: dict, found: list) -> None:
    if (
        node.get("Node Type") == "Seq Scan"
        and node.get("Actual Rows", 0) * node.get("Actual Loops", 1) + node.get("Rows Removed by Filter", 0) > BIG
    ):
        found.append(
            f"{node['Relation Name']} ({node.get('Actual Rows', 0) + node.get('Rows Removed by Filter', 0):,} rows read)"
        )
    for child in node.get("Plans", []):
        seq_scans(child, found)


def main() -> int:
    failures = 0
    with psycopg.connect(libpq_url(get_settings().database_url)) as conn:
        sizes = {}
        with conn.transaction():
            conn.execute("SELECT set_config('app.system', 'on', true)")
            conn.execute("SELECT set_config('app.org_id', %s, true)", (ORG,))
            for table in ("runs", "steps", "evidence", "sessions", "audit_log", "approvals"):
                sizes[table] = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608
        print("table sizes:", ", ".join(f"{t} {n:,}" for t, n in sizes.items()))
        for name, (sql, params) in REQUEST_PATH.items():
            with conn.transaction(force_rollback=True):  # the claim is an UPDATE; never keep its effect
                conn.execute("SELECT set_config('app.org_id', %s, true)", (ORG,))
                if name in ("claim a run", "session lookup"):
                    conn.execute("SELECT set_config('app.system', 'on', true)")
                plan = conn.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, params).fetchone()[0][0]
            found: list[str] = []
            seq_scans(plan["Plan"], found)
            verdict = "SEQUENTIAL SCAN on " + ", ".join(found) if found else "ok"
            failures += bool(found)
            print(f"  {name:<34}{plan['Execution Time']:>9.2f} ms  {verdict}")
        for name, sql in ANALYTICAL.items():
            with conn.transaction(force_rollback=True):
                conn.execute("SELECT set_config('app.org_id', %s, true)", (ORG,))
                bound = sql.replace(":start", "%(start)s").replace(":end", "%(end)s")
                plan = conn.execute(
                    "EXPLAIN (ANALYZE, FORMAT JSON) " + bound, {"start": "2026-07-01", "end": "2026-10-01"}
                ).fetchone()[0][0]
            print(f"  {name:<34}{plan['Execution Time']:>9.2f} ms  analytical (cached 60 s)")
    if "--json" in sys.argv:
        print(json.dumps({"failures": failures}))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
