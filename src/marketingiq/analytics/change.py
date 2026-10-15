"""Explaining a change between two periods, segment by segment.

For a count (spend, leads...), each segment's effect is its own change, and the effects add
up to the total change exactly. For a ratio (cost per qualified lead...), each segment's
effect is how much the total ratio moved because of it: the actual ratio minus the ratio
the total would have had if only that segment had kept its previous numerator and
denominator. Ratio effects don't add up exactly, and the result says so.

Each segment also gets a direction label such as `spend_up_qualified_leads_down`, so a
caller never has to compare signs itself. These are arithmetic contributions, not causes.
"""

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Engine

from marketingiq.analytics.metrics import BASES, DIMENSION_FAMILIES, METRICS, Dimension, MetricName
from marketingiq.analytics.performance import (
    AmountBasis,
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
from marketingiq.analytics.periods import PeriodSpec, comparison_period, resolve

METHOD = {
    "count": "Each segment's effect is its own change; effects add up to the total change.",
    "ratio": "Each segment's effect is the actual total minus the total it would have had if "
    "only that segment had kept its previous values. Effects don't add up exactly.",
}


class ChangeQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metric: MetricName
    dimension: Dimension
    period: PeriodSpec
    compare_to: Literal["previous_period", "same_period_last_year", "custom"] = "previous_period"
    comparison: PeriodSpec | None = None
    population: Population | None = None
    filters: Filters = Field(default_factory=Filters)
    attribution_model: Literal["first_touch", "last_non_direct", "linear"] = "last_non_direct"
    lookback_days: Literal[7, 30, 90] = 30
    amount_basis: AmountBasis | None = None
    limit: int = Field(10, ge=1, le=50)

    @model_validator(mode="after")
    def _measurable(self) -> "ChangeQuery":
        if (self.compare_to == "custom") != (self.comparison is not None):
            raise ValueError("comparison is required with compare_to='custom', and only then")
        missing = METRICS[self.metric].families - DIMENSION_FAMILIES[self.dimension]
        if missing:
            raise ValueError(f"{self.metric} can't be split by {self.dimension}")
        return self


def _direction(name: str, before: Decimal, after: Decimal) -> str:
    return f"{name}_{'up' if after > before else 'down' if after < before else 'flat'}"


def explain_metric_change(engine: Engine, org_slug: str, query: ChangeQuery) -> dict[str, Any]:
    metric = METRICS[query.metric]
    performance = PerformanceQuery(
        period=query.period,
        compare_to=query.compare_to,
        comparison=query.comparison,
        group_by=[query.dimension],
        metrics=[query.metric],
        population=query.population,
        filters=query.filters,
        attribution_model=query.attribution_model,
        lookback_days=query.lookback_days,
        amount_basis=query.amount_basis,
    )
    with engine.connect() as conn:
        ctx = load_context(conn, org_slug)
        period = resolve(query.period, ctx.data_as_of)
        previous = comparison_period(period, query.compare_to, query.comparison, ctx.data_as_of)
        population = query.population or "acquisition"
        families = metric.families
        now = measure(conn, ctx, performance, period, population, families)
        before = measure(conn, ctx, performance, previous, population, families)
        warnings = query_warnings(
            conn, ctx, performance, period, previous, population, families, now
        )

    numerator = metric.base or metric.numerator
    denominator = None if metric.base else metric.denominator

    def get(values: dict, base: str | None) -> Decimal:
        return (values.get(base) or Decimal(0)) if base else Decimal(1)

    def ratio(n: Decimal, d: Decimal) -> Decimal | None:
        return n / d if d else None

    n1, n0 = get(now.totals, numerator), get(before.totals, numerator)
    d1, d0 = get(now.totals, denominator), get(before.totals, denominator)
    total_now, total_before = ratio(n1, d1), ratio(n0, d0)

    keys = sorted(set(now.rows) | set(before.rows), key=str)
    empty = dict.fromkeys(BASES, Decimal(0))
    rows_now = [now.rows.get(key, empty) for key in keys]
    hidden = suppressed_bases(rows_now)
    hidden_before = suppressed_bases([before.rows.get(key, empty) for key in keys])

    segments = []
    for index, key in enumerate(keys):
        a, b = rows_now[index], before.rows.get(key, empty)
        sn1, sn0 = get(a, numerator), get(b, numerator)
        sd1, sd0 = get(a, denominator), get(b, denominator)
        if not any((sn1, sn0, sd1 if denominator else 0, sd0 if denominator else 0)):
            continue  # nothing in either period: no part in the change
        direction = _direction(numerator, sn0, sn1)
        if denominator:
            direction += "_" + _direction(denominator, sd0, sd1)
            counterfactual = ratio(n1 - sn1 + sn0, d1 - sd1 + sd0)
            effect = total_now - counterfactual if None not in (total_now, counterfactual) else None
        else:
            effect = sn1 - sn0
        bases = {numerator, denominator} - {None}
        segment: dict[str, Any] = {"key": str(key[0]), "label": label(ctx, query.dimension, key[0])}
        if bases & (hidden[index] | hidden_before[index]):
            segment |= {"suppressed": True}
            segments.append((Decimal(-1), segment))
            continue
        unit = "currency" if numerator in ("spend", "won_amount", "paid_won_amount") else "count"
        segment |= {
            "numerator": {
                "name": numerator,
                "value": round_value(sn1, unit),
                "previous": round_value(sn0, unit),
            },
            "direction": direction,
            "effect": round_value(effect, metric.unit) if effect is not None else None,
        }
        if denominator:
            segment["denominator"] = {
                "name": denominator,
                "value": round_value(sd1, "count"),
                "previous": round_value(sd0, "count"),
            }
        elif n1 != n0:
            segment["share_of_change"] = round_value(effect / (n1 - n0), "rate")
        segments.append((abs(effect) if effect is not None else Decimal(-1), segment))

    segments.sort(key=lambda item: item[0], reverse=True)
    if any(segment.get("suppressed") for _, segment in segments):
        warnings.append(warning("small_cell_suppressed"))

    def total(value: Decimal | None) -> float | int | None:
        return round_value(value, metric.unit) if value is not None else None

    change = total_now - total_before if None not in (total_now, total_before) else None
    change_pct = change / total_before if change is not None and total_before else None
    unit = "currency" if numerator in ("spend", "won_amount", "paid_won_amount") else "count"
    parts = {
        "numerator": {
            "name": numerator,
            "value": round_value(n1, unit),
            "previous": round_value(n0, unit),
        }
    }
    if denominator:
        parts["denominator"] = {
            "name": denominator,
            "value": round_value(d1, "count"),
            "previous": round_value(d0, "count"),
        }
    return {
        "resolved": {
            "period": period.as_dict(),
            "comparison": previous.as_dict() if previous else None,
            "compare_to": query.compare_to,
            "dimension": query.dimension,
            "population": population,
            "attribution_model": query.attribution_model,
            "lookback_days": query.lookback_days,
            "reporting_tz": ctx.reporting_tz,
            "currency": ctx.currency,
            "data_as_of": ctx.data_as_of.isoformat(),
            "synthetic": ctx.is_synthetic,
        },
        "metric": {
            "name": metric.name,
            "label": metric.label,
            "unit": metric.unit,
            "definition": metric.definition,
        },
        "total": {
            "value": total(total_now),
            "previous": total(total_before),
            "change": total(change),
            "change_pct": round_value(change_pct, "rate") if change_pct is not None else None,
            **parts,
        },
        "method": METHOD["ratio" if denominator else "count"],
        "segments": [segment for _, segment in segments[: query.limit]],
        "segment_count": len(segments),
        "warnings": unique_warnings(warnings),
    }
