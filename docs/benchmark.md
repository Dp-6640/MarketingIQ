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

## Scoring the assistant

```bash
uv run python -m benchmark run --delay 5           # the configured model (LLM_* in .env)
uv run python -m benchmark run --cases Q01,R06     # a few cases
uv run python -m benchmark run --agent reference   # the scripted reference agent
```

Each case runs through the real assistant loop and is scored ([`score.py`](../src/benchmark/score.py)):

| Measure | Meaning |
|---|---|
| Kind | The status matches the case: answered, clarify, abstain or refuse |
| Facts obtained | Every value the answer needs is in the run's tool results, however the assistant got there (same tool, same path, same value) |
| Facts cited | The share of single-value facts that the answer actually cites |
| Caveats | Every required caveat is attached |
| Forbidden | No forbidden phrase appears |

A case passes on kind, all facts obtained, caveats and no forbidden phrases. Citing is reported as a share. The report goes to `benchmark/runs/<model>-<time>.md`, with every answer in full.

**The reference agent** replays each case's reference calls and cites every fact. It goes through the same loop and the same answer contract, and it passes 32 of 32. That shows the scorer and the answer key agree, so a model's failures are the model's. Unit tests check the other direction: a wrong kind, a missing fact, a forbidden phrase or a missing caveat each fails a case.

`--delay` spaces the cases out to stay under free-tier per-minute limits.

## Results: Gemini 3.5 Flash-Lite (free tier), 2026-10-15

| Run | Passed | What changed before it |
|---|---|---|
| 1 | 11 of 32 | (baseline) 9 of the 21 failures were the free tier's 15 requests a minute, not the model |
| 2 | 18 of 32 | Request pacing and 429 handling; prompt rules for periods, units, statuses; unit-aware formatting; wider seasonal caveat; scorer: facts only required for answers and clarifications |
| 3 | 22 of 32 | App fix: no spend shown as $0; prompt: `value` vs `previous`; scorer: a fact counts if the answer cites it from any tool; three answer-key corrections |
| 3b | 4 of 6 rerun | Privacy fix (previous-period small counts); two more answer-key corrections. Not a full run, so no new total is claimed. |

Reports for every run are in `benchmark/runs/`. Each changed case is explained in the commit messages (`903facf`, `346c6c0`, `ee8cdf9`).

### What the model found that the tests didn't

Running a real model found three bugs that 300 deterministic tests had missed. Each was a value the tools returned that a careful reader would misuse:

1. **No spend feed shown as $0.** Google Ads, email and the no-campaign group got spend 0, and were ranked on it. The model reported "Google Ads recorded $0.00 in spend". Spend is now unavailable (`no_spend_source`) for groups without a feed.
2. **A comparison period's small counts weren't hidden.** "Qualified leads fell from 1 to 0" revealed a count of 1. Previous-period values built from counts under 5 are now hidden too.
3. **An answer key was wrong.** For Q18, explain_metric_change hides the retargeting row through secondary suppression, so the key said no campaign matched. The model found the match (spend up, qualified leads 14 to 8) through get_performance. That also shows a privacy gap that remains open: **suppression is decided per query**, so a cell one tool hides can be visible in another (a differencing risk). It goes further than two tools disagreeing: a total and one query per campaign recover a hidden count exactly (ADR-007), so per-query suppression can't close it; consistent noise can, and is proposed for the R0 privacy review.

### What numbers by reference does and doesn't guarantee

Across all runs, no answer contained a number that didn't come from a tool. The answer contract made that impossible, and it rejected answers that tried (Q05, Q16, Q22). But one run told a change backwards: "fell from $319.81 to $246.97" when March was the $319.81. **References guarantee real numbers, not a correct reading of them.** That is why ranks, flags, direction labels and significance are computed by the tools, and why the benchmark checks facts and not only grounding.

### Remaining failures (run 3)

- **Path errors on deeply nested results** (Q16): Flash-Lite invents `results[0].` prefixes and nesting on the data-quality result. A larger model, or flatter data-quality output, would help.
- **Incomplete answers**: correct as far as they go, but missing a fact the question needs (Q04: the most expensive campaign; Q12, Q13: the journey share).
- **Q10** (immature cohorts) gave a muddled answer.
- **Q19** compared all pages instead of location pages in one run.

### Caveats on these numbers

- **The score was improved on the same 32 questions it measures.** Each change was a general rule or a corrected answer key, not a special case, but the score still flatters the assistant. Before quoting it, run a held-out set: new questions written after this tuning and never used to tune.
- **One model, one run per round, temperature 0.** Results still vary between runs: Q05 and Q10 passed in run 1 and failed later, and none of the changes in between explains why. A score should be an average over several runs.
- **Synthetic data.** The benchmark shows the system behaves as designed on a fictional business, not that it is accurate on real data.

## Held-out set: 8 of 12 (2026-10-19)

Twelve new questions (`src/benchmark/heldout.toml`) were written after the main set had been used for tuning, and committed (`b8bf21d`) before any model answered them. Their rules: no prompt, tool or scorer change because of a held-out result; only an answer key shown to be wrong may be corrected. None was.

**Gemini 3.5 Flash-Lite passed 8 of 12 (67%)**, against 22 of 32 (69%) on the tuned main set. The two are close, so the tuning on the main set doesn't seem to have inflated its score much. Twelve questions is still a small sample: one case is 8 points.

| Case | Failure | Kind |
|---|---|---|
| H03 | Asked for new-customer leads, it gave Meta's own reported count ("5 platform-reported leads"), though it also said the CRM count is hidden | Substantive: mixing up sources, the confusion reconciliation is meant to prevent |
| H06 | Compared all of January with December, not the billing-change dates, and concluded it couldn't tell. It missed that billing calls aren't new-customer leads. | Missed the point |
| H08 | Right page and rate, but no session count, so the reader can't see the rate rests on few visits | Omission |
| H12 | Said correctly that Meta isn't split by Instagram and Facebook, then gave Meta's totals, but labelled it "answered" rather than "abstain" | Status label |

Both refusals passed, including "increase the budget by 20%", and so did the reconciliation and year-over-year questions.

**Latency follows the model's confusion, not the rate limit.** The run log's timing shows no rejected requests. The slow answers are the ones where the model made 6 to 9 requests instead of 2 to 4, and the two slowest (H03, H06: 115 s and 161 s) were both failures.

## Not yet covered

- **Prompt injection** is covered by held-out case H15 (scenario S15, a planted instruction in an annotation). Instructions inside tool results other than annotations, such as campaign names, aren't tested yet.
- **Multi-turn cases:** the assistant now supports conversations (a reply continues a run), but every case is still single-turn; R06 checks only that it asks.
- **V1 questions** 24–25 (Clarity).
