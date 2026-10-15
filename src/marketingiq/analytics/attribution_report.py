"""Comparing attribution models: the same leads' credit under first touch, last non-direct and
linear, side by side, with the evidence that limits what the comparison can show.

Models only differ for leads with a web journey (tier T1); every other lead gets the same
credit under all three. So the result always carries the evidence-tier breakdown, and how
much of the population the comparison is really about.
"""

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine

from marketingiq.analytics.metrics import BASES
from marketingiq.analytics.performance import (
    Filters,
    PerformanceQuery,
    Population,
    label,
    load_context,
    measure,
    query_warnings,
    round_value,
    suppressed_bases,
    unique_warnings,
    warning,
)
from marketingiq.analytics.periods import PeriodSpec, resolve

MODELS = ("first_touch", "last_non_direct", "linear")
TIERS = (
    "T1_journey",
    "T2_captured_source",
    "T3_platform_native",
    "T4_self_reported_channel",
    "T5_none",
)
NOTE = (
    "Models differ only for leads with a web journey (T1). Every other lead gets the same "
    "credit under all three, so differences between models describe the T1 share only."
)


class AttributionQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    period: PeriodSpec
    group_by: Literal["campaign", "channel", "platform", "campaign_tactic"] = "campaign"
    metric: Literal["leads", "qualified_leads", "consultations_completed", "sales_won"] = "leads"
    population: Population | None = None
    filters: Filters = Field(default_factory=Filters)
    lookback_days: Literal[7, 30, 90] = 30
    limit: int = Field(25, ge=1, le=100)


def compare_attribution_models(
    engine: Engine, org_slug: str, query: AttributionQuery
) -> dict[str, Any]:
    base = query.metric

    def performance(model: str, group_by: str) -> PerformanceQuery:
        return PerformanceQuery(
            period=query.period,
            group_by=[group_by],
            metrics=[base],
            population=query.population,
            filters=query.filters,
            attribution_model=model,
            lookback_days=query.lookback_days,
        )

    with engine.connect() as conn:
        ctx = load_context(conn, org_slug)
        period = resolve(query.period, ctx.data_as_of)
        population = query.population or "acquisition"
        measured = {
            model: measure(
                conn, ctx, performance(model, query.group_by), period, population, {"leads"}
            )
            for model in MODELS
        }
        tiers = measure(
            conn,
            ctx,
            performance("last_non_direct", "evidence_tier"),
            period,
            population,
            {"leads"},
        )
        default = performance("last_non_direct", query.group_by)
        warnings = query_warnings(
            conn, ctx, default, period, None, population, {"leads"}, measured["last_non_direct"]
        )

    # A row is hidden when any model's value for it is: three views of one small count
    # would otherwise give it away.
    keys = sorted({key for m in measured.values() for key in m.rows}, key=str)
    empty = dict.fromkeys(BASES, Decimal(0))
    hidden = [set() for _ in keys]
    for model in MODELS:
        model_rows = [measured[model].rows.get(key, empty) for key in keys]
        for index, bases in enumerate(suppressed_bases(model_rows)):
            hidden[index] |= bases

    rows = []
    for index, key in enumerate(keys):
        row: dict[str, Any] = {"key": str(key[0]), "label": label(ctx, query.group_by, key[0])}
        if base in hidden[index]:
            row["suppressed"] = True
            rows.append(row)
            continue
        values = {m: measured[m].rows.get(key, empty).get(base) or Decimal(0) for m in MODELS}
        if not any(values.values()):
            continue
        row["credit"] = {m: round_value(v, "count") for m, v in values.items()}
        row["spread"] = round_value(max(values.values()) - min(values.values()), "count")
        rows.append(row)
    if any(row.get("suppressed") for row in rows):
        warnings.append(warning("small_cell_suppressed"))
    rows.sort(
        key=lambda r: (
            r.get("suppressed", False),
            -(r.get("credit", {}).get("last_non_direct") or 0),
            r["key"],
        )
    )

    total = measured["last_non_direct"].totals.get(base) or Decimal(0)
    tier_rows = [tiers.rows.get((tier,), empty) for tier in TIERS]
    tier_hidden = suppressed_bases(tier_rows)
    evidence = {}
    for tier, values, hidden_bases in zip(TIERS, tier_rows, tier_hidden, strict=True):
        count = values.get(base) or Decimal(0)
        if base in hidden_bases:
            evidence[tier] = {"value": None, "suppressed": True}
        else:
            share = count / total if total else None
            evidence[tier] = {
                "value": round_value(count, "count"),
                "share": round_value(share, "rate") if share is not None else None,
            }

    def share(*names: str) -> float | None:
        part = sum((tiers.rows.get((t,), empty).get(base) or Decimal(0)) for t in names)
        return round_value(part / total, "rate") if total else None

    return {
        "resolved": {
            "period": period.as_dict(),
            "population": population,
            "group_by": query.group_by,
            "metric": base,
            "models": list(MODELS),
            "lookback_days": query.lookback_days,
            "reporting_tz": ctx.reporting_tz,
            "data_as_of": ctx.data_as_of.isoformat(),
            "synthetic": ctx.is_synthetic,
        },
        "total": round_value(total, "count"),
        "rows": rows[: query.limit],
        "row_count": len(rows),
        "evidence": {
            "by_tier": evidence,
            "journey_share": share("T1_journey"),
            "campaign_coverage": share("T1_journey", "T2_captured_source", "T3_platform_native"),
        },
        "note": NOTE,
        "warnings": unique_warnings(warnings),
    }
