"""The dashboard's headline figures: a few metrics, month by month, for the last year.

Computed by the same performance service as everything else (no model involved), so the
tiles work even when the assistant's provider is unavailable. Months are complete calendar
months ending at the data's last month. Results are cached per organization and data date.
"""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import Engine, text

from marketingiq.analytics.metrics import METRICS
from marketingiq.analytics.performance import PerformanceQuery, get_performance
from marketingiq.analytics.periods import PeriodSpec, resolve
from marketingiq.api.routes_analytics import Org
from marketingiq.config import get_settings
from marketingiq.db import get_app_engine

router = APIRouter(prefix="/api/v1", tags=["dashboard"])

# (metric, whether a rise is good: True, False, or None when neither)
TILES = [
    ("leads", True),
    ("qualified_leads", True),
    ("qualification_rate", True),
    ("spend", None),
    ("cost_per_lead", False),
    ("attribution_coverage", True),
]
MONTHS = 12

_cache: dict[tuple[str, date, int], dict[str, Any]] = {}


def _months(last: date, count: int) -> list[tuple[date, date]]:
    """`count` complete months ending with the month of `last`, oldest first."""
    year, month = last.year, last.month
    spans = []
    for _ in range(count):
        start = date(year, month, 1)
        next_start = date(year + month // 12, month % 12 + 1, 1)
        spans.append((start, date.fromordinal(next_start.toordinal() - 1)))
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return list(reversed(spans))


@router.get("/dashboard")
def dashboard(engine: Annotated[Engine, Depends(get_app_engine)], org: Org) -> dict[str, Any]:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT o.name, o.data_as_of, o.currency, o.is_synthetic,"
                " (SELECT max(b.id) FROM core.build_runs b WHERE b.org_id = o.id) AS build"
                " FROM core.organizations o WHERE o.slug = :slug"
            ),
            {"slug": org},
        ).one_or_none()
    if row is None or row.data_as_of is None or row.build is None:
        raise LookupError(f"{org} has no data or no core build yet")
    key = (org, row.data_as_of, row.build)  # a rebuild invalidates the cache
    if key not in _cache:
        _cache[key] = _build(engine, org, row)
    return _cache[key]


def _build(engine: Engine, org: str, row: Any) -> dict[str, Any]:
    as_of: date = row.data_as_of
    # The last complete month, by the same rule as every "last month" question.
    last_month = resolve(PeriodSpec(preset="last_month"), as_of)
    spans = _months(last_month.start, MONTHS)
    names = [name for name, _ in TILES]
    series: dict[str, list[dict[str, Any]]] = {name: [] for name in names}
    warnings: dict[str, dict[str, str]] = {}
    for start, end in spans:
        query = PerformanceQuery.model_validate(
            {
                "period": {"preset": "custom", "start": str(start), "end": str(end)},
                "metrics": names,
                "population": "acquisition",
            }
        )
        result = get_performance(engine, org, query)
        for name in names:
            cell = result["totals"][name]
            series[name].append(
                {"month": start.strftime("%Y-%m"), "value": cell.get("value"), **_reason(cell)}
            )
        for warning in result["warnings"]:
            warnings.setdefault(warning["code"], warning)
    settings = get_settings()
    return {
        "organization": row.name,
        "data_as_of": as_of.isoformat(),
        "currency": row.currency,
        "synthetic": row.is_synthetic,
        "model": settings.llm_model,
        "population": "new-customer (acquisition) leads, by lead creation month",
        "months": [start.strftime("%Y-%m") for start, _ in spans],
        "tiles": [
            {
                "metric": name,
                "label": METRICS[name].label,
                "unit": METRICS[name].unit,
                "definition": METRICS[name].definition,
                "rise_is_good": good,
                "series": series[name],
            }
            for name, good in TILES
        ],
        "warnings": [w for code, w in warnings.items() if code != "population_default"],
    }


def _reason(cell: dict[str, Any]) -> dict[str, Any]:
    if cell.get("suppressed"):
        return {"suppressed": True}
    if cell.get("null_reason"):
        return {"null_reason": cell["null_reason"]}
    return {}
