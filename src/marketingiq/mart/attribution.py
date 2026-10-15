"""Attribution credit: which campaign or channel each lead's credit goes to, per model.

Pure functions, applying docs/attribution.md:
- T1 (a web journey): first_touch, last_non_direct and linear over the non-direct sessions
  inside the lookback. A journey of only direct visits gives all its credit to `direct`.
- T2/T3: one credit of 1 to the captured or native campaign, the same under every model.
- T4: one credit of 1 to the self-reported channel, no campaign.
- T5: one credit of 1, unattributed.

Credits are exact decimals with 8 places; a lead's credits always sum to exactly 1, so
credited totals reconcile with lead counts.

Attribution is a convention for sharing credit, not evidence of cause.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from marketingiq.core.rules import Evidence

MODELS = ("first_touch", "last_non_direct", "linear")
_PLACES = Decimal("0.00000001")


@dataclass(frozen=True)
class Touch:
    user_pseudo_id: str
    ga_session_id: int
    started_at: datetime
    channel: str
    campaign_key: str | None
    campaign_value: str | None


@dataclass(frozen=True)
class Credit:
    model: str
    evidence_tier: str
    session: tuple[str, int] | None  # (user_pseudo_id, ga_session_id) of a credited visit
    campaign_key: str | None
    campaign_value: str | None  # set when a campaign was named, mapped or not
    channel: str | None  # None = unattributed
    credit: Decimal


def split(count: int) -> list[Decimal]:
    """`count` equal shares that sum to exactly 1 (the last absorbs the rounding)."""
    share = (Decimal(1) / count).quantize(_PLACES)
    shares = [share] * count
    shares[-1] += Decimal(1) - share * count
    return shares


def attribute(
    *,
    created_at: datetime,
    evidence: Evidence,
    evidence_campaign_key: str | None,
    touches: list[Touch],
    lookback: timedelta,
) -> list[Credit]:
    """Every model's credits for one lead. `touches` = all sessions of the lead's GA client
    id, sorted by (started_at, ga_session_id); only T1 leads use them."""
    tier = evidence.tier
    if tier != "T1_journey":
        value = None
        if evidence.identifier is not None:
            kind, identifier = evidence.identifier
            value = {"utm_campaign": identifier, "meta_campaign_id": f"meta:{identifier}"}.get(
                kind,
                f"({identifier})",  # a click ID alone: "(gclid)", "(fbclid)"
            )
        return [
            Credit(model, tier, None, evidence_campaign_key, value, evidence.channel, Decimal(1))
            for model in MODELS
        ]

    eligible = [t for t in touches if created_at - lookback <= t.started_at <= created_at]
    credited = [t for t in eligible if t.channel != "direct"]
    if not credited:
        return [Credit(model, tier, None, None, None, "direct", Decimal(1)) for model in MODELS]

    def credit(model: str, touch: Touch, share: Decimal) -> Credit:
        session = (touch.user_pseudo_id, touch.ga_session_id)
        return Credit(
            model, tier, session, touch.campaign_key, touch.campaign_value, touch.channel, share
        )

    credits = [
        credit("first_touch", credited[0], Decimal(1)),
        credit("last_non_direct", credited[-1], Decimal(1)),
    ]
    credits += [
        credit("linear", touch, share)
        for touch, share in zip(credited, split(len(credited)), strict=True)
    ]
    return credits
