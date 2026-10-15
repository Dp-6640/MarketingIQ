"""Performance metrics for a period, grouped and optionally compared.

The one function behind the "get performance" tool and REST endpoint. Every result carries:
- `resolved`: the exact dates, population, attribution model and settings used;
- `warnings`: caveat codes from docs/metrics.md that the numbers need;
- values with a `null_reason` instead of a number whenever one can't be computed honestly.

Three data families are summed separately and joined by group key: spend (Meta insights),
sessions (GA4) and leads (Salesforce cohort by creation date, weighted by attribution
credit). Credits sum to exactly 1 per lead, so credit-weighted counts equal plain counts
whatever the grouping.
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import median
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, text

from marketingiq.analytics.metrics import (
    AMOUNT_BASES,
    ATTRIBUTED_DIMENSIONS,
    BASES,
    DIMENSION_FAMILIES,
    METRICS,
    OUTCOME_BASES,
    SUPPRESSIBLE_BASES,
    Dimension,
    Family,
    MetricName,
)
from marketingiq.analytics.periods import (
    ComparisonKind,
    PeriodSpec,
    comparison_period,
    period_warnings,
    resolve,
)

SMALL_CELL = Decimal(5)
LOW_COVERAGE = 0.6
MATURITY_PERCENTILE = 0.8
MATURITY_MIN_CLOSED = 30

Population = Literal[
    "acquisition",
    "existing_customer_sales",
    "service_demand",
    "non_marketing",
    "junk",
    "unknown",
    "all",
]
LEAD_FILTERS = ("service_lines", "regions", "entry_points")
AmountBasis = Literal["purchase_price", "financed_total", "lease_contract", "monthly"]


class Filters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    campaigns: list[str] | None = None  # campaign keys
    channels: list[str] | None = None
    platforms: list[str] | None = None
    service_lines: list[str] | None = None
    regions: list[str] | None = None
    entry_points: list[str] | None = None


class PerformanceQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    period: PeriodSpec
    compare_to: ComparisonKind = "none"
    comparison: PeriodSpec | None = None  # only with compare_to = "custom"
    group_by: list[Dimension] = Field(default_factory=list, max_length=2)
    metrics: list[MetricName] = Field(min_length=1, max_length=12)
    population: Population | None = None  # None = the default, acquisition
    filters: Filters = Field(default_factory=Filters)
    attribution_model: Literal["first_touch", "last_non_direct", "linear"] = "last_non_direct"
    lookback_days: Literal[7, 30, 90] = 30
    amount_basis: AmountBasis | None = None
    sort_by: MetricName | None = None
    sort_desc: bool = True
    limit: int = Field(25, ge=1, le=100)
    # Deterministic row selections the tool makes, so an LLM never compares numbers itself.
    flags: list[Literal["cheap_leads_low_qualification"]] = Field(
        default_factory=list, max_length=1
    )

    @model_validator(mode="after")
    def _consistent(self) -> "PerformanceQuery":
        if (self.compare_to == "custom") != (self.comparison is not None):
            raise ValueError("comparison is required with compare_to='custom', and only then")
        if len(set(self.group_by)) != len(self.group_by):
            raise ValueError("group_by repeats a dimension")
        if self.sort_by is not None and self.sort_by not in self.metrics:
            raise ValueError("sort_by must be one of the requested metrics")
        if self.flags and self.group_by != ["campaign"]:
            raise ValueError("flags compare campaigns: group_by must be ['campaign']")
        if self.flags and "cost_per_lead" not in self.metrics:
            raise ValueError("cheap_leads_low_qualification needs cost_per_lead in metrics")
        return self


# Question 6, "low cost per lead but high cost per qualified lead". Cost per qualified lead
# is cost per lead / qualification rate, and costs per lead and per qualified lead rise and
# fall together across campaigns, so the question is answered by the rate that separates
# them: cheap leads, of which few qualify (docs/question-tool-map.md).
FLAG_RULES = {
    "cheap_leads_low_qualification": {
        "rule": "Among campaigns with spend and at least 10 credited leads: cost per lead "
        "below the median and qualification rate below the median, so each qualified lead "
        "costs more than the low cost per lead suggests.",
        "min_paid_leads": Decimal(10),
        "min_rows": 3,
    }
}


@dataclass(frozen=True)
class OrgContext:
    id: int
    tz: ZoneInfo
    reporting_tz: str
    currency: str
    is_synthetic: bool
    data_as_of: date
    data_start: date | None
    rules: dict[str, Any]
    meta_timezones: list[str]
    maturity_days: float | None
    campaign_names: dict[str, str]


def load_context(conn: Connection, org_slug: str) -> OrgContext:
    org = conn.execute(
        text(
            "SELECT id, reporting_tz, currency, is_synthetic, data_as_of"
            " FROM core.organizations WHERE slug = :slug"
        ),
        {"slug": org_slug},
    ).one_or_none()
    if org is None:
        raise LookupError(f"no organization with slug {org_slug!r}")
    if org.data_as_of is None:
        raise LookupError(f"{org_slug} has no data_as_of; load data first")
    params = {"org": org.id, "tz": org.reporting_tz}
    rules = conn.execute(
        text("SELECT rules FROM core.build_runs WHERE org_id = :org ORDER BY id DESC LIMIT 1"),
        params,
    ).scalar()
    if rules is None:
        raise LookupError(f"{org_slug} has no core build yet; run the core build first")
    data_start = conn.execute(
        text(
            "SELECT least("
            " (SELECT min(report_date) FROM core.ad_spend_daily WHERE org_id = :org),"
            " (SELECT min((created_at AT TIME ZONE :tz)::date) FROM core.leads"
            "  WHERE org_id = :org))"
        ),
        params,
    ).scalar()
    meta_timezones = [
        tz
        for (tz,) in conn.execute(
            text(
                "SELECT DISTINCT source_tz FROM core.ad_spend_daily WHERE org_id = :org ORDER BY 1"
            ),
            params,
        )
    ]
    closed, percentile = conn.execute(
        text(
            "SELECT count(*), percentile_cont(:p) WITHIN GROUP"
            " (ORDER BY o.close_date - (l.created_at AT TIME ZONE :tz)::date)"
            " FROM core.opportunities o JOIN core.leads l ON l.id = o.lead_id"
            " WHERE o.org_id = :org AND o.outcome IN ('won', 'lost')"
        ),
        {**params, "p": MATURITY_PERCENTILE},
    ).one()
    names = dict(
        conn.execute(text("SELECT key, name FROM core.campaigns WHERE org_id = :org"), params).all()
    )
    return OrgContext(
        id=org.id,
        tz=ZoneInfo(org.reporting_tz),
        reporting_tz=org.reporting_tz,
        currency=org.currency,
        is_synthetic=org.is_synthetic,
        data_as_of=org.data_as_of,
        data_start=data_start,
        rules=rules,
        meta_timezones=meta_timezones,
        maturity_days=float(percentile) if closed >= MATURITY_MIN_CLOSED else None,
        campaign_names=names,
    )


# --- SQL per family -------------------------------------------------------------------

_SPEND_DIMENSIONS = {
    "campaign": "c.key",
    "channel": "CASE c.platform WHEN 'meta' THEN 'paid_social'"
    " WHEN 'google_ads' THEN 'paid_search' ELSE 'other' END",
    "platform": "c.platform",
    "campaign_tactic": "coalesce(c.tactic, '(none)')",
}
_SESSION_DIMENSIONS = {
    "campaign": "coalesce(c.key, CASE WHEN s.campaign_value IS NOT NULL"
    " THEN '(unmapped)' ELSE '(no campaign)' END)",
    "channel": "s.channel",
    "platform": "coalesce(c.platform, '(none)')",
    "campaign_tactic": "coalesce(c.tactic, '(none)')",
    "landing_page": "p.path",
    "landing_page_type": "p.page_type",
}
_LEAD_DIMENSIONS = {
    "campaign": "coalesce(cc.key, CASE WHEN a.campaign_value IS NOT NULL THEN '(unmapped)'"
    " WHEN a.channel IS NULL THEN '(unattributed)' ELSE '(no campaign)' END)",
    "channel": "coalesce(a.channel, '(unattributed)')",
    "platform": "coalesce(cc.platform, '(none)')",
    "campaign_tactic": "coalesce(cc.tactic, '(none)')",
    "evidence_tier": "a.evidence_tier",
    "entry_point": "b.entry_point",
    "service_line": "b.service_line",
    "region": "coalesce(b.region, '(unknown)')",
    "lead_class": "b.lead_class",
    "customer_type": "b.customer_type",
    "lead_month": "b.lead_month",
}


def _group_sql(expressions: dict[str, str], dimensions: list[str]) -> tuple[str, str]:
    columns = [f"{expressions[d]} AS d{i}" for i, d in enumerate(dimensions)]
    select = ", ".join(columns) + ", " if columns else ""
    group = "GROUP BY " + ", ".join(f"d{i}" for i in range(len(dimensions))) if columns else ""
    return select, group


def _rows_by_key(result: Any, dimensions: list[str]) -> dict[tuple, dict[str, Decimal]]:
    rows: dict[tuple, dict[str, Decimal]] = {}
    for row in result.mappings():
        key = tuple(row[f"d{i}"] for i in range(len(dimensions)))
        rows[key] = {
            name: Decimal(value or 0) for name, value in row.items() if not name.startswith("d")
        }
    return rows


def _spend(conn, ctx, query, period, dimensions) -> dict[tuple, dict[str, Decimal]]:
    select, group = _group_sql(_SPEND_DIMENSIONS, dimensions)
    where, params = [], {"org": ctx.id, "start": period.start, "end": period.end}
    filters = query.filters
    if filters.campaigns:
        where.append("c.key = ANY(:campaigns)")
        params["campaigns"] = filters.campaigns
    if filters.channels:
        where.append(f"({_SPEND_DIMENSIONS['channel']}) = ANY(:channels)")
        params["channels"] = filters.channels
    if filters.platforms:
        where.append("c.platform = ANY(:platforms)")
        params["platforms"] = filters.platforms
    sql = (
        f"SELECT {select} sum(s.spend) AS spend, sum(s.impressions) AS impressions,"
        " sum(s.link_clicks) AS link_clicks,"
        " sum(s.platform_reported_leads) AS platform_reported_leads"
        " FROM core.ad_spend_daily s JOIN core.campaigns c ON c.id = s.campaign_id"
        " WHERE s.org_id = :org AND s.report_date BETWEEN :start AND :end"
        + "".join(f" AND {condition}" for condition in where)
        + f" {group}"
    )
    return _rows_by_key(conn.execute(text(sql), params), dimensions)


def _sessions(conn, ctx, query, period, dimensions) -> dict[tuple, dict[str, Decimal]]:
    select, group = _group_sql(_SESSION_DIMENSIONS, dimensions)
    start, end = period.utc_bounds(ctx.tz)
    where, params = [], {"org": ctx.id, "start": start, "end": end}
    filters = query.filters
    if filters.campaigns:
        where.append("c.key = ANY(:campaigns)")
        params["campaigns"] = filters.campaigns
    if filters.channels:
        where.append("s.channel = ANY(:channels)")
        params["channels"] = filters.channels
    if filters.platforms:
        where.append("c.platform = ANY(:platforms)")
        params["platforms"] = filters.platforms
    sql = (
        f"SELECT {select} count(*) AS sessions,"
        " sum(CASE WHEN s.ev_quote_submit + s.ev_callback_submit > 0 THEN 1 ELSE 0 END)"
        " AS form_submit_sessions"
        " FROM core.web_sessions s LEFT JOIN core.campaigns c ON c.id = s.campaign_id"
        " JOIN core.landing_pages p ON p.id = s.landing_page_id"
        " WHERE s.org_id = :org AND s.started_at >= :start AND s.started_at < :end"
        + "".join(f" AND {condition}" for condition in where)
        + f" {group}"
    )
    return _rows_by_key(conn.execute(text(sql), params), dimensions)


_COVERED = "('T1_journey', 'T2_captured_source', 'T3_platform_native')"


def _leads(conn, ctx, query, period, dimensions, population) -> dict[tuple, dict[str, Decimal]]:
    select, group = _group_sql(_LEAD_DIMENSIONS, dimensions)
    start, end = period.utc_bounds(ctx.tz)
    params: dict[str, Any] = {
        "org": ctx.id,
        "start": start,
        "end": end,
        "tz": ctx.reporting_tz,
        "model": query.attribution_model,
        "lookback": query.lookback_days,
        "basis": query.amount_basis,
    }
    lead_where, credit_where = [], []
    if population != "all":
        lead_where.append("l.lead_class = :population")
        params["population"] = population
    filters = query.filters
    for name, column in (
        ("service_lines", "l.service_line"),
        ("regions", "l.region"),
        ("entry_points", "l.entry_point"),
    ):
        if getattr(filters, name):
            lead_where.append(f"{column} = ANY(:{name})")
            params[name] = getattr(filters, name)
    if filters.campaigns:
        credit_where.append("cc.key = ANY(:campaigns)")
        params["campaigns"] = filters.campaigns
    if filters.channels:
        credit_where.append(f"({_LEAD_DIMENSIONS['channel']}) = ANY(:channels)")
        params["channels"] = filters.channels
    if filters.platforms:
        credit_where.append(f"({_LEAD_DIMENSIONS['platform']}) = ANY(:platforms)")
        params["platforms"] = filters.platforms

    paid = "a.credit * CASE WHEN cc.has_spend_feed THEN 1 ELSE 0 END"
    sql = (
        "WITH b AS (SELECT l.id, l.entry_point, l.service_line, l.region, l.lead_class,"
        " l.customer_type, to_char(l.created_at AT TIME ZONE :tz, 'YYYY-MM') AS lead_month,"
        " CASE WHEN l.is_qualified THEN 1 ELSE 0 END AS qualified,"
        " CASE WHEN EXISTS (SELECT 1 FROM core.appointments ap WHERE ap.lead_id = l.id"
        "   AND ap.kind = 'in_home_consultation') THEN 1 ELSE 0 END AS booked,"
        " CASE WHEN EXISTS (SELECT 1 FROM core.appointments ap WHERE ap.lead_id = l.id"
        "   AND ap.kind = 'in_home_consultation' AND ap.status = 'completed')"
        "   THEN 1 ELSE 0 END AS completed,"
        " CASE WHEN o.id IS NULL THEN 0 ELSE 1 END AS opportunity,"
        " CASE WHEN o.outcome IN ('won', 'lost') THEN 1 ELSE 0 END AS closed,"
        " CASE WHEN o.outcome = 'won' THEN 1 ELSE 0 END AS won,"
        " CASE WHEN o.outcome = 'won' AND o.amount_basis = :basis THEN o.amount ELSE 0 END"
        "   AS won_amount"
        " FROM core.leads l LEFT JOIN core.opportunities o ON o.lead_id = l.id"
        " WHERE l.org_id = :org AND l.duplicate_of IS NULL"
        " AND l.created_at >= :start AND l.created_at < :end"
        + "".join(f" AND {condition}" for condition in lead_where)
        + ")"
        f" SELECT {select}"
        " sum(a.credit) AS leads, sum(a.credit * b.qualified) AS qualified_leads,"
        " sum(a.credit * b.booked) AS consultations_booked,"
        " sum(a.credit * b.completed) AS consultations_completed,"
        " sum(a.credit * b.opportunity) AS opportunities,"
        " sum(a.credit * b.closed) AS sales_closed, sum(a.credit * b.won) AS sales_won,"
        " sum(a.credit * b.won_amount) AS won_amount,"
        f" sum(a.credit * CASE WHEN a.evidence_tier IN {_COVERED} THEN 1 ELSE 0 END)"
        "   AS covered_leads,"
        " sum(a.credit * CASE WHEN a.evidence_tier = 'T1_journey' THEN 1 ELSE 0 END)"
        "   AS journey_leads,"
        f" sum({paid}) AS paid_leads, sum({paid} * b.qualified) AS paid_qualified_leads,"
        f" sum({paid} * b.completed) AS paid_consultations_completed,"
        f" sum({paid} * b.won) AS paid_sales_won, sum({paid} * b.won_amount) AS paid_won_amount"
        " FROM b JOIN mart.lead_attribution_credits a ON a.lead_id = b.id"
        " AND a.model = :model AND a.lookback_days = :lookback"
        " LEFT JOIN core.campaigns cc ON cc.id = a.campaign_id"
        " WHERE true" + "".join(f" AND {condition}" for condition in credit_where) + f" {group}"
    )
    return _rows_by_key(conn.execute(text(sql), params), dimensions)


_FAMILY_QUERIES = {"spend": _spend, "sessions": _sessions, "leads": _leads}


# --- assembling the result ------------------------------------------------------------


@dataclass
class Measured:
    """Base values per group key for one period, and which families couldn't be measured."""

    rows: dict[tuple, dict[str, Decimal | None]]
    totals: dict[str, Decimal | None]
    unavailable: dict[Family, str]  # family -> why (a null_reason)


