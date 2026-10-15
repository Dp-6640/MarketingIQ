"""Mart tables: results derived from the core model, rebuilt with it."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Table,
    Text,
)

from marketingiq.core import vocabulary as vocab
from marketingiq.core.tables import one_of
from marketingiq.mart.attribution import MODELS
from marketingiq.models import Base

lead_attribution_credits = Table(
    "lead_attribution_credits",
    Base.metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column("org_id", SmallInteger, ForeignKey("core.organizations.id"), nullable=False),
    Column("lead_id", BigInteger, ForeignKey("core.leads.id", ondelete="CASCADE"), nullable=False),
    Column("model", Text, nullable=False),
    Column("lookback_days", Integer, nullable=False),
    Column("evidence_tier", Text, nullable=False),
    Column("session_id", BigInteger, ForeignKey("core.web_sessions.id", ondelete="CASCADE")),
    Column("campaign_id", BigInteger, ForeignKey("core.campaigns.id")),
    Column("campaign_value", Text),  # named campaign, mapped or not
    Column("channel", Text),  # None = unattributed
    Column("credit", Numeric(10, 8), nullable=False),
    Index(None, "org_id", "model", "lookback_days"),
    Index(None, "lead_id"),
    Index(None, "session_id"),
    Index(None, "campaign_id"),
    one_of("model", MODELS),
    one_of("evidence_tier", vocab.EVIDENCE_TIERS),
    one_of("channel", vocab.REPORTED_CHANNELS),
    CheckConstraint("credit > 0 AND credit <= 1", name="credit_share"),
    CheckConstraint("lookback_days > 0", name="lookback_positive"),
    schema="mart",
)

# Deleted before the core tables on every build (they reference leads and sessions).
REBUILT_TABLES = (lead_attribution_credits,)
