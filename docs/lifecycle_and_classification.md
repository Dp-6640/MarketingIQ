# Lead Lifecycle and Classification Rules

## Purpose

MarketingIQ must not treat every enquiry as a new sales opportunity. This draft separates new-customer acquisition from service demand, existing-customer activity and non-marketing submissions. The rules are deterministic and versioned; any use of unverified CRM values must be marked as such.

## Proposed canonical lifecycle

`enquiry/lead created → qualified or disqualified → consultation booked → consultation completed/no-show/cancelled → opportunity → won/lost`

Not every service line follows every stage. For example, a security product or maintenance plan may not use the same in-home consultation path as a furnace replacement. Preserve missing stages as missing; do not fabricate milestones.

## Entry point enum (proposed)

- `web_quote_form`
- `web_callback_form`
- `booking`
- `phone`
- `web_chat_agent`
- `meta_messaging_agent`
- `meta_lead_form`
- `email_sms`
- `other`
- `unknown`

These are canonical categories, not a claim about exact Salesforce picklist values.

## Request type enum (proposed)

- `install_replace`
- `repair_service`
- `maintenance`
- `sales_general`
- `billing`
- `customer_service`
- `non_sales_form`
- `other`
- `unknown`

### Where request type comes from

Track `request_type_source`: `form_field`, `entry_point_default`, `campaign`, `crm_field` or `unknown`.

The public quote form collects only name, phone, email, city and a free-text message, so it has **no structured request type**. Without a default, most quote-form leads would classify as `unknown` and drop out of acquisition. Proposed rules (all `verified=false`, register U-20):

| Entry point | Request type | Source |
|---|---|---|
| `web_callback_form` | From the public dropdown: Installation → `install_replace`; Service & Repair → `repair_service`; Billing → `billing`; Customer Service → `customer_service`; Sales → `sales_general`; Other → `other` | `form_field` |
| `web_quote_form` | `install_replace` | `entry_point_default` |
| `booking` (free in-home assessment) | `install_replace` | `entry_point_default` |
| `meta_lead_form` | From the campaign's `tactic`/objective mapping, else `unknown` | `campaign` |
| `phone`, `web_chat_agent`, `meta_messaging_agent`, others | A CRM field if one exists, else `unknown` | `crm_field` / `unknown` |

Whenever an acquisition figure includes leads whose request type came from `entry_point_default` or `campaign`, the result carries `classification_default_applied`, and data quality reports that share.

**Known effect, found by the ground-truth tests:** a non-sales submission sent through the quote form (for example a nomination) gets the `install_replace` default and is classed as acquisition. In the synthetic data that's 66 of 4,300 acquisition leads (1.5%). Only the free-text message, which is never read, would tell them apart; a real fix needs a form-type field or a separate nomination form. See `docs/core-model.md`.

## Service line enum (proposed)

- `furnace`
- `air_conditioner`
- `heat_pump`
- `water_heater`
- `water_treatment`
- `air_quality`
- `security`
- `generator`
- `maintenance_plan`
- `unknown`

Derive service line from a structured field where available. Otherwise use a versioned landing-page or campaign mapping. Do not send free-text customer messages to an LLM in the MVP.

## Customer type

- `new`
- `existing`
- `unknown`

Track the evidence source: `self_reported`, `crm_match` or `unknown`. Unknown must remain visible rather than silently being treated as known new or existing.

## Deterministic lead classification (draft)

`lead_class` enum: `acquisition`, `existing_customer_sales`, `service_demand`, `non_marketing`, `junk`, `unknown`. Junk rows also carry `junk_reason`: `test`, `invalid` or `duplicate`.

Apply ordered rules, and store the rule version:

1. Explicit test submissions, invalid junk, and duplicate submissions → `junk`.
2. `billing`, `customer_service` or non-sales/nomination form → `non_marketing`.
3. `repair_service` or `maintenance` → `service_demand`.
4. Install/replacement/general sales explicitly marked existing customer → `existing_customer_sales`.
5. Install/replacement/general sales with customer type `new` or `unknown` → `acquisition`; report the unknown-customer share separately.
6. Anything else (`other`, `unknown` request type) → `unknown` until a verified rule classifies it. `unknown` is excluded from acquisition and always reported in data quality.

The ordering is intentional: billing/service/non-sales submissions must not enter acquisition efficiency calculations merely because a form was submitted. Rules must be unit-tested, and actual mappings require stakeholder verification before being applied to real CRM data.

### Open classification questions (business decisions, register U-21)

- **Repair-to-replacement.** In HVAC, a repair visit often ends in a replacement sale. Rule 3 keeps such leads in `service_demand`, so the sale never appears in acquisition metrics. MVP proposal: keep the rule, but report "sales won from service-demand leads" as a separate measure so this path stays visible.
- **Maintenance plan purchase vs maintenance visit.** Buying a maintenance plan is a sale; booking a tune-up is service. Both currently map to `maintenance`. MVP proposal: a new customer buying a plan (`service_line = maintenance_plan` with `request_type = sales_general`) is `acquisition`; a tune-up request is `service_demand`.
- **Existing customers upgrading.** Rule 4 keeps them out of acquisition by design. Confirm the business also sees them this way.

## Deduplication

Synthetic data can include repeat quote/callback submissions from the same pseudonymous household and explicit test leads. The proposed duplicate window is 72 hours for matching pseudonymous person keys, but this is a **synthetic default only**. Real-world deduplication must be reviewed against actual CRM behaviour and must not use fuzzy IP matching. Preserve the source rows for audit rather than silently deleting history.

Within a duplicate group, the **earliest** lead is canonical: it keeps its entry point, classification and attribution evidence, and later submissions become `junk` with `junk_reason = duplicate` and a `duplicate_of` reference. Evidence from later duplicates is not merged into the canonical lead in the MVP; reconsider once real duplicate behaviour has been observed.

## Consultation and opportunity rules

- Distinguish in-home consultation from service visit.
- Appointment source (Salesforce Event, Calendly or other) is unverified.
- Use canonical `booked`, `completed`, `cancelled`, `no_show` statuses only after explicit mapping.
- Link opportunities through verified Salesforce relationships. Do not assume every lead converts into exactly one opportunity.
- Keep opportunity outcome separate from raw platform conversion metrics.
- Opportunity amount basis is unverified. Do not report combined ROAS across purchase price, financed total, lease contract and monthly-payment measures.

## Acceptance tests to write later

- Billing/customer-service submissions never count as acquisition leads.
- Existing-customer repairs do not inflate new-customer acquisition.
- Test and duplicate leads are excluded from acquisition counts but visible in data-quality results.
- Unknown classifications are surfaced explicitly.
- Quote-form and booking leads classify as acquisition through the entry-point default, and the result carries `classification_default_applied`.
- In a duplicate group only the earliest lead counts; later ones are `junk` with `duplicate_of` set.
- A missing stage timestamp stays null and carries an appropriate caveat.
- Every appointment/opportunity mapping can be traced to a versioned rule.
