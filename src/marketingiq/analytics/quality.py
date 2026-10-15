"""The data-quality report: what can't be trusted about a period, and why.

It answers "what can't we conclude?" and "is the data complete?" with measured facts:
evidence coverage, classification defaults, unmapped campaigns, channels without spend,
tracking capture by week (a sudden drop means broken hidden fields, not fewer customers),
missing days per source, load rejections, cohort maturity and time zones.
"""

from datetime import date, timedelta
from statistics import median
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine, text

from marketingiq.analytics.performance import (
    LOW_COVERAGE,
    SMALL_CELL,
    load_context,
    unique_warnings,
    warning,
)
from marketingiq.analytics.periods import PeriodSpec, period_warnings, resolve

CAPTURE_DROP = 0.5  # a week below half the usual capture share is flagged
CAPTURE_MIN_LEADS = 5
COVERED = ("T1_journey", "T2_captured_source", "T3_platform_native")


class QualityQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    period: PeriodSpec


def _count(value: int | float) -> dict[str, Any]:
    if 0 < value < SMALL_CELL:
        return {"value": None, "suppressed": True}
    return {"value": int(value)}


def _counts(rows: list[tuple[Any, int]]) -> dict[str, dict[str, Any]]:
    return {str(key): _count(value) for key, value in rows}


