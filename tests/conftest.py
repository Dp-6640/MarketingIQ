import os

import pytest
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError

from marketingiq.db import make_engine
from marketingiq.schema import SCHEMAS

APP_ROLE = "miq_app"


def _test_database_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL") or dotenv_values(".env").get("TEST_DATABASE_URL")


def _unavailable(reason: str) -> None:
    # CI sets MIQ_REQUIRE_TEST_DB=1 so a missing database fails the run instead of skipping.
    if os.environ.get("MIQ_REQUIRE_TEST_DB") == "1":
        pytest.fail(reason)
    pytest.skip(reason)


@pytest.fixture(scope="session")
def test_engine() -> Engine:
    """Engine for the disposable test database; skips integration tests when it's unavailable."""
    url = _test_database_url()
    if not url:
        _unavailable("TEST_DATABASE_URL is not set")
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError as exc:
        _unavailable(f"Test database unreachable: {exc.orig}")
    yield engine
    engine.dispose()


def reset_database(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {', '.join(SCHEMAS)} CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS public.alembic_version"))


@pytest.fixture
def alembic_cfg(test_engine) -> Config:
    cfg = Config("alembic.ini")
    cfg.attributes["url"] = test_engine.url.render_as_string(hide_password=False)
    cfg.attributes["app_db_role"] = APP_ROLE
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture
def migrated(test_engine, alembic_cfg):
    """The test database, wiped and migrated to the latest revision."""
    reset_database(test_engine)
    command.upgrade(alembic_cfg, "head")
    yield test_engine
    reset_database(test_engine)
