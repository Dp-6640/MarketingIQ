"""The metric registry: every metric's name, unit, formula and plain-language definition.

One place for definitions (docs/metrics.md), used by REST endpoints, assistant tools and
tests alike. Metrics are either a *base* quantity summed from one data family, or a *ratio*
of two base quantities. Cost metrics divide spend by leads credited to campaigns that have
a spend feed (the `paid_*` bases), so organic leads never dilute a cost per lead.
"""

from dataclasses import dataclass
from typing import Literal

Family = Literal["spend", "sessions", "leads"]
Unit = Literal["count", "currency", "rate", "ratio"]

# Base quantities, by the family (table) they're summed from.
BASES: dict[str, Family] = {
    "spend": "spend",
    "impressions": "spend",
    "link_clicks": "spend",
    "platform_reported_leads": "spend",
    "sessions": "sessions",
    "form_submit_sessions": "sessions",
    "leads": "leads",
    "qualified_leads": "leads",
    "consultations_booked": "leads",
    "consultations_completed": "leads",
    "opportunities": "leads",
    "sales_closed": "leads",
    "sales_won": "leads",
    "won_amount": "leads",
    "covered_leads": "leads",
    "journey_leads": "leads",
    "paid_leads": "leads",
    "paid_qualified_leads": "leads",
    "paid_consultations_completed": "leads",
    "paid_sales_won": "leads",
    "paid_won_amount": "leads",
}

# Lead-derived counts: small values are suppressed (docs/metrics.md, small-cell suppression).
SUPPRESSIBLE_BASES = frozenset(
    name for name, family in BASES.items() if family == "leads" and "amount" not in name
)
# Bases whose values depend on how sales close, so recent cohorts look worse than they are.
OUTCOME_BASES = frozenset({"opportunities", "sales_closed", "sales_won", "won_amount"})
AMOUNT_BASES = frozenset({"won_amount", "paid_won_amount"})


@dataclass(frozen=True)
class Metric:
    name: str
    label: str
    unit: Unit
    definition: str
    base: str | None = None  # a base quantity...
    numerator: str | None = None  # ...or a ratio of two
    denominator: str | None = None

    @property
    def bases(self) -> tuple[str, ...]:
        if self.base:
            return (self.base,)
        return (self.numerator, self.denominator)  # type: ignore[return-value]

    @property
    def families(self) -> set[Family]:
        return {BASES[base] for base in self.bases}


def _base(name: str, label: str, unit: Unit, definition: str) -> Metric:
    return Metric(name, label, unit, definition, base=name)


def _ratio(name: str, label: str, unit: Unit, definition: str, num: str, den: str) -> Metric:
    return Metric(name, label, unit, definition, numerator=num, denominator=den)


