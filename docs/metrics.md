# Metrics Registry — Draft Definitions

These definitions are the proposed contract for the MVP. They must be implemented centrally and reused by REST endpoints, LLM tools, answers and tests. Do not re-implement formulas separately in prompts.

## Reporting defaults

- **Population:** `lead_class = acquisition`, excluding duplicates and junk; always state this population in answers.
- **Lead-cohort basis:** lead and downstream outcome metrics use the lead's `created_at` date unless a metric explicitly says otherwise. A cohort's qualification/consultation/sale status is evaluated as of the dataset's `data_as_of` date.
- **Spend basis:** advertising measures use source-reported daily spend dates after documented timezone handling. Do not join or aggregate daily values across a timezone mismatch without a warning or a coarser reporting grain.
- **Reporting timezone:** `America/Toronto` provisionally; source account/property timezones are unverified.
- **Currency:** CAD provisionally; source currency must be verified before real-data use.
- **Attributed campaign metrics:** require an attribution model and lookback where applicable; defaults are `last_non_direct` and 30 days.
- **Zero denominators:** return `null` with a reason, not zero. Missing spend source is not zero spend.
- **Platform conversions:** report separately from Salesforce outcomes; never add them together.

## Metric definitions

| Metric | Definition | Null / caveat rules |
|---|---|---|
| `impressions` | Sum of source-reported impressions for the selected platform/campaign/date range. | 0 if no source rows exist only when source completeness is known; otherwise report incomplete coverage. |
| `link_clicks` | Sum of Meta link clicks or the clearly named click measure supplied by that platform. | Do not rename a platform-specific click measure to a universal click metric without documenting the definition. |
| `spend` | Sum of spend rows mapped to the requested grouping and period. | `null` for cost metrics if no spend source is available; never infer spend from GA4. |
| `CTR` | `link_clicks / impressions`. | `null` if impressions are zero. |
| `CPC` | `spend / link_clicks`. | `null` if clicks are zero or spend basis is unavailable. |
| `GA4 sessions` | Count of deduplicated exported sessions started in the selected reporting period. | State export completeness and timezone caveats. |
| `CRM leads` | Count of distinct non-duplicate Salesforce-style leads created in the period. | Population filter must be stated; excludes junk/duplicates from acquisition counts. |
| `attributed leads` | Sum of attribution credit across eligible leads for a campaign/channel under model M. | Always show model, lookback and evidence coverage. |
| `qualified leads` | Acquisition leads with an accepted qualification status or timestamp from a verified stage mapping. | If stage mapping is unverified, attach `mapping_unverified`; do not pretend synthetic labels are company facts. |
| `qualification rate` | Qualified acquisition leads / acquisition leads for the same cohort and scope. | `null` if lead denominator is zero. For attributed campaign views, use attributed credit consistently in numerator and denominator. |
| `cost per lead` | Relevant spend / attributed acquisition leads under the selected model. | `null` with `no_spend_source` if cost coverage is absent; `null` if attributed lead denominator is zero. |
| `cost per qualified lead` | Relevant spend / qualified attributed acquisition leads. | Same spend/source rules; add low-volume and coverage caveats. This is a primary efficiency metric. |
| `appointments booked` | Count of deduplicated, linked appointment records with a booking timestamp in the lead cohort. | Source and Salesforce/Calendly synchronization are unverified; don't count generic service visits as consultations. |
| `consultations completed` | Count of qualifying consultation appointments with canonical status `completed`. | Requires verified appointment type/status mapping. |
| `consultation completion rate` | Completed consultations / booked consultations for the same cohort. | `null` if booked consultations is zero. |
| `opportunities` | Count of distinct linked opportunities for the lead cohort, using verified relationship rules. | Stage/object mappings may be unverified. |
| `sales won` | Count of linked opportunities whose verified canonical outcome is `won`. | Apply cohort basis by lead creation date unless explicitly requesting close-date reporting. State the basis. |
| `win rate` | Won opportunities / closed (won + lost) opportunities in the selected cohort. | Exclude open opportunities from the denominator; `null` if no closed opportunities. |
| `lead-to-sale rate` | Won opportunities / acquisition leads for the same cohort. | `null` if no acquisition leads. Recent cohorts may be immature. |
| `recorded won amount` | Sum of opportunity amount only within a single verified `amount_basis`. | `null` or separated groups if amount basis is unknown or mixed; attach `amount_basis_unverified` when not verified. |
| `ROAS` | Attributed recorded won amount / matching ad spend. | Secondary only; valid only with matching scope, available spend and verified comparable amount basis. Never mix purchase price, financed total, lease contract value and monthly payment. |
| `attribution coverage` | Share of eligible acquisition leads with evidence at tiers T1–T3. | Always report numerator/denominator and evidence-tier breakdown. Initial low-coverage warning threshold: below 60%, configurable. |
| `journey-model coverage` | Share of eligible acquisition leads at tier T1 with a matched GA4 journey. | First/last/linear model differences are only meaningful for leads with a linked journey in this initial design. |
| `unmapped campaign share` | Share of applicable source records that cannot be linked to a canonical campaign. | Keep an explicit `(unmapped)` bucket and caveat. |
| `source reconciliation gap` | Side-by-side difference between independently reported measures (e.g. Meta leads and CRM leads); not a combined total. | Definitions and attribution settings may differ; present source totals separately and explain that they are not expected to match exactly. |
| `cost per completed consultation` | Relevant spend / attributed completed consultations (attributed credit of acquisition leads whose consultation is `completed`). | Same spend rules as cost per lead; `null` if no completed consultations. Needs the appointment mapping (U-04). |
| `cost per sale` | Relevant spend / attributed won sales. | Same spend rules; add `immature_cohort` for recent cohorts. |
| `form submit rate` | GA4 sessions with at least one form-submit key event (`quote_submit`, `callback_submit`) / GA4 sessions, for the same landing page or grouping. | `null` if sessions are zero. Event names are synthetic examples (U-16). A web-analytics rate, not a CRM lead rate. |
| `sales won from service-demand leads` | Won opportunities linked to `service_demand` leads in the cohort. | Reported separately; never added to acquisition sales (see the repair-to-replacement question in lifecycle_and_classification.md). |
| `source completeness` | Per source and period: days with loaded rows / days expected, where expected days come from the source's known reporting window and `load_batches` coverage. | Below 100% → `source_incomplete`, naming the source and the missing dates. |

