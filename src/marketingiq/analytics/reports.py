"""Two reports built on the core model: the lead funnel and source reconciliation."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, text

from marketingiq.analytics.metrics import Dimension
from marketingiq.analytics.performance import (
    SMALL_CELL,
    Filters,
    PerformanceQuery,
    Population,
    get_performance,
    load_context,
    unique_warnings,
    warning,
)
from marketingiq.analytics.periods import (
    ComparisonKind,
    PeriodSpec,
    period_warnings,
    resolve,
)

FUNNEL_STAGES = (
    "leads",
    "qualified_leads",
    "consultations_booked",
    "consultations_completed",
    "opportunities",
    "sales_won",
)
FUNNEL_RATES = (
    "qualification_rate",
    "consultation_booking_rate",
    "consultation_completion_rate",
    "win_rate",
    "lead_to_sale_rate",
)


class FunnelQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    period: PeriodSpec
    compare_to: ComparisonKind = "none"
    comparison: PeriodSpec | None = None
    group_by: list[Dimension] = Field(default_factory=list, max_length=1)
    population: Population | None = None
    filters: Filters = Field(default_factory=Filters)
    attribution_model: Literal["first_touch", "last_non_direct", "linear"] = "last_non_direct"
    lookback_days: Literal[7, 30, 90] = 30


def get_lead_funnel(engine: Engine, org_slug: str, query: FunnelQuery) -> dict[str, Any]:
    """Stage counts and conversion rates for a lead cohort: the same numbers as the
    performance service, because it is the performance service with fixed metrics."""
    result = get_performance(
        engine,
        org_slug,
        PerformanceQuery(
            **query.model_dump(exclude_none=True),
            metrics=[*FUNNEL_STAGES, *FUNNEL_RATES],
        ),
    )
    result["stages"] = list(FUNNEL_STAGES)
    return result


class ReconciliationQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    period: PeriodSpec
    lookback_days: Literal[7, 30, 90] = 30


def get_source_reconciliation(
    engine: Engine, org_slug: str, query: ReconciliationQuery
) -> dict[str, Any]:
    """Meta-reported leads, GA4 form-submit sessions and Salesforce leads linked to each
    Meta campaign, side by side. Each source counts differently; they're never added up.

    "Linked" CRM leads are first leads, of any class, with evidence naming the campaign
    (a journey touch inside the lookback, a captured UTM or a native Meta id).
    """
    with engine.connect() as conn:
        ctx = load_context(conn, org_slug)
        period = resolve(query.period, ctx.data_as_of)
        start, end = period.utc_bounds(ctx.tz)
        params = {
            "org": ctx.id,
            "from_date": period.start,
            "to_date": period.end,
            "start": start,
            "end": end,
            "lookback": query.lookback_days,
        }
        reported = dict(
            conn.execute(
                text(
                    "SELECT c.key, sum(s.platform_reported_leads) FROM core.ad_spend_daily s"
                    " JOIN core.campaigns c ON c.id = s.campaign_id WHERE s.org_id = :org"
                    " AND s.report_date BETWEEN :from_date AND :to_date GROUP BY c.key"
                ),
                params,
            ).all()
        )
        form_submits = dict(
            conn.execute(
                text(
                    "SELECT c.key, count(*) FROM core.web_sessions s"
                    " JOIN core.campaigns c ON c.id = s.campaign_id WHERE s.org_id = :org"
                    " AND c.platform = 'meta' AND s.started_at >= :start AND s.started_at < :end"
                    " AND s.ev_quote_submit + s.ev_callback_submit > 0 GROUP BY c.key"
                ),
                params,
            ).all()
        )
        linked = dict(
            conn.execute(
                text(
                    "SELECT c.key, count(DISTINCT a.lead_id) FROM mart.lead_attribution_credits a"
                    " JOIN core.leads l ON l.id = a.lead_id"
                    " JOIN core.campaigns c ON c.id = a.campaign_id"
                    " WHERE a.org_id = :org AND a.model = 'linear' AND a.lookback_days = :lookback"
                    " AND c.platform = 'meta' AND l.created_at >= :start AND l.created_at < :end"
                    " GROUP BY c.key"
                ),
                params,
            ).all()
        )
        totals = conn.execute(
            text(
                "SELECT"
                " (SELECT count(DISTINCT a.lead_id) FROM mart.lead_attribution_credits a"
                "  JOIN core.leads l ON l.id = a.lead_id"
                "  JOIN core.campaigns c ON c.id = a.campaign_id"
                "  WHERE a.org_id = :org AND a.model = 'linear' AND a.lookback_days = :lookback"
                "  AND c.platform = 'meta' AND l.created_at >= :start AND l.created_at < :end)"
                "  AS crm_leads_linked_to_meta,"
                " (SELECT count(*) FROM core.web_sessions WHERE org_id = :org"
                "  AND started_at >= :start AND started_at < :end"
                "  AND ev_quote_submit + ev_callback_submit > 0) AS ga4_form_submit_sessions,"
                " (SELECT count(*) FROM core.leads WHERE org_id = :org AND duplicate_of IS NULL"
                "  AND created_at >= :start AND created_at < :end"
                "  AND entry_point IN ('web_quote_form', 'web_callback_form'))"
                "  AS crm_web_form_leads"
            ),
            params,
        ).one()

    def count(value: int) -> dict[str, Any]:
        if 0 < value < SMALL_CELL:
            return {"value": None, "suppressed": True}
        return {"value": int(value)}

    rows = []
    for key in sorted(set(reported) | set(linked)):
        meta, crm = int(reported.get(key, 0)), int(linked.get(key, 0))
        rows.append(
            {
                "key": key,
                "label": ctx.campaign_names.get(key, key),
                "values": {
                    "meta_reported_leads": {"value": meta},
                    "ga4_form_submit_sessions": count(form_submits.get(key, 0)),
                    "crm_leads_linked": count(crm),
                    "meta_to_crm_ratio": (
                        {"value": round(meta / crm, 2)}
                        if crm >= SMALL_CELL
                        else {"value": None, "null_reason": "too_few_crm_leads"}
                    ),
                },
            }
        )
    codes = ["sources_not_additive", *period_warnings(period, None, "none", ctx.data_start)]
    if ctx.is_synthetic:
        codes.insert(0, "synthetic_data")
    if any(r["values"]["crm_leads_linked"].get("suppressed") for r in rows):
        codes.append("small_cell_suppressed")
    meta_total = int(sum(reported.values()))
    return {
        "resolved": {
            "period": period.as_dict(),
            "lookback_days": query.lookback_days,
            "reporting_tz": ctx.reporting_tz,
            "data_as_of": ctx.data_as_of.isoformat(),
            "synthetic": ctx.is_synthetic,
        },
        "rows": rows,
        "totals": {
            "meta_reported_leads": {"value": meta_total},
            "crm_leads_linked_to_meta": {"value": int(totals.crm_leads_linked_to_meta)},
            "ga4_form_submit_sessions": {"value": int(totals.ga4_form_submit_sessions)},
            "crm_web_form_leads": {"value": int(totals.crm_web_form_leads)},
        },
        "warnings": unique_warnings([warning(code) for code in codes]),
    }
