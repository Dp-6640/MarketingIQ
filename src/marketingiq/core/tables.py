"""Core tables: the canonical model the analytics read.

Every table is rebuilt per organization by marketingiq.core.build from the latest staging
batches. Columns that hold canonical values are checked against vocabulary.py. The
hand-written migration 0003 must match these definitions (the drift test checks it).
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from marketingiq.core import vocabulary as vocab
from marketingiq.models import Base

metadata = Base.metadata


def one_of(column: str, values: tuple[str, ...]) -> CheckConstraint:
    allowed = ", ".join(f"'{value}'" for value in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=column)


def _org() -> Column:
    return Column("org_id", SmallInteger, ForeignKey("core.organizations.id"), nullable=False)


def _id() -> Column:
    return Column("id", BigInteger, Identity(), primary_key=True)


campaigns = Table(
    "campaigns",
    metadata,
    _id(),
    _org(),
    Column("key", Text, nullable=False),  # the mapped UTM value, or "meta:<id>" if unmapped
    Column("name", Text, nullable=False),
    Column("platform", Text, nullable=False),
    Column("platform_campaign_id", Text),
    Column("utm_campaign", Text),
    Column("tactic", Text),
    Column("service_lines", ARRAY(Text), nullable=False),
    Column("region", Text),
    Column("in_mapping_sheet", Boolean, nullable=False),
    Column("has_spend_feed", Boolean, nullable=False),
    UniqueConstraint("org_id", "key"),
    schema="core",
)

campaign_identifiers = Table(
    "campaign_identifiers",
    metadata,
    _org(),
    Column(
        "campaign_id",
        BigInteger,
        ForeignKey("core.campaigns.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("kind", Text, nullable=False),
    Column("value", Text, nullable=False),
    PrimaryKeyConstraint("org_id", "kind", "value"),
    Index(None, "campaign_id"),
    one_of("kind", ("meta_campaign_id", "utm_campaign")),
    schema="core",
)

ad_spend_daily = Table(
    "ad_spend_daily",
    metadata,
    _org(),
    Column(
        "campaign_id",
        BigInteger,
        ForeignKey("core.campaigns.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("report_date", Date, nullable=False),  # in the ad account's time zone
    Column("source_tz", Text, nullable=False),
    Column("spend", Numeric(14, 2), nullable=False),
    Column("impressions", BigInteger, nullable=False),
    Column("link_clicks", BigInteger, nullable=False),
    Column("platform_reported_leads", BigInteger, nullable=False),
    Column("attribution_setting", Text, nullable=False),
    PrimaryKeyConstraint("campaign_id", "report_date"),
    Index(None, "org_id", "report_date"),
    schema="core",
)

landing_pages = Table(
    "landing_pages",
    metadata,
    _id(),
    _org(),
    Column("path", Text, nullable=False),
    Column("page_type", Text, nullable=False),
    Column("service_line", Text),
    Column("city", Text),
    UniqueConstraint("org_id", "path"),
    one_of("page_type", vocab.PAGE_TYPES),
    schema="core",
)

web_sessions = Table(
    "web_sessions",
    metadata,
    _id(),
    _org(),
    Column("user_pseudo_id", Text, nullable=False),
    Column("ga_session_id", BigInteger, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("source", Text, nullable=False),
    Column("medium", Text, nullable=False),
    Column("channel", Text, nullable=False),
    Column("campaign_value", Text),  # normalized; None when the visit wasn't tagged
    Column("campaign_id", BigInteger, ForeignKey("core.campaigns.id")),  # None = unmapped
    Column("landing_page_id", BigInteger, ForeignKey("core.landing_pages.id"), nullable=False),
    Column("device", Text, nullable=False),
    Column("has_gclid", Boolean, nullable=False),
    Column("has_fbclid", Boolean, nullable=False),
    Column("ev_quote_submit", BigInteger, nullable=False),
    Column("ev_callback_submit", BigInteger, nullable=False),
    Column("ev_phone_click", BigInteger, nullable=False),
    Column("ev_chat_start", BigInteger, nullable=False),
    Column("ev_booking_click", BigInteger, nullable=False),
    UniqueConstraint("org_id", "user_pseudo_id", "ga_session_id"),
    Index(None, "org_id", "started_at"),
    Index(None, "campaign_id"),
    Index(None, "landing_page_id"),
    one_of("channel", vocab.CHANNELS),
    schema="core",
)

leads = Table(
    "leads",
    metadata,
    _id(),
    _org(),
    Column("source_id", Text, nullable=False),  # Salesforce Id
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("lead_source_raw", Text),
    Column("status_raw", Text, nullable=False),
    Column("stage", Text, nullable=False),
    Column("is_qualified", Boolean, nullable=False),
    Column("qualified_at", DateTime(timezone=True)),
    Column("stage_time_source", Text, nullable=False),
    Column("is_converted", Boolean, nullable=False),
    Column("converted_opportunity_source_id", Text),
    Column("entry_point", Text, nullable=False),
    Column("entry_point_raw", Text),
    Column("request_type", Text, nullable=False),
    Column("request_type_source", Text, nullable=False),
    Column("customer_type", Text, nullable=False),
    Column("customer_type_source", Text, nullable=False),
    Column("service_line", Text, nullable=False),
    Column("service_line_source", Text, nullable=False),
    Column("lead_class", Text, nullable=False),
    Column("junk_reason", Text),
    Column("classification_version", Text, nullable=False),
    Column("city_raw", Text),
    Column("city", Text),
    Column("region", Text),
    Column("city_match", Text, nullable=False),
    Column("person_key", Text),
    Column("is_test", Boolean, nullable=False),
    Column("duplicate_of", BigInteger, ForeignKey("core.leads.id")),
    Column("ga_client_id", Text),
    Column("form_page_path", Text),
    Column("utm_source", Text),
    Column("utm_medium", Text),
    Column("utm_campaign", Text),  # normalized
    Column("click_id_type", Text),
    Column("meta_campaign_source_id", Text),
    Column("evidence_tier", Text),  # None for duplicates: only the first lead is tiered
    Column("evidence_detail", Text),
    Column("evidence_campaign_id", BigInteger, ForeignKey("core.campaigns.id")),
    Column("evidence_channel", Text),
    UniqueConstraint("org_id", "source_id"),
    Index(None, "org_id", "created_at"),
    Index(None, "org_id", "lead_class", "created_at"),
    Index(None, "org_id", "ga_client_id"),
    Index(None, "org_id", "person_key"),
    Index(None, "duplicate_of"),
    Index(None, "evidence_campaign_id"),
    one_of("stage", vocab.LEAD_STAGES),
    one_of("stage_time_source", ("field", "unavailable")),
    one_of("entry_point", vocab.ENTRY_POINTS),
    one_of("request_type", vocab.REQUEST_TYPES),
    one_of("request_type_source", vocab.REQUEST_TYPE_SOURCES),
    one_of("customer_type", vocab.CUSTOMER_TYPES),
    one_of("customer_type_source", vocab.CUSTOMER_TYPE_SOURCES),
    one_of("service_line", (*vocab.SERVICE_LINES, "unknown")),
    one_of("service_line_source", vocab.SERVICE_LINE_SOURCES),
    one_of("lead_class", vocab.LEAD_CLASSES),
    one_of("junk_reason", vocab.JUNK_REASONS),
    one_of("city_match", vocab.CITY_MATCHES),
    one_of("evidence_tier", vocab.EVIDENCE_TIERS),
    one_of("evidence_channel", vocab.REPORTED_CHANNELS),
    schema="core",
)

appointments = Table(
    "appointments",
    metadata,
    _id(),
    _org(),
    Column("source_id", Text, nullable=False),
    Column("lead_id", BigInteger, ForeignKey("core.leads.id")),  # None = no such lead
    Column("lead_source_id", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("kind_raw", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("status_raw", Text),
    Column("booked_at", DateTime(timezone=True), nullable=False),
    Column("scheduled_for", DateTime(timezone=True), nullable=False),
    UniqueConstraint("org_id", "source_id"),
    Index(None, "lead_id"),
    one_of("kind", vocab.APPOINTMENT_KINDS),
    one_of("status", vocab.APPOINTMENT_STATUSES),
    schema="core",
)

opportunities = Table(
    "opportunities",
    metadata,
    _id(),
    _org(),
    Column("source_id", Text, nullable=False),
    Column("lead_id", BigInteger, ForeignKey("core.leads.id")),  # None = no lead converted to it
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("stage_raw", Text, nullable=False),
    Column("outcome", Text, nullable=False),
    Column("close_date", Date, nullable=False),  # actual if closed, expected if open
    Column("amount", Numeric(14, 2)),
    Column("amount_basis", Text, nullable=False),
    Column("amount_basis_raw", Text),
    Column("service_line", Text, nullable=False),
    Column("service_line_raw", Text),
    UniqueConstraint("org_id", "source_id"),
    Index(None, "lead_id"),
    one_of("outcome", vocab.OPPORTUNITY_OUTCOMES),
    one_of("amount_basis", vocab.AMOUNT_BASES),
    one_of("service_line", (*vocab.SERVICE_LINES, "unknown")),
    schema="core",
)

annotations = Table(
    "annotations",
    metadata,
    _id(),
    _org(),
    Column("annotation_type", Text, nullable=False),
    Column("start_date", Date, nullable=False),
    Column("end_date", Date, nullable=False),
    Column("label", Text, nullable=False),
    UniqueConstraint("org_id", "annotation_type", "start_date", "label"),
    schema="core",
)

build_runs = Table(
    "build_runs",
    metadata,
    _id(),
    _org(),
    Column("built_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("batches", JSONB, nullable=False),  # staging table -> load batch id used
    Column("rules", JSONB, nullable=False),  # rule section -> {version, verified}
    Column("summary", JSONB, nullable=False),  # data-quality overview of the build
    Index(None, "org_id", "built_at"),
    schema="core",
)

# Rebuilt on every build, children first (the order deletes must run in).
REBUILT_TABLES = (
    appointments,
    opportunities,
    leads,
    web_sessions,
    landing_pages,
    ad_spend_daily,
    campaign_identifiers,
    campaigns,
    annotations,
)
