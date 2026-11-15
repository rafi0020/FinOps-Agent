# Database

PostgreSQL 16. Migrations are in `backend/alembic/versions/` and are the source of truth; the mapped classes
in `backend/app/models/` mirror them.

## Roles

| Role | Used by | Can do |
|---|---|---|
| `finops_owner` | migrations, demo data loader | Owns every table. Row-level security is `FORCE`d, so it applies to the owner too. |
| `finops_app` | API and workers | Read and write tables in `public`; not an owner. Cannot update or delete `audit_log`. |
| `finops_ro` | the agent's SQL tool | `SELECT` on schema `analytics` only. Read-only transactions. No right to call `set_config`. |

## Tenancy

Every table holding an organisation's data has `org_id` and this policy (`backend/app/rls.py`):

```sql
ALTER TABLE t ENABLE ROW LEVEL SECURITY;
ALTER TABLE t FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON t
  USING (org_id = app_current_org()) WITH CHECK (org_id = app_current_org());
```

`app_current_org()` reads the transaction-local setting `app.org_id`. The application sets it at the start
of each transaction (`tenant_session` in `backend/app/db.py`). With no organisation set, a tenant table
returns no rows.

Two tables, `users` and `runs`, also admit a "system" transaction (`app.system = on`), used only to find a
user at sign-in and for workers to claim runs across organisations.

## Tables

### Identity

| Table | Purpose | Notes |
|---|---|---|
| `orgs` | Organisations | |
| `users` | People | `email` unique across all organisations; `role` is viewer, analyst or admin; scrypt `password_hash` |
| `sessions` | Server-side sessions | Stores the SHA-256 of the cookie token, never the token |
| `audit_log` | Who did what | Append-only for the application |
| `llm_settings` | Model provider per organisation | `api_key_enc` is encrypted with `SECRET_KEY` |

### Agent

| Table | Purpose | Notes |
|---|---|---|
| `runs` | One question and how far it has got | Also the work queue: `status`, `lease_owner`, `lease_expires_at`, `attempts`. Counters: `steps_used`, `tokens_used`, `cost_usd`, `active_ms` |
| `steps` | Every model call, tool call and runtime note | Unique `(run_id, idx)` and unique `idempotency_key`; `state` is started, awaiting_approval, awaiting_user or done |
| `approvals` | Tool calls waiting for an administrator | Unique `(run_id, step_idx)` |
| `evidence` | Stored query results, calculations and charts | Primary key is the handle, e.g. `ev_7f3a91c2d4b65e10` (64 random bits, checked free before use) |
| `investigations` | Completed runs someone saved | Trigram index on `title` |
| `alert_rules`, `alert_events` | Approved rules and what they raised | Unique `(run_id, step_idx)` on rules; unique `(rule_id, period)` on events |
| `scheduled_jobs` | Recurring jobs | Not tenant data; one row per job |

Run status values: `queued`, `running`, `waiting_approval`, `waiting_user`, `completed`, `failed`,
`cancelled`, `budget_exceeded`.

### Finance (synthetic)

`regions`, `suppliers`, `products`, `product_costs`, `customers`, `orders`, `order_items`, `invoices`,
`payments`, `expenses`, `budgets`, `fx_rates`. About 284,000 rows across two demo organisations, generated
by `backend/seed/generate.py` (seed 7), covering 2024-01-01 to 2026-09-30.

Schema `analytics` has one view per finance table without `org_id`, plus `order_lines`: one row per line of
a completed order with money converted to USD. The views are what the agent sees; they are documented for it
in `backend/app/finance/catalog.py`, and a test checks that file against the database.

Three causes are planted in the data so that questions have verifiable answers (`seed.generate.PLANTED`):

| Organisation | What | When |
|---|---|---|
| Northwind Supply | Supplier Calder Metals raises unit cost 18%; hits the West region hardest because of its product mix | from 2026-07-01 |
| Northwind Supply | SMB discount rate rises from 4% to 11% | 2026-Q2 only |
| Harbor Trade | 14 customers in the North region pay 45 or more days late | from 2026-04-01 |

## Indexes worth knowing

| Index | Serves |
|---|---|
| `runs_claim_idx` (partial, queued or running) | The worker's claim query |
| `runs_org_created_idx`, `runs_org_active_idx` | Run lists, queue-limit check, daily spend |
| `steps (run_id, idx)` unique | Loading a run's steps in order; prevents duplicate steps |
| `orders_org_date_idx`, `order_items_order_idx` | Period aggregates |
| `approvals_org_status_idx` | Pending approvals |

`python -m load.explain` checks the plans of the request-path queries and fails if one scans a large table.
