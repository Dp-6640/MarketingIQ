# Phase 0 — Decisions and Definitions

## Objective

Agree on the product boundary and the meaning of its measures before implementing analytics. A technically correct query can still produce a misleading answer if population, date basis, attribution model or data coverage is unclear.

## Deliverables

- [x] Product scope and initial canonical question list drafted.
- [x] Metric definitions and null rules drafted.
- [x] Lead lifecycle and deterministic classification drafted.
- [x] Evidence-tiered attribution rules drafted.
- [x] Source-to-canonical data mapping drafted.
- [x] Unverified items and verification methods documented.
- [x] Initial architecture decisions drafted (ADR-001 to ADR-006).
- [x] Every canonical question mapped to tools, metrics and caveats (`question-tool-map.md`).
- [x] Internal contradictions fixed: verified-vs-mapped credit rule, tier precedence, direct-traffic convention, quote-form request type, `unknown` lead class, duplicate handling, small-cell suppression.
- [x] Primary user and Google Ads answered provisionally (2026-10-14): the performance marketing manager is the demo audience, not yet a confirmed user; Google Ads is believed not to be used. Both stay open in the register (U-01, U-10).
- [x] U-20 and U-21 proposals accepted provisionally by the project owner (2026-10-14).
- [ ] Review the definitions with the performance marketing manager during the MVP demo. This happens *after* the build and replaces a pre-build stakeholder review, because this is a side project.

**Phase 0 status:** closed provisionally on 2026-10-14. Everything marked provisional remains `verified=false` in configuration and produces caveats in results.

## Exit criteria

Phase 0 is ready to close when:

1. Every MVP question maps to a metric and a supported analytical tool, or is explicitly out of scope.
2. Every metric has a formula, date basis, population and null/zero-denominator rule.
3. Attribution outputs show evidence coverage and the model used.
4. Unverified CRM fields and source mappings are represented as unverified in configuration and in result caveats.
5. Synthetic data parameters are visibly labelled as assumptions rather than facts about LG Home Comfort.
6. Real company data remains out of scope until its approval gate is met.

## Provisional decisions so work can continue

- Primary user: performance/digital marketing manager; validate this assumption.
- Secondary user: sales or operations manager; validate this assumption.
- Business archetype: Ontario home-services lead generation with downstream consultation/sales outcomes.
- Reporting timezone: `America/Toronto` provisionally.
- Currency: `CAD` provisionally.
- Default analysis population: non-duplicate new-customer acquisition leads.
- Initial attribution lookback: 30 days for matched web journeys.
- Synthetic data horizon: 24 months for year-over-year comparisons.
- Data sources in the MVP simulation: Meta Ads, GA4, Salesforce-style records.
- Microsoft Clarity: V1, aggregate page-level diagnostics only.
- Google Ads spend: unknown; the synthetic scenario should demonstrate what happens when a source appears in GA4 but there is no matching spend feed.

## First concrete action

Open `docs/scope.md`, then `docs/unverified-register.md`. Mark any assumption you know is wrong. We can keep unknowns as explicit placeholders while building the synthetic prototype.
