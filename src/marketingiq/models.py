"""Table definitions.

Migrations in migrations/versions/ are hand-written for review; an integration test checks
that a migrated database matches these models. Schema layout follows ADR-005:
staging (source-shaped), core (canonical + config), mart (derived), app (assistant runs).
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMAS = ("staging", "core", "mart", "app")

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Organization(Base):
    """The analysed business. One synthetic org in the MVP."""

    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso"),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(SmallInteger, Identity(), primary_key=True)
    slug: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    # IANA zone used for reporting days, e.g. America/Toronto (provisional, U-11).
    reporting_tz: Mapped[str] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(String(3))
    is_synthetic: Mapped[bool]
    # "Today" for relative periods such as "last month"; the newest date the data covers.
    data_as_of: Mapped[date | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LoadBatch(Base):
    """One load of one source file into one staging table."""

    __tablename__ = "load_batches"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'succeeded', 'failed')", name="status"),
        CheckConstraint(
            "rows_read >= 0 AND rows_loaded >= 0 AND rows_rejected >= 0 AND rows_duplicate >= 0",
            name="row_counts_non_negative",
        ),
        # Loading the same file into the same table twice is a no-op once it has succeeded.
        Index(
            "uq_load_batches_succeeded_file",
            "org_id",
            "entity",
            "file_sha256",
            unique=True,
            postgresql_where=text("status = 'succeeded'"),
        ),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    org_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("core.organizations.id"))
    source_system: Mapped[str] = mapped_column(Text)  # meta_ads, ga4, salesforce, clarity
    entity: Mapped[str] = mapped_column(Text)  # target staging table
    source_file: Mapped[str] = mapped_column(Text)
    file_sha256: Mapped[str] = mapped_column(String(64))
    generator_seed: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(Text, server_default="running")
    rows_read: Mapped[int] = mapped_column(Integer, server_default="0")
    rows_loaded: Mapped[int] = mapped_column(Integer, server_default="0")
    rows_rejected: Mapped[int] = mapped_column(Integer, server_default="0")
    rows_duplicate: Mapped[int] = mapped_column(Integer, server_default="0")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)  # why a failed load failed


class RejectedRow(Base):
    """A source row that failed validation, kept with its errors for the data-quality report.

    `raw` holds the row as read. Before any real-data load, the field allowlist must keep
    personal data out of source files, because this column stores rows verbatim.
    """

    __tablename__ = "rejected_rows"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    load_batch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("core.load_batches.id", ondelete="CASCADE"), index=True
    )
    row_number: Mapped[int] = mapped_column(Integer)  # 1-based data row in the source file
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