def measure(conn, ctx, query, period, population, families) -> Measured:
    dimensions = list(query.group_by)
    lead_filtered = any(getattr(query.filters, name) for name in LEAD_FILTERS)
    unavailable: dict[Family, str] = {}
    rows: dict[tuple, dict[str, Decimal | None]] = {}
    totals: dict[str, Decimal | None] = {}
    for family in sorted(families):
        if any(family not in DIMENSION_FAMILIES[d] for d in dimensions):
            unavailable[family] = "not_available_for_dimension"
            continue
        if family != "leads" and lead_filtered:
            unavailable[family] = "not_available_for_filter"
            continue
        run = _FAMILY_QUERIES[family]
        args = (conn, ctx, query, period)
        extra = (population,) if family == "leads" else ()
        grouped = run(*args, dimensions, *extra)
        total = run(*args, [], *extra).get((), {})
        for key, values in grouped.items():
            rows.setdefault(key, {}).update(values)
        totals.update(total)
    for values in [*rows.values(), totals]:
        for base, family in BASES.items():
            if family in families:
                values.setdefault(base, None if family in unavailable else Decimal(0))
    return Measured(rows, totals, unavailable)


def _value(metric_name: str, values: dict[str, Decimal | None], measured: Measured, query) -> dict:
    metric = METRICS[metric_name]
    for family in metric.families:
        if family in measured.unavailable:
            return {"value": None, "null_reason": measured.unavailable[family]}
    if any(base in AMOUNT_BASES for base in metric.bases) and query.amount_basis is None:
        return {"value": None, "null_reason": "amount_basis_required"}
    if metric.base:
        return {"value": values.get(metric.base) or Decimal(0)}
    numerator = values.get(metric.numerator) or Decimal(0)
    denominator = values.get(metric.denominator) or Decimal(0)
    if denominator == 0:
        if "spend" in metric.bases and (values.get("spend") or 0) == 0:
            return {"value": None, "null_reason": "no_spend_source"}
        return {"value": None, "null_reason": "zero_denominator"}
    return {"value": numerator / denominator}


