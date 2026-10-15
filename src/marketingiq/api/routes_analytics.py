"""Analytics endpoints: thin wrappers over the analytics services, under the read-only role.

Request bodies are the same Pydantic models the services (and, later, the assistant's tools)
use, so a query means the same thing everywhere. Analytics requests are POSTs because their
queries are structured; nothing here writes data.
"""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Engine

from marketingiq.analytics.annotations import AnnotationsQuery, list_annotations
from marketingiq.analytics.attribution_report import AttributionQuery, compare_attribution_models
from marketingiq.analytics.change import ChangeQuery, explain_metric_change
from marketingiq.analytics.dimensions import (
    DimensionValuesQuery,
    ResolvableDimension,
    list_dimension_values,
)
from marketingiq.analytics.performance import PerformanceQuery, get_performance
from marketingiq.analytics.quality import QualityQuery, get_data_quality
from marketingiq.analytics.reports import (
    FunnelQuery,
    ReconciliationQuery,
    get_lead_funnel,
    get_source_reconciliation,
)
from marketingiq.config import get_settings
from marketingiq.db import get_app_engine

router = APIRouter(prefix="/api/v1", tags=["analytics"])

AppEngine = Annotated[Engine, Depends(get_app_engine)]


def organization(org: Annotated[str | None, Query(description="organization slug")] = None) -> str:
    return org or get_settings().default_org_slug


Org = Annotated[str, Depends(organization)]


@router.get("/dimensions/{dimension}/values")
def dimension_values(
    dimension: ResolvableDimension,
    engine: AppEngine,
    org: Org,
    search: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    """Find exact values by name ("the furnace campaign"); `match` says if several fit."""
    query = DimensionValuesQuery(dimension=dimension, search=search, limit=limit)
    return list_dimension_values(engine, org, query)


@router.get("/annotations")
def annotations(
    engine: AppEngine,
    org: Org,
    start: date | None = None,
    end: date | None = None,
    annotation_type: Annotated[str | None, Query(max_length=50)] = None,
) -> dict[str, Any]:
    """Dated business events (site changes, demand events, launches) overlapping a range."""
    query = AnnotationsQuery(start=start, end=end, annotation_type=annotation_type)
    return list_annotations(engine, org, query)


@router.post("/analytics/performance")
def performance(query: PerformanceQuery, engine: AppEngine, org: Org) -> dict[str, Any]:
    return get_performance(engine, org, query)


@router.post("/analytics/attribution-models")
def attribution_models(query: AttributionQuery, engine: AppEngine, org: Org) -> dict[str, Any]:
    return compare_attribution_models(engine, org, query)


@router.post("/analytics/funnel")
def funnel(query: FunnelQuery, engine: AppEngine, org: Org) -> dict[str, Any]:
    return get_lead_funnel(engine, org, query)


@router.post("/analytics/reconciliation")
def reconciliation(query: ReconciliationQuery, engine: AppEngine, org: Org) -> dict[str, Any]:
    return get_source_reconciliation(engine, org, query)


@router.post("/analytics/change")
def change(query: ChangeQuery, engine: AppEngine, org: Org) -> dict[str, Any]:
    return explain_metric_change(engine, org, query)


@router.post("/analytics/data-quality")
def data_quality(query: QualityQuery, engine: AppEngine, org: Org) -> dict[str, Any]:
    return get_data_quality(engine, org, query)
