# Synthetic Data Specification

**Every number in this document is a synthetic assumption, not a fact about LG Home Comfort.** It describes a fictional Ontario home-services business shaped like the real one (same kinds of services, entry points, seasons and data systems) so MarketingIQ can be built and tested without company data.

The generator reads every value from [`src/synthetic/config/default.toml`](../src/synthetic/config/default.toml); this document is the human-readable version of that file. Status: implemented with the default values below; still open to review.

```bash
uv run python -m synthetic generate                          # -> data/synthetic/default-seed-20261014/
uv run python -m synthetic generate --config tiny --seed 7   # small world used by the tests
```

## Review checklist: where your knowledge helps most

You don't need to check every number. These are the assumptions that most change the results. A rough "higher/lower" is enough:

1. **Entry-point mix** (section 6): is phone really about a quarter of new-customer leads? Are Meta lead forms about 10%?
2. **Service-line mix** (section 3): is furnace + AC about half of new-customer demand?
3. **Seasonality** (section 3): is the furnace peak October–January and the AC peak May–August?
4. **Funnel rates and sales lags** (section 7): are qualification ~50–65% and win rate ~30–55% in the right range?
5. **Amount basis** (section 7): how are sales recorded: purchase price, financed total, lease contract, monthly? (Public promotions advertise monthly pricing, so the generator mixes these.)
6. **Tracking reality** (section 8): do web forms pass UTMs into Salesforce? Is there call tracking?

Anything left unreviewed stays labelled as an assumption.

## 1. Rules

- No real data: no real customer records, campaign names, spend, or performance figures.
- Place names (Toronto, Ottawa, …) and URL patterns (`/locations/{city}/`) come from the public website; volumes per place are invented. The site domain is the reserved `homeservices.example`.
- Campaign names are fictional and follow a documented naming convention (section 5).
- The generator first simulates what "really happened" (ground truth), then simulates what the tracking systems *recorded*, including their gaps and errors. Only the recorded version is loaded into the application.
- Ground truth is written to separate files for testing and is never loaded where the application role can read it.

## 2. Size and time window

Realized values for the default seed are in each dataset's `manifest.json`; the figures below are from seed `20261014`.

| Setting | Default | Tiny (tests) |
|---|---|---|
| Date range | 2024-10-01 → 2026-09-30 (24 months) | 2026-01-01 → 2026-03-31 |
| `data_as_of` | 2026-09-30 | 2026-03-31 |
| Burn-in (simulated, never exported) | 30 days | 14 days |
| Regions | 7 | 1 (GTA) |
| GA4 sessions | ~140,000 | ~2,400 |
| CRM leads (all classes) | ~13,300, including ~700 duplicates and ~80 test leads | ~300 |
| Acquisition leads | ~4,500 | ~100 |
| Won sales | ~500 from acquisition + ~220 from service-demand leads | a handful (cohorts mostly immature) |
| Campaigns | 13 (11 Meta, paid search, email) plus organic, direct, referral and organic social | 7 |
| Generation time | ~45 seconds | under 1 second |

Volumes are deliberately small so the whole dataset regenerates in under a minute. They say nothing about the real company's traffic.

## 3. Demand

**Household needs** (share of households that make contact on their own):

| Need | Share | Behaviour |
|---|---|---|
| Planned replacement / new install | 30% | Several website visits over days or weeks, then a form, booking or call |
| Emergency repair | 25% | Mostly phone, often at once, little browsing |
| Research only | 20% | Browses, rarely becomes a lead |
| Existing-customer service (repair, maintenance) | 15% | Phone or callback form; `customer_type = existing` |
| Billing / customer service | 7% | Callback form or phone; never a sales lead |
| Junk / other | 3% | Spam and non-sales forms such as nominations |

Meta ads bring in additional households (section 5); their mix is set separately.

**Service-line mix for new-customer demand:** furnace 30%, air conditioner 20%, heat pump 15%, water heater 15%, water treatment 8%, air quality 5%, security 4%, generator 2%, maintenance plan 1%.

**Monthly seasonality index** (normalized to an average of 1.0 in code):

