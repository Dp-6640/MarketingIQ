"""The data-quality report on the tiny world (capture outage planted 10-15 March 2026)."""

import pytest

from marketingiq.analytics.quality import QualityQuery, get_data_quality
from marketingiq.core.build import build_core
from marketingiq.ingest.loader import load_dataset
from synthetic.export import generate

pytestmark = pytest.mark.integration

ORG = "synthetic-home-services"


@pytest.fixture(scope="module")
def engine(migrated_module, tmp_path_factory):
    load_dataset(migrated_module, generate("tiny", 7, tmp_path_factory.mktemp("dataset")))
    build_core(migrated_module, ORG)
    return migrated_module


def report(engine, start: str, end: str) -> dict:
    query = QualityQuery.model_validate(
        {"period": {"preset": "custom", "start": start, "end": end}}
    )
    return get_data_quality(engine, ORG, query)


def codes(result: dict) -> set[str]:
    return {w["code"] for w in result["warnings"]}


def test_the_capture_outage_is_found_without_being_told(engine):
    result = report(engine, "2026-02-23", "2026-03-29")
    weeks = {w["week_of"]: w for w in result["capture_by_week"]}

    outage = weeks["2026-03-09"]
    if outage["web_form_leads"]["value"] is None:
        pytest.skip("too few web-form leads that week in the tiny world")
    assert outage["dropped"] is True
    assert not weeks["2026-02-23"]["dropped"]
    assert "capture_drop" in codes(result)


def test_unmapped_campaigns_and_spend_are_listed(engine):
    result = report(engine, "2026-01-01", "2026-03-31")

    assert "meta_prospecting_summer_test" in result["campaign_mapping"]["unmapped_campaign_values"]
    assert "Prospecting | Summer Test" in result["campaign_mapping"]["spend_not_in_mapping_sheet"]
    assert result["acquisition_without_spend_feed_by_channel"]
    assert {"unmapped_campaigns", "no_spend_source", "timezone_mismatch"} <= codes(result)


def test_days_before_the_data_starts_are_reported_missing(engine):
    result = report(engine, "2025-12-28", "2026-01-03")

    assert result["days_without_data"]["ga4_sessions"][:4] == [
        "2025-12-28",
        "2025-12-29",
        "2025-12-30",
        "2025-12-31",
    ]
    assert "source_incomplete" in codes(result)


def test_loads_and_maturity_are_summarized(engine):
    result = report(engine, "2026-01-01", "2026-03-31")

    assert result["latest_loads"]["sf_leads"]["rejected"] == 0
    assert result["failed_loads"] == 0
    assert result["evidence"]["acquisition_coverage"] is not None
    # Too few closed sales in three months to measure how long sales take.
    assert result["cohort_maturity_days"] is None
    assert "maturity_unknown" in codes(result)
