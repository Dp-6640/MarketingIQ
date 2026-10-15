# Synthetic Data Specification (Draft for review)

**Every number in this document is a synthetic assumption, not a fact about LG Home Comfort.** It describes a fictional Ontario home-services business shaped like the real one (same kinds of services, entry points, seasons and data systems) so MarketingIQ can be built and tested without company data. The generator reads all of these values from `synthetic/config/default.yaml`; this document is the human-readable version of that file.

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
- Place names (Toronto, Ottawa, …) and URL patterns (`/locations/{city}/`) come from the public website; volumes per place are invented.
- Campaign names are fictional and follow a documented naming convention (section 5).
- The generator first simulates what "really happened" (ground truth), then simulates what the tracking systems *recorded*, including their gaps and errors. Only the recorded version is loaded into the application.
- Ground truth is written to separate files for testing and is never loaded where the application role can read it.

## 2. Size and time window

| Setting | Default | Tiny (integration tests) |
|---|---|---|
| Date range | 2024-10-01 → 2026-09-30 (24 months) | 2026-01-01 → 2026-03-31 |
| `data_as_of` | 2026-09-30 | 2026-03-31 |
| Regions | 7 | 1 (GTA) |
| GA4 sessions | ~150,000 | ~2,000 |
| CRM leads (all classes) | ~12,000 | ~200 |
| Acquisition leads | ~4,500 | ~80 |
| Won sales | ~500 from acquisition + ~150 from service-demand leads (follows from the section 7 rates) | few (cohorts mostly immature) |
| Campaigns | 18 | 6 |

Volumes are deliberately small so the whole dataset regenerates in under a minute. They say nothing about the real company's traffic.

## 3. Demand

**Household needs** (share of households that make contact):

