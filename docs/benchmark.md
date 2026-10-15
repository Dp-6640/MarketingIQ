# The Benchmark

The benchmark is how MarketingIQ's assistant will be judged before anyone relies on it. It's written now, before any LLM work, so the assistant can't shape its own test.

```bash
uv run python -m benchmark check     # needs the default dataset loaded and built
```

The command writes [`benchmark/reference-report.md`](../benchmark/reference-report.md): which cases pass, and the answer key (every fact each answer must cite, with its value).

## What a case is

Cases live in [`src/benchmark/cases.toml`](../src/benchmark/cases.toml). Each has:

| Field | Meaning |
|---|---|
| `question` | Worded the way a marketing manager would ask it |
| `kind` | The right kind of response: `answer`, `clarify` (ask which one), `abstain` (the data can't give a number) or `refuse` (out of scope by design) |
| `calls` | The reference tool calls. The assistant may reach the same results another way. |
| `warnings` | Caveat codes the answer must carry |
| `facts` | Paths into the results, the numbers and values the answer must cite (`1:rows{key=meta_prospecting_furnace}.values.cost_per_lead.value`) |
| `expect` | What the results must show for the planted scenario, such as which campaign is flagged |
| `forbidden` | Phrases the answer must not use: causal language about attribution, adding sources together |

There are 32 cases. 24 cover the 23 canonical questions in `question-tool-map.md`; question 4 has two cases, one of them for the Ottawa scenario. The other 8 test refusing (real-business questions, person-level data, transcripts, write actions), clarifying (an ambiguous campaign name), abstaining (no spend feed, an unknown campaign) and a causal question that attribution can't answer.

## What the reference run checks

For every case, against the default synthetic dataset:

1. Every reference call validates against its tool's input model and runs.
2. Every required caveat appears in the results.
3. Every scenario expectation holds.
4. Every fact the answer must cite exists. A fact that is hidden or empty is noted: the answer must say so.
5. Every number the oracle can compute matches it: performance and funnel cells, previous-period values, model-comparison credits and change-explanation parts. That's 663 numbers. Data quality, reconciliation and lookups are checked structurally.

The run proves the answer key is right and reachable with the tools. Phase 4 will score the assistant against it: tool choice and arguments, every number traced to a tool result, required caveats present, forbidden phrases absent, and the right kind of response.

## What writing the cases found

Writing an answer key means stating what's true, and four cases showed that the honest answer differed from what the scenario or the Phase 0 plan expected:

| Case | Finding | What changed |
|---|---|---|
| Q06 (S01) | The Phase 0 rule "cost per lead below the median and cost per qualified lead above it" never selected anything, including the planted promos. The two costs rise and fall together. | The rule compares the qualification rate instead (`question-tool-map.md`, revision note) |
| Q19 (S05) | The planted +20% form-submit rate on location pages can't be detected: about 420 sessions and 19 submissions a month, where chance alone moves the rate by about 23% | Rate changes now carry `change_significant` (a two-proportion test at 95%) and the `change_within_noise` warning, plus a `landing_page_type` dimension. The right answer is "no detectable change". |
| Q17/Q18 (S04) | The heat-pump prospecting campaign gets almost no lead credit in any month, so its planted drop in lead quality is invisible in attributed numbers. Its rising spend still makes it the biggest contributor to March's cost-per-qualified-lead increase. | Q18's right answer is that no visible campaign had spend up and qualified leads down |
| Q04 | Filtered to Meta campaigns, attribution coverage is high, so `low_attribution_coverage` correctly doesn't appear | The case expected it wrongly and was corrected |

The first three are lessons a real analysis would teach too: a rule should be tested on data before it's trusted, small samples can't show small effects, and prospecting work is invisible to last-touch attribution.

## Not yet covered

- **Prompt injection:** a campaign name containing an instruction, which the answer must treat as data. It needs a dataset with such a name; it comes with the Phase 4 harness.
- **Multi-turn clarification:** cases are single-turn; R06 checks only that the assistant asks.
- **V1 questions** 24–25 (Clarity).