def round_value(value: Decimal, unit: str) -> float | int:
    places = {"currency": 2, "rate": 4, "ratio": 2, "count": 2}[unit]
    rounded = round(value, places)
    return (
        int(rounded)
        if unit == "count" and rounded == rounded.to_integral_value()
        else float(rounded)
    )


def suppressed_bases(rows: list[dict[str, Decimal | None]]) -> list[set[str]]:
    """Per row, which lead-derived counts must be hidden (primary and secondary)."""
    hidden = []
    for values in rows:
        small = {
            base
            for base in SUPPRESSIBLE_BASES
            if values.get(base) is not None and 0 < values[base] < SMALL_CELL  # type: ignore[operator]
        }
        hidden.append(small)
    # Secondary suppression: one hidden cell could be recovered from the total, so hide
    # the next-smallest one too.
    for base in SUPPRESSIBLE_BASES:
        flagged = [i for i, h in enumerate(hidden) if base in h]
        if len(flagged) == 1:
            others = [
                (rows[i][base], i)
                for i in range(len(rows))
                if i not in flagged and rows[i].get(base)
            ]
            if others:
                hidden[min(others)[1]].add(base)
    return hidden


def get_performance(engine: Engine, org_slug: str, query: PerformanceQuery) -> dict[str, Any]:
    with engine.connect() as conn:
        ctx = load_context(conn, org_slug)
        period = resolve(query.period, ctx.data_as_of)
        previous = comparison_period(period, query.compare_to, query.comparison, ctx.data_as_of)
        population = query.population or "acquisition"
        families = {family for name in query.metrics for family in METRICS[name].families}
        current = measure(conn, ctx, query, period, population, families)
        prior = measure(conn, ctx, query, previous, population, families) if previous else None
        warnings = query_warnings(conn, ctx, query, period, previous, population, families, current)

    keys = list(current.rows)
    if prior:
        keys += [key for key in prior.rows if key not in current.rows]
    base_rows = [current.rows.get(key, dict.fromkeys(current.totals, Decimal(0))) for key in keys]
    hidden = suppressed_bases(base_rows)
    total_hidden = suppressed_bases([current.totals])[0]
    if any(hidden) or total_hidden:
        warnings.append(warning("small_cell_suppressed"))

    noisy = []

    def values_for(base_values, prior_values, hidden_bases) -> dict[str, dict]:
        result = {}
        for name in query.metrics:
            metric = METRICS[name]
            cell = _value(name, base_values, current, query)
            # A cell with no number for a stated reason keeps that reason; only a real
            # number built from a small count is hidden.
            if hidden_bases & set(metric.bases) and cell.get("value") is not None:
                cell = {"value": None, "suppressed": True}
            if prior_values is not None and not cell.get("suppressed"):
                before = _value(name, prior_values, prior, query)  # type: ignore[arg-type]
                if before.get("value") is not None:
                    cell["previous"] = before["value"]
                    if cell.get("value") is not None:
                        cell["change"] = cell["value"] - before["value"]
                        if before["value"] != 0:
                            cell["change_pct"] = cell["change"] / before["value"]
                        if metric.unit == "rate":
                            significant = _significant(metric, base_values, prior_values)
                            if significant is not None:
                                cell["change_significant"] = significant
                                noisy.append(not significant)
            for field in ("value", "previous", "change"):
                if cell.get(field) is not None:
                    cell[field] = round_value(cell[field], metric.unit)
            if cell.get("change_pct") is not None:
                cell["change_pct"] = round_value(cell["change_pct"], "rate")
            result[name] = cell
        return result

    rows = []
    flag_results = {
        name: _flag(name, keys, base_values=base_rows, hidden=hidden) for name in query.flags
    }
    for key, base_values, hidden_bases in zip(keys, base_rows, hidden, strict=True):
        prior_values = (
            prior.rows.get(key, dict.fromkeys(prior.totals, Decimal(0))) if prior else None
        )
        dimensions = dict(zip(query.group_by, key, strict=True))
        rows.append(
            {
                "key": "|".join(str(part) for part in key),
                "dimensions": dimensions,
                "labels": {d: label(ctx, d, v) for d, v in dimensions.items()},
                "values": values_for(base_values, prior_values, hidden_bases),
            }
        )
        if query.flags:
            rows[-1]["flags"] = [name for name in query.flags if key in flag_results[name]["keys"]]
    _rank(rows, query.metrics)
    totals = values_for(current.totals, prior.totals if prior else None, total_hidden)
    if any(noisy):
        warnings.append(warning("change_within_noise"))
    if query.sort_by:
        rows.sort(key=lambda r: (r["values"][query.sort_by].get("value") is None, r["key"]))
        present = [r for r in rows if r["values"][query.sort_by].get("value") is not None]
        present.sort(key=lambda r: r["values"][query.sort_by]["value"], reverse=query.sort_desc)
        rows = present + [r for r in rows if r["values"][query.sort_by].get("value") is None]
    else:
        rows.sort(key=lambda r: r["key"])

    return {
        "resolved": {
            "period": period.as_dict(),
            "comparison": previous.as_dict() if previous else None,
            "compare_to": query.compare_to,
            "population": population,
            "group_by": list(query.group_by),
            "attribution_model": query.attribution_model,
            "lookback_days": query.lookback_days,
            "amount_basis": query.amount_basis,
            "reporting_tz": ctx.reporting_tz,
            "currency": ctx.currency,
            "data_as_of": ctx.data_as_of.isoformat(),
            "synthetic": ctx.is_synthetic,
        },
        "metrics": {
            name: {
                "label": METRICS[name].label,
                "unit": METRICS[name].unit,
                "definition": METRICS[name].definition,
            }
            for name in query.metrics
        },
        "rows": rows[: query.limit],
        "row_count": len(rows),
        "totals": totals,
        **(
            {"flag_rules": {n: f["summary"] for n, f in flag_results.items()}}
            if query.flags
            else {}
        ),
        "warnings": unique_warnings(warnings),
    }


