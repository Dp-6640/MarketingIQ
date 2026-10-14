import pytest
from fastapi.testclient import TestClient

from marketingiq.api.app import app
from marketingiq.db import get_app_engine, make_engine


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health_reports_unavailable_when_database_is_down(client):
    # Nothing listens on port 1, so the connection fails fast.
    dead = make_engine("postgresql+psycopg://nobody:secret@127.0.0.1:1/none?connect_timeout=2")
    app.dependency_overrides[get_app_engine] = lambda: dead

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["database"] == "error"
    assert "secret" not in response.text


@pytest.mark.integration
def test_health_ok_against_test_database(client, test_engine):
    app.dependency_overrides[get_app_engine] = lambda: test_engine

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "version": "0.1.0"}
