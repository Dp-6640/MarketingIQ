import os

import pytest
from dotenv import dotenv_values
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError

from marketingiq.db import make_engine


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
