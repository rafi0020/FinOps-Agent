# Security

What is defended, how, and what is not. Controls are listed with the test that exercises them.

## Position on prompt injection

Prompt injection is treated as unsolved. The instructions do tell the model that query results are data and
not commands, and in the attack suite both models ignored instructions planted in the data
(`EVALUATION.md`). Nothing depends on that. The design question is: *if the model were fully controlled by
an attacker, what could it do?*

| It could | It could not |
|---|---|
| Read anything in schema `analytics` for the organisation of the person who asked | Read another organisation's rows, the `users` or `sessions` tables, or any system table |
| Spend that run's budget | Exceed the per-run or per-day limits |
| Write a misleading report | Put a figure in the report that is not in the stored evidence |
| Propose an alert rule | Create one: an administrator must approve it |
| | Modify or delete any data; call a tool its user's role does not have; add a tool; reach the network |

So the worst outcome of a successful injection is a wrong or misleading report about data the user was
already allowed to see, and a wasted budget. That boundary is enforced by PostgreSQL and the runtime, not
by the model.

## Controls, mapped to the OWASP Top 10 for LLM Applications (2025)

| Risk | Control | Proven by |
|---|---|---|
| **LLM01 Prompt injection** | Privilege separation as above. Query results are delivered under an `untrusted_data` key. Text from data can never widen the tool list, change the role or approve an action. | `eval/attacks.py` (2 cases); `tests/test_finance_tools.py::test_database_content_is_delivered_as_untrusted_data` |
| **LLM02 Sensitive information disclosure** | The agent's database role has no access to identity tables. Secrets are masked before anything is stored, logged, traced or sent to a browser (`security/redact.py`). Provider keys are encrypted at rest and write-only in the API. Spans carry no prompt, completion or tool arguments. | `tests/test_sqlexec.py`; `tests/test_runtime.py::test_secrets_are_masked_in_stored_steps_and_events`; `tests/test_llm_settings.py`; `tests/test_tracing.py` |
| **LLM03 Supply chain** | Dependencies pinned by lock files (`uv.lock`, `package-lock.json`). Containers run as a non-root user. | not tested |
| **LLM04 Data and model poisoning** | No training or fine-tuning; no retrieval corpus that users can write to. | not applicable |
| **LLM05 Improper output handling** | Model-written SQL is parsed and re-generated, then run only as a read-only role. Model text is rendered by React as text, never as HTML. Tool arguments are validated against a schema before use. | `tests/test_sqlguard.py` (36 refusals); `tests/test_runtime.py` |
| **LLM06 Excessive agency** | Tools are few and narrow. Each has a level; `needs_approval` tools do not run until an administrator approves, checked on the server. Tools are filtered by the asking user's role before the model sees them. | `tests/test_approvals_api.py`; `tests/test_runtime.py::test_a_tool_the_role_may_not_use_does_not_exist_for_it` |
| **LLM07 System prompt leakage** | The system prompt contains no secret, credential or tenant data, so leaking it reveals nothing that this repository does not. The model is asked to decline. | `eval/attacks.py` (prompt_leak) |
| **LLM08 Vector and embedding weaknesses** | No vector store is used. | not applicable |
| **LLM09 Misinformation** | The model does no arithmetic. Every figure in a report is matched against stored evidence; unsupported statements are removed and shown as removed. | `tests/test_grounding.py`; `tests/test_finance_tools.py::test_invented_figures_get_one_chance_to_be_fixed_then_are_removed` |
| **LLM10 Unbounded consumption** | Per-run limits on model steps, tokens, time and cost; per-organisation daily cost limit; queue limit and per-user rate limit on new runs; 10 s query timeout and 5,000-row cap; a cap on concurrent model calls per process. | `tests/test_budgets.py`; `tests/test_runs_api.py`; `tests/test_sqlexec.py` |

## The SQL boundary

A model-written query is run by `backend/app/finance/sqlexec.py` as role `finops_ro`:

1. `SELECT` on schema `analytics` only; no privilege on schema `public`.
2. Read-only transactions, set on the role.
3. Row-level security through the views, so only the asker's organisation is visible.
4. The role cannot switch organisation: `EXECUTE` on `set_config` is revoked from it, and the query is sent
   with a bound parameter, which makes PostgreSQL reject a second statement such as a trailing `SET`.
5. Statement timeout and a row cap.

