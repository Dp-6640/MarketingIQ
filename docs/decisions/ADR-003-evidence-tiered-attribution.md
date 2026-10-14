# ADR-003: Evidence-Tiered Attribution

- **Status:** Proposed
- **Decision:** Return attribution credit together with the evidence tier and coverage. Use session-level first-touch, last-non-direct and linear models only when a matching journey is available. Lower-evidence records receive single-touch, channel-only or unattributed treatment as documented in `../attribution.md`.
- **Context:** Phone, native Meta leads and other journeys may not have a GA4-linked session history. A single model cannot honestly imply equal evidence for every lead.
- **Consequences:** Reports can explain how much is attributable and how reliable the available evidence is. Attribution remains credit assignment, not proof of causation.
