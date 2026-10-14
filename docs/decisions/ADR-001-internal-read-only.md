# ADR-001: Internal, Read-Only Product Boundary

- **Status:** Proposed
- **Decision:** MarketingIQ is an internal analytical assistant. MVP tools are read-only; the app will not contact customers, update CRM records, adjust budgets or execute marketing actions.
- **Context:** The business already has customer-facing enquiry flows and AI agents. The distinct need is internal understanding of marketing performance and downstream lead quality.
- **Consequences:** Smaller safety surface, easier evaluation, and clearer separation from customer-facing systems. Real deployment still requires approval and proper identity/access controls.
