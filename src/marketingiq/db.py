"""Database engines.

Two engines on purpose: the owner engine writes (migrations, loaders, transforms);
the app engine is the least-privilege role every read path uses.
"""

from collections.abc import Iterable, Mapping
from functools import lru_cache
from typing import Any

from sqlalchemy import Connection, Engine, Table, create_engine

from marketingiq.config import get_settings


def make_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True)


@lru_cache
def get_owner_engine() -> Engine:
    return make_engine(get_settings().database_url)


@lru_cache
def get_app_engine() -> Engine:
    return make_engine(get_settings().app_url)


def copy_records(conn: Connection, table: Table, records: Iterable[Mapping[str, Any]]) -> int:
    """Bulk-insert records with PostgreSQL COPY, inside the caller's transaction.

    Every column except an identity column is sent; a key missing from a record is NULL.
    Returns the number of rows written.
    """
    columns = [column.name for column in table.columns if column.identity is None]
    statement = f"COPY {table.schema}.{table.name} ({', '.join(columns)}) FROM STDIN"
    count = 0
    with conn.connection.dbapi_connection.cursor() as cursor, cursor.copy(statement) as copy:
        for record in records:
            copy.write_row(tuple(record.get(column) for column in columns))
            count += 1
    return count
