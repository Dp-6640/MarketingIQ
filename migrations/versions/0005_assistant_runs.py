"""The assistant's run log in the app schema.

The app role can insert and read it (default privileges from 0001), and nothing else in
the database is writable by that role.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = ("answered", "clarify", "abstain", "refuse", "failed")


def upgrade() -> None:
    op.create_table(
        "assistant_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.SmallInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("trace", postgresql.JSONB(), nullable=False),
        sa.Column("steps", sa.SmallInteger(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in STATUSES) + ")",
            name="ck_assistant_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["core.organizations.id"],
            name="fk_assistant_runs_org_id_organizations",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_assistant_runs"),
        schema="app",
    )
    op.create_index(
        "ix_assistant_runs_org_id_created_at",
        "assistant_runs",
        ["org_id", "created_at"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_table("assistant_runs", schema="app")
