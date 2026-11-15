# AI assistance disclosure

FinOps Agent was built with AI coding assistance. This document states what was generated, what was decided by
the maintainer, and how the result was verified. It also describes the AI that runs inside the product.

## Tools

| Tool | Use |
|---|---|
| Claude (Anthropic), via Claude Code | Code generation, refactoring, tests, evaluation scripts, documentation, debugging, running the Docker stack and the evaluations |
| Playwright | Browser journeys in `frontend/e2e`; the README screenshots in `docs/screenshots` |
| Archify | Generation and validation of the architecture diagram in `docs/architecture.html` |
| Hallmark (design skill) | Design rules for the web interface |
| An LLM (optional, runtime) | The agent's reasoning and tool choice when a model is configured; see [PROMPTS.md](PROMPTS.md) |

## Division of responsibility

The architecture decisions are recorded in [ARCHITECTURE.md](ARCHITECTURE.md#design-decisions). The assistant
implemented the project under that direction. The decisions recorded in the project documents include:

- A hand-written agent loop instead of an agent framework, with the run's steps stored in PostgreSQL.
- PostgreSQL row-level security for tenancy, and a read-only database role as the boundary for model-written SQL.
- Deterministic calculations for every derived figure, with the report's figures checked against stored evidence.
- A static web interface served by nginx, with no Node server in production.
- A built-in script that runs the agent without any model, so the product works without a key, with the optional
  model added through configuration.

## Verification

- **Backend tests** (`backend/tests`, run by `make test`): 356 passed and 5 skipped on the run recorded in
  [`docs/test-results`](test-results). The skipped tests are the live tests that call a real model
  (`make test-live`). They cover the agent runtime, budgets, tool validation, SQL guard and execution, tenant
  isolation, approvals, alerts, authentication, sessions, the API and the worker crash and lease recovery.
- **Lint and types:** `make lint` (ruff) and `npx tsc --noEmit && npx eslint src` for the frontend.
- **Browser journeys:** 16 Playwright journeys in `frontend/e2e` against the running stack, covering sign-in,
  roles, the question trail, evidence, saved investigations, approvals and cross-organisation isolation.
- **Evaluation:** 60 questions over the seeded data, 40 development and 20 held out, reference answers computed from
  SQL, and a set of eight hostile requests. Results, method and failures are in [EVALUATION.md](EVALUATION.md) and
  the raw output in [`backend/eval/results`](../backend/eval/results). Two hosted models were evaluated; no local
  model was.
- **Load:** measured on one laptop with the load generator on the same machine; see [SCALE.md](SCALE.md).

## Data

No AI-generated data is presented as real. The demo data is produced by a deterministic generator in this
repository (`backend/seed`), with planted causes that the evaluation checks against. The evaluation reference
answers are computed from that data by `backend/eval/build_questions.py`.

## Runtime use of AI

With `LLM_PROVIDER=stub`, the default, no model is called and the agent runs a fixed script. When a provider is
configured, the question, the agent's instructions and the results of its queries are sent to that provider. For
sensitive data use a local model through Ollama, or keep the stub. Database content in tool results is marked as
data, and every figure in a report must be traceable to a query in the same run; figures that are not are removed
from the report and shown as removed. The prompts and the checks are described in [PROMPTS.md](PROMPTS.md).

## Limitations

- The account and security controls were covered by automated tests and maintainer review, not an independent
  security audit. See [SECURITY.md](SECURITY.md).
- The evaluation is small: 20 held-out questions, one run per model, so one question is five percentage points.
  Differences of one or two questions are within noise.
- The grounding check proves that a figure exists in the evidence, not that the sentence around it is right.
- The model's output is not streamed, and the attack suite covers eight cases. Holding those cases does not prove
  that an injection cannot succeed with other wording or another model; the design assumes one eventually will.
