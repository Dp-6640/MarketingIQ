# The Oracle: a Second Implementation

The oracle (`src/oracle/`) recomputes MarketingIQ's numbers a second, independent way, so the application can be checked against something other than itself.

```bash
uv run python -m oracle summary data/synthetic/default-seed-20261014
```

## What makes it independent

| | Application | Oracle |
|---|---|---|
| Reads | Staging tables, then the core model in PostgreSQL | The dataset's CSV files directly |
| Written from | Its own design, over several commits | The documents only: `attribution.md`, `lifecycle_and_classification.md`, `metrics.md`, `core-model.md` |
| Style | Set-based SQL, decimals stored to 8 places | One loop per lead, exact fractions |
| Shares | The rule book (`rules.toml`) | The same rule book |

The rule book is shared on purpose. It is configuration (which page means which service line, which lead source means which channel), and two copies of it would only drift apart. Everything that *applies* the rules is written twice.

The oracle never imports `marketingiq`, and it never reads the generator's `truth/` folder. Ground-truth checks are a different question ("does the system recover what really happened?") and live in the core-build tests.

## What it computes

For each lead: entry point, request type and its source, customer type, service line, region, duplicate link, class, qualification, consultation booked and completed, opportunity, won and closed. For each first lead, and each lookback window (7, 30 and 90 days): evidence tier and credit under every model.

`oracle.count` aggregates these the way `metrics.md` defines: credit-weighted lead counts by any lead property or attributed dimension, `paid_*` counts (credit to campaigns with a spend feed), evidence-tier counts, Meta spend, impressions, clicks and reported leads, and GA4 sessions and form-submit sessions.

## How it's used

`tests/integration/test_oracle.py` builds the tiny world and compares the application's raw measurements, before rounding and small-cell suppression, with the oracle's numbers, cell by cell:

- every lead base by every lead property, for three populations;
- every lead base by campaign, channel, platform and tactic, under all 3 models × 3 lookback windows;
- a two-dimension split (campaign × service line);
- evidence tiers, ad-platform measures and sessions.

The same comparison was also run once on the full default dataset (one year of data, 640 comparisons), and every cell agreed.

## What the comparison found

| Finding | Who was wrong | Fix |
|---|---|---|
| Leads with only a click ID (gclid, no UTM) were credited to `(no campaign)` | The application: `attribution.md` puts them under `(unmapped)` | Fixed (`995b15c`); 272 leads on the default dataset |
| Offer pages (`/offers/heat-pump/`) give a service line | The documents didn't say so | `core-model.md` step 5 now does |
| A trailing province is dropped from cities ("Vaughan ON") | The documents only said "cleaned spelling" | `core-model.md` step 6 now spells out the cleaning |
| Exact duplicate GA4 rows | The oracle's first draft (the loader drops them, as documented) | Oracle fixed |

Each disagreement meant a bug or an ambiguous document. Once fixed, both implementations match exactly.

## Limits

- Both implementations share the rule book, so a wrong rule is wrong in both. Only checking against the real systems (`docs/unverified-register.md`) can catch that.
- The display names for empty groups (`(no campaign)`, `(none)`, `(unknown)`) are compared as "no group". The comparison test maps them, and the oracle doesn't reproduce them.
- Rounding, suppression, warnings and period resolution are outside the oracle; they have their own tests.