Z_95 = 1.96


def _significant(metric, now: dict, before: dict) -> bool | None:
    """Whether a rate's change is larger than chance would produce, by a two-proportion
    z-test at 95%. None when it can't be tested (empty or degenerate counts). Credit-weighted
    counts are treated as counts, which is an approximation."""
    n1, d1 = float(now.get(metric.numerator) or 0), float(now.get(metric.denominator) or 0)
    n0, d0 = float(before.get(metric.numerator) or 0), float(before.get(metric.denominator) or 0)
    if d1 <= 0 or d0 <= 0:
        return None
    pooled = (n1 + n0) / (d1 + d0)
    if not 0 < pooled < 1:
        return None
    error = math.sqrt(pooled * (1 - pooled) * (1 / d1 + 1 / d0))
    return abs(n1 / d1 - n0 / d0) / error >= Z_95


def _rank(rows: list[dict], metrics: list[str]) -> None:
    """Per metric, rank 1 = the largest shown value; ties share a rank; no rank without a
    value (hidden, or null with a reason). Ranks cover every row, before `limit`."""
    for name in metrics:
        shown = [
            r["values"][name]["value"] for r in rows if r["values"][name].get("value") is not None
        ]
        ordered = sorted(shown, reverse=True)
        for row in rows:
            cell = row["values"][name]
            if cell.get("value") is not None:
                cell["rank"] = ordered.index(cell["value"]) + 1
                cell["rank_of"] = len(shown)


