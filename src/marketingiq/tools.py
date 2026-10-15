"""The assistant's tools: typed, read-only, and the same functions the REST API calls.

Each tool is a name, a description written for the model that will choose it, a Pydantic
input model (so a bad argument fails validation before any SQL), and the service that runs
it. There is no tool that accepts SQL or free text to execute.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Engine

from marketingiq.analytics.annotations import AnnotationsQuery, list_annotations
from marketingiq.analytics.attribution_report import AttributionQuery, compare_attribution_models
from marketingiq.analytics.change import ChangeQuery, explain_metric_change
from marketingiq.analytics.dimensions import DimensionValuesQuery, list_dimension_values
from marketingiq.analytics.performance import PerformanceQuery, get_performance
from marketingiq.analytics.quality import QualityQuery, get_data_quality
from marketingiq.analytics.reports import (
    FunnelQuery,
    ReconciliationQuery,
    get_lead_funnel,
    get_source_reconciliation,
)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    run: Callable[[Engine, str, Any], dict[str, Any]]

    def input_schema(self) -> dict[str, Any]:
        return self.input_model.model_json_schema()


TOOLS: dict[str, Tool] = {
    tool.name: tool
    for tool in (
        Tool(
            "list_dimension_values",
            "Find the exact value for a name the user used: a campaign ('the furnace "
            "campaign'), region (also by city), landing page, service line, entry point, "
            "channel, platform or tactic. Use it before filtering or naming a value. If "
            "`match` is 'several', ask the user which one they mean; if 'none', say so.",
            DimensionValuesQuery,
            list_dimension_values,
        ),
        Tool(
            "list_annotations",
            "Dated business events (site changes, demand events such as cold snaps, "
            "launches, system changes) overlapping a date range. Use it to find when "
            "something happened before comparing before and after. Annotations say that "
            "something happened, never what it caused.",
            AnnotationsQuery,
            list_annotations,
        ),
        Tool(
            "get_performance",
            "Any registry metric for a period, grouped by up to two dimensions, optionally "
            "compared with a previous period, the same period last year or custom dates. "
            "Rows carry ranks. Lead counts by campaign or channel are attribution credit "
            "under the chosen model. Flags select rows by a fixed rule "
            "(cheap_leads_low_qualification).",
            PerformanceQuery,
            get_performance,
        ),
        Tool(
            "get_lead_funnel",
            "Lead → qualified → consultation booked → completed → opportunity → won for a "
            "lead cohort, with the rate between stages, optionally by one dimension. "
            "Recent cohorts are immature: their later stages are still filling.",
            FunnelQuery,
            get_lead_funnel,
        ),
        Tool(
            "compare_attribution_models",
            "Credit by campaign, channel, platform or tactic under first touch, last "
            "non-direct and linear, side by side, with the evidence-tier breakdown. Models "
            "only differ for leads with a web journey (T1); report that share.",
            AttributionQuery,
            compare_attribution_models,
        ),
        Tool(
            "get_source_reconciliation",
            "Meta-reported leads, GA4 form-submit sessions and CRM leads per Meta campaign, "
            "side by side. The sources count differently: compare them, never add them.",
            ReconciliationQuery,
            get_source_reconciliation,
        ),
        Tool(
            "explain_metric_change",
            "Which segments (campaigns, channels...) moved a metric between two periods, "
            "with each segment's numerator and denominator before and after, its effect "
            "and a direction label such as spend_up_paid_qualified_leads_down. Effects are "
            "arithmetic contributions, not causes.",
            ChangeQuery,
            explain_metric_change,
        ),
        Tool(
            "get_data_quality",
            "What can't be trusted about a period: evidence coverage, classification "
            "defaults, unmapped campaigns, channels without spend data, tracking capture "
            "by week (a sudden drop means broken tracking), missing days, rejected rows, "
            "cohort maturity and time zones. Use it for 'what can't we conclude?'.",
            QualityQuery,
            get_data_quality,
        ),
    )
}


def call_tool(engine: Engine, org_slug: str, name: str, arguments: dict[str, Any]) -> dict:
    """Validate the arguments with the tool's input model, then run it. Raises KeyError for
    an unknown tool and pydantic.ValidationError for bad arguments."""
    tool = TOOLS[name]
    return tool.run(engine, org_slug, tool.input_model.model_validate(arguments))
