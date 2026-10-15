"""The application against the oracle: every base measure, by every dimension, model and window.

The comparison uses the application's raw measurements (before rounding and small-cell
suppression), so a tiny world can be checked cell by cell. Rounding and suppression have
their own tests.
"""

from datetime import date
from decimal import Decimal
from fractions import Fraction

import pytest

from marketingiq.analytics.attribution_report import AttributionQuery, compare_attribution_models
from marketingiq.analytics.metrics import BASES
from marketingiq.analytics.performance import PerformanceQuery, load_context, measure
from marketingiq.analytics.periods import resolve
from marketingiq.core.build import build_core
from marketingiq.ingest.loader import load_dataset
from oracle import count, load
from synthetic.export import generate

pytestmark = pytest.mark.integration

ORG = "synthetic-home-services"
QUARTER = (date(2026, 1, 1), date(2026, 3, 31))
MARCH = (date(2026, 3, 1), date(2026, 3, 31))
ATTRIBUTED = ("campaign", "channel", "platform", "campaign_tactic")
LEAD_PROPERTIES = ("entry_point", "service_line", "region", "customer_type", "lead_month")
MODELS = ("first_touch", "last_non_direct", "linear")
METRIC_FOR_FAMILY = {"leads": "leads", "spend": "spend", "sessions": "sessions"}


@pytest.fixture(scope="module")
def world(migrated_module, tmp_path_factory):
    dataset = generate("tiny", 7, tmp_path_factory.mktemp("dataset"))
    load_dataset(migrated_module, dataset)
    build_core(migrated_module, ORG)
    return migrated_module, load(dataset)


# The application's display names for a missing group; the oracle uses None.
NO_GROUP = {"(no campaign)", "(none)", "(unknown)"}


def _key(value) -> str | None:
    if isinstance(value, date):
        return value.strftime("%Y-%m")
    return None if value is None or value in NO_GROUP else str(value)


def app(engine, family, period, group_by=(), population="acquisition", **query) -> dict:
    """The application's raw values: {base: {group key: value}}, zeros left out."""
    performance = PerformanceQuery.model_validate(
        {
            "period": {"preset": "custom", "start": str(period[0]), "end": str(period[1])},
            "metrics": [METRIC_FOR_FAMILY[family]],
            "group_by": list(group_by),
            "population": population,
            **query,
        }
    )
    with engine.connect() as conn:
        ctx = load_context(conn, ORG)
        resolved = resolve(performance.period, ctx.data_as_of)
        measured = measure(conn, ctx, performance, resolved, population, {family})
    rows = measured.rows if group_by else {(): measured.totals}
    result: dict[str, dict] = {}
    for key, values in rows.items():
        for base, value in values.items():
            if BASES[base] == family and value:
                result.setdefault(base, {})[tuple(_key(k) for k in key)] = value
    return result


def oracle_leads(facts, period, base, group_by=(), population="acquisition", **kw) -> dict:
    paid = base.startswith("paid_")
    values = count.leads(
        facts, *period, base.removeprefix("paid_"), tuple(group_by), population, paid=paid, **kw
    )
    return {k: v for k, v in values.items() if v}


def assert_same(actual: dict, expected: dict, label: str) -> None:
    keys = set(actual) | set(expected)
    wrong = {
        k: (actual.get(k), expected.get(k))
        for k in keys
        if abs(Fraction(actual.get(k, 0)) - Fraction(expected.get(k, 0))) > Fraction(1, 10**6)
    }
    assert not wrong, (
        f"{label}: app vs oracle differ for {len(wrong)} of {len(keys)} groups: "
        + str(dict(sorted(wrong.items(), key=str)[:8]))
    )


LEAD_BASES = sorted(b for b, family in BASES.items() if family == "leads" and "amount" not in b)


