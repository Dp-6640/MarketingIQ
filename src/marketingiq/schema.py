"""Every table the application owns, on one MetaData (used by Alembic and the drift test)."""

from marketingiq.core import tables as core_tables
from marketingiq.ingest.staging import STAGING_TABLES
from marketingiq.models import SCHEMAS, Base

metadata = Base.metadata

__all__ = ["SCHEMAS", "STAGING_TABLES", "core_tables", "metadata"]
