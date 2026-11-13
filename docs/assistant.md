# The Assistant

The assistant answers a marketing question by choosing tools, reading their results and writing an answer. It never computes a number: every number in an answer is filled in by the backend from a tool result (ADR-006).

```bash
uv run python -m marketingiq.assistant "Which campaigns brought in the most qualified leads last month?" --trace
```

Or `POST /api/v1/assistant/ask` with `{"question": "..."}`.

## The demo page

`uv run uvicorn marketingiq.api.app:app`, then open `http://127.0.0.1:8000/`.

A full-screen dashboard:

- **Headline tiles** for the last complete month (leads, qualified leads, qualification rate, spend, cost per lead, attribution coverage), each with its change from the month before and a 12-month sparkline. They come from `GET /api/v1/dashboard`, which calls the performance service directly. No model is involved, so the tiles work even when the model's quota is used up. "Show as table" gives every value.
- **Recent questions** (left): searchable, and each one reopens its whole conversation.
- **The conversation** (centre): the question, the answer with every number highlighted, the caveats, and replies that continue the conversation. When the assistant asks a clarifying question, the box is ready for the reply.
- **The inspector** (right): **Evidence** (click a highlighted number to jump to the tool call and path it came from), **Tool calls** (each call's arguments and result status) and **Timing** (model, tools and waiting on the provider).
- **A link to any answer**: the address ends in `#run=<id>`, so an answer can be bookmarked or opened directly.
- Light and dark themes, keyboard shortcuts (`/` focuses the question, Enter asks, Shift+Enter adds a line), side panels that become drawers on narrower screens, and respect for the system's reduce-motion and reduce-transparency settings.

The look mixes three materials: a slowly moving colour background, frosted-glass panels with a light-catching "liquid glass" rim, and soft neumorphic tiles and controls. The chart colours were validated for colour-blind readers and contrast in both themes.

The page is plain HTML and JavaScript ([`static/index.html`](../src/marketingiq/api/static/index.html)) with no build step. Model and data text is always inserted as text, never as HTML.

## Setup: a free model

The assistant talks to any OpenAI-compatible endpoint. The default is **Google Gemini's free tier** (`gemini-3.5-flash-lite`):

1. Create a key at [Google AI Studio](https://aistudio.google.com/apikey). It's free and needs no card.
2. Add `LLM_API_KEY=<your key>` to `.env`.

Other providers are a configuration change (`LLM_BASE_URL`, `LLM_MODEL`; see `.env.example`): Groq, OpenRouter, or a local Ollama, which needs no key. This laptop has no GPU, so a local model works but answers slowly.

**Free tiers may use prompts to improve the provider's products.** That is acceptable here only because every number describes a fictional business. No company data may ever go to a free tier (U-14).

## Conversations

A question can continue an earlier run: send `{"question": "...", "follows": "<run id>"}`. The model then sees up to four earlier question-and-answer turns, so a short reply ("the promo one") answers its clarifying question. Earlier answers are context only: a number in the new answer still has to come from this run's own tool calls. The demo page continues the conversation automatically after a clarifying question, and offers a checkbox otherwise.

## The run log, and where the time goes

`GET /api/v1/assistant/runs` lists recent questions and `GET /api/v1/assistant/runs/{id}` reopens one in the same shape as a fresh answer. The demo page lists them, so earlier answers open instantly.

Every run records model time, tool time and time spent waiting on the provider (pacing to 14 requests a minute, rate-limit sleeps). The page, the terminal command and the log show it. On Gemini's free tier, tools take well under a second. A simple answer takes 10 to 30 seconds, mostly the model. A long one usually means the model took many steps, and that is often a sign of a weak answer.

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