def _flag(name: str, keys: list[tuple], base_values: list[dict], hidden: list[set]) -> dict:
    """Which rows a flag selects, from unrounded base values. A row whose counts are hidden
    by suppression is not judged, so a flag can't reveal a hidden value."""
    rule = FLAG_RULES[name]
    judged = {}
    for key, values, hidden_bases in zip(keys, base_values, hidden, strict=True):
        spend = values.get("spend") or Decimal(0)
        leads = values.get("paid_leads") or Decimal(0)
        qualified = values.get("paid_qualified_leads") or Decimal(0)
        if hidden_bases & {"paid_leads", "paid_qualified_leads"}:
            continue
        if leads >= rule["min_paid_leads"] and spend > 0:
            judged[key] = (spend / leads, qualified / leads)
    summary: dict[str, Any] = {"rule": rule["rule"], "rows_judged": len(judged)}
    if len(judged) < rule["min_rows"]:
        summary["flagged"] = 0
        summary["note"] = f"Fewer than {rule['min_rows']} campaigns qualify; nothing flagged."
        return {"keys": set(), "summary": summary}
    cpl_median = median(cpl for cpl, _ in judged.values())
    rate_median = median(rate for _, rate in judged.values())
    selected = {k for k, (cpl, rate) in judged.items() if cpl < cpl_median and rate < rate_median}
    summary |= {
        "median_cost_per_lead": round_value(cpl_median, "currency"),
        "median_qualification_rate": round_value(rate_median, "rate"),
        "flagged": len(selected),
    }
    return {"keys": selected, "summary": summary}


