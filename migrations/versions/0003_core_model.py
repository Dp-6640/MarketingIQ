"""Core model: campaigns, spend, landing pages, sessions, leads, appointments,
opportunities, annotations and build runs.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Canonical values as of this revision. Literal copies on purpose: a migration must keep
# meaning the same thing even after the application's vocabulary changes.
SERVICE_LINES = (
    "furnace", "air_conditioner", "heat_pump", "water_heater", "water_treatment",
    "air_quality", "security", "generator", "maintenance_plan",
)  # fmt: skip
ENTRY_POINTS = (
    "web_quote_form", "web_callback_form", "booking", "phone", "web_chat_agent",
    "meta_messaging_agent", "meta_lead_form", "email_sms", "other", "unknown",
)  # fmt: skip
REQUEST_TYPES = (
    "install_replace", "repair_service", "maintenance", "sales_general", "billing",
    "customer_service", "non_sales_form", "other", "unknown",
)  # fmt: skip
LEAD_STAGES = (
    "new", "working", "qualified", "disqualified", "converted", "invalid",
    "service_scheduled", "closed_no_action", "unknown",
)  # fmt: skip
CHANNELS = (
    "organic_search", "paid_search", "paid_social", "organic_social", "direct",
    "referral", "email", "other",
)  # fmt: skip
REPORTED_CHANNELS = (
    *CHANNELS, "search_unspecified", "social_unspecified", "offline_media", "word_of_mouth",
)  # fmt: skip
EVIDENCE_TIERS = (
    "T1_journey", "T2_captured_source", "T3_platform_native", "T4_self_reported_channel",
    "T5_none",
)  # fmt: skip
LEAD_CLASSES = (
    "acquisition", "existing_customer_sales", "service_demand", "non_marketing", "junk",
    "unknown",
)  # fmt: skip
PAGE_TYPES = ("home", "service", "location", "offer", "quote", "careers", "blog", "other")
CITY_MATCHES = ("exact", "normalized", "alias", "region_only", "blank", "unrecognized")
AMOUNT_BASES = ("purchase_price", "financed_total", "lease_contract", "monthly", "unknown")
TABLES = (
    "build_runs",
    "annotations",
    "opportunities",
    "appointments",
    "leads",
    "web_sessions",
    "landing_pages",
    "ad_spend_daily",
    "campaign_identifiers",
    "campaigns",
)


def _one_of(table: str, column: str, values: tuple[str, ...]) -> sa.CheckConstraint:
    allowed = ", ".join(f"'{value}'" for value in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=f"ck_{table}_{column}")


def _id() -> sa.Column:
    return sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False)


def _org(table: str) -> tuple[sa.Column, sa.ForeignKeyConstraint]:
    return (
        sa.Column("org_id", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id"], ["core.organizations.id"], name=f"fk_{table}_org_id_organizations"
        ),
    )


def _text(name: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.Text(), nullable=nullable)


def _tz(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _index(table: str, *columns: str) -> None:
    op.create_index(f"ix_{table}_{'_'.join(columns)}", table, list(columns), schema="core")


def upgrade() -> None:
    op.create_table(
        "campaigns",
        _id(),
        *_org("campaigns"),
        _text("key", nullable=False),
        _text("name", nullable=False),
        _text("platform", nullable=False),
        _text("platform_campaign_id"),
        _text("utm_campaign"),
        _text("tactic"),
        sa.Column("service_lines", postgresql.ARRAY(sa.Text()), nullable=False),
        _text("region"),
        sa.Column("in_mapping_sheet", sa.Boolean(), nullable=False),
        sa.Column("has_spend_feed", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_campaigns"),
        sa.UniqueConstraint("org_id", "key", name="uq_campaigns_org_id_key"),
        schema="core",
    )

    op.create_table(
        "campaign_identifiers",
        *_org("campaign_identifiers"),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        _text("kind", nullable=False),
        _text("value", nullable=False),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["core.campaigns.id"],
            name="fk_campaign_identifiers_campaign_id_campaigns",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("org_id", "kind", "value", name="pk_campaign_identifiers"),
        _one_of("campaign_identifiers", "kind", ("meta_campaign_id", "utm_campaign")),
        schema="core",
    )

    op.create_table(
        "ad_spend_daily",
        *_org("ad_spend_daily"),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        _text("source_tz", nullable=False),
        sa.Column("spend", sa.Numeric(14, 2), nullable=False),
        sa.Column("impressions", sa.BigInteger(), nullable=False),
        sa.Column("link_clicks", sa.BigInteger(), nullable=False),
        sa.Column("platform_reported_leads", sa.BigInteger(), nullable=False),
        _text("attribution_setting", nullable=False),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["core.campaigns.id"],
            name="fk_ad_spend_daily_campaign_id_campaigns",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("campaign_id", "report_date", name="pk_ad_spend_daily"),
        schema="core",
    )
    _index("ad_spend_daily", "org_id", "report_date")

    op.create_table(
        "landing_pages",
        _id(),
        *_org("landing_pages"),
        _text("path", nullable=False),
        _text("page_type", nullable=False),
        _text("service_line"),
        _text("city"),
        sa.PrimaryKeyConstraint("id", name="pk_landing_pages"),
        sa.UniqueConstraint("org_id", "path", name="uq_landing_pages_org_id_path"),
        _one_of("landing_pages", "page_type", PAGE_TYPES),
        schema="core",
    )

    op.create_table(
        "web_sessions",
        _id(),
        *_org("web_sessions"),
        _text("user_pseudo_id", nullable=False),
        sa.Column("ga_session_id", sa.BigInteger(), nullable=False),
        _tz("started_at"),
        _text("source", nullable=False),
        _text("medium", nullable=False),
        _text("channel", nullable=False),
        _text("campaign_value"),
        sa.Column("campaign_id", sa.BigInteger(), nullable=True),
        sa.Column("landing_page_id", sa.BigInteger(), nullable=False),
        _text("device", nullable=False),
        sa.Column("has_gclid", sa.Boolean(), nullable=False),
        sa.Column("has_fbclid", sa.Boolean(), nullable=False),
        *(
            sa.Column(name, sa.BigInteger(), nullable=False)
            for name in (
                "ev_quote_submit",
                "ev_callback_submit",
                "ev_phone_click",
                "ev_chat_start",
                "ev_booking_click",
            )
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["core.campaigns.id"], name="fk_web_sessions_campaign_id_campaigns"
        ),
        sa.ForeignKeyConstraint(
            ["landing_page_id"],
            ["core.landing_pages.id"],
            name="fk_web_sessions_landing_page_id_landing_pages",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_web_sessions"),
        sa.UniqueConstraint(
            "org_id",
            "user_pseudo_id",
            "ga_session_id",
            name="uq_web_sessions_org_id_user_pseudo_id_ga_session_id",
        ),
        _one_of("web_sessions", "channel", CHANNELS),
        schema="core",
    )
    _index("web_sessions", "org_id", "started_at")
    _index("web_sessions", "campaign_id")

    op.create_table(
        "leads",
        _id(),
        *_org("leads"),
        _text("source_id", nullable=False),
        _tz("created_at"),
        _text("lead_source_raw"),
        _text("status_raw", nullable=False),
        _text("stage", nullable=False),
        sa.Column("is_qualified", sa.Boolean(), nullable=False),
        _tz("qualified_at", nullable=True),
        _text("stage_time_source", nullable=False),
        sa.Column("is_converted", sa.Boolean(), nullable=False),
        _text("converted_opportunity_source_id"),
        _text("entry_point", nullable=False),
        _text("entry_point_raw"),
        _text("request_type", nullable=False),
        _text("request_type_source", nullable=False),
        _text("customer_type", nullable=False),
        _text("customer_type_source", nullable=False),
        _text("service_line", nullable=False),
        _text("service_line_source", nullable=False),
        _text("lead_class", nullable=False),
        _text("junk_reason"),
        _text("classification_version", nullable=False),
        _text("city_raw"),
        _text("city"),
        _text("region"),
        _text("city_match", nullable=False),
        _text("person_key"),
        sa.Column("is_test", sa.Boolean(), nullable=False),
        sa.Column("duplicate_of", sa.BigInteger(), nullable=True),
        _text("ga_client_id"),
        _text("form_page_path"),
        _text("utm_source"),
        _text("utm_medium"),
        _text("utm_campaign"),
        _text("click_id_type"),
        _text("meta_campaign_source_id"),
        _text("evidence_tier"),
        _text("evidence_detail"),
        sa.Column("evidence_campaign_id", sa.BigInteger(), nullable=True),
        _text("evidence_channel"),
        sa.ForeignKeyConstraint(
            ["duplicate_of"], ["core.leads.id"], name="fk_leads_duplicate_of_leads"
        ),
        sa.ForeignKeyConstraint(
            ["evidence_campaign_id"],
            ["core.campaigns.id"],
            name="fk_leads_evidence_campaign_id_campaigns",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_leads"),
        sa.UniqueConstraint("org_id", "source_id", name="uq_leads_org_id_source_id"),
        _one_of("leads", "stage", LEAD_STAGES),
        _one_of("leads", "stage_time_source", ("field", "unavailable")),
        _one_of("leads", "entry_point", ENTRY_POINTS),
        _one_of("leads", "request_type", REQUEST_TYPES),
        _one_of(
            "leads",
            "request_type_source",
            ("crm_field", "entry_point_default", "campaign", "unknown"),
        ),
        _one_of("leads", "customer_type", ("new", "existing", "unknown")),
        _one_of("leads", "customer_type_source", ("self_reported", "crm_match", "unknown")),
        _one_of("leads", "service_line", (*SERVICE_LINES, "unknown")),
        _one_of("leads", "service_line_source", ("crm_field", "form_page", "campaign", "unknown")),
        _one_of("leads", "lead_class", LEAD_CLASSES),
        _one_of("leads", "junk_reason", ("test", "invalid", "duplicate")),
        _one_of("leads", "city_match", CITY_MATCHES),
        _one_of("leads", "evidence_tier", EVIDENCE_TIERS),
        _one_of("leads", "evidence_channel", REPORTED_CHANNELS),
        schema="core",
    )
    _index("leads", "org_id", "created_at")
    _index("leads", "org_id", "lead_class", "created_at")
    _index("leads", "org_id", "ga_client_id")
    _index("leads", "org_id", "person_key")

    op.create_table(
        "appointments",
        _id(),
        *_org("appointments"),
        _text("source_id", nullable=False),
        sa.Column("lead_id", sa.BigInteger(), nullable=True),
        _text("lead_source_id", nullable=False),
        _text("kind", nullable=False),
        _text("kind_raw", nullable=False),
        _text("status", nullable=False),
        _text("status_raw"),
        _tz("booked_at"),
        _tz("scheduled_for"),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["core.leads.id"], name="fk_appointments_lead_id_leads"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_appointments"),
        sa.UniqueConstraint("org_id", "source_id", name="uq_appointments_org_id_source_id"),
        _one_of("appointments", "kind", ("in_home_consultation", "service_visit", "other")),
        _one_of(
            "appointments", "status", ("booked", "completed", "no_show", "cancelled", "unknown")
        ),
        schema="core",
    )
    _index("appointments", "lead_id")

    op.create_table(
        "opportunities",
        _id(),
        *_org("opportunities"),
        _text("source_id", nullable=False),
        sa.Column("lead_id", sa.BigInteger(), nullable=True),
        _tz("created_at"),
        _text("stage_raw", nullable=False),
        _text("outcome", nullable=False),
        sa.Column("close_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=True),
        _text("amount_basis", nullable=False),
        _text("amount_basis_raw"),
        _text("service_line", nullable=False),
        _text("service_line_raw"),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["core.leads.id"], name="fk_opportunities_lead_id_leads"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_opportunities"),
        sa.UniqueConstraint("org_id", "source_id", name="uq_opportunities_org_id_source_id"),
        _one_of("opportunities", "outcome", ("open", "won", "lost")),
        _one_of("opportunities", "amount_basis", AMOUNT_BASES),
        _one_of("opportunities", "service_line", (*SERVICE_LINES, "unknown")),
        schema="core",
    )
    _index("opportunities", "lead_id")

    op.create_table(
        "annotations",
        _id(),
        *_org("annotations"),
        _text("annotation_type", nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        _text("label", nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_annotations"),
        sa.UniqueConstraint(
            "org_id",
            "annotation_type",
            "start_date",
            "label",
            name="uq_annotations_org_id_annotation_type_start_date_label",
        ),
        schema="core",
    )

    op.create_table(
        "build_runs",
        _id(),
        *_org("build_runs"),
        sa.Column(
            "built_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("batches", postgresql.JSONB(), nullable=False),
        sa.Column("rules", postgresql.JSONB(), nullable=False),
        sa.Column("summary", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_build_runs"),
        schema="core",
    )
    _index("build_runs", "org_id", "built_at")


def downgrade() -> None:
    for name in TABLES:
        op.drop_table(name, schema="core")