def get_data_quality(engine: Engine, org_slug: str, query: QualityQuery) -> dict[str, Any]:
    with engine.connect() as conn:
        ctx = load_context(conn, org_slug)
        period = resolve(query.period, ctx.data_as_of)
        start, end = period.utc_bounds(ctx.tz)
        params = {
            "org": ctx.id,
            "start": start,
            "end": end,
            "from_date": period.start,
            "to_date": period.end,
            "tz": ctx.reporting_tz,
        }

        def rows(sql: str) -> list[tuple]:
            return [tuple(row) for row in conn.execute(text(sql), params)]

        leads_in_period = (
            "FROM core.leads WHERE org_id = :org AND created_at >= :start AND created_at < :end"
        )
        first_leads = f"{leads_in_period} AND duplicate_of IS NULL"
        tiers = rows(f"SELECT evidence_tier, count(*) {first_leads} GROUP BY 1 ORDER BY 1")
        acquisition_tiers = dict(
            rows(
                f"SELECT evidence_tier, count(*) {first_leads}"
                " AND lead_class = 'acquisition' GROUP BY 1"
            )
        )
        classes = rows(f"SELECT lead_class, count(*) {first_leads} GROUP BY 1 ORDER BY 1")
        request_sources = rows(
            f"SELECT request_type_source, count(*) {first_leads} GROUP BY 1 ORDER BY 1"
        )
        acquisition = sum(acquisition_tiers.values())
        unknown_service, unknown_customer = rows(
            "SELECT count(*) FILTER (WHERE service_line = 'unknown'),"
            " count(*) FILTER (WHERE customer_type = 'unknown')"
            f" {first_leads} AND lead_class = 'acquisition'"
        )[0]
        junk = rows(
            f"SELECT junk_reason, count(*) {leads_in_period}"
            " AND junk_reason IS NOT NULL GROUP BY 1 ORDER BY 1"
        )
        cities = rows(f"SELECT city_match, count(*) {first_leads} GROUP BY 1 ORDER BY 1")
        unmapped = rows(
            "SELECT campaign_value, count(*) FROM core.web_sessions WHERE org_id = :org"
            " AND started_at >= :start AND started_at < :end AND campaign_value IS NOT NULL"
            " AND campaign_id IS NULL GROUP BY 1 ORDER BY 2 DESC"
        )
        spend_outside_sheet = rows(
            "SELECT c.name, sum(s.spend) FROM core.ad_spend_daily s"
            " JOIN core.campaigns c ON c.id = s.campaign_id WHERE s.org_id = :org"
            " AND NOT c.in_mapping_sheet AND s.report_date BETWEEN :from_date AND :to_date"
            " GROUP BY 1 ORDER BY 1"
        )
        no_spend_channels = rows(
            "SELECT coalesce(a.channel, '(unattributed)'), sum(a.credit)"
            " FROM mart.lead_attribution_credits a JOIN core.leads l ON l.id = a.lead_id"
            " LEFT JOIN core.campaigns c ON c.id = a.campaign_id"
            " WHERE a.org_id = :org AND a.model = 'last_non_direct' AND a.lookback_days = 30"
            " AND l.lead_class = 'acquisition' AND l.created_at >= :start AND l.created_at < :end"
            " AND coalesce(c.has_spend_feed, false) = false GROUP BY 1 ORDER BY 2 DESC"
        )
        weekly = rows(
            "SELECT date_trunc('week', created_at AT TIME ZONE :tz)::date AS week, count(*),"
            " count(*) FILTER (WHERE utm_source IS NOT NULL OR click_id_type IS NOT NULL"
            "  OR ga_client_id IS NOT NULL OR form_page_path IS NOT NULL)"
            " FROM core.leads WHERE org_id = :org AND duplicate_of IS NULL"
            " AND entry_point IN ('web_quote_form', 'web_callback_form') GROUP BY 1 ORDER BY 1"
        )
        empty_days = {
            "meta_insights": _missing_days(
                period,
                rows(
                    "SELECT DISTINCT report_date FROM core.ad_spend_daily"
                    " WHERE org_id = :org AND report_date BETWEEN :from_date AND :to_date"
                ),
            ),
            "ga4_sessions": _missing_days(
                period,
                rows(
                    "SELECT DISTINCT (started_at AT TIME ZONE :tz)::date FROM core.web_sessions"
                    " WHERE org_id = :org AND started_at >= :start AND started_at < :end"
                ),
            ),
            "salesforce_leads": _missing_days(
                period,
                rows(
                    "SELECT DISTINCT (created_at AT TIME ZONE :tz)::date FROM core.leads"
                    " WHERE org_id = :org AND created_at >= :start AND created_at < :end"
                ),
            ),
        }
        loads = rows(
            "SELECT b.entity, b.rows_loaded, b.rows_rejected, b.rows_duplicate"
            " FROM core.load_batches b WHERE b.org_id = :org AND b.id IN ("
            " SELECT max(id) FROM core.load_batches WHERE org_id = :org"
            " AND status = 'succeeded' GROUP BY entity) ORDER BY 1"
        )
        failed_loads = rows(
            "SELECT count(*) FROM core.load_batches WHERE org_id = :org AND status = 'failed'"
        )[0][0]

    shares = [captured / total for _, total, captured in weekly if total >= CAPTURE_MIN_LEADS]
    usual = median(shares) if shares else None
    capture_weeks = []
    for week, total, captured in weekly:
        if not period.start - timedelta(days=6) <= week <= period.end:
            continue
        share = captured / total if total else None
        dropped = bool(
            usual
            and share is not None
            and total >= CAPTURE_MIN_LEADS
            and share < CAPTURE_DROP * usual
        )
        capture_weeks.append(
            {
                "week_of": week.isoformat(),
                "web_form_leads": _count(total),
                "capture_share": round(share, 4)
                if share is not None and total >= SMALL_CELL
                else None,
                "dropped": dropped,
            }
        )
    covered = sum(acquisition_tiers.get(tier, 0) for tier in COVERED)
    coverage = covered / acquisition if acquisition else None

    codes = ["synthetic_data"] if ctx.is_synthetic else []
    codes += period_warnings(period, None, "none", ctx.data_start)
    if not all(section["verified"] for section in ctx.rules.values()):
        codes.append("mapping_unverified")
    if coverage is not None and coverage < LOW_COVERAGE:
        codes.append("low_attribution_coverage")
    if any(
        source == "entry_point_default" or source == "campaign" for source, _ in request_sources
    ):
        codes.append("classification_default_applied")
    if unmapped or spend_outside_sheet:
        codes.append("unmapped_campaigns")
    if no_spend_channels:
        codes.append("no_spend_source")
    if any(week["dropped"] for week in capture_weeks):
        codes.append("capture_drop")
    if any(days for days in empty_days.values()):
        codes.append("source_incomplete")
    if any(tz != ctx.reporting_tz for tz in ctx.meta_timezones):
        codes.append("timezone_mismatch")
    if ctx.maturity_days is None:
        codes.append("maturity_unknown")
    elif period.end > ctx.data_as_of - timedelta(days=ctx.maturity_days):
        codes.append("immature_cohort")

    return {
        "resolved": {
            "period": period.as_dict(),
            "reporting_tz": ctx.reporting_tz,
            "data_as_of": ctx.data_as_of.isoformat(),
            "synthetic": ctx.is_synthetic,
        },
        "evidence": {
            "first_leads_by_tier": _counts(tiers),
            "acquisition_coverage": round(coverage, 4) if coverage is not None else None,
        },
        "classification": {
            "first_leads_by_class": _counts(classes),
            "request_type_sources": _counts(request_sources),
            "acquisition_unknown_service_line": _count(unknown_service),
            "acquisition_unknown_customer_type": _count(unknown_customer),
            "junk_by_reason": _counts(junk),
        },
        "campaign_mapping": {
            "unmapped_campaign_values": {value: {"sessions": n} for value, n in unmapped},
            "spend_not_in_mapping_sheet": {
                name: {"spend": float(s)} for name, s in spend_outside_sheet
            },
        },
        "acquisition_without_spend_feed_by_channel": {
            channel: _count(round(float(credit))) for channel, credit in no_spend_channels
        },
        "capture_by_week": capture_weeks,
        "usual_weekly_capture_share": round(usual, 4) if usual is not None else None,
        "days_without_data": {
            source: [day.isoformat() for day in days] for source, days in empty_days.items()
        },
        "cities": _counts(cities),
        "latest_loads": {
            entity: {"loaded": loaded, "rejected": rejected, "duplicates": duplicates}
            for entity, loaded, rejected, duplicates in loads
        },
        "failed_loads": failed_loads,
        "cohort_maturity_days": round(ctx.maturity_days) if ctx.maturity_days else None,
        "timezones": {"reporting": ctx.reporting_tz, "meta_accounts": ctx.meta_timezones},
        "warnings": unique_warnings([warning(code) for code in codes]),
    }


def _missing_days(period, rows: list[tuple[date]]) -> list[date]:
    present = {day for (day,) in rows}
    return [
        period.start + timedelta(days=offset)
        for offset in range(period.days)
        if period.start + timedelta(days=offset) not in present
    ]
