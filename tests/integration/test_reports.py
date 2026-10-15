"""Funnel and source reconciliation on the tiny world."""

import pytest
from sqlalchemy import text

from marketingiq.analytics.reports import (
    FUNNEL_STAGES,
    FunnelQuery,
    ReconciliationQuery,
    get_lead_funnel,
    get_source_reconciliation,
)
from marketingiq.core.build import build_core
from marketingiq.ingest.loader import load_dataset
from synthetic.export import generate

pytestmark = pytest.mark.integration

ORG = "synthetic-home-services"
QUARTER = {"preset": "custom", "start": "2026-01-01", "end": "2026-03-31"}


@pytest.fixture(scope="module")
def engine(migrated_module, tmp_path_factory):
    load_dataset(migrated_module, generate("tiny", 7, tmp_path_factory.mktemp("dataset")))
    build_core(migrated_module, ORG)
    return migrated_module


def test_funnel_stages_never_grow_until_opportunities(engine):
    funnel = get_lead_funnel(engine, ORG, FunnelQuery.model_validate({"period": QUARTER}))
    cells = {stage: funnel["totals"][stage] for stage in FUNNEL_STAGES}
    totals = {stage: cell["value"] for stage, cell in cells.items()}

    assert funnel["stages"] == list(FUNNEL_STAGES)
    # Small counts are hidden rather than shown (the tiny world has few closed sales).
    assert all(cell.get("suppressed") for cell in cells.values() if cell["value"] is None)
    shown = [totals[stage] for stage in FUNNEL_STAGES[:4]]
    assert all(value is not None for value in shown)
    assert shown == sorted(shown, reverse=True)  # each stage is at most the one before
    if totals["sales_won"] is not None:
        assert totals["opportunities"] >= totals["sales_won"]
    rate = funnel["totals"]["qualification_rate"]["value"]
    assert rate == pytest.approx(totals["qualified_leads"] / totals["leads"], abs=1e-4)


def test_funnel_can_be_grouped_by_entry_point(engine):
    funnel = get_lead_funnel(
        engine,
        ORG,
        FunnelQuery.model_validate({"period": QUARTER, "group_by": ["entry_point"]}),
    )

    assert {row["dimensions"]["entry_point"] for row in funnel["rows"]} >= {"web_quote_form"}


def test_reconciliation_keeps_sources_apart(engine):
    result = get_source_reconciliation(
        engine, ORG, ReconciliationQuery.model_validate({"period": QUARTER})
    )

    assert "sources_not_additive" in [w["code"] for w in result["warnings"]]
    assert set(result["totals"]) == {
        "meta_reported_leads",
        "crm_leads_linked_to_meta",
        "ga4_form_submit_sessions",
        "crm_web_form_leads",
    }
    with engine.connect() as conn:
        reported = conn.execute(
            text(
                "SELECT sum(platform_reported_leads) FROM core.ad_spend_daily"
                " WHERE report_date BETWEEN '2026-01-01' AND '2026-03-31'"
            )
        ).scalar_one()
    assert result["totals"]["meta_reported_leads"]["value"] == reported


def test_meta_claims_more_than_the_crm_can_link(engine):
    result = get_source_reconciliation(
        engine, ORG, ReconciliationQuery.model_validate({"period": QUARTER})
    )
    totals = result["totals"]

    assert totals["meta_reported_leads"]["value"] > totals["crm_leads_linked_to_meta"]["value"]
    summer = next(r for r in result["rows"] if r["key"] == "meta:120200000000000111")
    assert summer["values"]["crm_leads_linked"]["value"] == 0  # unmapped: nothing links (S09)