def label(ctx: OrgContext, dimension: str, value: Any) -> str:
    if dimension == "campaign":
        return ctx.campaign_names.get(value, value)
    return str(value)


WARNING_MESSAGES = {
    "synthetic_data": "Synthetic data: these numbers describe a fictional business.",
    "population_default": "Population defaulted to new-customer acquisition leads.",
    "mapping_unverified": "Results use mapping rules that haven't been verified against the "
    "real systems.",
    "low_attribution_coverage": "Less than 60% of these leads have campaign-level evidence; "
    "campaign figures describe a minority of leads.",
    "no_spend_source": "Some groups have no spend feed, so their cost metrics are empty.",
    "spend_not_by_dimension": "Spend can't be split by this dimension or filter, so cost "
    "metrics are empty.",
    "amount_basis_unverified": "What an opportunity's amount means (price, financed total, "
    "lease value or monthly) is unverified.",
    "amount_basis_mixed": "Amounts are recorded on different bases; choose one amount_basis "
    "to get amounts and ROAS.",
    "immature_cohort": "Recent leads haven't had time to close; sales figures for this period "
    "will still grow.",
    "maturity_unknown": "Too few closed opportunities to tell how long sales take; recent "
    "sales figures may be incomplete.",
    "timezone_mismatch": "Ad spend days follow the ad account's time zone, which differs from "
    "the reporting time zone.",
    "classification_default_applied": "Some leads were classified with a default because no "
    "request type was recorded (U-20).",
    "seasonal_comparison": "Month-over-month comparisons are seasonal in home services; "
    "compare with the same period last year.",
    "unequal_periods": "The two periods have different lengths.",
    "source_incomplete": "Part of the requested period is before the data starts.",
    "small_cell_suppressed": "Counts under 5 are hidden to protect privacy.",
    "change_within_noise": "Some rate changes are within what chance alone produces at these "
    "volumes (95% test); don't read them as real changes.",
    "unmapped_campaigns": "Some campaign traffic or spend can't be linked to a campaign in "
    "the mapping sheet.",
    "capture_drop": "Tracking capture on web forms fell sharply in at least one week; fewer "
    "attributed leads that week reflect broken tracking, not fewer customers.",
    "sources_not_additive": "Meta, GA4 and Salesforce each count leads their own way; compare "
    "them side by side, never add them.",
}


