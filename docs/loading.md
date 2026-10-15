# Loading Source Files into Staging

The loader reads source files into the `staging` schema without changing their meaning. Each row is validated, invalid rows are kept with a named reason, and every file load is recorded in `core.load_batches`.

```bash
uv run python -m marketingiq.ingest load data/synthetic/default-seed-20261014   # generated dataset
uv run python -m marketingiq.ingest load path/to/folder --org <slug>             # any other folder
```

A generated dataset carries `manifest.json`, which describes its organization; the loader creates or updates that organization. Any other folder needs `--org` naming an organization that already exists.

## What happens to each file

1. **Hash.** The file's SHA-256 is computed. If the same file already loaded successfully into the same table for the same organization, it's skipped.
2. **Header check.** Every required column must be present, or the whole file fails (recorded as a failed batch with the reason). Extra columns are ignored.
3. **Row checks.** Each row is validated by its row model in `src/marketingiq/ingest/rows.py`. Empty cells count as missing.
4. **Duplicates.** A row identical to an earlier row in the same file is counted as a duplicate and skipped. A row with the same key but different values is rejected as `conflicting_duplicate`.
5. **One transaction.** The batch row, the valid rows (bulk-inserted with PostgreSQL `COPY`) and the rejected rows commit together. A failure leaves nothing half-loaded.

One file failing doesn't stop the others. The command exits with status 1 if any file failed.

**Snapshot semantics:** each file is treated as a full export of its source. Staging keeps every batch; the core step will read the latest successful batch per table.

## Files and staging tables

| File in the dataset folder | Staging table | One row per |
|---|---|---|
| `meta/insights_daily.csv` | `staging.meta_insights_daily` | date + campaign id |
| `ga4/sessions.csv` | `staging.ga4_sessions` | user pseudo id + GA session id |
| `salesforce/leads.csv` | `staging.sf_leads` | Salesforce Id |
| `salesforce/events.csv` | `staging.sf_events` | Salesforce Id |
| `salesforce/opportunities.csv` | `staging.sf_opportunities` | Salesforce Id |
| `reference/campaign_mappings.csv` | `staging.campaign_mapping_sheet` | utm_campaign |
| `annotations.csv` | `staging.annotations` | type + start date + label |

Column names are the source headers in snake_case (`CreatedDate` → `created_date`); a few avoid SQL keywords (`date` → `report_date`, `Type` → `event_type`, `type` → `annotation_type`). Salesforce custom fields (`__c`) are all optional, because their existence is unverified (U-02). Clarity files are V1 and aren't loaded yet. Files under `truth/` are never read.

The staging tables are built from the row models (`src/marketingiq/ingest/staging.py`), and the hand-written migration must match them; a test fails if they drift apart.

## Error codes

Every rejected row is stored in `core.rejected_rows` with its raw values and a list of `{field, code, message}`.

| Code | Meaning |
|---|---|
| `missing_required` | A required value is empty |
| `invalid_number` | Not a number, or too many digits |
| `negative_value` | A count or amount below zero |
| `invalid_date` | Not a valid YYYY-MM-DD date |
| `invalid_timestamp` | Not a valid timestamp with a time zone |
| `invalid_boolean` | Not true or false |
| `invalid_salesforce_id` | Not a 15- or 18-character Salesforce id |
| `clicks_exceed_impressions` | More link clicks than impressions |
| `conversion_mismatch` | IsConverted disagrees with ConvertedOpportunityId |
| `won_but_not_closed` | IsWon is true but IsClosed is false |
| `end_before_start` | An annotation ends before it starts |
| `conflicting_duplicate` | Same key as an earlier row in the file, different values |
| `malformed_row` | More values than the header has columns |
| `invalid_value` | Any other invalid value (a test makes sure the fixtures never need it) |

The hand-written fixtures in `tests/fixtures/dirty/` hold one problem per row; `expected_errors.csv` lists the code each must get.

## What staging deliberately doesn't check

These belong to the core step, because they need more than one row or a business rule:

- Links between files (an event's `WhoId` pointing at a lead that doesn't exist).
- Picklist values, city spellings, campaign mapping and lead classification.
- Duplicate leads from the same person across different submissions.
- Time-zone consistency between sources.

## Before any real data

`core.rejected_rows.raw` stores rows exactly as they arrived. Real exports must therefore be cut down to the approved field allowlist **before** loading, so no personal data can ever reach the database (see the R0–R3 gates in `unverified-register.md`).
