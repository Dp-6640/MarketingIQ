"""The assistant's run log: one row per question, with the full trace.

The trace holds every tool call (arguments, whether it worked, how long it took), the answer
template, each resolved reference and the caveats, so any number in an answer can be traced
back to the call that produced it. Tool results themselves are aggregates; the question text
is stored as typed, so it's the one free-text field to keep in mind for retention.
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Engine,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Table,
    Text,
    Uuid,
    func,
    insert,
)
from sqlalchemy.dialects.postgresql import JSONB

from marketingiq.models import Base

RUN_STATUSES = ("answered", "clarify", "abstain", "refuse", "failed")

assistant_runs = Table(
    "assistant_runs",
    Base.metadata,
    Column("id", Uuid, primary_key=True),
    Column("org_id", SmallInteger, ForeignKey("core.organizations.id"), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("question", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("answer", Text),
    Column("trace", JSONB, nullable=False),
    Column("steps", SmallInteger, nullable=False),
    Column("prompt_tokens", Integer, nullable=False),
    Column("completion_tokens", Integer, nullable=False),
    Column("latency_ms", Integer, nullable=False),
    CheckConstraint(
        "status IN (" + ", ".join(f"'{s}'" for s in RUN_STATUSES) + ")",
        name="status",
    ),
    Index("ix_assistant_runs_org_id_created_at", "org_id", "created_at"),
    schema="app",
)


def save_run(engine: Engine, row: dict) -> None:
    with engine.begin() as conn:
        conn.execute(insert(assistant_runs), row)
