# The Assistant

The assistant answers a marketing question by choosing tools, reading their results and writing an answer. It never computes a number: every number in an answer is filled in by the backend from a tool result (ADR-006).

```bash
uv run python -m marketingiq.assistant "Which campaigns brought in the most qualified leads last month?" --trace
```

Or `POST /api/v1/assistant/ask` with `{"question": "..."}`.

## Setup: a free model

The assistant talks to any OpenAI-compatible endpoint. The default is **Google Gemini's free tier** (`gemini-3.5-flash-lite`):

1. Create a key at [Google AI Studio](https://aistudio.google.com/apikey). It's free and needs no card.
2. Add `LLM_API_KEY=<your key>` to `.env`.

Other providers are a configuration change (`LLM_BASE_URL`, `LLM_MODEL`; see `.env.example`): Groq, OpenRouter, or a local Ollama, which needs no key. This laptop has no GPU, so a local model works but answers slowly.

**Free tiers may use prompts to improve the provider's products.** That is acceptable here only because every number describes a fictional business. No company data may ever go to a free tier (U-14).

## How a run works

1. The model gets a system prompt ([`prompt.py`](../src/marketingiq/assistant/prompt.py)), the question, and nine tools: the eight read-only analytics tools plus `submit_answer`. The prompt sets the rules: resolve names first, never type numbers, the four statuses, no causal language, never add sources together.
2. Each tool call is validated by the tool's input model and run under the read-only database role. A successful result is numbered (`c1`, `c2`...) and returned to the model. Invalid arguments go back to the model with the validation errors, so it can correct them.
3. The model ends with `submit_answer`: a status (`answered`, `clarify`, `abstain`, `refuse`) and an answer template.
4. The backend renders the template ([`answer.py`](../src/marketingiq/assistant/answer.py)) and attaches the caveats from the tools' warnings.
5. The run is stored in `app.assistant_runs`: question, status, answer, every call with its arguments and timing, every resolved reference, the caveats, tokens and latency.

The loop stops after 10 model steps.

## Numbers by reference

The model writes references, and the backend fills in the values:

```text
Template:  Cost per lead was {{c1:rows[key=meta_lead_form_furnace_promo].values.cost_per_lead}}
           ({{c1:rows[key=meta_lead_form_furnace_promo].values.cost_per_lead.change_pct}}).
Answer:    Cost per lead was $31.20 (+24.8%).
```

- A reference points at one value in a result, using the [path language](../src/marketingiq/assistant/paths.py). The value is formatted from the metric it names: currency, percentage, signed change or count.
- A hidden value renders as "hidden (fewer than 5)" and a null one as "not available (reason)", never as 0.
- **A number the model typed is rejected.** Dates, years and lookback windows ("30-day") are the only exceptions. A rejected answer goes back to the model with the reasons, and it gets one more try. If that fails too, the run fails, and no answer is better than an invented one.
- A reference to a call that doesn't exist, or to a group of values instead of one, is rejected the same way.

So an answer can't contain a value that didn't come from a tool, and every number in it is traceable through the run log to the call and path that produced it.

## Provider-portable tool schemas

Pydantic's JSON Schema uses features some providers reject (`$ref`, `anyOf`, `additionalProperties`). [`schemas.py`](../src/marketingiq/assistant/schemas.py) inlines and reduces each schema to the portable core. Defaults are stated in descriptions instead. The full input models still validate every call, so nothing is lost in safety. The nine tool definitions come to about 3,800 tokens.

## Tests

Tests use `ScriptedModel`, which plays back fixed replies, so they need no network or key. They cover the answer contract, schema portability, the retry and failure paths, invalid arguments, clarification, the run log, the app role's lack of write access, and the API. Judging a real model's answers is the benchmark's job (`docs/benchmark.md`).
