# How the agent works: a guided read

This is a reading order for the code, for someone who wants to understand how an agentic system is built
rather than just run one. Each section names the file and function to open, what to notice there, and the
test that proves the behaviour. Read them in order; it takes about an hour.

Nothing in this repository uses an agent framework. The loop, the tool registry, the durable state and the
recovery logic are about 900 lines in `backend/app/agent/` and `backend/app/worker/`, written to be read.

## 1. What makes something an agent

A pipeline runs fixed steps. An agent is given a goal and a set of tools, and the model decides, step by step,
which tool to call next based on what the previous one returned. That one difference is where every hard
problem in this codebase comes from:

- the model can loop forever, so there are **budgets**;
- the model can ask for something harmful, so tools are **validated, permissioned and sometimes approved**;
- a run takes minutes and many steps, so its state must be **durable** and it must **resume** after a crash;
- the model can state things it never retrieved, so the output is **checked against evidence**.

Keep those four in mind; each later section is one of them.

## 2. The loop

Open `backend/app/agent/runtime.py` and read `advance()` and `next_action()`.

```
load the run and its steps from the database
decide the next action from the steps alone:
    a tool call is unfinished (waiting for approval, an answer, or left by a crash)  -> resolve it
    the last model message asked for a tool that has not been started               -> start it
    otherwise                                                                       -> ask the model
do exactly one action, commit it, publish an event, repeat
```

Notice what is *not* there: no variable holding the conversation, no in-memory list of pending tool calls.
`next_action()` takes the stored steps and nothing else. That is the property everything else depends on: if
the process stops at any line, calling `advance()` again continues correctly.

Test to read: `tests/test_runtime.py::test_happy_path_runs_tools_in_order_and_completes`.

## 3. The conversation is rebuilt, not remembered

Open `backend/app/agent/context.py`, `build_messages()`.

Every time the model is called, the message list is derived from the `steps` table: the system prompt, the
question, then each model turn and each tool result in order. Two details matter:

- A tool result larger than 4,000 characters is not replayed. The model sees a one-line summary and a
  **handle** (`ev_7f3a91c2d4b65e10`) it can pass to other tools. This is how context stays small on a long run.
- The system prompt is identical for every run and every organisation (`backend/app/finance/prompts.py`).
  Anything that varies, such as the company's name, goes in the first user message instead
  (`backend/app/finance/agent.py`, `company_context`). Providers cache a stable prefix, so only the first
  step of a run pays full price for the instructions. The Anthropic adapter marks the prefix explicitly
  (`backend/app/llm/anthropic.py`, `cache_control`).

Test: `tests/test_runtime.py::test_conversation_is_rebuilt_identically_from_the_database`.

## 4. Tools

Open `backend/app/agent/tools.py`, then `backend/app/finance/tools.py`.

A tool is an async function taking a Pydantic model. The registry turns that model into the JSON schema the
LLM is shown, so the description the model reads and the validation the runtime applies come from the same
source and cannot drift apart. Each tool declares:

| Attribute | Meaning |
|---|---|
| `level` | `read`, `write`, or `needs_approval` |
| `roles` | which user roles may use it; other roles are never even shown it |
| `timeout_s` | how long it may run |
| `idempotent` | whether it is safe to run again after a crash |

What happens when the model gets it wrong is in `_validate()` and `_start_tool()` in `runtime.py`: an unknown
tool name or bad arguments become a tool *error message returned to the model*, so it can correct itself.
Two such mistakes in a row end the run.

Design rule used throughout: **tool errors are written for the model to act on.** Compare the SQL guard's
messages in `backend/app/finance/sqlguard.py` ("Table 'users' is not available. Use list_tables to see…")
with a bare "permission denied".

Tests: `tests/test_runtime.py::test_unknown_tool_and_bad_arguments_are_told_to_the_model`,
`::test_a_tool_the_role_may_not_use_does_not_exist_for_it`.

## 5. Durability: every step is a committed row

