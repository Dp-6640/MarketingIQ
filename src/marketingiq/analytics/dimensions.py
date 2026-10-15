"""Finding dimension values by name: which campaign is "the furnace campaign"?

The assistant resolves a user's words to exact values before it queries anything. When the
words match several values, the result says so (`match: "several"`), so the assistant asks
which one was meant instead of picking one.
"""

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, text

from marketingiq.analytics.performance import load_context
from marketingiq.core import vocabulary as vocab
from marketingiq.core.rules import load_rulebook

ResolvableDimension = Literal[
    "campaign",
    "platform",
    "campaign_tactic",
    "channel",
    "landing_page",
    "evidence_tier",
    "entry_point",
    "service_line",
    "region",
    "lead_class",
    "customer_type",
]

# Lead properties: the values present in the organization's first leads.
_LEAD_COLUMNS = {
    "entry_point": "entry_point",
    "service_line": "service_line",
    "lead_class": "lead_class",
    "customer_type": "customer_type",
}


class DimensionValuesQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension: ResolvableDimension
    search: str | None = Field(None, max_length=100)
    limit: int = Field(50, ge=1, le=200)


def _words(value: str) -> list[str]:
    return re.sub(r"[_\-|/]+", " ", value.casefold()).split()


def _haystack(value: dict[str, Any]) -> str:
    """The words a value can be found by: its value, its name, and a region's cities."""
    parts = [
        str(value["value"]),
        str(value["label"]),
        *value.get("cities", []),
        *value.get("aliases", []),
    ]
    return " ".join(w for part in parts for w in _words(part))


def _values(conn, ctx, dimension: str) -> list[dict[str, Any]]:
    org = {"org": ctx.id}
    if dimension == "campaign":
        rows = conn.execute(
            text(
                "SELECT key AS value, name AS label, platform, tactic, service_lines, region,"
                " in_mapping_sheet, has_spend_feed FROM core.campaigns WHERE org_id = :org"
            ),
            org,
        ).mappings()
        return [dict(r) for r in rows]
    if dimension in ("platform", "campaign_tactic"):
        column = "platform" if dimension == "platform" else "tactic"
        rows = conn.execute(
            text(
                f"SELECT DISTINCT {column} FROM core.campaigns"
                f" WHERE org_id = :org AND {column} IS NOT NULL"
            ),
            org,
        ).scalars()
        return [{"value": v, "label": v} for v in rows]
    if dimension == "landing_page":
        rows = conn.execute(
            text(
                "SELECT path AS value, path AS label, page_type, service_line, city"
                " FROM core.landing_pages WHERE org_id = :org"
            ),
            org,
        ).mappings()
        return [dict(r) for r in rows]
    if dimension == "channel":
        return [{"value": v, "label": v} for v in vocab.REPORTED_CHANNELS]
    if dimension == "evidence_tier":
        return [{"value": v, "label": v} for v in vocab.EVIDENCE_TIERS]
    if dimension == "region":
        # Regions are found by any of their cities or aliases too ("Kitchener", "KW").
        geography = load_rulebook().geography
        aliases = {
            r.key: [a for a, k in geography.region_aliases.items() if k == r.key]
            for r in geography.regions
        }
        return [
            {"value": r.key, "label": r.key, "cities": list(r.cities), "aliases": aliases[r.key]}
            for r in geography.regions
        ]
    column = _LEAD_COLUMNS[dimension]
    rows = conn.execute(
        text(
            f"SELECT DISTINCT {column} FROM core.leads"
            f" WHERE org_id = :org AND duplicate_of IS NULL AND {column} IS NOT NULL"
        ),
        org,
    ).scalars()
    return [{"value": v, "label": v} for v in rows]


def list_dimension_values(
    engine: Engine, org_slug: str, query: DimensionValuesQuery
) -> dict[str, Any]:
    """Values of a dimension; with `search`, those whose words contain every searched word
    (as a prefix: "furn" finds furnace campaigns)."""
    with engine.connect() as conn:
        ctx = load_context(conn, org_slug)
        values = _values(conn, ctx, query.dimension)
    if query.search:
        wanted = _words(query.search)
        values = [
            v
            for v in values
            if all(any(h.startswith(w) for h in _haystack(v).split()) for w in wanted)
        ]
    values.sort(key=lambda v: str(v["label"]))
    match = "none" if not values else "one" if len(values) == 1 else "several"
    return {
        "dimension": query.dimension,
        "search": query.search,
        "match": match,
        "count": len(values),
        "values": values[: query.limit],
    }
