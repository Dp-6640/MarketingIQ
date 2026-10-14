# MarketingIQ — Product Scope (Draft v0.2)

## 1. Product statement

MarketingIQ is an **internal, read-only GenAI marketing intelligence assistant** for LG Home Comfort's marketing and sales/operations stakeholders. It analyses campaign spend, website behaviour, lead quality, consultations and recorded sales outcomes. It uses deterministic Python/SQL services for calculations and an LLM to interpret questions, select approved tools and explain results using evidence.

It complements the existing customer-facing enquiry journeys and agents; it does not contact customers, replace customer-facing agents, write to Salesforce or advertising platforms, or make budget changes.

## 2. Business context

LG Home Comfort is a home-services business with quote-driven and service-related customer journeys. Enquiries may arrive through website quote forms, callback forms, bookings, phone, web chat, Meta lead forms or Meta messaging. Some submissions are existing-customer requests, service/repair needs, billing questions or other non-acquisition activity. These must not be blended into new-customer acquisition metrics.

Source context supplied for this project: Meta Ads, GA4, Salesforce and Microsoft Clarity. Availability of specific fields, exports and join keys has not yet been verified.

## 3. Intended users (assumptions to validate)

**Project context:** a personal side project by a web developer at LG Home Comfort. It is not commissioned or endorsed by the company. Its first audience is a demo to the performance marketing manager; whether it scales up depends on their approval. The users below are therefore the *intended* users, to be validated during that demo.

- **Primary:** performance/digital marketing manager reviewing campaigns weekly.
- **Secondary:** sales or operations manager reviewing lead quality, consultations and recorded sales outcomes.
- **Later:** leadership receiving a regular evidence-backed brief.

## 4. MVP goal

Given reproducible synthetic data, an authorized internal user can ask questions about acquisition quality, efficiency, funnel outcomes, attribution coverage, source reconciliation and period changes. Every answer must:

- report the resolved date range and comparison period;
- state the population being analysed (default: `acquisition`);
- identify the attribution model when campaign-attributed metrics are used;
- show evidence coverage and deterministic data-quality caveats;
- use only backend-computed metrics for numbers;
- distinguish observed facts from hypotheses and recommendations;
- ask for clarification or abstain where the data cannot answer;
- avoid exposing person-level or contact information.

## 5. MVP included

1. Seeded synthetic generator representing 24 months of home-services demand and marketing activity.
2. Source-shaped synthetic datasets for Meta campaign insights, GA4 session exports and Salesforce-style leads/appointments/opportunities. Ground-truth data is kept separate from application-accessible data.
3. Validating, repeatable staging loaders, deduplication, rejected-row report and load-batch audit.
4. Configurable, versioned source mappings, city/region normalization, stage mapping, channel rules, deterministic lead classification and attribution evidence tiers.
5. Deterministic metrics, funnel analytics, YoY and previous-period comparisons, attribution comparison, source reconciliation, data-quality reporting and change decomposition.
6. FastAPI REST endpoints and a single-turn assistant endpoint.
7. A small set of typed, read-only analytical tools; no unrestricted text-to-SQL.
8. A benchmark and independent oracle before the real LLM integration is treated as complete.
9. Aggregate-only assistant outputs, small-cell suppression and run traces.
10. A minimal demo page (question box, rendered answer, evidence table, caveats, "synthetic data" banner) so the MVP can be shown to the performance marketing manager without Swagger. This was moved forward from V1 because the manager demo is the project's decision point.

## 6. V1 and later

- V1: aggregate Microsoft Clarity daily page-level friction summaries; fuller React UI with charts and a trace viewer; auth/roles; synthetic demo deployment; weekly written brief; data-readiness CLI for approved, de-identified exports.
- Advanced: real read-only connectors, subject to approval; text-to-SQL comparison experiment; service-line classification from free-text messages after governance review; causal/incrementality demonstration; advanced attribution models.

## 7. Explicitly excluded from MVP

- Real company data or live integrations.
- Customer-facing chatbot functionality.
- Writing to Salesforce, Meta Ads or campaign budgets.
- Chat/call transcripts, PII, contact details or raw session recordings.
- Clarity session-level joins to leads; Clarity remains page-level and diagnostic.
- Forecasting and claims of causal marketing lift.
- Data-driven/Markov attribution.
- Multi-currency.
- Treating platform-reported conversions as the same thing as CRM outcomes.

## 8. Canonical questions

### Acquisition quality
1. Which campaigns received credit for the most qualified new-customer acquisition leads last month?
2. What is the qualified-lead rate by entry point: quote form, callback, booking, phone, web chat, Meta messaging or Meta lead form?
3. How do qualified acquisition leads by service line and region compare with the same period last year?

### Efficiency
4. What is the cost per qualified lead by Meta campaign?
5. What is the cost per completed consultation by campaign where spend is available?
6. Which campaigns have low cost per raw lead but high cost per qualified lead?
7. Where can we not calculate a cost metric, and why is spend missing?

### Funnel and outcomes
8. Which campaign-attributed lead cohorts progressed to completed consultations or won sales?
9. How does the funnel compare across furnace, heat pump and water-related service lines?
10. Which recent lead cohorts are too immature for a reliable outcome comparison?

### Attribution and evidence
11. How does campaign credit differ between first-touch, last-non-direct and linear attribution?
12. What share of acquisition leads can be attributed to a campaign, and what evidence supports it?
13. How much credit does retargeting receive under each attribution model?

### Source reconciliation
14. How do Meta-reported leads compare with Salesforce-recorded leads by campaign where mapping exists?
15. How do GA4 form-submit events compare with CRM leads over the same period?
16. Which campaigns or UTM values could not be mapped?

### Performance changes
17. What factors contributed to the change in cost per qualified lead in a selected month?
18. Where did spend rise while qualified leads fell?
19. Did a landing-page change coincide with a change in form-submit rate?

### Population and data limits
20. How many records are existing-customer or service requests rather than acquisition leads?
21. During a recorded demand event (e.g. a cold snap logged as an annotation), did service demand rise rather than new-customer acquisition?
22. What can't we conclude about the selected period, and why?
23. Is source data incomplete for the selected period?

### V1 — Clarity
24. Which high-traffic landing pages show elevated rage-click or dead-click signals?
25. Did page-level friction signals change after a landing-page redesign?

Questions about service-line labels, source mappings or Salesforce lifecycle stages must include a caveat whenever the mappings have not been verified.

The tool, metrics and caveats behind each question are in `question-tool-map.md`.

## 9. Definition of success

The MVP is successful when the synthetic-data flow runs end to end; deterministic analytics tests pass; the assistant benchmark measures tool, argument, factuality, refusal and privacy behaviour; ungrounded numeric claims are structurally prevented and tested; and the README explains the architecture, assumptions, evaluation results and limitations.

Synthetic benchmark performance is not proof of business impact or accuracy on real LG Home Comfort data.