Still in `runtime.py`: `_model_step()`, `_start_tool()`, `_execute()`, `_record_outcome()`.

A tool call is recorded in two writes:

1. **Intent.** A `steps` row is inserted with state `started` *before* the tool runs.
2. **Outcome.** After the tool returns, the row is updated with its output and state `done`.

If the worker dies between the two, the next worker finds a `started` row with no outcome
(`_resolve()`). What it does depends on the tool: a `read` tool is simply run again; a tool with effects
outside the database is **not** repeated, and the model is told it was interrupted and may or may not have
taken effect.

For effects *inside* the database there is a cleaner answer. A tool returns its writes as a `commit` hook
(`ToolResult.commit`), and `_record_outcome()` applies that hook in the **same transaction** that marks the
step done. Either both happen or neither does, so the effect is exactly-once without any extra machinery.
`run_sql` saves its evidence this way; `propose_alert` creates its rule this way.

The `(run_id, idx)` unique constraint on `steps` is the last line of defence: if two workers ever advance the
same run, the second one's insert fails and it lets go (`RunConflict`). This actually happened while building
the evaluation harness, and the constraint did its job.

Test: `tests/test_worker_crash.py`. It starts a real worker process, kills it with `SIGKILL` in the middle of a
tool call, starts another, and checks the run completes with no duplicated or missing step.

## 6. The queue is a table

Open `backend/app/worker/run.py`: the `CLAIM` query, `claim_next()`, `heartbeat()`, `run_one()`, `serve()`.

There is no separate job queue. A run is claimed by writing a worker id and a lease expiry onto its row:

```sql
... WHERE status = 'queued' OR (status = 'running' AND lease_expires_at <= now())
ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED
```

- The worker renews the lease every ten seconds while it works (`keep_lease`).
- If it dies, the lease runs out and the second half of that `WHERE` makes the run claimable again.
- A run that keeps killing its workers is abandoned after five attempts instead of looping.
- `SIGTERM` (a deploy) stops claiming and hands unfinished runs back immediately.

Why not Redis or a queue library, as DocIntel used? Because the run, its steps and the claim on it live in
one transactional store, "the step was recorded" and "the run is still mine" can never disagree. Durable
execution products (Temporal, DBOS) do the same thing underneath; here you can read it.

Tests: `tests/test_worker_claim.py`.

## 7. Human in the loop

Two ways a run stops to wait for a person, both in `runtime.py`:

- **Approval** (`_start_tool`, the `needs_approval` branch). The step is stored as `awaiting_approval`, an
  `approvals` row is created, the run is parked. `backend/app/api/approvals.py::decide` records an
  administrator's decision and puts the run back in the queue. `_resolve()` then either executes the tool or
  tells the model it was rejected and why. The decision is enforced on the server: the model cannot talk its
  way past it, because the tool is simply not executed until the row says `approved`.
- **A question** (`ToolResult(signal="wait_user")`). Same idea; `backend/app/api/runs.py::answer` writes the
  person's reply as the tool's output.

Parked runs hold no worker, no connection and no memory. They are rows.

Tests: `tests/test_approvals_api.py`, `tests/test_runs_api.py::test_answering_a_question_resumes_the_run`.

## 8. Budgets

Open `backend/app/agent/budgets.py`.

Before every model call the runtime checks the run's model steps, tokens, working time and cost, and the
organisation's spend for the day. Exceeding any of them ends the run with status `budget_exceeded` and keeps
the evidence gathered so far. Nothing in a prompt can be relied on to stop a model; this can.

Tests: `tests/test_budgets.py`.

## 9. The security boundary is the database

Read in this order:

1. `infra/postgres/init.sh` and `hardening.sql`: three roles. `finops_ro` can `SELECT` from schema `analytics` and
   nothing else, and has had the right to call `set_config` and read the statistics views removed.
2. `backend/app/rls.py` and `backend/alembic/versions/0002_finance.py`: row-level security on every tenant
   table, and the `analytics` views the agent reads.
