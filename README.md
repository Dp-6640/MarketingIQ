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
- `docs/synthetic-data.md` — generator assumptions, planted scenarios and output files (all values synthetic).
- `docs/question-tool-map.md` — each canonical question mapped to tools, metrics and expected caveats; seed for the benchmark.
- `docs/source-to-canonical.md` — proposed source mappings and data flow.
- `docs/unverified-register.md` — unknowns, provisional defaults and how to verify them.
- `docs/phase-0-checklist.md` — Phase 0 exit criteria.
- `docs/decisions/` — initial architecture decision records (ADRs).

## Development setup

Requirements: [uv](https://docs.astral.sh/uv/) and PostgreSQL 18 (16+ should work).

1. Create two roles and two databases (as the `postgres` superuser):
   - `miq_owner`: owns `marketingiq` and `marketingiq_test`; runs migrations and loaders.
   - `miq_app`: login role with `CONNECT` only; migrations grant it read access. Set `timezone = 'UTC'` on both roles.
2. Copy `.env.example` to `.env` and fill in the passwords.
3. Install and test:

   ```bash
   uv sync
   uv run pytest            # integration tests skip if TEST_DATABASE_URL is unreachable
   uv run ruff check . && uv run ruff format --check .
   ```

4. Run the API: `uv run uvicorn marketingiq.api.app:app --reload`, then open `http://127.0.0.1:8000/health`.
5. Generate synthetic data: `uv run python -m synthetic generate` writes a fictional 24-month dataset to `data/synthetic/` (ignored by git). See `docs/synthetic-data.md`.

Phase 0 definitions live in `docs/`. No LLM and no company data are part of the project at this stage.

## Data and security principles

- Synthetic data only during initial development.
- Never use real customer records, contact details, chat transcripts or Clarity recordings in the prototype.
- The LLM will see aggregate analytical results only; no person-level rows or unrestricted SQL.
- Platform-reported conversions and CRM outcomes are separate measures and must never be added together.
- Attribution represents assigned credit, not causal proof.
- Any future use of real company data requires explicit approval and a data-readiness review.