@pytest.mark.parametrize("population", ["acquisition", "all", "service_demand"])
def test_lead_totals_and_lead_properties(world, population):
    engine, facts = world
    for group_by in [(), *[(d,) for d in LEAD_PROPERTIES], ("service_line", "region")]:
        measured = app(engine, "leads", QUARTER, group_by, population)
        for base in LEAD_BASES:
            expected = oracle_leads(facts, QUARTER, base, group_by, population)
            assert_same(measured.get(base, {}), expected, f"{base} by {group_by} ({population})")


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("lookback", [7, 30, 90])
def test_attributed_leads_under_every_model_and_window(world, model, lookback):
    engine, facts = world
    for dimension in ATTRIBUTED:
        measured = app(
            engine, "leads", QUARTER, (dimension,), attribution_model=model, lookback_days=lookback
        )
        for base in LEAD_BASES:
            expected = oracle_leads(
                facts, QUARTER, base, (dimension,), model=model, lookback=lookback
            )
            assert_same(
                measured.get(base, {}), expected, f"{base} by {dimension}, {model}/{lookback}"
            )


def test_attributed_by_lead_property(world):
    engine, facts = world
    measured = app(engine, "leads", MARCH, ("campaign", "service_line"))
    for base in LEAD_BASES:
        expected = oracle_leads(facts, MARCH, base, ("campaign", "service_line"))
        assert_same(measured.get(base, {}), expected, f"{base} by campaign x service line")


@pytest.mark.parametrize(
    "group_by", [(), ("campaign",), ("platform",), ("channel",), ("campaign_tactic",)]
)
def test_ad_platform_measures(world, group_by):
    engine, facts = world
    measured = app(engine, "spend", QUARTER, group_by)
    for base in ("spend", "impressions", "link_clicks", "platform_reported_leads"):
        expected = {k: v for k, v in count.ad_measure(facts, *QUARTER, base, group_by).items() if v}
        assert_same(measured.get(base, {}), expected, f"{base} by {group_by}")


@pytest.mark.parametrize(
    "group_by",
    [(), ("campaign",), ("channel",), ("platform",), ("landing_page",), ("campaign_tactic",)],
)
def test_sessions(world, group_by):
    engine, facts = world
    measured = app(engine, "sessions", MARCH, group_by)
    assert_same(
        measured.get("sessions", {}),
        count.sessions(facts, *MARCH, group_by),
        f"sessions by {group_by}",
    )
    assert_same(
        measured.get("form_submit_sessions", {}),
        count.sessions(facts, *MARCH, group_by, form_submits=True),
        f"form-submit sessions by {group_by}",
    )


def test_evidence_tiers(world):
    engine, facts = world
    measured = app(engine, "leads", QUARTER, ("evidence_tier",))
    expected = {(tier,): n for tier, n in count.tiers(facts, *QUARTER).items()}
    assert_same(measured["leads"], expected, "leads by evidence tier")


def test_the_oracle_sees_the_planted_unmapped_campaign(world):
    _, facts = world
    unmapped = [c for c in facts.campaigns.values() if not c.in_mapping_sheet]
    assert unmapped, "scenario S09 should leave a Meta campaign out of the mapping sheet"
    spend = count.ad_measure(facts, *QUARTER, "spend", ("campaign",))
    assert any(spend.get((c.key,), Decimal(0)) > 0 for c in unmapped)


@pytest.mark.parametrize("group_by", ["campaign", "channel", "campaign_tactic"])
def test_model_comparison_matches_the_oracle(world, group_by):
    engine, facts = world
    period = {"preset": "custom", "start": str(QUARTER[0]), "end": str(QUARTER[1])}
    result = compare_attribution_models(
        engine, ORG, AttributionQuery.model_validate({"period": period, "group_by": group_by})
    )

    assert result["total"] == count.leads(facts, *QUARTER)[()]
    shown = [row for row in result["rows"] if not row.get("suppressed")]
    assert shown
    for model in MODELS:
        expected = count.leads(facts, *QUARTER, group_by=(group_by,), model=model)
        for row in shown:
            oracle = expected.get((_key(row["key"]),), 0)
            assert row["credit"][model] == pytest.approx(float(oracle), abs=0.01), (model, row)
    tiers = count.tiers(facts, *QUARTER)
    for tier, cell in result["evidence"]["by_tier"].items():
        if not cell.get("suppressed"):
            assert cell["value"] == tiers.get(tier, 0), tier
