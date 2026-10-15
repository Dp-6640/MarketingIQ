# Analytics Services and REST API

Every number MarketingIQ shows comes from one of seven services in `src/marketingiq/analytics/`.
The REST API is a thin layer over them, and the assistant (Phase 4) will call the same services
as tools. A query is the same Pydantic model in all three places, so it means the same thing
everywhere. All read paths use the read-only `miq_app` role.

Run it: `uv run uvicorn marketingiq.api.app:app --reload`, then open `http://127.0.0.1:8000/docs`.

## Endpoints

| Method and path | Service | Answers |
|---|---|---|
| `GET /health` | – | Is the API up, and can it reach the database? |
| `GET /api/v1/dimensions/{dimension}/values?search=` | `list_dimension_values` | Which campaign is "the furnace campaign"? Which region is Kitchener in? `match` is `none`, `one` or `several`, so an ambiguous name leads to a clarifying question, never a guess |
| `GET /api/v1/annotations?start=&end=&annotation_type=` | – | What happened in the business around these dates? |
| `POST /api/v1/analytics/performance` | `get_performance` | Any registry metric, by up to two dimensions, with a comparison |
| `POST /api/v1/analytics/attribution-models` | `compare_attribution_models` | Credit under first touch, last non-direct and linear side by side, with the evidence tiers that limit the comparison |
| `POST /api/v1/analytics/funnel` | `get_lead_funnel` | Leads → contacted → booked → qualified → opportunity → won, with stage rates |
| `POST /api/v1/analytics/reconciliation` | `get_source_reconciliation` | GA4 vs Meta-reported vs CRM, side by side and never added together |
| `POST /api/v1/analytics/change` | `explain_metric_change` | Which segments moved a metric between two periods |
| `POST /api/v1/analytics/data-quality` | `get_data_quality` | What can't be trusted about this period, and why |

Every request takes an optional `?org=<slug>`. Without it, the API uses `DEFAULT_ORG_SLUG`
(default `synthetic-home-services`).

## Error behaviour

- **422**: the query is invalid before any SQL runs. Examples: an unknown metric, a field that
  isn't in the model (so there is no way to send free-text SQL), spend split by a lead
  property, or a custom comparison with no comparison period.
- **404**: the organization doesn't exist, has no data loaded, or has no core build yet.
- **503** from `/health`: the database is unreachable. Connection details go to the log only.

## What every analytics result contains

- `resolved`: the exact period and comparison dates, population, attribution model, lookback,
  time zone, currency, `data_as_of` and `synthetic`. "Last month" is never left for the reader
  to guess.
- Values, with a `null_reason` instead of a misleading 0, and `suppressed: true` for cells
  under the small-cell threshold (k = 5).
- `warnings`: caveat codes with plain-English messages (see `docs/metrics.md`).
- In performance rows, every shown value has a `rank` (1 = largest, ties share a rank) and `rank_of` (how many rows have a value). Ranks cover all rows, before `limit`, so "third of eight" can be stated without counting.

## Flags: selections the tool makes

Some questions ask which rows meet a condition ("campaigns with cheap leads that rarely qualify"). The selection is a deterministic rule in the tool, never a comparison the LLM makes. A performance query takes `flags`; each flagged row lists it, and `flag_rules` states the rule, how many rows were judged, the medians used and how many were flagged.

| Flag | Rule | Needs |
|---|---|---|
| `cheap_leads_low_qualification` | Cost per lead below the median and qualification rate below the median, among campaigns with spend and at least 10 credited leads; at least 3 such campaigns, or nothing is flagged | `group_by=["campaign"]`, `cost_per_lead` among the metrics |

A row whose counts are hidden by small-cell suppression is not judged, so a flag can't reveal a hidden value.

## The model comparison

`compare_attribution_models` measures the same leads under all three models and lists them side by side, with a `spread` per row (the largest minus the smallest credit). Models only differ for leads with a web journey (T1), so the result always includes the evidence-tier breakdown, `journey_share` (the T1 share: the part of the population the comparison is really about) and `campaign_coverage` (T1–T3). If any model's value for a row is under 5, the whole row is hidden: three views of one small count would otherwise reveal it.

On the default synthetic data, over the year to September 2026, retargeting is credited with 91 leads under first touch, 152 under last non-direct and 177 under linear (scenario S08), while prospecting goes the other way (229 → 78). Only 32% of the leads have a journey, which is why the result says so.

## The four reports, briefly

**Funnel.** Stage counts over lead properties, plus stage-to-stage rates. Leads are counted by
creation date, so recent cohorts look worse until they mature, and a maturity warning says so.
A funnel can be split by one dimension.

**Reconciliation.** Puts three sources next to each other for one period: GA4 key events, Meta's
platform-reported conversions (including view-through) and CRM leads by evidence tier. The
three are not additive, and the report says so every time with `sources_not_additive`. On the
synthetic data Meta reports about 1.2× the CRM leads that carry Meta evidence (scenario S07).
That gap is expected, not an error.

**Change explanation.** For a count metric, each segment's effect is its own change, and the
effects add up exactly to the total change (`share_of_change`). For a ratio (cost per lead,
booking rate), each segment's effect is the actual total minus the total there would have been
if only that segment had kept its previous numerator and denominator. Ratio effects don't add
up exactly, and the `method` field says so. Labels such as `spend_up_paid_leads_down` spare a
caller from comparing signs. These are arithmetic contributions, not causes.

**Data quality.** Evidence-tier coverage, classification defaults, unmapped campaigns, channels
with leads but no spend feed, hidden-field capture by week, days without data per source,
latest loads and their rejections, cohort maturity and time zones. A week's capture rate below
half the median weekly rate is flagged as `capture_drop`, which means tracking broke, not that
customers disappeared. Synthetic scenario S06 plants exactly this.

## Known trade-off: suppression at this scale

With k = 5, many campaign × month cells in a change explanation are hidden at this business's
volume, especially for qualified leads and sales. That is deliberate (privacy before detail),
but it means a manager may see "suppressed" where they expect a number. The options, to decide
once real volumes are known (U-15):

1. Keep k = 5 and explain at a coarser level (channel instead of campaign).
2. Lower k for aggregated, non-identifying metrics such as spend. Spend is not about people.
3. Widen the default period for ratio explanations.
