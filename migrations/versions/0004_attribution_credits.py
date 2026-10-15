"""Attribution credits, and indexes on every foreign key a rebuild deletes through.

Credits: one row per lead, model, lookback window and credited touch. A rebuild deletes and
rewrites whole tables; without an index on each referencing column, Postgres checks every
deleted row against a full scan of the referencing table (minutes instead of seconds).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "lead_attribution_credits"
CORE_FOREIGN_KEYS = (
    ("web_sessions", "landing_page_id"),
    ("leads", "duplicate_of"),
    ("leads", "evidence_campaign_id"),
    ("campaign_identifiers", "campaign_id"),
)
MODELS = ("first_touch", "last_non_direct", "linear")
EVIDENCE_TIERS = (
    "T1_journey", "T2_captured_source", "T3_platform_native", "T4_self_reported_channel",
    "T5_none",
)  # fmt: skip
CHANNELS = (
    "organic_search", "paid_search", "paid_social", "organic_social", "direct", "referral",
    "email", "other", "search_unspecified", "social_unspecified", "offline_media",
    "word_of_mouth",
)  # fmt: skip


def _one_of(column: str, values: tuple[str, ...]) -> sa.CheckConstraint:
    allowed = ", ".join(f"'{value}'" for value in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=f"ck_{TABLE}_{column}")


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("org_id", sa.SmallInteger(), nullable=False),
        sa.Column("lead_id", sa.BigInteger(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("lookback_days", sa.Integer(), nullable=False),
        sa.Column("evidence_tier", sa.Text(), nullable=False),
        sa.Column("session_id", sa.BigInteger(), nullable=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=True),
        sa.Column("campaign_value", sa.Text(), nullable=True),
        sa.Column("channel", sa.Text(), nullable=True),
        sa.Column("credit", sa.Numeric(10, 8), nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id"], ["core.organizations.id"], name=f"fk_{TABLE}_org_id_organizations"
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["core.leads.id"], name=f"fk_{TABLE}_lead_id_leads", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["core.web_sessions.id"],
            name=f"fk_{TABLE}_session_id_web_sessions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["core.campaigns.id"], name=f"fk_{TABLE}_campaign_id_campaigns"
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{TABLE}"),
        _one_of("model", MODELS),
        _one_of("evidence_tier", EVIDENCE_TIERS),
        _one_of("channel", CHANNELS),
        sa.CheckConstraint("credit > 0 AND credit <= 1", name=f"ck_{TABLE}_credit_share"),
        sa.CheckConstraint("lookback_days > 0", name=f"ck_{TABLE}_lookback_positive"),
        schema="mart",
    )
    op.create_index(
        f"ix_{TABLE}_org_id_model_lookback_days",
        TABLE,
        ["org_id", "model", "lookback_days"],
        schema="mart",
    )
    for column in ("lead_id", "session_id", "campaign_id"):
        op.create_index(f"ix_{TABLE}_{column}", TABLE, [column], schema="mart")
    for table, column in CORE_FOREIGN_KEYS:
        op.create_index(f"ix_{table}_{column}", table, [column], schema="core")


def downgrade() -> None:
    for table, column in CORE_FOREIGN_KEYS:
        op.drop_index(f"ix_{table}_{column}", table_name=table, schema="core")
    op.drop_table(TABLE, schema="mart")