6. No access to `pg_stat_activity` and similar views. All organisations' agent queries run as this one role,
   and a role can otherwise read the query text of its own other sessions.

`tests/test_sqlexec.py` bypasses the parser deliberately and attacks these directly. The parser
(`sqlguard.py`) sits in front and refuses anything that is not a single `SELECT` over catalogue tables with
allowed functions, mainly so the model gets a precise error.

## Tenancy

Row-level security is enabled and forced on every table holding an organisation's data; the organisation is
set per transaction. Objects of another organisation return 404, not 403, so their existence is not
revealed. `tests/test_tenant_isolation.py`, `tests/test_roles.py`, `frontend/e2e/isolation.spec.ts`.

## Accounts and sessions

| Concern | Decision |
|---|---|
| Passwords | scrypt with a per-user salt; minimum 10 characters with a letter and a digit; an unknown e-mail costs the same hashing time as a wrong password and returns the same message |
| Sessions | Random 256-bit token in an HttpOnly, SameSite=Lax cookie (`Secure` when `COOKIE_SECURE=true`); only its SHA-256 is stored; revoked at once on sign-out, deactivation and password change |
| CSRF | State-changing requests must carry `X-CSRF-Token`, which a cross-site page cannot read |
| Brute force | 5 sign-in attempts per e-mail per minute and 30 per address; 10 sign-ups per address per hour |
| Roles | viewer, analyst, admin, checked by a dependency on every route; an organisation always keeps one active administrator |
| Audit | Sign-ins, user changes, runs, approvals, settings and alert changes are recorded with user and address; the application role cannot update or delete the log |
| Headers | `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, a Content-Security-Policy, and HSTS when cookies are secure |
| Server-side request forgery | The model base URL an administrator sets is checked when saved and again on every connection: http or https only; link-local, multicast, carrier-grade NAT (100.64/10) and other reserved addresses always refused; private networks refused when `ALLOW_PRIVATE_LLM_URLS=false`. The connection is made to the address that was checked, so DNS rebinding does not redirect it |

## Known limitations

- **The default `SECRET_KEY` in `docker-compose.yml` is public.** It exists so the demo starts with one
  command. Any real deployment must set its own, or stored provider keys are encrypted with a known secret.
- **Demo accounts with published passwords** are created when `SEED_DEMO=true`. Set it to false outside a demo.
- **The CSP for the static UI allows inline scripts and styles**, which the framework's static export needs.
  It still restricts sources to the same origin.
- **The API port (8110 by default, `API_PORT`) is published on 127.0.0.1 only**, for `/docs` and `/metrics` on
  the machine running it. The web port is published on 127.0.0.1 unless `WEB_BIND` says otherwise; it is plain HTTP. The API trusts `X-Forwarded-For` because it sits behind nginx, so it must never be published to a
  network directly: a client reaching it could spoof its address for rate limiting.
- **`/metrics` is open unless `METRICS_TOKEN` is set** (reachable from the host only, with the default ports).
- **Open sign-up shares the server's model key.** With `ALLOW_SIGNUP=true`, each new organisation gets its own
  daily budget on the key in `.env`. `GLOBAL_DAILY_COST_USD` caps the total; set `ALLOW_SIGNUP=false` if
  strangers can reach the installation.
- **Model calls do not use `HTTP_PROXY` / `HTTPS_PROXY`.** The connection must be made to the address that was
  checked, which a proxy would hide. A deployment that reaches providers only through an egress proxy needs a
  network route that does not depend on those variables.
- **Model base URLs on private networks are allowed by default** (`ALLOW_PRIVATE_LLM_URLS=true`), because a
  local gateway or Ollama needs it. On a shared installation set it to false.
- **Some database hardening needs a superuser**, so the migration owner cannot apply it: revoking `set_config`
  and the statistics views from the agent's role, and the role's read-only and timeout defaults. It is in
  `infra/postgres/hardening.sql`, which `init.sh` applies. Any other database must have that file run as a
  superuser before the first migration; migration `0009_hardening_check` verifies it and refuses to run otherwise.
- **No multi-factor authentication, single sign-on, password reset by e-mail, or account lockout** beyond
  rate limiting.
- **Injection resistance was measured on eight cases and two models.** It is evidence, not proof.
- **No independent penetration test** has been done.
- **Evidence is retained indefinitely**; there is no retention or deletion policy for runs.
