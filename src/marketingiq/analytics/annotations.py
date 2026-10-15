"""Dated business events: site changes, demand events, launches, system changes.

Annotations record that something happened, never its effect. A before/after comparison
around one describes what coincided with it, not what it caused.
"""

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, text

from marketingiq.analytics.performance import load_context


class AnnotationsQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start: date | None = None
    end: date | None = None
    annotation_type: str | None = Field(None, max_length=50)


def list_annotations(engine: Engine, org_slug: str, query: AnnotationsQuery) -> dict[str, Any]:
    """Annotations overlapping [start, end], optionally of one type, oldest first."""
    with engine.connect() as conn:
        ctx = load_context(conn, org_slug)
        rows = conn.execute(
            text(
                "SELECT annotation_type, start_date, end_date, label FROM core.annotations"
                " WHERE org_id = :org"
                " AND (CAST(:end AS date) IS NULL OR start_date <= :end)"
                " AND (CAST(:start AS date) IS NULL OR end_date >= :start)"
                " AND (CAST(:kind AS text) IS NULL OR annotation_type = :kind)"
                " ORDER BY start_date"
            ),
            {"org": ctx.id, "start": query.start, "end": query.end, "kind": query.annotation_type},
        ).mappings()
        annotations = [dict(row) for row in rows]
    return {
        "annotations": annotations,
        "note": "Annotations record that something happened, not its effect.",
    }
