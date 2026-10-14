# ADR-005: Staging → Core → Mart Data Layers

- **Status:** Proposed
- **Decision:** Use separate PostgreSQL schemas. `staging` holds one typed table per source object, shaped like the source export. `core` holds canonical entities and the versioned mapping/config tables. `mart` holds derived outputs such as `lead_attribution_credits`. `app` holds `assistant_runs`. Ground truth lives in a separate schema or database that the application role can't read.
- **Context:** The long-term goal is to swap synthetic files for approved real exports from Meta, GA4 and Salesforce without touching analytics code. Source formats aren't verified (U-02, U-09, U-16), so the adapter boundary has to be explicit.
- **Consequences:** Replacing a source means writing a new loader and transform into `core`; analytics, tools and tests don't change. It costs more tables and a transform step than loading straight into canonical tables. Transforms are plain SQL plus Python run from a CLI; dbt is not used unless the number of transforms grows substantially.