| Service line | J | F | M | A | M | J | J | A | S | O | N | D |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Furnace | 1.5 | 1.4 | 1.0 | 0.7 | 0.5 | 0.4 | 0.4 | 0.5 | 0.9 | 1.4 | 1.6 | 1.6 |
| Air conditioner | 0.3 | 0.3 | 0.5 | 0.9 | 1.5 | 2.0 | 2.1 | 1.6 | 0.9 | 0.5 | 0.3 | 0.3 |
| Heat pump | 0.8 | 0.8 | 1.1 | 1.3 | 1.2 | 1.0 | 0.9 | 0.9 | 1.1 | 1.2 | 1.0 | 0.8 |
| Water heater | 1.1 | 1.1 | 1.0 | 1.0 | 0.9 | 0.9 | 0.9 | 0.9 | 1.0 | 1.0 | 1.1 | 1.1 |
| Others | 1.0 flat; air quality +20% in April–May |

- **Day of week:** Mon 1.20, Tue 1.15, Wed 1.10, Thu 1.05, Fri 1.00, Sat 0.80, Sun 0.70.
- **Time of day:** forms and chat peak 9:00–21:00 local time; emergency phone calls happen around the clock; offline contact for planned work happens in business hours.
- **Growth:** a linear trend; year 2 is 8% above year 1 overall, heat pump +25% (so year-over-year comparisons aren't flat).

**Regions** (share of demand): GTA 55%, Hamilton–Niagara 10%, Ottawa 12%, Kitchener–Waterloo–Guelph 8%, London–Windsor 8%, Barrie–Simcoe 5%, Northern and other 2%. Each region has a list of cities, used for the free-text City field.

## 4. What gets recorded where

| System | What the generator writes | Notes |
|---|---|---|
| Meta Ads | Daily rows per campaign: spend, impressions, link clicks, Meta-reported leads | Spend exists **only** for Meta campaigns |
| GA4 | One row per session: pseudonymous user ID, start time (UTC), source/medium/campaign, landing page, form/chat/phone-click events | Sessions from visitors who rejected analytics cookies are missing |
| Salesforce-style | Leads, appointments (Events), opportunities | Field names ending in `__c` are hypothetical |
| Clarity | Daily page-level friction summaries (UTC days) | Generated now, loaded in V1 |

## 5. Campaigns

Naming convention: `{platform}_{tactic}_{service}[_{region}]`. Tactics: `prospecting`, `retargeting`, `lead_form`, `messaging`, `promo`, `search`, `email`.

| Campaign (fictional) | Runs | Notes |
|---|---|---|
| `meta_prospecting_furnace` | Sep–Feb each year | Seasonal |
| `meta_prospecting_ac` | Apr–Aug | Seasonal |
| `meta_prospecting_heatpump` | Always on | Creative fatigue in March 2026 (S04) |
| `meta_prospecting_water` | Always on | Water heater + treatment |
| `meta_lead_form_furnace_promo` | Oct–Dec | Cheap leads, poor quality (S01) |
| `meta_lead_form_ac_promo` | May–Jul | Same pattern, milder |
| `meta_retargeting_all` | Always on | Shown mostly to high-intent past visitors (S08) |
| `meta_messaging_general` | Always on | Click-to-Messenger (Claire) |
| `meta_promo_security` | Always on | Low budget |
| `meta_prospecting_furnace_ottawa` | Sep–Feb | Regional; expensive per qualified lead (S11) |
| `meta_prospecting_summer_test` | From 2026-06 | **No mapping entry** (S09) |
| `search_paid_generic` | Always on | Appears in GA4 as paid search; **no spend feed** (S02) |
| `email_newsletter` | Monthly sends | `utm_medium=email`; no spend |
| Organic search, direct, referral, organic social | Always | No campaign |

**Meta delivery:** spend → impressions (CPM CAD 9–15) → link clicks (CTR 0.6–1.8%). Prospecting clicks bring in a small share of people with a real need (1.3–2% of landed clicks, higher in season); lead-form and Messenger clicks create leads inside Meta without a site visit. Total Meta spend averages about CAD 4,700 a month: the whole world is scaled down.

**Meta-reported leads** count every lead form and Messenger lead, plus every website lead from a visitor who clicked a Meta ad in the previous 7 days, once per campaign clicked, plus view-through claims. Meta can't see phone leads or visitors who rejected cookies, so the overall total lands at about **1.2×** the CRM's count of leads with Meta evidence (S07). Either way, the two are never added together.

## 6. Journeys and how leads arrive

- Each household gets a pseudonymous `person_key`, region, city, need, service line, customer type and a hidden **intent** score (0–1) that drives both which ads reach it and how likely it is to convert.
- **Planned replacement:** 1 + Poisson(2.5) visits spread over a lognormal span (median 7 days, capped at 45) before the lead; 15% never visit the website and phone instead.
- **Emergency repair:** 60% visit the website once first; about 70% phone overall.
- **Retargeting** reaches only households that already visited and accepted cookies, weighted toward high intent. It's placed after each household's outcome is decided, so it never changes conversion (S08).

**Entry-point mix for new-customer leads:**

| Entry point | Target | Realized (default seed) |
|---|---|---|
| Phone | 25% | 23% |
| Web quote form | 30% | 31% |
| Web callback form | 12% | 12% |
| Meta lead form | 10% | 11% |
| Booking (in-home assessment) | 8% | 7% |
| Web chat (Sarah) | 8% | 9% |
| Meta Messenger (Claire) | 5% | 5% |
| Email / SMS | 2% | 2% |

Emergency repairs: phone ~70%, callback form ~15%, chat ~10%, other ~5%.

## 7. What happens after the lead (new-customer acquisition)

| Service line | Qualified (of leads) | Consultation booked (of qualified) | Consultation completed (of booked) | Opportunity (of completed) | Won (of closed) | Median days lead → close |
|---|---|---|---|---|---|---|
| Furnace | 60% | 55% | 85% | 90% | 45% | 21 |
| Air conditioner | 60% | 55% | 85% | 90% | 45% | 18 |
| Heat pump | 55% | 60% | 85% | 90% | 35% | 35 |
| Water heater | 65% | 40% | 85% | 90% | 55% | 10 |
| Water treatment | 50% | 50% | 80% | 85% | 35% | 25 |
| Air quality | 50% | 35% | 80% | 85% | 40% | 20 |
| Security | 55% | — (no consultation) | — | 100% | 50% | 7 |
| Generator | 45% | 55% | 80% | 85% | 30% | 45 |
| Maintenance plan | 70% | — | — | 100% | 60% | 5 |

- **Qualification** is the rate above × the household's intent factor (intent ÷ 0.57, clipped to 0.5–1.5) × entry-point and origin multipliers: Meta lead form ×0.5, Sarah/Claire chat ×0.9, paid-search origin ×1.2, organic-search origin ×1.1. Retargeting has **no** multiplier: its leads look better only because it reaches high-intent visitors (S08). Realized qualification: Meta lead form ~25% vs quote form ~67%.
- The decision comes 0.2–4 days after the lead; booked consultations happen 1–10 days later. Leads that book online already have a consultation when they arrive.
- **Lags** are lognormal around the medians above (σ = 0.6). Deals not closed by `data_as_of` stay open, which naturally creates immature recent cohorts (S12).
- **Sale amounts (CAD, lognormal medians, σ = 0.35):** furnace 5,500; AC 5,000; heat pump 9,000; water heater 2,800; water treatment 3,200; air quality 1,500; security 900; generator 12,000; maintenance plan 250.
- **Amount basis mix:** purchase price 55%, financed total 25% (price × 1.15), lease contract 15% (monthly × 120 months), monthly amount 5% (price ÷ 90). Every basis mapping stays `verified=false`, so ROAS always carries a caveat.
- **Service leads:** 85% book a service visit and 90% of those happen. About 30% of completed repair visits on systems 15+ years old produce a replacement opportunity. These are reported as "sales won from service-demand leads", never as acquisition.

## 8. Tracking gaps and noise (applied after the truth is written)

| What | Rate | Effect |
|---|---|---|
| Visitor rejects analytics cookies | 20% | Their sessions are missing from GA4; Meta's pixel can't see them either |
| UTMs / click ID copied into the lead (web forms) | 85% | From the latest tagged visit in the last 30 days. Meta and email visits carry UTMs; auto-tagged paid search only passes a gclid. Otherwise no T2 evidence |
| GA client ID copied into the lead (web forms) | 75% of visitors who accepted cookies (≈60% overall) | Needed for T1 journeys |
| Form page path copied into the lead | 85% | Lets the service line be inferred from the page |
| Captures on the booking page (third-party) | 30% | Weaker evidence for bookings |
| Captures in Sarah chat | 40% | |
| Meta campaign ID present on lead-form / Messenger leads | 90% / 70% | T3 evidence |
| Phone call tracking | 0% | Phone leads are T5, unless… |
| …the CRM LeadSource records where a phone caller heard about the company | 50% | …then T4 (channel only); 10% of those values are wrong |
| Request type recorded | callback form 100%, phone 85%, chat 75%, Messenger 60%; quote form, booking and lead forms never | The rest rely on the entry-point defaults (U-20) |
| City left blank | phone 20%, Messenger 40%, lead form 10% | |
| City typed in a non-standard way | 15% | e.g. "KW", "mississauga", "Toronto, Ontario"; 2% unrecognizable |
| Second submission within 72 hours | 6% of leads | Must be deduplicated |
| Second submission after 72 hours | 1% of leads | Must **not** be deduplicated |
| Test leads | 0.5% | Marked by a hypothetical `Is_Test__c` field |
| Qualification timestamp recorded | 70% of qualified leads | Stage history is unverified (U-03) |
| Exact duplicate GA4 session rows | 0.5% | Dropped at load |
| Meta `utm_campaign` typed in a different letter case | 5% of ad clicks | Tests case-insensitive mapping |
| Meta account time zone | America/Toronto | The tiny config uses America/Los_Angeles to test `timezone_mismatch` |

**Invalid rows for loader tests** are not generated: they're hand-written fixtures in `tests/fixtures/dirty/`, one problem per row, with the expected error code for each in `expected_errors.csv` (see `docs/loading.md`). Links between files, such as an event pointing at a missing lead, are checked later, in the core step.

## 9. Planted scenarios

| ID | Scenario | When | What MarketingIQ must show | Question |
|---|---|---|---|---|
| S01 | Lead-form promo: cheap but low quality | Oct–Dec each year | Cost per lead well below the median, qualification rate well below it (so each qualified lead costs far more than the cost per lead suggests) | Q6 |
| S02 | Paid search traffic with no spend feed | Always | Strong lead quality, but cost metrics are null with `no_spend_source` | Q7 |
| S03 | Cold snaps | 2025-01-20→26, 2026-02-09→14 | Repair and phone demand up about 3×, acquisition barely moves, attribution coverage drops | Q21 |
| S04 | Creative fatigue on `meta_prospecting_heatpump` | March 2026 | Spend +25%, CTR −35%, qualified leads about −30%; change explanation names this campaign | Q17, Q18 |
| S05 | Location-page change | 2026-05-12 | Form submit rate about +20% afterwards; recorded as an annotation; phrased as "coincided" | Q19 |
| S06 | Hidden-field capture breaks | 2026-07-07→16 | Captures drop to 0; data quality must detect it **without** an annotation, and it must not read as a performance drop | Q22, Q23 |
| S07 | Meta reports more leads than the CRM | Always | Shown side by side, never added together | Q14 |
| S08 | Retargeting selection bias | Always | Retargeting gets large last-touch credit; the truth files show zero true effect (V1 demonstration) | Q13 |
| S09 | New campaign without a mapping | From 2026-06 | Appears as `(unmapped)` and in the unmapped list | Q16 |
| S10 | Billing callback spike | 2026-01-12→31 | Billing callbacks ×4; classified `non_marketing`; cost per lead unaffected | Q20 |
| S11 | Ottawa regional campaign | Sep–Feb | Cost per qualified lead well above the province-wide furnace campaign | Q3, Q4 |
| S12 | Immature recent cohorts | Last ~8 weeks | `immature_cohort` on recent sales metrics | Q10 |
| S13 | Small northern towns | Always | Cells under 5 suppressed | (privacy) |
| S14 | Sarah and Claire leads | Always | Qualification about 0.9× web forms; visible as entry points | Q2 |

`annotations.csv` holds what a marketer would know: S03 cold snaps, S05 page change, S10 billing change and campaign launches. S06 is deliberately **not** annotated.

## 10. Output files

```text
data/synthetic/<config>-seed-<seed>/
├── meta/insights_daily.csv            # date, account_id, account_timezone, campaign_id, campaign_name,
│                                      # spend, impressions, inline_link_clicks, leads_reported, attribution_setting
├── ga4/sessions.csv                   # user_pseudo_id, ga_session_id, session_start_utc, source, medium,
│                                      # campaign, content, landing_page, device_category, has_gclid, has_fbclid,
│                                      # ev_quote_submit, ev_callback_submit, ev_phone_click, ev_chat_start, ev_booking_click
├── salesforce/leads.csv               # Id, CreatedDate, LeadSource, Status, IsConverted, ConvertedDate,
│                                      # ConvertedOpportunityId, City, Entry_Point__c, Request_Type__c,
│                                      # Existing_Customer__c, Service_Line__c, Form_Page_Path__c, UTM_Source__c,
│                                      # UTM_Medium__c, UTM_Campaign__c, Click_Id_Type__c, GA_Client_Id__c,
│                                      # Meta_Campaign_Id__c, Person_Key__c, Qualified_Date__c, Is_Test__c
├── salesforce/events.csv              # Id, WhoId, Type, Appointment_Status__c, CreatedDate, ActivityDateTime
├── salesforce/opportunities.csv       # Id, CreatedDate, StageName, CloseDate, IsClosed, IsWon, Amount,
│                                      # Amount_Basis__c, Service_Line__c
├── clarity/page_daily.csv             # V1: date_utc, url, sessions, bot_sessions, dead_clicks, rage_clicks,
│                                      # quickbacks, excessive_scroll, avg_scroll_depth, script_errors
├── annotations.csv                    # type, start_date, end_date, label
├── reference/campaign_mappings.csv    # the team's campaign naming sheet (unmapped campaigns are missing)
├── truth/                             # NEVER loaded into the app database
│   ├── households.csv                 # need, intent, consent, true service line and customer type, origin
│   ├── sessions.csv                   # every real visit, including the ones GA4 never saw
│   ├── journeys.csv                   # per lead: true class, duplicate links, first/last real touch,
│   │                                  # retargeted before the lead
│   └── scenarios.json                 # planted scenarios with dates and parameters
└── manifest.json                      # seed, config hash, generator version, row counts, SHA-256 per file,
                                       # realized rates
```

Expected evidence tiers and metric values are **not** stored in the truth files: the evaluation oracle computes them independently from the recorded files, so the tests check the application against a second implementation rather than against the generator's own logic.

Salesforce-style rows contain **no names, emails, phone numbers or free-text messages**: the quote form's Message field is simply not generated. A test enforces that no output has such a column.

## 11. Reproducibility

- One integer seed (default `20261014`). Every random draw comes from a stream keyed by the seed, a stream name and integer keys such as the day, region or household, so the numbers don't depend on the order in which parts of the simulation run. Turning a scenario on or off mostly changes only its own records; display ids such as `00Q…` may renumber.
- **Test:** generating twice with the same seed gives byte-identical files (same SHA-256 in `manifest.json`).
- The manifest records realized rates (for example consent among web leads, Meta's reported-to-CRM ratio, acquisition entry-point shares), so tests and readers can compare them with the config.

## 12. What this data can't tell you

- Whether any of these rates resemble LG Home Comfort's reality.
- How real tracking behaves: real gaps will be messier and less tidy than these.
- Anything about the commercial business, existing-customer service operations, or call-centre behaviour beyond the simple rules above.
- Cross-device journeys (not modelled; one household = one device).

Results from this data demonstrate that the software is correct and robust. They are not evidence of marketing performance.
