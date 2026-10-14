# Unverified Register

This register is a safeguard against turning plausible assumptions into company facts. Synthetic defaults exist only to make development possible. Before real-data use, each applicable row needs an owner, verification evidence and an updated status.

| ID | Unverified item | Why it matters | How to verify | Synthetic default for now |
|---|---|---|---|---|
| U-01 | Primary internal user | Determines questions and workflow priority | Validate during the demo to the performance marketing manager (2026-10-14: personal side project; the manager is the first audience, not yet a confirmed user) | Performance marketing manager; secondary sales/operations user |
| U-02 | Salesforce Lead/Opportunity custom fields and picklists | Lifecycle, qualification and classification | Review object/field/picklist metadata, not customer records | Plausible source values with `verified=false` mappings |
| U-03 | Whether stage history timestamps are tracked | Time-to-qualification and maturity | Check field history settings and available date fields | Some timestamps unavailable; never infer missing dates |
| U-04 | Appointment source and sync (Salesforce Event, Calendly or other) | Consultation metrics | Confirm with sales operations and integration settings | Salesforce-style appointment rows for synthetic data only |
| U-05 | Opportunity Amount meaning | ROAS and revenue comparison | Confirm with finance/sales documentation | Mixed amount bases; ROAS caveated or suppressed |
| U-06 | Hidden-field capture of UTM, GA client ID and click IDs | T1/T2 attribution coverage | Inspect form/chat implementation and corresponding Salesforce fields | Configurable synthetic capture rates and outages |
| U-07 | Meta Lead Ads/Messenger campaign IDs reach Salesforce | T3 evidence tier | Review connector field mapping with a small approved test | IDs present on a configurable proportion of synthetic records |
| U-08 | Phone call tracking | Phone-lead attribution | Confirm tracking provider, numbers and CRM fields | Phone leads without identifiers are T5 unattributed |
| U-09 | GA4 BigQuery export enabled | Session-level attribution and historical availability | GA4 admin checks product links and export configuration | Synthetic GA4 session export; no real data assumption |
| U-10 | Google Ads in use and spend export availability | Cost metrics for Google paid search | Confirm with the performance marketing manager (2026-10-14: project owner believes it isn't used, unconfirmed) | No Google Ads campaigns. One generic "paid-looking traffic with no spend feed" scenario stays in the generator as a data-quality test, because `no_spend_source` handling is needed for any unknown paid source. |
| U-11 | Reporting timezones for Meta, GA4, Salesforce and Clarity | Day-level joins and comparisons | Check account/property/org settings | `America/Toronto` reporting timezone; include a mismatch scenario |
| U-12 | Sales cycle and deal-value distributions by service line | Cohort maturity and revenue modelling | Analyse approved de-identified exports after approval | Clearly labelled synthetic distributions only |
| U-13 | Clarity masking and export settings | Privacy and page-level diagnostics | Review project settings and current official docs | V1 only; aggregate page-level synthetic data, no recordings |
| U-14 | LLM provider approval, retention and data region | Determines whether any company-derived data can be sent to a model | Privacy/security review of provider terms and approved deployment | Synthetic aggregate data only; one provider behind an interface |
| U-15 | Privacy Officer approval/legal basis for CRM analytics and LLM processing | Required before real-data use | Formal review and written authorization | No genuine company data in development |
| U-16 | Source completeness and event naming in GA4 | Reconciliation interpretation | Review event definitions, tag setup and export coverage | Synthetic event names, marked as examples |
| U-17 | Campaign mapping between platform IDs and UTMs | Campaign-level cost and credit | Compare approved export schemas and campaign naming rules | Versioned synthetic mappings, with unmapped cases and `verified=false` flag |
| U-18 | City aliases and region mapping | Geographic reporting and small-cell risks | Validate an approved normalization list | Synthetic alias file, versioned; unknown city retained as unknown |
| U-19 | Real-data access route and owner | Whether real-world validation is feasible | Request approved export and integration process | No API credentials or production connectors in MVP |
| U-20 | Request type for leads without a structured field (quote form, booking, Meta lead forms, phone, chat) | Decides how many leads count as acquisition | Ask sales ops how these enquiries are typed in Salesforce; check whether a CRM request-type field exists | Quote form and booking default to `install_replace`; Meta lead forms use campaign tactic; others `unknown` (see lifecycle_and_classification.md). Accepted provisionally by the project owner 2026-10-14; business confirmation still needed. |
| U-21 | Business treatment of repair-to-replacement sales, maintenance-plan purchases and existing-customer upgrades | Acquisition boundary and sales attribution | Confirm with marketing and sales leadership | Proposals in lifecycle_and_classification.md; service-demand sales reported separately. Accepted provisionally by the project owner 2026-10-14; business confirmation still needed. |
| U-22 | Campaign naming convention (tactic, service line, region in campaign names) | Retargeting/prospecting questions and campaign-level filters | Review an approved list of campaign names and naming rules | Synthetic names follow a documented convention; tactic mapping `verified=false` |
| U-23 | Permission to name LG Home Comfort in the project, publish the repository, or use it in a public portfolio; ownership of the work under employment terms | A personal side project modelled on the employer's business | Check the employment agreement, and ask the manager before publishing anything | Private repository; company named only in private docs; a public version, if any, says "an Ontario home-services company" until approved |

## Real-data gates

- **R0 — Governance:** written approval of purpose, field allowlist, de-identification, storage, LLM boundary and retention. Do not load company data before this gate.
- **R1 — Readiness:** run a local-only audit of approved de-identified exports; no LLM. Measure identifier capture, mapping coverage, stage timestamp availability, duplicates, timezone consistency and reconciliation gaps.
- **R2 — Controlled integration:** read-only credentials with least privilege; compare imported totals with source system reports.
- **R3 — Operational approval:** approved provider/hosting, authentication/roles, logging, retention and security review.

A synthetic prototype does not require R0 because it contains no company records. The approval process should begin only if/when a real-data pilot is planned.

**Time-sensitive exception (configuration questions, not data access):** GA4's BigQuery export (U-09) and Clarity's data export (U-13) can't be backfilled. GA4 exports only from the day the link is created, and the Clarity API returns only the last 1–3 days. If a real-data pilot is likely later, it's worth asking early whether the BigQuery export is already enabled, because every month without it is journey history that will never exist. Asking that question involves no company records.
