"""Change explanation on the tiny world: February to March 2026."""

import pytest
from pydantic import ValidationError

from marketingiq.analytics.change import ChangeQuery, explain_metric_change
from marketingiq.core.build import build_core
from marketingiq.ingest.loader import load_dataset
from synthetic.export import generate

pytestmark = pytest.mark.integration

ORG = "synthetic-home-services"
MARCH = {"preset": "custom", "start": "2026-03-01", "end": "2026-03-31"}


@pytest.fixture(scope="module")
def engine(migrated_module, tmp_path_factory):
    load_dataset(migrated_module, generate("tiny", 7, tmp_path_factory.mktemp("dataset")))
    build_core(migrated_module, ORG)
    return migrated_module


def explain(engine, **query) -> dict:
    return explain_metric_change(engine, ORG, ChangeQuery.model_validate(query))


def test_count_effects_add_up_to_the_total_change(engine):
    result = explain(engine, metric="spend", dimension="campaign", period=MARCH)
    segments = result["segments"]

    assert result["resolved"]["comparison"] == {"start": "2026-02-01", "end": "2026-02-28"}
    assert sum(s["effect"] for s in segments) == pytest.approx(result["total"]["change"], abs=0.02)
    assert sum(s["share_of_change"] for s in segments) == pytest.approx(1, abs=0.001)
    assert all(s["direction"] in ("spend_up", "spend_down", "spend_flat") for s in segments)


def test_ratio_effects_follow_the_counterfactual(engine):
    result = explain(
        engine,
        metric="cost_per_lead",
        dimension="campaign",
        period=MARCH,
        population="all",
        attribution_model="first_touch",
    )
    total = result["total"]
    n1, d1 = total["numerator"]["value"], total["denominator"]["value"]
    shown = [s for s in result["segments"] if not s.get("suppressed")]

    assert shown
    for segment in shown:
        num, den = segment["numerator"], segment["denominator"]
        counterfactual = (n1 - num["value"] + num["previous"]) / (
            d1 - den["value"] + den["previous"]
        )
        assert segment["effect"] == pytest.approx(total["value"] - counterfactual, abs=0.02)
        assert segment["direction"].startswith("spend_") and "_paid_leads_" in segment["direction"]
    assert "add up exactly" in result["method"]


def test_segments_with_nothing_in_either_period_are_left_out(engine):
    result = explain(engine, metric="spend", dimension="campaign", period=MARCH)

    keys = {s["key"] for s in result["segments"]}
    assert "(no campaign)" not in keys  # no spend in either month
    assert "meta_prospecting_furnace" in keys


def test_month_over_month_is_flagged_as_seasonal(engine):
    result = explain(engine, metric="spend", dimension="campaign", period=MARCH)

    assert "seasonal_comparison" in [w["code"] for w in result["warnings"]]


def test_a_metric_that_cannot_be_split_that_way_is_rejected():
    with pytest.raises(ValidationError, match="can't be split"):
        ChangeQuery.model_validate(
            {"metric": "spend", "dimension": "service_line", "period": MARCH}
        )
