"""Foundation: schemas, role grants, organizations, load batches, rejected rows.

Revision ID: 0001
Revises:
Create Date: 2026-10-14
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMAS = ("staging", "core", "mart", "app")


def _app_role() -> str:
    role = context.config.attributes["app_db_role"]
    # The role name is interpolated into DDL, so only plain identifiers are accepted.
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role):
        raise ValueError(f"Invalid app_db_role: {role!r}")
    return role


def upgrade() -> None:
    for schema in SCHEMAS:
        op.execute(f"CREATE SCHEMA {schema}")

    # The app role reads core and mart, and writes only its own run log in app.
    # It gets nothing in staging: analytics must never read unvalidated source rows.
    role = _app_role()
    op.execute(f"GRANT USAGE ON SCHEMA core, mart, app TO {role}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA core, mart GRANT SELECT ON TABLES TO {role}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT SELECT, INSERT ON TABLES TO {role}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT USAGE ON SEQUENCES TO {role}")

    op.create_table(
        "organizations",
        sa.Column("id", sa.SmallInteger(), sa.Identity(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("reporting_tz", sa.Text(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("data_as_of", sa.Date(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_organizations_currency_iso"),
        sa.PrimaryKeyConstraint("id", name="pk_organizations"),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
        schema="core",
    )

    op.create_table(
        "load_batches",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("org_id", sa.SmallInteger(), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("entity", sa.Text(), nullable=False),
        sa.Column("source_file", sa.Text(), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("generator_seed", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.Text(), server_default="running", nullable=False),
        sa.Column("rows_read", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rows_loaded", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rows_rejected", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rows_duplicate", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')", name="ck_load_batches_status"
        ),
        sa.CheckConstraint(
            "rows_read >= 0 AND rows_loaded >= 0 AND rows_rejected >= 0 AND rows_duplicate >= 0",
            name="ck_load_batches_row_counts_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["core.organizations.id"],
            name="fk_load_batches_org_id_organizations",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_load_batches"),
        schema="core",
    )
    op.create_index(
        "uq_load_batches_succeeded_file",
        "load_batches",
        ["org_id", "entity", "file_sha256"],
        unique=True,
        schema="core",
        postgresql_where=sa.text("status = 'succeeded'"),
    )

    op.create_table(
        "rejected_rows",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("load_batch_id", sa.BigInteger(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("raw", postgresql.JSONB(), nullable=False),
        sa.Column("errors", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["load_batch_id"],
            ["core.load_batches.id"],
            name="fk_rejected_rows_load_batch_id_load_batches",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rejected_rows"),
        schema="core",
    )
    op.create_index(
        "ix_rejected_rows_load_batch_id", "rejected_rows", ["load_batch_id"], schema="core"
    )


def downgrade() -> None:
    # Dropping the schemas also removes their tables and default privileges.
    for schema in reversed(SCHEMAS):
        op.execute(f"DROP SCHEMA {schema} CASCADE")
