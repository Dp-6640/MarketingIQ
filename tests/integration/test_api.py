"""The REST endpoints, end to end on the tiny world, under the read-only app role."""

import pytest
from fastapi.testclient import TestClient

from marketingiq.api.app import app
from marketingiq.api.routes_assistant import chat_model
from marketingiq.assistant.llm import ModelNotConfigured, Reply, ScriptedModel, call
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


def test_dimension_values_resolve_names_and_flag_ambiguity(client):
    def find(dimension, search=None):
        params = {"search": search} if search else {}
        return client.get(f"/api/v1/dimensions/{dimension}/values", params=params).json()

    furnace = find("campaign", "furnace")
    assert furnace["match"] == "several"
    assert all("furnace" in (v["value"] + v["label"]).lower() for v in furnace["values"])
    assert find("campaign", "furnace promo")["match"] == "one"
    assert find("region", "kitchener")["values"][0]["value"] == "kw_guelph"
    assert find("campaign", "no such thing")["match"] == "none"
    assert find("campaign")["count"] > len(furnace["values"])


def test_dimensions_that_are_not_names_are_rejected(client):
    assert client.get("/api/v1/dimensions/lead_month/values").status_code == 422


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
        ("attribution-models", {"period": QUARTER, "group_by": "channel"}),
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


def test_the_assistant_answers_through_the_api(client):
    script = ScriptedModel(
        [
            Reply(None, [call("get_performance", {"period": QUARTER, "metrics": ["leads"]})]),
            Reply(
                None,
                [
                    call(
                        "submit_answer",
                        {"status": "answered", "answer": "{{c1:totals.leads}} leads."},
                    )
                ],
            ),
        ]
    )
    app.dependency_overrides[chat_model] = lambda: script
    try:
        response = client.post("/api/v1/assistant/ask", json={"question": "How many leads?"})
    finally:
        del app.dependency_overrides[chat_model]

    body = response.json()
    assert response.status_code == 200 and body["status"] == "answered"
    assert body["citations"][0]["path"] == "totals.leads"
    assert body["calls"][0]["tool"] == "get_performance"


def test_the_assistant_says_when_no_model_is_configured(client, monkeypatch):
    def unconfigured():
        raise ModelNotConfigured("LLM_API_KEY is not set.")

    monkeypatch.setattr("marketingiq.api.routes_assistant.get_chat_model", unconfigured)
    response = client.post("/api/v1/assistant/ask", json={"question": "How many leads?"})

    assert response.status_code == 503 and "LLM_API_KEY" in response.json()["detail"]
