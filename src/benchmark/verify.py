"""Checking a tool result's numbers against the oracle.

Every shown number the oracle can compute is recomputed and compared at the result's own
rounding. Hidden (suppressed) and null values are skipped; amounts are outside the oracle.
Period resolution isn't re-derived: the oracle uses the dates the result says it covers,
and the cases check those dates separately.
"""

from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction
from functools import cache
from typing import Any

from marketingiq.analytics.metrics import BASES, METRICS
from marketingiq.analytics.reports import FUNNEL_RATES, FUNNEL_STAGES
from oracle import count
from oracle.facts import Facts

NO_GROUP = {"(no campaign)", "(none)", "(unknown)"}
TOLERANCE = {"currency": 0.0051, "count": 0.0051, "ratio": 0.0051, "rate": 0.000051}


@dataclass
class Check:
    checked: int = 0
    mismatches: list[str] = field(default_factory=list)
    skipped: str | None = None  # why a result wasn't checked at all


def _key(value: Any) -> str | None:
    if isinstance(value, date):
        return value.strftime("%Y-%m")
    return None if value is None or value in NO_GROUP else str(value)


class Oracle:
    """Oracle values for one query's context, cached per base and period."""

    def __init__(self, facts: Facts, group_by, population, model, lookback, filters):
        self.facts = facts
        self.group_by = tuple(group_by)
        self.population = population
        self.model = model
        self.lookback = lookback
        self.filters = {k: v for k, v in (filters or {}).items() if v}

    @cache  # noqa: B019 (one Oracle per checked result)
    def base(self, name: str, start: date, end: date) -> dict | None:
        family = BASES.get(name)
        if family == "leads" and "amount" not in name:
            values = count.leads(
                self.facts,
                start,
                end,
                name.removeprefix("paid_"),
                self.group_by,
                self.population,
                self.model,
                self.lookback,
                paid=name.startswith("paid_"),
                filters=self.filters,
            )
            return {k: Fraction(v) for k, v in values.items()}
        if family == "spend":
            values = count.ad_measure(self.facts, start, end, name, self.group_by, self.filters)
            return {k: Fraction(v) for k, v in values.items()}
        if family == "sessions" and not self.filters:
            values = count.sessions(
                self.facts, start, end, self.group_by, form_submits=name == "form_submit_sessions"
            )
            return {k: Fraction(v) for k, v in values.items()}
        return None

    def value(self, base: str, key: tuple, start: date, end: date) -> Fraction | None:
        values = self.base(base, start, end)
        return None if values is None else values.get(key, Fraction(0))

    def metric(self, name: str, key: tuple, start: date, end: date) -> Fraction | None:
        metric = METRICS[name]
        if metric.base:
            return self.value(metric.base, key, start, end)
        numerator = self.value(metric.numerator, key, start, end)
        denominator = self.value(metric.denominator, key, start, end)
        if numerator is None or denominator is None or denominator == 0:
            return None
        return numerator / denominator


def _dates(period: dict | None) -> tuple[date, date] | None:
    if not period:
        return None
    return date.fromisoformat(str(period["start"])), date.fromisoformat(str(period["end"]))


def _compare(check: Check, label: str, shown: Any, expected: Fraction | None, unit: str) -> None:
    if shown is None:
        return
    check.checked += 1
    if expected is None:
        check.mismatches.append(f"{label}: shown {shown}, the oracle has no value")
    elif abs(float(shown) - float(expected)) > TOLERANCE[unit]:
        check.mismatches.append(f"{label}: shown {shown}, oracle {float(expected):.4f}")


def check_performance(facts: Facts, args: dict, result: dict, metrics: list[str]) -> Check:
    check = Check()
    resolved = result["resolved"]
    context = (
        resolved["population"],
        resolved["attribution_model"],
        resolved["lookback_days"],
        args.get("filters"),
    )
    grouped = Oracle(facts, resolved["group_by"], *context)
    now, before = _dates(resolved["period"]), _dates(resolved.get("comparison"))
    rows = [
        (tuple(_key(v) for v in r["dimensions"].values()), r["key"], r["values"], grouped)
        for r in result["rows"]
    ]
    rows.append(((), "totals", result["totals"], Oracle(facts, [], *context)))
    for key, label, values, oracle in rows:
        for name in metrics:
            cell, unit = values[name], METRICS[name].unit
            if any(oracle.base(base, *now) is None for base in METRICS[name].bases):
                continue  # amounts, or sessions under a filter: outside the oracle
            _compare(
                check, f"{label}.{name}", cell.get("value"), oracle.metric(name, key, *now), unit
            )
            if before and "previous" in cell:
                _compare(
                    check,
                    f"{label}.{name}.previous",
                    cell["previous"],
                    oracle.metric(name, key, *before),
                    unit,
                )
    return check


def check_models(facts: Facts, args: dict, result: dict) -> Check:
    check = Check()
    resolved = result["resolved"]
    now = _dates(resolved["period"])
    for model in resolved["models"]:
        oracle = Oracle(
            facts,
            [resolved["group_by"]],
            resolved["population"],
            model,
            resolved["lookback_days"],
            args.get("filters"),
        )
        for row in result["rows"]:
            if not row.get("suppressed"):
                expected = oracle.value(resolved["metric"], (_key(row["key"]),), *now)
                _compare(check, f"{row['key']}.{model}", row["credit"][model], expected, "count")
    total = Oracle(
        facts,
        [],
        resolved["population"],
        "last_non_direct",
        resolved["lookback_days"],
        args.get("filters"),
    )
    _compare(check, "total", result["total"], total.value(resolved["metric"], (), *now), "count")
    return check


def check_change(facts: Facts, args: dict, result: dict) -> Check:
    check = Check()
    resolved = result["resolved"]
    oracle = Oracle(
        facts,
        [resolved["dimension"]],
        resolved["population"],
        resolved["attribution_model"],
        resolved["lookback_days"],
        args.get("filters"),
    )
    totals = Oracle(
        facts,
        [],
        resolved["population"],
        resolved["attribution_model"],
        resolved["lookback_days"],
        args.get("filters"),
    )
    now, before = _dates(resolved["period"]), _dates(resolved["comparison"])
    parts = [((), "total", result["total"], totals)]
    parts += [
        ((_key(s["key"]),), s["key"], s, oracle)
        for s in result["segments"]
        if not s.get("suppressed")
    ]
    for key, label, part, source in parts:
        for side in ("numerator", "denominator"):
            if side not in part:
                continue
            name = part[side]["name"]
            unit = "currency" if BASES[name] == "spend" and name == "spend" else "count"
            if source.base(name, *now) is None:
                continue
            _compare(
                check, f"{label}.{side}", part[side]["value"], source.value(name, key, *now), unit
            )
            _compare(
                check,
                f"{label}.{side}.previous",
                part[side]["previous"],
                source.value(name, key, *before),
                unit,
            )
    return check


def check_result(facts: Facts, tool: str, args: dict, result: dict) -> Check:
    if tool == "get_performance":
        return check_performance(facts, args, result, list(args["metrics"]))
    if tool == "get_lead_funnel":
        return check_performance(facts, args, result, [*FUNNEL_STAGES, *FUNNEL_RATES])
    if tool == "compare_attribution_models":
        return check_models(facts, args, result)
    if tool == "explain_metric_change":
        return check_change(facts, args, result)
    return Check(skipped="not covered by the oracle (structural checks only)")
