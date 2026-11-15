# API reference

Generated from the application's OpenAPI schema (`python -m scripts.api_docs`). The interactive version, with
request and response schemas, is served at `/docs` on the API (http://localhost:8110/docs).

All routes under `/api` except sign-up and sign-in need the session cookie. State-changing requests also need
the `X-CSRF-Token` header, whose value is returned by sign-in and by `GET /api/auth/me`. Errors are
`{"detail": "..."}` with a conventional status: 401 not signed in, 403 role or CSRF, 404 not found (also
returned for another organisation's objects), 409 conflicting state, 422 invalid input, 429 limit reached
(with `Retry-After`).

## Auth

| Method | Path | What it does |
|---|---|---|
| POST | `/api/auth/login` | Login |
| POST | `/api/auth/logout` | Logout |
| GET | `/api/auth/me` | Me |
| POST | `/api/auth/password` | Change Password |
| POST | `/api/auth/signup` | Create a new organisation; the person signing up becomes its first administrator. |

## Users

| Method | Path | What it does |
|---|---|---|
| GET | `/api/users` | List Users |
| POST | `/api/users` | Create User |
| PATCH | `/api/users/{user_id}` | Update User |

## Runs

| Method | Path | What it does |
|---|---|---|
| GET | `/api/runs` | List Runs |
| POST | `/api/runs` | Ask |
| GET | `/api/runs/{run_id}` | Get Run |
| POST | `/api/runs/{run_id}/answer` | Reply to the agent's clarifying question; the run goes back to the queue and continues. |
| POST | `/api/runs/{run_id}/cancel` | Cancel |
| GET | `/api/runs/{run_id}/events` | Run Events |
| GET | `/api/runs/{run_id}/evidence/{handle}` | Get Evidence |

## Approvals

| Method | Path | What it does |
|---|---|---|
| GET | `/api/approvals` | List Approvals |
| POST | `/api/approvals/{approval_id}/decide` | Decide |

## Investigations

| Method | Path | What it does |
|---|---|---|
| GET | `/api/investigations` | List Investigations |
| POST | `/api/investigations` | Save |
| DELETE | `/api/investigations/{investigation_id}` | Delete |
| PATCH | `/api/investigations/{investigation_id}` | Patch |
| POST | `/api/investigations/{investigation_id}/rerun` | Ask the same question again, as a new run against today's data. |

## Alerts

| Method | Path | What it does |
|---|---|---|
| POST | `/api/alerts/evaluate` | Check the rules now instead of waiting for the schedule. |
| GET | `/api/alerts/events` | List Events |
| POST | `/api/alerts/events/{event_id}/ack` | Acknowledge |
| GET | `/api/alerts/rules` | List Rules |
| PATCH | `/api/alerts/rules/{rule_id}` | Patch Rule |

## Overview

| Method | Path | What it does |
|---|---|---|
| GET | `/api/overview` | Get Overview |

## Catalog

| Method | Path | What it does |
|---|---|---|
| GET | `/api/catalog` | Get Catalog |

## Usage

| Method | Path | What it does |
|---|---|---|
| GET | `/api/usage` | Usage |

## Settings

| Method | Path | What it does |
|---|---|---|
| GET | `/api/settings/llm` | Get Llm |
| PUT | `/api/settings/llm` | Put Llm |
| POST | `/api/settings/llm/test` | Send one tiny request with the saved settings and report whether it worked. |

## Audit

| Method | Path | What it does |
|---|---|---|
| GET | `/api/audit` | List Audit |

## Evaluation

| Method | Path | What it does |
|---|---|---|
| GET | `/api/eval/results` | Results |

## Health

| Method | Path | What it does |
|---|---|---|
| GET | `/healthz` | Healthz |
| GET | `/readyz` | Readyz |

## Live events

`GET /api/runs/{run_id}/events` is a Server-Sent Events stream. Each event has an `id`; send it back as
`Last-Event-ID` to resume. Event types: `run.status`, `step.started`, `step.finished`, `approval.requested`,
`question.asked`, `report.ready`. The stream closes after a `run.status` event with a final status.
