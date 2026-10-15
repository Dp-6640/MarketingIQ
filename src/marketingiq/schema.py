"""Every table the application owns, on one MetaData (used by Alembic and the drift test)."""

from marketingiq.ingest.staging import STAGING_TABLES
from marketingiq.models import SCHEMAS, Base

metadata = Base.metadata

__all__ = ["SCHEMAS", "STAGING_TABLES", "metadata"]
