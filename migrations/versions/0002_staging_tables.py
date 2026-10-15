"""Staging tables, one per source file, and a reason column on failed load batches.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "meta_insights_daily",
    "ga4_sessions",
    "sf_leads",
    "sf_events",
    "sf_opportunities",
    "campaign_mapping_sheet",
    "annotations",
)


def _text(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.Text(), nullable=nullable)


def _staging_table(name: str, key: tuple[str, ...], *columns: sa.Column) -> None:
    """A staging table: the batch it came from, its row number in the file, its columns,
    and one row per natural key within a batch."""
    op.create_table(
        name,
        sa.Column("load_batch_id", sa.BigInteger(), nullable=False),
        sa.Column("source_row", sa.Integer(), nullable=False),
        *columns,
        sa.ForeignKeyConstraint(
            ["load_batch_id"],
            ["core.load_batches.id"],
            name=f"fk_{name}_load_batch_id_load_batches",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("load_batch_id", "source_row", name=f"pk_{name}"),
        sa.UniqueConstraint("load_batch_id", *key, name=f"uq_{name}_load_batch_id_{'_'.join(key)}"),
        schema="staging",
    )


def upgrade() -> None:
    op.add_column("load_batches", sa.Column("error", sa.Text(), nullable=True), schema="core")

    _staging_table(
        "meta_insights_daily",
        ("report_date", "campaign_id"),
        sa.Column("report_date", sa.Date(), nullable=False),
        _text("account_id"),
        _text("account_timezone"),
        _text("campaign_id"),
        _text("campaign_name"),
        sa.Column("spend", sa.Numeric(14, 2), nullable=False),
        sa.Column("impressions", sa.BigInteger(), nullable=False),
        sa.Column("inline_link_clicks", sa.BigInteger(), nullable=False),
        sa.Column("leads_reported", sa.BigInteger(), nullable=False),
        _text("attribution_setting"),
    )
    _staging_table(
        "ga4_sessions",
        ("user_pseudo_id", "ga_session_id"),
        _text("user_pseudo_id"),
        sa.Column("ga_session_id", sa.BigInteger(), nullable=False),
        sa.Column("session_start_utc", sa.DateTime(timezone=True), nullable=False),
        _text("source"),
        _text("medium"),
        _text("campaign", nullable=True),
        _text("content", nullable=True),
        _text("landing_page"),
        _text("device_category"),
        sa.Column("has_gclid", sa.Boolean(), nullable=False),
        sa.Column("has_fbclid", sa.Boolean(), nullable=False),
        sa.Column("ev_quote_submit", sa.BigInteger(), nullable=False),
        sa.Column("ev_callback_submit", sa.BigInteger(), nullable=False),
        sa.Column("ev_phone_click", sa.BigInteger(), nullable=False),
        sa.Column("ev_chat_start", sa.BigInteger(), nullable=False),
        sa.Column("ev_booking_click", sa.BigInteger(), nullable=False),
    )
    _staging_table(
        "sf_leads",
        ("id",),
        _text("id"),
        sa.Column("created_date", sa.DateTime(timezone=True), nullable=False),
        _text("lead_source", nullable=True),
        _text("status"),
        sa.Column("is_converted", sa.Boolean(), nullable=False),
        sa.Column("converted_date", sa.Date(), nullable=True),
        _text("converted_opportunity_id", nullable=True),
        _text("city", nullable=True),
        _text("entry_point", nullable=True),
        _text("request_type", nullable=True),
        _text("existing_customer", nullable=True),
        _text("service_line", nullable=True),
        _text("form_page_path", nullable=True),
        _text("utm_source", nullable=True),
        _text("utm_medium", nullable=True),
        _text("utm_campaign", nullable=True),
        _text("click_id_type", nullable=True),
        _text("ga_client_id", nullable=True),
        _text("meta_campaign_id", nullable=True),
        _text("person_key", nullable=True),
        sa.Column("qualified_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_test", sa.Boolean(), nullable=False),
    )
    _staging_table(
        "sf_events",
        ("id",),
        _text("id"),
        _text("who_id"),
        _text("event_type"),
        _text("appointment_status", nullable=True),
        sa.Column("created_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activity_date_time", sa.DateTime(timezone=True), nullable=False),
    )
    _staging_table(
        "sf_opportunities",
        ("id",),
        _text("id"),
        sa.Column("created_date", sa.DateTime(timezone=True), nullable=False),
        _text("stage_name"),
        sa.Column("close_date", sa.Date(), nullable=False),
        sa.Column("is_closed", sa.Boolean(), nullable=False),
        sa.Column("is_won", sa.Boolean(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=True),
        _text("amount_basis", nullable=True),
        _text("service_line", nullable=True),
    )
    _staging_table(
        "campaign_mapping_sheet",
        ("utm_campaign",),
        _text("platform"),
        _text("platform_campaign_id", nullable=True),
        _text("campaign_name"),
        _text("utm_campaign"),
        _text("tactic", nullable=True),
        _text("service_lines", nullable=True),
        _text("region", nullable=True),
    )
    _staging_table(
        "annotations",
        ("annotation_type", "start_date", "label"),
        _text("annotation_type"),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        _text("label"),
    )


def downgrade() -> None:
    for name in reversed(TABLES):
        op.drop_table(name, schema="staging")
    op.drop_column("load_batches", "error", schema="core")
