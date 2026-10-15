"""Counting, as metrics.md defines it: credit-weighted leads, spend, sessions and tiers.

Periods are inclusive dates in the reporting time zone. Lead metrics count by the lead's
creation date (the cohort basis). Credit with no evidence is "(unattributed)" and credit
from an unmapped campaign value is "(unmapped)"; other missing groups come back as None
(channel-only credit has no campaign, an unrecognized city has no region).
"""

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from datetime import date
from decimal import Decimal
from fractions import Fraction

from oracle.facts import Credit, Facts, Lead

LEAD_BASES: dict[str, Callable[[Lead], bool]] = {
    "leads": lambda lead: True,
    "qualified_leads": lambda lead: lead.qualified,
    "consultations_booked": lambda lead: lead.booked,
    "consultations_completed": lambda lead: lead.completed,
    "opportunities": lambda lead: lead.opportunity,
    "sales_closed": lambda lead: lead.closed,
    "sales_won": lambda lead: lead.won,
}
COVERED = ("T1_journey", "T2_captured_source", "T3_platform_native")
ATTRIBUTED = ("campaign", "channel", "platform", "campaign_tactic")
LEAD_PROPERTIES = ("entry_point", "service_line", "region", "lead_class", "customer_type")


def _population(facts: Facts, start: date, end: date, population: str) -> Iterable[Lead]:
    for lead in facts.leads:
        if not lead.first or not start <= lead.day <= end:
            continue
        if population == "all" or lead.lead_class == population:
            yield lead


UNMAPPED, UNATTRIBUTED = "(unmapped)", "(unattributed)"


def _attributed(facts: Facts, credit: Credit, dimension: str) -> str | None:
    """A credit's group: unmapped and unattributed credit get their own named buckets."""
    campaign = facts.campaigns.get(credit.campaign) if credit.campaign else None
    if dimension == "campaign":
        if credit.channel is None:
            return UNATTRIBUTED
        return UNMAPPED if credit.unmapped else credit.campaign
    if dimension == "channel":
        return credit.channel or UNATTRIBUTED
    if dimension == "platform":
        return campaign.platform if campaign else None
    return campaign.tactic if campaign else None


def _property(lead: Lead, dimension: str) -> str | None:
    if dimension == "lead_month":
        return lead.day.strftime("%Y-%m")
    return getattr(lead, dimension)


def campaigns_with_spend(facts: Facts) -> set[str]:
    return {row["campaign"] for row in facts.spend_rows}


def leads(
    facts: Facts,
    start: date,
    end: date,
    base: str = "leads",
    group_by: tuple[str, ...] = (),
    population: str = "acquisition",
    model: str = "last_non_direct",
    lookback: int = 30,
    paid: bool = False,
) -> dict[tuple, Fraction]:
    """Credit-weighted lead counts. `paid` keeps only credit given to campaigns with spend.

    Besides the stage bases, `covered_leads` are leads with campaign-level evidence (T1-T3)
    and `journey_leads` those with a web journey (T1), both at this lookback.
    """
    if base == "covered_leads":
        keep = lambda lead: lead.tier[lookback] in COVERED  # noqa: E731
    elif base == "journey_leads":
        keep = lambda lead: lead.tier[lookback] == "T1_journey"  # noqa: E731
    else:
        keep = LEAD_BASES[base]
    with_spend = campaigns_with_spend(facts) if paid else set()
    totals: dict[tuple, Fraction] = defaultdict(Fraction)
    for lead in _population(facts, start, end, population):
        if not keep(lead):
            continue
        for credit in lead.credits[(model, lookback)]:
            if paid and credit.campaign not in with_spend:
                continue
            key = tuple(
                _attributed(facts, credit, d) if d in ATTRIBUTED else _property(lead, d)
                for d in group_by
            )
            totals[key] += credit.share
    return dict(totals)


def ad_measure(
    facts: Facts, start: date, end: date, measure: str = "spend", group_by: tuple[str, ...] = ()
) -> dict[tuple, Decimal | int]:
    """Meta insights (spend, impressions, link_clicks, platform_reported_leads), by account day."""
    totals: dict[tuple, Decimal | int] = defaultdict(int)
    for row in facts.spend_rows:
        if start <= row["day"] <= end:
            credit = Credit(row["campaign"], facts.campaigns[row["campaign"]].channel, Fraction(1))
            key = tuple(_attributed(facts, credit, d) for d in group_by)
            totals[key] += row[measure]
    return dict(totals)


def sessions(
    facts: Facts, start: date, end: date, group_by: tuple[str, ...] = (), form_submits=False
) -> dict[tuple, int]:
    totals: Counter = Counter()
    for session in facts.sessions:
        if not start <= session.day <= end or (form_submits and not session.form_submit):
            continue
        credit = Credit(session.campaign, session.channel, Fraction(1), session.unmapped)
        key = tuple(
            session.landing_page if d == "landing_page" else _attributed(facts, credit, d)
            for d in group_by
        )
        totals[key] += 1
    return dict(totals)


def tiers(
    facts: Facts, start: date, end: date, population: str = "acquisition", lookback: int = 30
) -> Counter:
    return Counter(lead.tier[lookback] for lead in _population(facts, start, end, population))


def classes(facts: Facts, start: date, end: date) -> Counter:
    """Every lead, duplicates included, by class."""
    return Counter(lead.lead_class for lead in facts.leads if start <= lead.day <= end)