3. `backend/app/finance/sqlexec.py::execute_readonly`: how a query is actually run.
4. `backend/app/finance/sqlguard.py`: the parser-based checks.

The order of importance is the reverse of what most text-to-SQL demos do. The parser (4) is a convenience
that gives the model a precise error. The guarantees come from the role and row-level security (1–3). To see
that this is true and not just claimed, read `tests/test_sqlexec.py`: those tests **skip the guard on
purpose** and hand the executor `DELETE`, a query on `public.users`, an attempt to switch organisation, and a
smuggled second statement. The database refuses each one.

Prompt injection is handled the same way. The system prompt does tell the model that query results are data,
not instructions, but nothing depends on the model obeying: text in a database row cannot add a tool, change
a role, or approve an action. See `docs/SECURITY.md`.

## 10. Grounding: checking the answer

Open `backend/app/finance/grounding.py`, then `finish()` in `backend/app/finance/tools.py`.

When the model submits its report, every number in the summary and findings is extracted and looked up in
the stored evidence (query results and calculation outputs), with tolerance for rounding and for "20.5%"
versus `0.2047`. A sentence containing a number with no source is refused once, with the list of offending
statements, so the model can fix it; if it submits again unfixed, those sentences are removed and shown to
the reader as unsupported.

This is also why the model is not allowed to do arithmetic. `backend/app/finance/compute.py` holds
deterministic calculations in `Decimal`; the model names an operation and the columns of a stored result.
A subtraction done "in its head" produces a number that is in no evidence, and the check catches it.

Read the module docstring for the honest limits of this check.

Tests: `tests/test_grounding.py`, `tests/test_finance_tools.py::test_invented_figures_get_one_chance_to_be_fixed_then_are_removed`.

## 11. Providers

Open `backend/app/llm/types.py`, `base.py`, then one adapter.

The runtime only knows `Message`, `ToolSpec`, `ToolCall` and `LLMResponse`. Each provider adapter translates
to and from its wire format. `call_with_retry()` in `base.py` holds the policy shared by all of them: retry
timeouts, 429 and 5xx with exponential back-off and jitter, honour `Retry-After`, never retry a 400 or 401,
then try a fallback model once. A semaphore caps concurrent model calls per process so a burst of runs
produces back-pressure instead of a burst of 429s.

One real-world detail worth seeing: `openai_compat.py::merge_stream`. Some gateways stream even when asked
not to, so the adapter parses both shapes into the same response.

## 12. Live updates

`backend/app/agent/events.py` appends an event to a Redis stream after each committed step.
`backend/app/api/events.py` serves that stream to the browser as Server-Sent Events, and
`frontend/src/lib/sse.ts` consumes it. A stream is used rather than publish/subscribe so that a browser which
reconnects can send the id of the last event it saw and receive everything after it.

Redis is never the source of truth. If it were emptied, no run would be lost; open pages would refresh from
the database.

## 13. Evaluation

`backend/eval/build_questions.py` builds 60 questions whose reference answers are computed by SQL, never
typed. `run_eval.py` runs them through the real agent and scores them. `attacks.py` runs hostile requests and
checks the outcome in the database. Results, including failures, are in `docs/EVALUATION.md`.

The discipline that matters: the prompt was tuned on the development set only, and the held-out set was run
once at the end.

## Exercises

1. Add a tool `top_n` that returns the top N rows of a stored result by a column. You will touch
   `finance/tools.py` only. Write its test first, in the style of `tests/test_finance_tools.py`.
2. Make `ask_user` time out: a run waiting more than 24 hours is cancelled by a scheduled job. Look at
   `worker/scheduler.py` and `finance/alerts_eval.py::evaluate_all` for the pattern.
3. Kill the worker container during a live run (`docker compose kill worker`), start it again, and watch the
   trail in the browser continue from where it stopped.
4. Replace the hand-written loop with LangGraph in a branch, keeping the tests green. Note what the library
   gives you for free and what you can no longer see. (The VoiceOps system in this portfolio does exactly this.)
