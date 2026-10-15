from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from marketingiq.core.rules import Evidence
from marketingiq.mart.attribution import MODELS, Touch, attribute, split

LEAD_AT = datetime(2026, 3, 10, 12, tzinfo=UTC)
LOOKBACK = timedelta(days=30)


def touch(days_before: float, channel: str, campaign: str | None = None, session: int = 0) -> Touch:
    return Touch(
        "1.1",
        session or int(days_before * 1000),
        LEAD_AT - timedelta(days=days_before),
        channel,
        campaign,
        campaign,
    )


JOURNEY = Evidence("T1_journey")


def credits_by_model(touches, evidence=JOURNEY, campaign_key=None):
    result = attribute(
        created_at=LEAD_AT,
        evidence=evidence,
        evidence_campaign_key=campaign_key,
        touches=sorted(touches, key=lambda t: (t.started_at, t.ga_session_id)),
        lookback=LOOKBACK,
    )
    grouped = {model: [] for model in MODELS}
    for credit in result:
        grouped[credit.model].append(credit)
    return grouped


@pytest.mark.parametrize("count", [1, 2, 3, 6, 7])
def test_shares_always_sum_to_exactly_one(count):
    shares = split(count)

    assert sum(shares) == Decimal(1)
    assert max(shares) - min(shares) < Decimal("0.0000001")


def test_journey_models_credit_first_last_and_every_non_direct_touch():
    journey = [
        touch(20, "paid_social", "meta_a"),
        touch(10, "direct"),
        touch(5, "organic_search"),
        touch(1, "paid_social", "meta_b"),
    ]

    credits = credits_by_model(journey)

    assert [c.campaign_key for c in credits["first_touch"]] == ["meta_a"]
    assert [c.campaign_key for c in credits["last_non_direct"]] == ["meta_b"]
    assert [c.channel for c in credits["linear"]] == [
        "paid_social",
        "organic_search",
        "paid_social",
    ]
    for model in MODELS:
        assert sum(c.credit for c in credits[model]) == Decimal(1)


def test_sessions_outside_the_lookback_or_after_the_lead_get_nothing():
    journey = [
        touch(45, "paid_social", "too_early"),
        touch(3, "organic_search"),
        touch(-1, "paid_social", "after_the_lead"),
    ]

    credits = credits_by_model(journey)

    for model in MODELS:
        assert [c.channel for c in credits[model]] == ["organic_search"]


def test_a_journey_of_only_direct_visits_credits_direct():
    credits = credits_by_model([touch(4, "direct"), touch(1, "direct")])

    for model in MODELS:
        assert [(c.channel, c.campaign_key, c.credit) for c in credits[model]] == [
            ("direct", None, Decimal(1))
        ]


def test_ties_break_by_session_id_so_results_are_deterministic():
    same_time = [touch(2, "referral", session=2), touch(2, "organic_search", session=1)]

    credits = credits_by_model(same_time)

    assert credits["first_touch"][0].channel == "organic_search"
    assert credits["last_non_direct"][0].channel == "referral"


def test_single_touch_tiers_give_the_same_credit_under_every_model():
    captured = Evidence(
        "T2_captured_source", identifier=("utm_campaign", "x"), channel="paid_social"
    )
    native = Evidence(
        "T3_platform_native", identifier=("meta_campaign_id", "99"), channel="paid_social"
    )

    for evidence, key, value in ((captured, "x", "x"), (native, None, "meta:99")):
        credits = credits_by_model([], evidence, campaign_key=key)
        assert {
            (c.campaign_key, c.campaign_value, c.credit) for m in MODELS for c in credits[m]
        } == {(key, value, Decimal(1))}


def test_unattributed_and_self_reported_leads():
    none = credits_by_model([], Evidence("T5_none"))
    reported = credits_by_model([], Evidence("T4_self_reported_channel", channel="word_of_mouth"))

    assert none["linear"][0].channel is None
    assert reported["first_touch"][0].channel == "word_of_mouth"
    assert reported["first_touch"][0].campaign_key is None
