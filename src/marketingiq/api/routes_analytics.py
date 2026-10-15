"""Analytics endpoints: thin wrappers over the analytics services, under the read-only role.

Request bodies are the same Pydantic models the services (and, later, the assistant's tools)
use, so a query means the same thing everywhere. Analytics requests are POSTs because their
queries are structured; nothing here writes data.
"""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Engine, text

from marketingiq.analytics.change import ChangeQuery, explain_metric_change
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


@router.get("/campaigns")
def list_campaigns(
    engine: AppEngine,
    org: Org,
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> dict[str, Any]:
    """Campaigns, for finding the key of "the furnace campaign" before querying it."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.key, c.name, c.platform, c.tactic, c.service_lines, c.region,"
                " c.in_mapping_sheet, c.has_spend_feed FROM core.campaigns c"
                " JOIN core.organizations o ON o.id = c.org_id WHERE o.slug = :org"
                " AND (CAST(:search AS text) IS NULL OR c.name ILIKE '%' || :search || '%'"
                "  OR c.key ILIKE '%' || :search || '%') ORDER BY c.name"
            ),
            {"org": org, "search": search},
        ).mappings()
        return {"campaigns": [dict(row) for row in rows]}


@router.get("/annotations")
def list_annotations(
    engine: AppEngine,
    org: Org,
    start: date | None = None,
    end: date | None = None,
    annotation_type: str | None = None,
) -> dict[str, Any]:
    """Dated business events (site changes, demand events, launches) overlapping a range."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT a.annotation_type, a.start_date, a.end_date, a.label"
                " FROM core.annotations a JOIN core.organizations o ON o.id = a.org_id"
                " WHERE o.slug = :org"
                " AND (CAST(:end AS date) IS NULL OR a.start_date <= :end)"
                " AND (CAST(:start AS date) IS NULL OR a.end_date >= :start)"
                " AND (CAST(:kind AS text) IS NULL OR a.annotation_type = :kind)"
                " ORDER BY a.start_date"
            ),
            {"org": org, "start": start, "end": end, "kind": annotation_type},
        ).mappings()
        return {"annotations": [dict(row) for row in rows]}


@router.post("/analytics/performance")
def performance(query: PerformanceQuery, engine: AppEngine, org: Org) -> dict[str, Any]:
    return get_performance(engine, org, query)


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