| Need | Share | Behaviour |
|---|---|---|
| Planned replacement / new install | 30% | Several website visits over days or weeks, then a form, booking or call |
| Emergency repair | 25% | Mostly phone, often at once, little browsing |
| Research only | 20% | Browses, rarely becomes a lead |
| Existing-customer service (repair, maintenance) | 15% | Phone or callback form; `customer_type = existing` |
| Billing / customer service | 7% | Callback form or phone; never a sales lead |
| Junk / other | 3% | Spam, tests, nominations |

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
- **Time of day:** forms and chat peak 9:00–21:00 local time; emergency phone calls happen around the clock.
- **Growth:** year 2 is 8% above year 1 overall; heat pump +25% (so year-over-year comparisons aren't flat).

**Regions** (share of demand): GTA 55%, Hamilton–Niagara 10%, Ottawa 12%, Kitchener–Waterloo–Guelph 8%, London–Windsor 8%, Barrie–Simcoe 5%, Northern and other 2%. Each region has a list of cities, used for the free-text City field.

## 4. What gets recorded where

| System | What the generator writes | Notes |
|---|---|---|
| Meta Ads | Daily rows per campaign: spend, impressions, link clicks, Meta-reported leads | Spend exists **only** for Meta campaigns |
| GA4 | One row per session: pseudonymous user ID, start time (UTC), source/medium/campaign, landing page, form/chat/phone-click events | Sessions from households that rejected analytics cookies are missing |
| Salesforce-style | Leads, appointments, opportunities | Field names marked (?) are hypothetical |
| Clarity | Daily page-level friction summaries | Generated now, loaded in V1 |

## 5. Campaigns

Naming convention: `{platform}_{tactic}_{service}[_{region}]`. Tactics: `prospecting`, `retargeting`, `lead_form`, `messaging`, `brand`, `promo`.

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

**Meta delivery:** CPM CAD 8–14, link CTR 0.8–1.6% (lead-form campaigns run on Meta without a site visit). Total Meta spend averages about CAD 45,000 a month, higher in season. **Meta-reported leads** count lead events under a 7-day-click / 1-day-view window, so they run about 1.3–1.5× the CRM's count for the same campaigns (S07).

## 6. Journeys and how leads arrive

- Each household gets a pseudonymous `person_key`, region, city, need, service line, customer type and a hidden **intent** score (0–1) that drives both which ads reach it and how likely it is to convert.
- **Planned replacement:** 1 + Poisson(2.5) sessions spread over 3–21 days before the lead.
- **Emergency repair:** 0–1 sessions; 70% phone.
- **Retargeting** reaches only households that already visited, weighted toward high intent. It does **not** raise conversion probability (S08).

**Entry-point mix for new-customer leads:**

| Entry point | Share |
|---|---|
| Phone | 25% |
| Web quote form | 30% |
| Web callback form | 12% |
| Meta lead form | 10% |
| Booking (in-home assessment) | 8% |
| Web chat (Sarah) | 8% |
| Meta Messenger (Claire) | 5% |
| Email / SMS | 2% |

Emergency repairs: phone 70%, callback form 15%, chat 10%, other 5%.

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

- **Qualification multipliers by source:** Meta lead form ×0.5, retargeting ×1.1, paid search ×1.2, organic ×1.1, others ×1.0.
- **Lags** are lognormal around the medians above (σ = 0.6). Deals not closed by `data_as_of` stay open, which naturally creates immature recent cohorts (S12).
- **Sale amounts (CAD, lognormal medians):** furnace 5,500; AC 5,000; heat pump 9,000; water heater 2,800; water treatment 3,200; air quality 1,500; security 900; generator 12,000; maintenance plan 250.
- **Amount basis mix:** purchase price 55%, financed total 25%, lease contract 15%, monthly amount 5%. Every basis mapping stays `verified=false`, so ROAS always carries a caveat.
- **Existing-customer and service leads:** about 30% of repair visits on systems over 15 years old produce a replacement opportunity. These are reported as "sales won from service-demand leads", never as acquisition.

## 8. Tracking gaps and noise (applied after the truth is written)

| What | Rate | Effect |
|---|---|---|
| Household rejects analytics cookies | 20% | Its sessions are missing from GA4 |
| UTMs captured into the Salesforce lead (web forms) | 85% | Otherwise no T2 evidence |
| GA client ID captured (web forms) | 60% | Needed for T1 journeys |
| Captures on the booking page (third-party) | 30% | Weaker evidence for bookings |
| GA client ID captured in Sarah chat | 40% | |
| Meta campaign ID present on lead-form / Messenger leads | 90% / 70% | T3 evidence |
| Phone call tracking | 0% | Phone leads are T5, unless… |
| …the CRM LeadSource is filled for phone leads | 50% | …then T4 (channel only); 10% of LeadSource values are wrong or "Other" |
| City typed in a non-standard way | 15% | e.g. "KW", "mississauga on"; 2% unrecognizable |
| Second submission within 72 hours | 6% of leads | Must be deduplicated |
| Second submission after 72 hours | 1% of leads | Must **not** be deduplicated |
| Test leads | 0.5% | Marked by a hypothetical `Is_Test__c` field (?) |
| Exact duplicate GA4 session rows | 0.5% | Dropped at load |
| Meta account timezone | America/Toronto | Tiny config has a mismatch variant (America/Los_Angeles) to test `timezone_mismatch` |

A separate `dirty/` folder holds about 20 deliberately invalid rows per source (negative spend, clicks above impressions, impossible dates, missing IDs, orphan references), each labelled with the error code the loader must report.

## 9. Planted scenarios

| ID | Scenario | When | What MarketingIQ must show | Question |
|---|---|---|---|---|
| S01 | Lead-form promo: cheap but low quality | Oct–Dec each year | Cost per lead well below the median, cost per qualified lead above it | Q6 |
| S02 | Paid search traffic with no spend feed | Always | Strong lead quality, but cost metrics are null with `no_spend_source` | Q7 |
| S03 | Cold snaps | 2025-01-20→26, 2026-02-09→14 | Repair and phone demand up about 3×, acquisition barely moves, attribution coverage drops | Q21 |
| S04 | Creative fatigue on `meta_prospecting_heatpump` | March 2026 | Spend +25%, CTR −35%, qualified leads −30%; change explanation names this campaign | Q17, Q18 |
| S05 | Location-page change | 2026-05-12 | Form submit rate about +20% afterwards; recorded as an annotation; phrased as "coincided" | Q19 |
| S06 | Hidden-field capture breaks | 2026-07-07→16 | Captures drop to 0; data quality must detect it **without** an annotation, and it must not read as a performance drop | Q22, Q23 |
| S07 | Meta reports more leads than the CRM | Always | Shown side by side, never added together | Q14 |
| S08 | Retargeting selection bias | Always | Retargeting gets large last-touch credit; the truth file shows zero true effect (V1 demonstration) | Q13 |
| S09 | New campaign without a mapping | From 2026-06 | Appears as `(unmapped)` and in the unmapped list | Q16 |
| S10 | Billing callback spike | 2026-01-12→31 | Billing callbacks ×4; classified `non_marketing`; cost per lead unaffected | Q20 |
| S11 | Ottawa regional campaign | Sep–Feb | Cost per qualified lead about 1.6× the GTA | Q3, Q4 |
| S12 | Immature recent cohorts | Last ~8 weeks | `immature_cohort` on recent sales metrics | Q10 |
| S13 | Small northern towns | Always | Cells under 5 suppressed | (privacy) |
| S14 | Sarah and Claire leads | Always | Qualification about 0.9× web forms; visible as entry points | Q2 |

Annotations written to `annotations.csv` (things a marketer would know): S03 cold snaps, S05 page change, S10 billing change, campaign launches. S06 is deliberately **not** annotated.

## 10. Output files

```text
data/synthetic/seed-<seed>/
├── meta/insights_daily.csv            # date, account_id, account_timezone, campaign_id, campaign_name,
│                                      # spend, impressions, inline_link_clicks, leads_reported, attribution_setting
├── ga4/sessions.csv                   # user_pseudo_id, ga_session_id, session_start_utc, source, medium,
│                                      # campaign, content, landing_page, device_category, has_gclid, has_fbclid,
│                                      # ev_quote_submit, ev_callback_submit, ev_phone_click, ev_chat_start, ev_booking_click
├── salesforce/leads.csv               # Id, CreatedDate, LeadSource, Status, IsConverted, ConvertedDate,
│                                      # ConvertedOpportunityId, City, Entry_Point__c (?), Request_Type__c (?),
│                                      # Existing_Customer__c (?), Service_Line__c (?), UTM_Campaign__c (?),
│                                      # UTM_Source__c (?), UTM_Medium__c (?), Click_Id_Type__c (?),
│                                      # GA_Client_Id__c (?), Meta_Campaign_Id__c (?), Person_Key__c (?), Is_Test__c (?)
├── salesforce/events.csv              # Id, WhoId, Type, Status, CreatedDate, ActivityDateTime
├── salesforce/opportunities.csv       # Id, CreatedDate, StageName, CloseDate, IsClosed, IsWon, Amount,
│                                      # Amount_Basis__c (?), Service_Line__c (?)
├── clarity/page_daily.csv             # V1: date_utc, url, sessions, bot_sessions, dead_clicks, rage_clicks,
│                                      # quickbacks, excessive_scroll, avg_scroll_depth, script_errors
├── annotations.csv                    # type, start_date, end_date, label
├── dirty/*.csv                        # invalid rows + expected error codes
├── truth/                             # NEVER loaded into the app database
│   ├── households.csv                 # need, intent, true service line, true customer type
│   ├── journeys.csv                   # per lead: all real touches, true first/last campaign, expected tier
│   └── scenarios.json                 # planted scenarios with dates and intended effects
└── manifest.json                      # seed, config hash, generator version, row counts, SHA-256 per file,
                                       # realized noise rates
```

Salesforce-like rows contain **no names, emails, phone numbers or free-text messages**: the quote form's Message field is simply not generated.

## 11. Reproducibility

- One integer seed (default `20261014`). Each part of the simulation (calendar, campaigns, each region's households, noise) gets its own random stream derived from it with NumPy's `SeedSequence.spawn`. Turning a scenario on or off then changes only its own stream, not every row in the dataset.
- **Test:** generating twice with the same seed gives byte-identical files (same SHA-256 in `manifest.json`).
- The generator records the realized rates (e.g. "UTM capture was 84.7%") in the manifest; tests compare loader and transform outputs against these counts.

## 12. What this data can't tell you

- Whether any of these rates resemble LG Home Comfort's reality.
- How real tracking behaves: real gaps will be messier and less tidy than these.
- Anything about the commercial business, existing-customer service operations, or call-centre behaviour beyond the simple rules above.
- Cross-device journeys (not modelled; one household = one device).

Results from this data demonstrate that the software is correct and robust. They are not evidence of marketing performance.
