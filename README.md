# MarketingIQ — Phase 0 Starter Pack

**Project:** AI Marketing Intelligence & Attribution Platform  
**Business context:** LG Home Comfort (`lghomecomfort.ca`)  
**Specification baseline:** v0.2, 14 October 2026  
**Status:** Phase 0 — lock definitions before implementing the backend

MarketingIQ is a proposed **internal, read-only marketing intelligence assistant** for LG Home Comfort. It will use synthetic data first, then may be adapted to approved and appropriately de-identified company data after governance and data-readiness checks.

> **Scope boundary:** This project is for LG Home Comfort only. It has no connection to The RO brand or website.
>
> **Status:** a personal side project, not commissioned or endorsed by LG Home Comfort. It will be demoed to the performance marketing manager, and scaling up depends on their approval. Keep the repository private, and don't publish it or use the company name publicly until that's cleared (see U-23).

## What this first pack contains

- `docs/scope.md` — product goal, intended users, MVP boundaries and canonical questions.
- `docs/metrics.md` — metric definitions and reporting rules.
- `docs/lifecycle_and_classification.md` — lead lifecycle and deterministic lead classification.
- `docs/attribution.md` — attribution evidence tiers and model rules.
- `docs/question-tool-map.md` — each canonical question mapped to tools, metrics and expected caveats; seed for the benchmark.
- `docs/source-to-canonical.md` — proposed source mappings and data flow.
- `docs/unverified-register.md` — unknowns, provisional defaults and how to verify them.
- `docs/phase-0-checklist.md` — Phase 0 exit criteria.
- `docs/decisions/` — initial architecture decision records (ADRs).

## Recommended next steps

1. Read `docs/scope.md` and check whether the intended users and business questions match the problem you want to solve.
2. Review `docs/unverified-register.md`. Unknown company configuration is intentionally marked as unverified; we will not invent it.
3. Once Phase 0 definitions are stable, create the Python backend, PostgreSQL setup, synthetic generator and loader.

No dependencies need to be installed for this documentation-only pack. We are deliberately not putting an LLM or live company data into the project at this stage.

## Data and security principles

- Synthetic data only during initial development.
- Never use real customer records, contact details, chat transcripts or Clarity recordings in the prototype.
- The LLM will see aggregate analytical results only; no person-level rows or unrestricted SQL.
- Platform-reported conversions and CRM outcomes are separate measures and must never be added together.
- Attribution represents assigned credit, not causal proof.
- Any future use of real company data requires explicit approval and a data-readiness review.