METRICS: dict[str, Metric] = {
    metric.name: metric
    for metric in (
        _base("spend", "Spend", "currency", "Ad spend reported by the platform, by spend date."),
        _base("impressions", "Impressions", "count", "Ad impressions reported by the platform."),
        _base("link_clicks", "Link clicks", "count", "Clicks on the ad's link (Meta)."),
        _base(
            "platform_reported_leads",
            "Platform-reported leads",
            "count",
            "Leads the ad platform claims under its own attribution setting. Never added to "
            "CRM leads.",
        ),
        _base("sessions", "Sessions", "count", "GA4 sessions started in the period."),
        _base(
            "leads",
            "Leads",
            "count",
            "First leads (not duplicates) created in the period, in the population. Grouped by "
            "campaign or channel, it's the attribution credit under the selected model.",
        ),
        _base(
            "qualified_leads",
            "Qualified leads",
            "count",
            "Leads of the cohort whose stage is qualified or converted as of data_as_of.",
        ),
        _base(
            "consultations_booked",
            "Consultations booked",
            "count",
            "Leads of the cohort with an in-home consultation booked.",
        ),
        _base(
            "consultations_completed",
            "Consultations completed",
            "count",
            "Leads of the cohort whose in-home consultation took place.",
        ),
        _base(
            "opportunities",
            "Opportunities",
            "count",
            "Leads of the cohort converted to an opportunity (quote).",
        ),
        _base("sales_won", "Sales won", "count", "Leads of the cohort whose opportunity was won."),
        _base(
            "won_amount",
            "Recorded won amount",
            "currency",
            "Opportunity amounts of won sales, for one amount basis only (purchase price, "
            "financed total, lease contract or monthly).",
        ),
        _ratio(
            "ctr",
            "Click-through rate",
            "rate",
            "Link clicks / impressions.",
            "link_clicks",
            "impressions",
        ),
        _ratio("cpc", "Cost per click", "currency", "Spend / link clicks.", "spend", "link_clicks"),
        _ratio(
            "form_submit_rate",
            "Form submit rate",
            "rate",
            "Sessions with a quote or callback form submission / sessions.",
            "form_submit_sessions",
            "sessions",
        ),
        _ratio(
            "lead_conversion_rate",
            "Lead conversion rate",
            "rate",
            "Leads / sessions, in the same grouping.",
            "leads",
            "sessions",
        ),
        _ratio(
            "qualification_rate",
            "Qualification rate",
            "rate",
            "Qualified leads / leads, same cohort.",
            "qualified_leads",
            "leads",
        ),
        _ratio(
            "consultation_booking_rate",
            "Consultation booking rate",
            "rate",
            "Consultations booked / qualified leads, same cohort.",
            "consultations_booked",
            "qualified_leads",
        ),
        _ratio(
            "consultation_completion_rate",
            "Consultation completion rate",
            "rate",
            "Consultations completed / consultations booked, same cohort.",
            "consultations_completed",
            "consultations_booked",
        ),
        _ratio(
            "win_rate",
            "Win rate",
            "rate",
            "Sales won / closed opportunities (won or lost).",
            "sales_won",
            "sales_closed",
        ),
        _ratio(
            "lead_to_sale_rate",
            "Lead-to-sale rate",
            "rate",
            "Sales won / leads, same cohort.",
            "sales_won",
            "leads",
        ),
        _ratio(
            "cost_per_lead",
            "Cost per lead",
            "currency",
            "Spend / leads credited to campaigns with a spend feed.",
            "spend",
            "paid_leads",
        ),
        _ratio(
            "cost_per_qualified_lead",
            "Cost per qualified lead",
            "currency",
            "Spend / qualified leads credited to campaigns with a spend feed.",
            "spend",
            "paid_qualified_leads",
        ),
        _ratio(
            "cost_per_completed_consultation",
            "Cost per completed consultation",
            "currency",
            "Spend / completed consultations credited to campaigns with a spend feed.",
            "spend",
            "paid_consultations_completed",
        ),
        _ratio(
            "cost_per_sale",
            "Cost per sale",
            "currency",
            "Spend / sales won credited to campaigns with a spend feed.",
            "spend",
            "paid_sales_won",
        ),
        _ratio(
            "roas",
            "Return on ad spend",
            "ratio",
            "Won amount credited to campaigns with a spend feed / spend, for one amount basis.",
            "paid_won_amount",
            "spend",
        ),
        _ratio(
            "attribution_coverage",
            "Attribution coverage",
            "rate",
            "Leads with campaign-level evidence (tiers T1 to T3) / leads.",
            "covered_leads",
            "leads",
        ),
        _ratio(
            "journey_model_coverage",
            "Journey coverage",
            "rate",
            "Leads with a linked web journey (T1), where attribution models can differ / leads.",
            "journey_leads",
            "leads",
        ),
    )
}

MetricName = Literal[
    "spend",
    "impressions",
    "link_clicks",
    "platform_reported_leads",
    "sessions",
    "leads",
    "qualified_leads",
    "consultations_booked",
    "consultations_completed",
    "opportunities",
    "sales_won",
    "won_amount",
    "ctr",
    "cpc",
    "form_submit_rate",
    "lead_conversion_rate",
    "qualification_rate",
    "consultation_booking_rate",
    "consultation_completion_rate",
    "win_rate",
    "lead_to_sale_rate",
    "cost_per_lead",
    "cost_per_qualified_lead",
    "cost_per_completed_consultation",
    "cost_per_sale",
    "roas",
    "attribution_coverage",
    "journey_model_coverage",
]

# Dimensions, and which data families can be grouped by each.
ATTRIBUTED_DIMENSIONS = ("campaign", "channel", "platform", "campaign_tactic", "evidence_tier")
LEAD_DIMENSIONS = (
    "entry_point",
    "service_line",
    "region",
    "lead_class",
    "customer_type",
    "lead_month",
)
DIMENSION_FAMILIES: dict[str, set[Family]] = {
    "campaign": {"spend", "sessions", "leads"},
    "channel": {"spend", "sessions", "leads"},
    "platform": {"spend", "sessions", "leads"},
    "campaign_tactic": {"spend", "sessions", "leads"},
    "evidence_tier": {"leads"},
    "landing_page": {"sessions"},
    **{dimension: {"leads"} for dimension in LEAD_DIMENSIONS},
}
Dimension = Literal[
    "campaign",
    "channel",
    "platform",
    "campaign_tactic",
    "evidence_tier",
    "landing_page",
    "entry_point",
    "service_line",
    "region",
    "lead_class",
    "customer_type",
    "lead_month",
]
