"""The performance service, checked against direct SQL and the source files (tiny world)."""

import csv
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from dotenv import dotenv_values
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.engine import make_url

from marketingiq.analytics.performance import (
    PerformanceQuery,
    _measure,
    get_performance,
    load_context,
)
from marketingiq.analytics.periods import Period, PeriodSpec
from marketingiq.core.build import build_core
from marketingiq.db import make_engine
from marketingiq.ingest.loader import load_dataset
from synthetic.export import generate

pytestmark = pytest.mark.integration

ORG = "synthetic-home-services"
MARCH = Period(date(2026, 3, 1), date(2026, 3, 31))  # "last month" in the tiny world
QUARTER = {"preset": "custom", "start": "2026-01-01", "end": "2026-03-31"}


@pytest.fixture(scope="module")
def world(migrated_module, tmp_path_factory):
    dataset = generate("tiny", 7, tmp_path_factory.mktemp("dataset"))
    load_dataset(migrated_module, dataset)
    build_core(migrated_module, ORG)
    return migrated_module, dataset


@pytest.fixture(scope="module")
def app_engine(world):
    """The read-only app role, on the test database: analytics must work without writes."""
    app_url = os.environ.get("DATABASE_URL_APP") or dotenv_values(".env").get("DATABASE_URL_APP")
    if not app_url:
        pytest.skip("DATABASE_URL_APP is not set")
    owner = world[0].url
    app = make_url(app_url)
    engine = make_engine(owner.set(username=app.username, password=app.password))
    yield engine
    engine.dispose()


def perf(engine, **query) -> dict:
    return get_performance(engine, ORG, PerformanceQuery.model_validate(query))


def row(result: dict, key: str) -> dict:
    return next(r for r in result["rows"] if r["key"] == key)["values"]


