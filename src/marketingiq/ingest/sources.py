"""The source files the loader knows: where each lives in a dataset folder, which staging
table it lands in, and which columns identify a row."""

from dataclasses import dataclass

from marketingiq.ingest.rows import (
    AnnotationRow,
    CampaignMappingRow,
    Ga4SessionRow,
    MetaInsightsRow,
    SalesforceEventRow,
    SalesforceLeadRow,
    SalesforceOpportunityRow,
    SourceRow,
)


@dataclass(frozen=True)
class Source:
    entity: str  # staging table name
    path: str  # relative path inside a dataset folder
    source_system: str
    row_model: type[SourceRow]
    key: tuple[str, ...]  # field names that identify one row within a file

    def required_columns(self) -> set[str]:
        """Column headers the file must have (fields without a default)."""
        return {
            field.alias or name
            for name, field in self.row_model.model_fields.items()
            if field.is_required()
        }


SOURCES = (
    Source(
        "meta_insights_daily",
        "meta/insights_daily.csv",
        "meta_ads",
        MetaInsightsRow,
        ("report_date", "campaign_id"),
    ),
    Source(
        "ga4_sessions",
        "ga4/sessions.csv",
        "ga4",
        Ga4SessionRow,
        ("user_pseudo_id", "ga_session_id"),
    ),
    Source("sf_leads", "salesforce/leads.csv", "salesforce", SalesforceLeadRow, ("id",)),
    Source("sf_events", "salesforce/events.csv", "salesforce", SalesforceEventRow, ("id",)),
    Source(
        "sf_opportunities",
        "salesforce/opportunities.csv",
        "salesforce",
        SalesforceOpportunityRow,
        ("id",),
    ),
    Source(
        "campaign_mapping_sheet",
        "reference/campaign_mappings.csv",
        "marketing_team",
        CampaignMappingRow,
        ("utm_campaign",),
    ),
    Source(
        "annotations",
        "annotations.csv",
        "marketing_team",
        AnnotationRow,
        ("annotation_type", "start_date", "label"),
    ),
)
