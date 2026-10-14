"""Database engines.

Two engines on purpose: the owner engine writes (migrations, loaders, transforms);
the app engine is the least-privilege role every read path uses.
"""

from functools import lru_cache

from sqlalchemy import Engine, create_engine

from marketingiq.config import get_settings


def make_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True)


@lru_cache
def get_owner_engine() -> Engine:
    return make_engine(get_settings().database_url)


@lru_cache
def get_app_engine() -> Engine:
    return make_engine(get_settings().app_url)