def warning(code: str) -> dict[str, str]:
    return {"code": code, "message": WARNING_MESSAGES[code]}


def unique_warnings(warnings: list[dict[str, str]]) -> list[dict[str, str]]:
    seen, result = set(), []
    for warning in warnings:
        if warning["code"] not in seen:
            seen.add(warning["code"])
            result.append(warning)
    return result


def query_warnings(conn, ctx, query, period, previous, population, families, current) -> list[dict]:
    codes = []
    if ctx.is_synthetic:
        codes.append("synthetic_data")
    if query.population is None:
        codes.append("population_default")
    codes += period_warnings(period, previous, query.compare_to, ctx.data_start)
    bases = {base for name in query.metrics for base in METRICS[name].bases}
    if "leads" in families and not all(section["verified"] for section in ctx.rules.values()):
        codes.append("mapping_unverified")
    if "spend" in families:
        if "spend" in current.unavailable:
            codes.append("spend_not_by_dimension")
        elif any(name.startswith("cost_per") or name == "roas" for name in query.metrics) and any(
            values.get("spend") in (None, 0)
            and values.get("paid_leads") in (None, 0)
            and (values.get("leads") or 0) > 0
            for values in current.rows.values()
        ):
            codes.append("no_spend_source")
        if any(tz != ctx.reporting_tz for tz in ctx.meta_timezones):
            codes.append("timezone_mismatch")
    if bases & AMOUNT_BASES:
        codes.append("amount_basis_unverified")
        if query.amount_basis is None:
            codes.append("amount_basis_mixed")
    if bases & OUTCOME_BASES:
        if ctx.maturity_days is None:
            codes.append("maturity_unknown")
        elif period.end > ctx.data_as_of - timedelta(days=ctx.maturity_days):
            codes.append("immature_cohort")
    if "leads" in families and "leads" not in current.unavailable:
        totals = current.totals
        attributed = any(d in ATTRIBUTED_DIMENSIONS for d in query.group_by)
        leads = totals.get("leads") or Decimal(0)
        if attributed and leads and (totals.get("covered_leads") or 0) / leads < LOW_COVERAGE:
            codes.append("low_attribution_coverage")
        if population in ("acquisition", "existing_customer_sales", "all") and _defaults_used(
            conn, ctx, period
        ):
            codes.append("classification_default_applied")
    return [warning(code) for code in codes]


def _defaults_used(conn, ctx, period) -> bool:
    start, end = period.utc_bounds(ctx.tz)
    return bool(
        conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM core.leads WHERE org_id = :org"
                " AND created_at >= :start AND created_at < :end AND duplicate_of IS NULL"
                " AND request_type_source IN ('entry_point_default', 'campaign'))"
            ),
            {"org": ctx.id, "start": start, "end": end},
        ).scalar()
    )
