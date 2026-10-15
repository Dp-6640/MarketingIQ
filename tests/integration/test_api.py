"""The REST endpoints, end to end on the tiny world, under the read-only app role."""

import pytest
from fastapi.testclient import TestClient

from marketingiq.api.app import app
from marketingiq.core.build import build_core
from marketingiq.db import get_app_engine
from marketingiq.ingest.loader import load_dataset
from synthetic.export import generate

pytestmark = pytest.mark.integration

ORG = "synthetic-home-services"
QUARTER = {"preset": "custom", "start": "2026-01-01", "end": "2026-03-31"}
MARCH = {"preset": "custom", "start": "2026-03-01", "end": "2026-03-31"}


@pytest.fixture(scope="module")
def client(migrated_module, app_role_engine, tmp_path_factory):
    load_dataset(migrated_module, generate("tiny", 7, tmp_path_factory.mktemp("dataset")))
    build_core(migrated_module, ORG)
    app.dependency_overrides[get_app_engine] = lambda: app_role_engine(migrated_module)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_campaign_search_finds_by_name_or_key(client):
    everything = client.get("/api/v1/campaigns").json()["campaigns"]
    furnace = client.get("/api/v1/campaigns", params={"search": "furnace"}).json()["campaigns"]

    assert len(everything) > len(furnace) > 0
    assert all("furnace" in (c["name"] + c["key"]).lower() for c in furnace)


def test_annotations_overlap_the_requested_range(client):
    march = client.get("/api/v1/annotations", params={"start": "2026-03-01", "end": "2026-03-31"})

    assert march.status_code == 200
    for note in march.json()["annotations"]:
        assert note["start_date"] <= "2026-03-31" and note["end_date"] >= "2026-03-01"


def test_performance_endpoint_matches_the_service(client):
    body = {"period": QUARTER, "metrics": ["leads", "spend"], "group_by": ["channel"]}
    response = client.post("/api/v1/analytics/performance", json=body)

    assert response.status_code == 200
    result = response.json()
    assert result["resolved"]["period"] == {"start": "2026-01-01", "end": "2026-03-31"}
    assert result["resolved"]["synthetic"] is True
    assert result["rows"]


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("funnel", {"period": QUARTER}),
        ("reconciliation", {"period": QUARTER}),
        ("data-quality", {"period": QUARTER}),
        ("change", {"metric": "spend", "dimension": "campaign", "period": MARCH}),
    ],
)
def test_every_report_answers(client, path, body):
    response = client.post(f"/api/v1/analytics/{path}", json=body)

    assert response.status_code == 200, response.text
    assert "warnings" in response.json()


def test_invalid_queries_are_rejected_before_any_sql(client):
    unknown_metric = {"period": QUARTER, "metrics": ["revenue_magic"]}
    wrong_split = {"metric": "spend", "dimension": "service_line", "period": MARCH}
    free_text = {"period": QUARTER, "metrics": ["leads"], "sql": "DROP TABLE core.leads"}

    for path, body in [
        ("performance", unknown_metric),
        ("change", wrong_split),
        ("performance", free_text),
    ]:
        assert client.post(f"/api/v1/analytics/{path}", json=body).status_code == 422


def test_unknown_organization_is_404(client):
    response = client.post(
        "/api/v1/analytics/funnel", params={"org": "nobody"}, json={"period": QUARTER}
    )

    assert response.status_code == 404
    assert "nobody" in response.json()["detail"]
