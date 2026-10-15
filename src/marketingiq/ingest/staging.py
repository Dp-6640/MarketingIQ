"""Staging tables, built from the row models so the two can't drift apart.

One table per source file in the `staging` schema: the row model's fields become columns,
plus the load batch and the row's number in the file. The hand-written migration must
create exactly these tables; tests/integration/test_migrations.py checks that it does.
"""

from datetime import date, datetime
from decimal import Decimal
from types import NoneType, UnionType
from typing import Annotated, Any, Union, get_args, get_origin

from pydantic import AwareDatetime
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.types import TypeEngine

from marketingiq.ingest.sources import SOURCES, Source
from marketingiq.models import Base


def column_type(annotation: Any) -> tuple[TypeEngine, bool]:
    """(SQL type, nullable) for a row-model field annotation."""
    nullable = False
    if get_origin(annotation) in (Union, UnionType):
        members = get_args(annotation)
        (annotation,) = [member for member in members if member is not NoneType]
        nullable = NoneType in members
    if get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]
    # Order matters: bool is a subclass of int, and datetime a subclass of date.
    if annotation in (AwareDatetime, datetime):
        return DateTime(timezone=True), nullable
    if annotation is bool:
        return Boolean(), nullable
    if annotation is int:
        return BigInteger(), nullable
    if annotation is Decimal:
        return Numeric(14, 2), nullable
    if annotation is date:
        return Date(), nullable
    if annotation is str:
        return Text(), nullable
    raise TypeError(f"no staging column type for {annotation!r}")


def _staging_table(source: Source) -> Table:
    columns = []
    for name, field in source.row_model.model_fields.items():
        sql_type, nullable = column_type(field.annotation)
        columns.append(Column(name, sql_type, nullable=nullable))
    return Table(
        source.entity,
        Base.metadata,
        Column(
            "load_batch_id",
            BigInteger,
            ForeignKey("core.load_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        Column("source_row", Integer, nullable=False),
        *columns,
        PrimaryKeyConstraint("load_batch_id", "source_row"),
        UniqueConstraint("load_batch_id", *source.key),
        schema="staging",
    )


STAGING_TABLES = {source.entity: _staging_table(source) for source in SOURCES}
