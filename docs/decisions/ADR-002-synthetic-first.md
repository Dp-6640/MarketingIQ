# ADR-002: Synthetic-First Development

- **Status:** Proposed
- **Decision:** Build and test with reproducible, clearly labelled synthetic datasets before loading genuine company records or enabling live connectors.
- **Context:** Source fields, join coverage, CRM stages, timezone settings and data-processing approval are not yet verified.
- **Consequences:** The team can build deterministic analytics and benchmarks now. Synthetic results demonstrate technical correctness only; they do not prove real-data readiness or business impact.
- **Follow-up:** Keep generator ground truth inaccessible to the application, and document every synthetic assumption.
