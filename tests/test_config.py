import pytest
from pydantic import ValidationError

from marketingiq.config import Settings

URL = "postgresql+psycopg://u:p@localhost:5432/db"
APP_URL = "postgresql+psycopg://app:p@localhost:5432/db"


def test_reads_urls_from_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("DATABASE_URL_APP", APP_URL)

    settings = Settings(_env_file=None)

    assert settings.database_url == URL
    assert settings.app_url == APP_URL
    assert settings.app_db_role == "miq_app"


def test_app_url_falls_back_to_owner_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.delenv("DATABASE_URL_APP", raising=False)

    assert Settings(_env_file=None).app_url == URL


def test_database_url_is_required(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