## Period comparison rules

- Supported in MVP: `none`, `previous_period`, `same_period_last_year`.
- Period boundaries are inclusive calendar dates in the reporting timezone.
- The backend resolves relative language such as “last month” against the dataset's `data_as_of` date, not the machine's current date.
- If comparing across a likely seasonal boundary month-over-month, attach `seasonal_comparison` and recommend a year-over-year comparison where available.
- A partial-period vs full-period comparison must be flagged as unequal periods or disallowed by the API contract.
- `custom` comparison: the caller supplies explicit comparison dates. This is needed for before/after questions around a dated annotation (e.g. a landing-page change). Before/after results describe what coincided with the change, never what it caused.

## Dimensions: lead properties vs attributed

- **Lead-property dimensions** (`entry_point`, `service_line`, `region`, `lead_class`, `customer_type`, `lead_month`) are facts recorded on the lead. Grouping by them counts leads directly and does **not** depend on an attribution model.
- **Attributed dimensions** (`campaign`, `channel`, `platform`, `campaign_tactic`, `landing_page`) need an attribution model, lookback and coverage, because a lead can only be assigned to them through attribution credit.
- A grouping may combine at most two dimensions in the MVP (e.g. service line × region).

## Small-cell suppression

Applies to every REST and assistant output built from lead-level data (spend-only results are exempt):

- Any count below **k = 5** (configurable) is returned as `{"suppressed": true}`, and so is every rate or cost derived from it.
- **Secondary suppression:** if exactly one cell in a group is suppressed and the group total is shown, the next-smallest cell is suppressed too, so the hidden value can't be recovered by subtracting from the total.
- Any suppression adds `small_cell_suppressed`.
- k = 5 is a starting value, not a privacy-reviewed threshold; it is part of the R0 review.

## Required metadata in every result

Every analytical result should include `resolved` context (period, comparison period, population, attribution model, lookback, reporting timezone, currency, `data_as_of`, synthetic flag) and machine-readable `warnings[]`.

## Caveat codes expected by the MVP

`population_default`, `low_attribution_coverage`, `no_spend_source`, `amount_basis_unverified`, `mapping_unverified`, `seasonal_comparison`, `immature_cohort`, `maturity_unknown`, `small_cell_suppressed`, `timezone_mismatch`, `synthetic_data`, `source_incomplete`, `classification_default_applied`, `unequal_periods`.
