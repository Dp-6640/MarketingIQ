# ADR-004: Aggregate-Only LLM Boundary

- **Status:** Proposed
- **Decision:** The LLM receives only validated aggregate tool results and safe labels. Tools do not return contact information, raw CRM rows, person keys, chat transcripts or raw session recordings. No unrestricted text-to-SQL in the MVP.
- **Context:** Marketing/CRM data may be commercially sensitive, and campaign names or tracking parameters are untrusted input.
- **Consequences:** Lower data exposure and a more testable answer path. Small-cell suppression, output validation and a privacy scan are required; aggregates may still be confidential and need approval before real-data use.
