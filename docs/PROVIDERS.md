# Model providers

The agent works with any model that supports tool calling. Choose a provider in one of two ways:

- **Environment** (`.env`): the default for every organisation.
- **Administration → Model** in the UI: per organisation, overrides the environment. The key is stored
  encrypted and never shown again. "Test the saved settings" sends one small request and reports the result.

When the stack runs in Docker, `localhost` inside a container is the container itself. To reach something on
your machine (Ollama, 9Router, LiteLLM) use `http://host.docker.internal:<port>`.

| Provider | `.env` | Tested here |
|---|---|---|
| **9Router** (local gateway) | `LLM_PROVIDER=openai_compat`<br>`LLM_BASE_URL=http://host.docker.internal:20128/v1`<br>`LLM_API_KEY=<9Router key>`<br>`LLM_MODEL=cc/claude-sonnet-5-5` | Yes: `cx/gpt-6-luna`, `cc/claude-sonnet-5-5`, `ag/gemini-3.8-flash` returned valid tool calls; the first two ran the full evaluation |
| **OpenAI** | `LLM_PROVIDER=openai_compat`<br>`LLM_BASE_URL=https://api.openai.com/v1`<br>`LLM_API_KEY=sk-...`<br>`LLM_MODEL=<model id>` | Protocol tested through 9Router; not called directly |
| **Anthropic** (native API) | `LLM_PROVIDER=anthropic`<br>`LLM_API_KEY=sk-ant-...`<br>`LLM_MODEL=claude-sonnet-5-5` | Adapter covered by unit tests against recorded response shapes; not called directly |
| **Google Gemini** (OpenAI-compatible endpoint) | `LLM_PROVIDER=openai_compat`<br>`LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai`<br>`LLM_API_KEY=<key>`<br>`LLM_MODEL=<model id>` | Through 9Router only |
| **Groq** | `LLM_PROVIDER=openai_compat`<br>`LLM_BASE_URL=https://api.groq.com/openai/v1`<br>`LLM_API_KEY=gsk_...`<br>`LLM_MODEL=<model id>` | Not tested |
| **Any OpenAI-compatible gateway** (LiteLLM, OpenRouter, vLLM, LM Studio) | `LLM_PROVIDER=openai_compat`<br>`LLM_BASE_URL=<its /v1 URL>`<br>`LLM_API_KEY=<key or empty>`<br>`LLM_MODEL=<model id>` | 9Router is one of these |
| **Ollama** (local) | `LLM_PROVIDER=ollama`<br>`LLM_BASE_URL=http://host.docker.internal:11434/v1`<br>`LLM_MODEL=<model with tool support>` | Not tested; see below |
| **No model** | `LLM_PROVIDER=stub` | Yes. A built-in script runs one fixed analysis so the application works end to end without any key. Its report says it is a script. |

Optional for all: `LLM_FALLBACK_MODEL` (tried once when the main model is unavailable after retries) and
`LLM_PRICE_INPUT_PER_MTOK` / `LLM_PRICE_OUTPUT_PER_MTOK`.

## Prices and budgets

Cost is estimated from the two price settings (USD per million tokens; cached input is counted at one tenth).
The defaults, 3 and 15, are placeholders. Set them to what your provider charges, in `.env` or per
organisation in the UI, or the per-run and per-day cost limits will be enforced against the wrong numbers.
Step, token and time limits do not depend on prices.

## Local models

The agent needs a model that calls tools reliably over 8 to 20 steps and writes correct SQL. Small local
models often fail at this: they call a tool once and then answer in prose, or produce invalid arguments.
The runtime handles both (one reminder, then a clear failure), but the run does not succeed.

Rough guidance for a laptop GPU:

| GPU memory | What to expect |
|---|---|
| 6 GB | 3–4 B-parameter models at 4-bit. Simple look-ups may work; multi-step root-cause questions usually do not. Suitable for seeing the system run, not for trusting its answers. |
| 12–16 GB | 7–14 B models with tool-calling support. Look-ups and comparisons are realistic. |
| 24 GB or more | 20–32 B models. Closer to hosted mid-tier models. |

Pick a model whose Ollama page lists tool support, and raise its context window: the instructions and tool
definitions alone are about 2,500 tokens, and a run can reach 20,000. Run the evaluation
(`python -m eval.run_eval --split dev --model <name>` with `EVAL_BASE_URL=http://localhost:11434/v1`) before
relying on one; the numbers in `EVALUATION.md` are for hosted models only.

Everything stays on your machine with Ollama: no question, query result or figure leaves it.

## Gateway quirk worth knowing

9Router streams the response unless `"stream": false` is sent explicitly. The adapter always sends it, and
also accepts a streamed body, so both behaviours work (`backend/app/llm/openai_compat.py::merge_stream`). The
Anthropic adapter accepts a streamed body too (`backend/app/llm/anthropic.py::merge_stream`).

Every call sends `temperature: 0`. A model that accepts only its default temperature will answer 400; use a
model that accepts 0.
