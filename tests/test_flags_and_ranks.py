"""Ranks and flags in performance results: pure rules, checked on hand-built rows."""

from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from marketingiq.analytics.performance import PerformanceQuery, _flag, _rank

QUARTER = {"preset": "custom", "start": "2026-01-01", "end": "2026-03-31"}


def campaign(spend, leads, qualified):
    return {"spend": D(spend), "paid_leads": D(leads), "paid_qualified_leads": D(qualified)}


def test_ranks_put_the_largest_first_share_ties_and_skip_missing_values():
    rows = [
        {"values": {"leads": {"value": 7}}},
        {"values": {"leads": {"value": 12}}},
        {"values": {"leads": {"value": 7}}},
        {"values": {"leads": {"value": None, "suppressed": True}}},
    ]

    _rank(rows, ["leads"])

    assert [r["values"]["leads"].get("rank") for r in rows] == [2, 1, 2, None]
    assert rows[0]["values"]["leads"]["rank_of"] == 3


def test_cheap_leads_that_rarely_qualify_are_flagged():
    keys = [("promo",), ("retargeting",), ("prospecting",), ("messaging",)]
    rows = [
        campaign(300, 10, 2),  # CPL 30, 20% qualify: cheap, poor quality
        campaign(500, 10, 7),  # CPL 50, 70% qualify: cheap, good quality
        campaign(3000, 10, 6),  # CPL 300, 60% qualify: expensive
        campaign(1000, 10, 3),  # CPL 100, 30% qualify: expensive, poor quality
    ]

    result = _flag("cheap_leads_low_qualification", keys, rows, [set()] * 4)

    assert result["keys"] == {("promo",)}
    assert result["summary"]["rows_judged"] == 4
    assert result["summary"]["median_cost_per_lead"] == 75.0
    assert result["summary"]["median_qualification_rate"] == 0.45


def test_small_or_hidden_campaigns_are_not_judged():
    keys = [("a",), ("b",), ("c",), ("tiny",), ("hidden",)]
    rows = [
        campaign(300, 10, 2),
        campaign(500, 10, 7),
        campaign(3000, 10, 6),
        campaign(10, 4, 0),  # under 10 leads
        campaign(100, 12, 3),  # its qualified count is suppressed
    ]
    hidden = [set(), set(), set(), set(), {"paid_qualified_leads"}]

    result = _flag("cheap_leads_low_qualification", keys, rows, hidden)

    assert result["summary"]["rows_judged"] == 3
    assert ("tiny",) not in result["keys"] and ("hidden",) not in result["keys"]


def test_fewer_than_three_campaigns_flag_nothing_and_say_why():
    result = _flag(
        "cheap_leads_low_qualification",
        [("a",), ("b",)],
        [campaign(300, 10, 2), campaign(3000, 10, 6)],
        [set(), set()],
    )

    assert result["keys"] == set()
    assert "Fewer than 3" in result["summary"]["note"]


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ({"group_by": ["channel"], "metrics": ["cost_per_lead"]}, "group_by must be"),
        ({"group_by": ["campaign"], "metrics": ["leads"]}, "needs cost_per_lead"),
    ],
)
def test_flags_need_campaign_rows_and_costs(query, message):
    with pytest.raises(ValidationError, match=message):
        PerformanceQuery.model_validate(
            {"period": QUARTER, "flags": ["cheap_leads_low_qualification"], **query}
        )
