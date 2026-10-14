# Attribution and Evidence Rules

## Principle

Attribution is a documented convention for assigning credit across observable touchpoints. It is **not evidence that a campaign caused the conversion**. Results must show the attribution model, lookback, evidence coverage and any mapping caveats.

## Evidence tiers

| Tier | Evidence available | MVP behaviour |
|---|---|---|
| `T1_journey` | A CRM lead has a captured GA identifier that matches one or more exported GA4 sessions. | Eligible matched sessions can be evaluated using first-touch, last-non-direct and linear models. |
| `T2_captured_source` | UTM or click ID was captured on the form/lead, but no full GA4 journey is available. | Single-touch credit to the campaign the captured UTM maps to; no multi-touch inference. A click ID alone (gclid/fbclid, no UTM) identifies the channel but not the campaign, so credit is channel-level under `(unmapped)`. |
| `T3_platform_native` | A Meta lead-form or Messenger record has a native campaign/ad identifier linked to the lead. | Single-touch credit to the Meta campaign the native ID maps to. |
| `T4_self_reported_channel` | Only a CRM LeadSource or self-reported channel is available. | Channel-level credit only; campaign-level attribution is not claimed. |
| `T5_none` | No usable source evidence. | Put the lead in an explicit `unattributed` bucket. |

T1–T3 count toward campaign-attribution coverage. T1 is the share for which alternative web-journey attribution models can meaningfully differ. T4 must not be presented as campaign-level evidence.

### Mapping status vs verification status

Two separate questions, two separate effects:

- **Is there a mapping?** If a captured UTM, GA4 campaign or native ID has no entry in `campaign_mappings`, credit goes to `(unmapped)` at channel level. This decides *where credit lands*.
- **Is the mapping verified?** An unverified mapping still assigns credit, and the result carries `mapping_unverified`. This decides *which caveat is attached*, never whether credit is assigned. (Every synthetic mapping starts as `verified=false`; gating credit on verification would make T2/T3 assign nothing.)

### Tier assignment precedence

Each lead gets exactly one tier, assigned in this order (first match wins):

1. **T1** — the lead has a GA pseudo-ID **and** at least one eligible session (see *Lookback and eligibility*). A GA ID with no eligible session does not qualify; it falls through and is counted in data quality as `ga_id_unmatched` or `journey_outside_lookback`.
2. **T3** — entry point is `meta_lead_form` or `meta_messaging_agent` with a native campaign ID. (T2 and T3 are normally mutually exclusive by entry point; if both exist and disagree, T3 wins and a `source_conflict` data-quality row is logged.)
3. **T2** — a captured UTM campaign or click ID exists.
4. **T4** — the CRM lead source maps to a channel through `channel_rules`.
5. **T5** — nothing usable.

Duplicates are resolved before tiering: only the canonical (earliest) lead of a duplicate group is tiered and credited.

## Models

Within a T1 journey, *eligible touches* are the sessions that pass lookback and eligibility. *Direct touches* are eligible touches with channel `direct`.

- **Direct-traffic convention (all three models):** if any non-direct eligible touch exists, direct touches are excluded. If every eligible touch is direct, all three models give 1.0 credit to channel `direct` (no campaign).
- `first_touch`: 100% credit to the earliest non-direct eligible touch.
- `last_non_direct`: 100% credit to the latest non-direct eligible touch.
- `linear`: credit of 1/n to each of the n non-direct eligible touches.
- T2 and T3 are single-touch assignments, so all three model reports show the same credit for those records.
- T4 is channel-only; T5 is unattributed.

## Lookback and eligibility

- Default lookback: 30 days; supported synthetic alternatives: 7 and 90 days.
- For T1, eligible sessions occur at or before the lead creation time and within the lookback window.
- Sessions after the lead are never used to attribute that lead.
- Use deterministic tie-breaking by timestamp and stable session ID.
- Cross-device identity is not inferred.
- Leads without eligible evidence are assigned to `unattributed` rather than dropped.

## Spend-to-campaign mapping

Maintain a versioned mapping between source campaign IDs, normalized UTM campaign names and GA4 campaign IDs. Unmapped records remain visible in an `(unmapped)` bucket. Case and whitespace normalization can be applied deterministically, but fuzzy name matches require review and must not silently become verified mappings.

## Required outputs

For each requested attribution report, return:

- the population and period;
- model and lookback window;
- total eligible leads;
- credit assigned by campaign/channel, including `unattributed`;
- T1/T2/T3/T4/T5 counts or shares;
- T1 share (model-comparison coverage);
- T1–T3 campaign-coverage share;
- relevant unverified mapping and low-coverage warnings.

Initial low-attribution-coverage caveat threshold: below 60% T1–T3 coverage. This is configurable and should be reconsidered after synthetic evaluation; it is not a company-specific measured threshold.

## Invariants and tests

1. Within a model and population, each lead's credit sums to 1 (within numeric tolerance), including `unattributed`.
2. Total assigned credit reconciles to the eligible lead count, across all three models.
3. First/last model outputs match expected hand-built journeys.
4. Linear credit is equal across eligible touches.
5. T2/T3 credits do not change across attribution models.
6. T4 is channel-level only; it must never be shown as campaign-level certainty.
7. Results are deterministic when input rows are shuffled.
8. No post-lead session receives credit.
9. Platform-reported conversion totals are never added to Salesforce lead totals.
10. Attribution language uses “credited to” or “attributed to”; causal language requires independent causal evidence.
11. Tier precedence: hand-built leads carrying several kinds of evidence receive the tier the precedence list dictates (one test per precedence step, plus the GA-ID-without-eligible-session fall-through).
12. An unverified mapping assigns the same credit as a verified one and adds `mapping_unverified`; a missing mapping sends credit to `(unmapped)`.
