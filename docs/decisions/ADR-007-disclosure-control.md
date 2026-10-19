# ADR-007: Small-Cell Suppression Can't Stop Differencing; Use Consistent Noise for Real Data

- **Status:** Proposed, 2026-10-19. A decision for the R0 privacy review; nothing changes in the synthetic MVP until then.
- **Context:** Every lead count under 5 is hidden (k = 5), plus secondary suppression within a result so a hidden cell can't be worked out from the total (`docs/metrics.md`). That protects one result. It doesn't protect across results, because each query decides what to hide on its own.

  **Demonstration, on the default synthetic dataset (March 2026, qualified leads, Meta campaigns):**

  1. One query gives the total: 9.
  2. One query per campaign shows each campaign's count unless it is under 5: Retargeting 8, eight others 0, Messenger | General hidden.
  3. So Messenger | General = 9 − 8 − 0 = **1**. A hidden count is recovered exactly with ordinary, read-only tool calls.

  The benchmark found the same thing by accident (Q18): `explain_metric_change` hid Retargeting by secondary suppression while `get_performance` showed it. Any tool, filter or grouping that shows the secondary cell defeats secondary suppression, and the assistant can make those calls on its own.

- **Options:**

  | Option | Stops differencing? | Cost |
  |---|---|---|
  | Keep k = 5, document the limit | No | None. Acceptable only while the data is synthetic. |
  | Raise k, or coarser dimensions for small populations | No: the same subtraction works at any k | Less detail for every question |
  | Query auditing: track what each user has seen, refuse queries that would complete a subtraction | Partly; hard to get right, and needs per-user state | Complex; refusals surprise users |
  | **Consistent noise (the cell key method).** Each lead gets a fixed random key; a cell's key is derived from its leads' keys, and a lookup table turns it into a small fixed adjustment (for example −2 to +2) for counts. The same cell always gets the same noise, in any query, so repeating or rearranging queries can't average or subtract it away. Small cells are still suppressed after perturbation. | Yes, to the degree the noise is set | Every count is off by a little, and rows no longer add up exactly to totals. Credit-weighted counts and rates need a defined treatment. |
  | Formal differential privacy, with a privacy budget | Yes, with a provable bound | Budget accounting across all questions; noisier for the small numbers this business has |

  The cell key method is what the Australian Bureau of Statistics uses for TableBuilder, its self-service table tool. That is the closest public analogue to an assistant that builds tables on request.

- **Decision (proposed):** before any real data (gate R0), adopt the cell key method for lead-derived counts, keep k-suppression on top, and state in every result that counts are perturbed. Keep exact numbers only for spend and other measures that aren't about people. For the synthetic MVP, keep the current suppression and document the limit.
- **Consequences:**
  - The oracle and the benchmark would compare unperturbed values (perturbation applied last, in one place), so correctness checks stay exact.
  - Answers would say "about 40 leads" for perturbed counts, and the answer contract would format them so.
  - The privacy review must set the noise table, k, and which measures are exempt.
  - Until then, `docs/metrics.md` and the assistant's caveats must not claim that hidden counts can't be recovered.
