# The Core Model

The core build turns raw staging rows into the canonical model the analytics will read: campaigns linked across platforms, sessions with a channel, and leads with a class, a clean city and an evidence tier.

```bash
uv run python -m marketingiq.core build --org synthetic-home-services
```

## How a build works

1. Find the latest successful load batch of each staging table for the organization.
2. Build every core record in memory with pure functions (`src/marketingiq/core/records.py`), applying the rule book.
3. In **one transaction**, delete the organization's core rows and write the new ones. Readers see the old build or the new one, never a mix, and building twice gives the same result.
4. Record the build in `core.build_runs`: which batches it used, every rule section's version and `verified` flag, and a data-quality summary.

## The rule book

Every cleaning rule lives in [`src/marketingiq/core/rules.toml`](../src/marketingiq/core/rules.toml): channel grouping, the site's page map, regions and city aliases, Salesforce picklist and stage mappings, request-type defaults, the duplicate window and the attribution lookback. Every section has a `version` and `verified = false`. A Pydantic model rejects any mapping to a value that isn't in [`vocabulary.py`](../src/marketingiq/core/vocabulary.py).

## Tables

| Table | One row per | Built from |
|---|---|---|
| `core.campaigns` | Campaign | The team's mapping sheet, plus any Meta campaign with spend that the sheet doesn't list (kept as `meta:<id>`, unmapped) |
| `core.campaign_identifiers` | Way of recognizing a campaign: a Meta campaign id or a UTM value | The same |
| `core.ad_spend_daily` | Campaign and day (ad account time zone) | Meta insights |
| `core.landing_pages` | Page path, with page type, service line and city | GA4 landing pages + the page map |
| `core.web_sessions` | GA4 session, with channel and campaign (none if unmapped) | GA4 sessions |
| `core.leads` | Salesforce lead, classified and tiered | Salesforce leads + sessions + campaigns |
| `core.appointments` | Salesforce event, linked to its lead | Salesforce events |
| `core.opportunities` | Opportunity, linked to the lead converted into it | Salesforce opportunities |
| `core.annotations` | Dated business event | Annotations file |
| `core.build_runs` | Build | The build itself |
| `mart.lead_attribution_credits` | Credited touch of a first lead, per model and lookback window | Leads + sessions, with `src/marketingiq/mart/attribution.py` |

## What happens to a lead

In this order (each step is a function in `rules.py` with its own tests):

1. **Entry point and stage** from the Salesforce picklists.
2. **Linked campaign**: the native Meta campaign id if present, otherwise the captured UTM campaign.
3. **Request type**: the CRM field if recorded; otherwise the entry-point default (quote form and booking → `install_replace`, U-20); otherwise the linked campaign's tactic; otherwise `unknown`. The source is stored in `request_type_source`.
4. **Customer type**: the recorded Yes/No answer, else `unknown`.
5. **Service line**: the CRM field, then the form's page, then the linked campaign's single service line.
6. **City and region**: cleaned spelling, known aliases, or a region-only match ("KW"); anything else stays `unrecognized` and the raw text is kept.
7. **Duplicates**: the same person within 72 hours of their first lead. Only the first lead counts.
8. **Class**: the ordered rules in `docs/lifecycle_and_classification.md`.
9. **Evidence tier** (first leads only): T1 journey → T3 platform-native → T2 captured source → T4 self-reported channel → T5 none, as in `docs/attribution.md`.
10. **Attribution credits** (first leads only), for every model (first touch, last non-direct, linear) and every supported lookback window (7, 30 and 90 days). Credits are exact decimals that sum to exactly 1 per lead, so credited totals always equal lead counts.

## Results on the default synthetic dataset

| Measure | Value |
|---|---|
| Leads | 13,263 |
| Acquisition / service demand / non-marketing / junk / unknown | 4,300 / 5,161 / 1,013 / 1,077 / 1,618 |
| Duplicates · spam · test leads | 676 · 324 · 77 (all match the ground truth) |
| Evidence tiers T1 / T2 / T3 / T4 / T5 | 2,639 / 664 / 659 / 3,057 / 5,568 |
| Cities: exact or cleaned / alias / region only / blank / unrecognized | 11,477 / 112 / 17 / 1,445 / 212 |
| Unmapped campaign values in GA4 | `meta_prospecting_summer_test`, 2,124 sessions (scenario S09) |
| Appointments or opportunities without a lead | 0 |
| Attribution credit rows | about 127,000 (12,587 first leads × 3 models × 3 windows, plus extra rows for linear splits) |
| Build time | about 40 seconds |

## Performance notes

- **Every foreign key a rebuild deletes through has an index.** Without one on `mart.lead_attribution_credits.session_id`, deleting 138,000 sessions made Postgres scan the whole credits table once per session: a rebuild ran for over five minutes before being cancelled. A test now fails if any foreign key lacks a supporting index.
- **Most of a build is the database enforcing integrity.** Profiling a build: about 18 of its 26 writing seconds are Postgres checking foreign keys and updating indexes while `COPY` streams about 290,000 rows. That's acceptable for a prototype. At real-data volumes the options are an incremental mart, or building into new tables and swapping them in.

## Known limitations

- **Nominations sent through the quote form count as acquisition.** The quote form has no request-type field, so the U-20 default reads every submission as a quote request. In the synthetic data that's 66 of 4,300 acquisition leads (1.5%). Only the free-text message would tell them apart, and it's never read. A real fix needs a form-type field or a separate nomination form (U-20).
- **Most acquisition leads have an unknown customer type** (3,155 of 4,300), because the quote form doesn't ask. Some existing customers asking for an upgrade are therefore counted as acquisition. Results report the unknown share.
- **Leads with no recorded request type are `unknown`** (1,618): phone calls without the agent's note, and some chat and Messenger leads. They're excluded from acquisition metrics and reported separately.
- **One device per household**: GA client ids join sessions from one browser only; cross-device journeys aren't joined.

## What the tests check against the ground truth

`tests/integration/test_core_build.py` builds the tiny world and checks:

- duplicates match the generator's exactly;
- test leads and spam become junk;
- no billing, customer-service or repair lead is ever classified as acquisition;
- the only leaks into acquisition are non-sales forms sent through the quote form, under 3%;
- recognized cities resolve to the household's true region;
- every T1 lead has a session inside the lookback;
- the unmapped campaign keeps its spend but its sessions stay unlinked;
- UTM case variants still link to their campaign;
- a rebuild produces the same result.
