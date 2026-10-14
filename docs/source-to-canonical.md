# Source-to-Canonical Mapping (Proposed)

This mapping describes an intended adapter boundary. It is not a verified inventory of LG Home Comfort's actual exports. Every field, join key, timezone and stage mapping must be checked against the configured systems before real-data use.

## Source responsibilities

| Source | Source-shaped dataset in synthetic MVP | Canonical target | Main limitations to model |
|---|---|---|---|
| Meta Ads | Daily account/campaign insights: campaign ID/name, date, spend, impressions, link clicks, platform-reported lead actions and attribution setting | `campaigns`, `ad_spend_daily`, `platform_reported_conversions` | Account timezone and the precise meaning of each click/conversion field must be verified. Meta conversions are kept separately from CRM leads. |
| Meta Lead Ads / Messenger | Salesforce-style lead rows with optional native campaign/ad IDs and entry-point category | `leads.entry_point`, source evidence fields, campaign mapping | Whether campaign/ad IDs are persisted in Salesforce is unverified. No ID means no campaign-level claim. |
| GA4 | BigQuery-export-shaped sessions/events, flattened to one row per session for the MVP | `web_sessions`, `landing_pages`, event aggregates | Existence of BigQuery export, exact event names, consent effects and captured identifiers are unverified. Without a matching identifier, do not infer a journey. |
| Salesforce | Lead, appointment/event and opportunity-shaped records | `leads`, `appointments`, `opportunities`, `stage_mappings` | Actual fields, custom fields, picklists, history tracking, object relationships and appointment sync are unverified. |
| Microsoft Clarity (V1) | Synthetic daily page-level interaction summaries | `clarity_page_daily` mart | Aggregate diagnostics only; never join to individual leads. Snapshot retention/history limitations should be checked before implementation. |
| Phone | Synthetic lead source and optional call-tracking key | `leads.entry_point = phone` | Call-tracking integration and number-level tracking are unverified; default to unattributed when no usable identifier exists. |
| Web form/chat | Optional synthetic hidden-field capture: UTM, click-ID type, GA pseudo-ID | Lead evidence fields | Actual capture configuration is unknown. Missing identifiers must be represented as missing, not fabricated. |

## Suggested canonical entities

- `organizations` — reporting timezone, currency, `is_synthetic`, `data_as_of`.
- `load_batches`, `rejected_rows` — input lineage and row validation.
- `regions`, `cities`, `city_aliases` — normalized location grouping; keep unverified aliases marked.
- `campaigns`, `campaign_mappings`, `channel_rules` — canonical campaign identity and versioned mappings. Campaigns carry a `tactic` attribute (`prospecting`, `retargeting`, `lead_form`, `brand`, `promo`, `other`) taken from a versioned naming-convention mapping (U-22); needed for retargeting questions.
- `annotations` — dated business events a marketer would know about: landing-page changes, promotions, weather or demand events, tracking incidents (`type`, `start_date`, `end_date`, `label`, `source`). In synthetic data they come from the generator's *public* event list. They record **that** something happened, never its effect, so they are not ground truth. Needed for before/after and demand-event questions.
- `ad_spend_daily`, `platform_reported_conversions` — separate ad platform observations.
- `landing_pages`, `web_sessions` — aggregate/session-level web facts needed for synthetic attribution.
- `leads`, `appointments`, `opportunities`, `stage_mappings` — CRM lifecycle.
- `lead_attribution_credits` — output of the deterministic attribution engine.
- `assistant_runs` — question, resolved context, tool traces, answer status, token/latency/cost metadata; never store PII.
- V1 only: `clarity_page_daily` — page-level friction summaries.

## Adapter flow

`source-shaped synthetic files → staging validation → versioned mapping/transformation → canonical core entities → attribution/analytics marts → read-only REST/assistant tools`

Keep generator ground truth outside the application-accessible schema/database. The production-like application role must not be able to query ground-truth labels, or the evaluation would be invalid.

## Timezone rule

Store event timestamps in UTC. Keep source timezone metadata for daily source aggregates. Reporting uses `America/Toronto` provisionally. If source timezone mismatch makes a day-level comparison unsafe, refuse the join or report at a supported coarser grain with `timezone_mismatch`; never silently convert mismatched dates and imply exact alignment.

## Unknown mapping behaviour

- Do not fuzzy-match campaign names automatically.
- Keep unmapped rows and report the coverage impact.
- Mapping/config entries have a version and `verified` flag.
- Any metric that depends on an unverified mapping carries `mapping_unverified`.
- Never infer a stage timestamp from a later status; if the source has no timestamp, keep it null.