def scalar(engine, sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


def codes(result: dict) -> list[str]:
    return [warning["code"] for warning in result["warnings"]]


def test_results_echo_what_they_resolved_to(app_engine):
    result = perf(app_engine, period={"preset": "last_month"}, metrics=["leads"])

    assert result["resolved"]["period"] == {"start": "2026-03-01", "end": "2026-03-31"}
    assert result["resolved"]["population"] == "acquisition"
    assert result["resolved"]["attribution_model"] == "last_non_direct"
    assert result["resolved"]["synthetic"] is True
    assert {"synthetic_data", "population_default", "mapping_unverified"} <= set(codes(result))


def test_lead_total_matches_a_direct_count(app_engine, world):
    result = perf(app_engine, period={"preset": "last_month"}, metrics=["leads"])

    expected = scalar(
        world[0],
        "SELECT count(*) FROM core.leads WHERE duplicate_of IS NULL"
        " AND lead_class = 'acquisition'"
        " AND (created_at AT TIME ZONE 'America/Toronto')::date BETWEEN :start AND :end",
        start=MARCH.start,
        end=MARCH.end,
    )
    assert result["totals"]["leads"]["value"] == expected


def test_spend_matches_the_meta_file(app_engine, world):
    _, dataset = world
    with (dataset / "meta/insights_daily.csv").open(encoding="utf-8", newline="") as handle:
        expected = sum(
            Decimal(r["spend"])
            for r in csv.DictReader(handle)
            if "2026-03-01" <= r["date"] <= "2026-03-31"
        )

    result = perf(app_engine, period={"preset": "last_month"}, metrics=["spend"])

    assert result["totals"]["spend"]["value"] == float(expected)
    assert "timezone_mismatch" in codes(result)  # the tiny world's Meta account is in LA


def test_campaign_rows_add_up_to_the_totals(world):
    engine, _ = world
    query = PerformanceQuery.model_validate(
        {"period": QUARTER, "group_by": ["campaign"], "metrics": ["leads", "spend", "sessions"]}
    )
    with engine.connect() as conn:
        ctx = load_context(conn, ORG)
        families = {"leads", "spend", "sessions"}
        measured = _measure(
            conn, ctx, query, Period(date(2026, 1, 1), date(2026, 3, 31)), "all", families
        )

    for base in ("leads", "spend", "sessions"):
        assert sum(values[base] for values in measured.rows.values()) == measured.totals[base]


def test_cost_per_lead_is_spend_over_credited_leads(app_engine, world):
    engine, _ = world
    result = perf(
        app_engine,
        period=QUARTER,
        group_by=["campaign"],
        metrics=["spend", "cost_per_lead"],
        population="all",
        attribution_model="first_touch",
    )
    start, end = date(2026, 1, 1), date(2026, 3, 31)
    spend = scalar(
        engine,
        "SELECT sum(s.spend) FROM core.ad_spend_daily s JOIN core.campaigns c"
        " ON c.id = s.campaign_id WHERE c.key = 'meta_prospecting_furnace'"
        " AND s.report_date BETWEEN :start AND :end",
        start=start,
        end=end,
    )
    credited = scalar(
        engine,
        "SELECT sum(a.credit) FROM mart.lead_attribution_credits a"
        " JOIN core.leads l ON l.id = a.lead_id JOIN core.campaigns c ON c.id = a.campaign_id"
        " WHERE c.key = 'meta_prospecting_furnace' AND a.model = 'first_touch'"
        " AND a.lookback_days = 30"
        " AND (l.created_at AT TIME ZONE 'America/Toronto')::date BETWEEN :start AND :end",
        start=start,
        end=end,
    )

    cell = row(result, "meta_prospecting_furnace")["cost_per_lead"]
    assert credited >= 5  # large enough not to be suppressed
    assert cell["value"] == pytest.approx(float(spend / credited), abs=0.01)


def test_comparisons_report_previous_values_and_changes(app_engine):
    result = perf(
        app_engine, period={"preset": "last_month"}, compare_to="previous_period", metrics=["leads"]
    )
    leads = result["totals"]["leads"]

    assert result["resolved"]["comparison"] == {"start": "2026-02-01", "end": "2026-02-28"}
    assert leads["change"] == leads["value"] - leads["previous"]
    assert leads["change_pct"] == pytest.approx(leads["change"] / leads["previous"], abs=1e-4)
    assert "seasonal_comparison" in codes(result)


def test_spend_cannot_be_split_by_a_lead_property(app_engine):
    result = perf(
        app_engine, period=QUARTER, group_by=["service_line"], metrics=["leads", "cost_per_lead"]
    )

    cells = [r["values"]["cost_per_lead"] for r in result["rows"]]
    assert cells and all(
        c == {"value": None, "null_reason": "not_available_for_dimension"} for c in cells
    )
    assert "spend_not_by_dimension" in codes(result)


def test_groups_without_a_spend_feed_explain_their_missing_costs(app_engine):
    result = perf(app_engine, period=QUARTER, group_by=["campaign"], metrics=["cost_per_lead"])

    assert row(result, "(no campaign)")["cost_per_lead"]["null_reason"] == "no_spend_source"
    assert "no_spend_source" in codes(result)


def test_amounts_need_one_amount_basis(app_engine):
    mixed = perf(app_engine, period=QUARTER, metrics=["won_amount"], population="all")
    one = perf(
        app_engine,
        period=QUARTER,
        metrics=["won_amount"],
        population="all",
        amount_basis="purchase_price",
    )

    assert mixed["totals"]["won_amount"] == {"value": None, "null_reason": "amount_basis_required"}
    assert {"amount_basis_mixed", "amount_basis_unverified"} <= set(codes(mixed))
    assert one["totals"]["won_amount"]["value"] >= 0
    assert "amount_basis_mixed" not in codes(one)


def test_small_counts_are_hidden(app_engine):
    result = perf(
        app_engine, period={"preset": "last_month"}, group_by=["service_line"], metrics=["leads"]
    )

    hidden = [r for r in result["rows"] if r["values"]["leads"].get("suppressed")]
    assert hidden
    assert all(r["values"]["leads"]["value"] is None for r in hidden)
    assert "small_cell_suppressed" in codes(result)


def test_unmapped_campaign_spend_stays_apart_from_its_leads(app_engine):
    result = perf(
        app_engine,
        period=QUARTER,
        group_by=["campaign"],
        metrics=["spend", "leads"],
        population="all",
        attribution_model="first_touch",
    )

    summer = row(result, "meta:120200000000000111")
    assert summer["spend"]["value"] > 0
    assert summer["leads"]["value"] == 0  # its visits can't be linked to it (S09)
    assert any(r["key"] == "(unmapped)" for r in result["rows"])


def test_coverage_by_evidence_tier(app_engine):
    result = perf(
        app_engine,
        period=QUARTER,
        group_by=["evidence_tier"],
        metrics=["leads", "attribution_coverage"],
        population="all",
    )

    assert row(result, "T1_journey")["attribution_coverage"]["value"] == 1.0
    assert row(result, "T5_none")["attribution_coverage"]["value"] == 0.0
    assert 0 < result["totals"]["attribution_coverage"]["value"] < 1


@pytest.mark.parametrize(
    "query",
    [
        {"period": {"preset": "last_month"}, "metrics": ["leads"], "compare_to": "custom"},
        {"period": {"preset": "last_month"}, "metrics": ["leads"], "sort_by": "spend"},
        {"period": {"preset": "last_month"}, "metrics": ["leads"], "group_by": ["campaign"] * 2},
        {"period": {"preset": "last_month"}, "metrics": ["leads"], "group_by": ["a", "b", "c"]},
        {"period": {"preset": "last_month"}, "metrics": []},
    ],
)
def test_invalid_queries_are_rejected(query):
    with pytest.raises(ValidationError):
        PerformanceQuery.model_validate(query)


def test_period_spec_is_reused(world):
    assert PeriodSpec(preset="last_month").preset == "last_month"
    assert Path(world[1]).exists()
