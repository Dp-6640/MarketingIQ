"""The answer contract (ADR-006): the model writes a template, the backend writes the numbers.

The model ends a run with `submit_answer`. Its text refers to values in earlier tool results,
such as `{{c2:rows[key=meta_prospecting_furnace].values.cost_per_lead}}`, and the backend
resolves and formats each one. A number the model typed itself is rejected, so an answer can't
contain a value that didn't come from a tool. Caveats come from the tools' warnings, never from
the model.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from marketingiq.analytics.metrics import METRICS
from marketingiq.analytics.performance import WARNING_MESSAGES
from marketingiq.assistant.paths import Missing, walk

Status = Literal["answered", "clarify", "abstain", "refuse"]


class SubmitAnswer(BaseModel):
    """Finish the run. `answer` is plain text for the user. Every number in it must be a
    reference to a tool result, {{c<call number>:<path>}}; never type a number yourself."""

    model_config = ConfigDict(extra="forbid")

    status: Status = Field(
        description="answered: a result from the tools. clarify: ask which one the user means. "
        "abstain: the data can't give this number; say why. refuse: out of scope by design."
    )
    answer: str = Field(max_length=4000, description="The answer, with numbers as references.")


SUBMIT_DESCRIPTION = (
    "Give the final answer to the user and end the run. Every number must be a reference "
    "{{c<N>:<path>}} to a value in the result of call cN, for example "
    "{{c1:rows[key=meta_prospecting_furnace].values.cost_per_lead}} or "
    "{{c1:totals.leads.change_pct}}. Text values (keys, labels, dates) may be referenced too."
)

REFERENCE = re.compile(r"\{\{\s*c(\d+)\s*:\s*(.+?)\s*\}\}")
# A number written by the model: digits, optionally signed, with separators, decimals, a
# currency sign or a percent, standing alone (not inside a word, key or date).
_NUMERAL = re.compile(r"(?<![\w./-])[-+]?\$?\d(?:[\d,]*\d)?(?:\.\d+)?%?(?![\w/-])")
_ALLOWED = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),  # ISO dates
    re.compile(
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:,\s*\d{4})?\b"
    ),
    re.compile(r"\b(?:19|20)\d{2}\b"),  # years
    re.compile(r"\b(?:7|30|90)-day\b"),  # lookback windows
]
_PERCENT_NAMES = ("change_pct", "share", "coverage", "rate", "capture_share")
_CURRENCY_NAMES = ("spend", "cost", "amount", "won_amount")


@dataclass
class Citation:
    reference: str
    call: str
    path: str
    value: Any
    display: str


@dataclass
class Rendered:
    status: Status
    text: str
    template: str
    citations: list[Citation] = field(default_factory=list)
    caveats: list[dict[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def bare_numerals(template: str) -> list[str]:
    """Numbers typed into the template outside references (dates and years excepted)."""
    text = REFERENCE.sub(" ", template)
    for pattern in _ALLOWED:
        text = pattern.sub(" ", text)
    return _NUMERAL.findall(text)


def _unit(path: str, context: str | None = None) -> str:
    """How to format the value a path points at, from the metric it names. `context` is the
    unit of a result about one metric (a change explanation), for its totals and effects."""
    steps = re.split(r"[.\[\]{}=]", path)
    last = next((s for s in reversed(steps) if s and s != "value"), "")
    metric = next((METRICS[s] for s in reversed(steps) if s in METRICS), None)
    if last in ("change_pct", "share_of_change") or any(n in last for n in _PERCENT_NAMES):
        return "percent_change" if last == "change_pct" else "percent"
    if last in ("rank", "rank_of", "rows_judged", "flagged", "count", "row_count"):
        return "integer"
    if metric is not None:
        return {"rate": "percent", "currency": "currency"}.get(metric.unit, "number")
    if any(n in last for n in _CURRENCY_NAMES):
        return "currency"
    if context and steps[0] in ("total", "segments"):
        return {"rate": "percent", "currency": "currency"}.get(context, "number")
    return "number"


def _format(value: Any, unit: str) -> str:
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value.isoformat() if isinstance(value, date) else str(value)
    if unit == "percent":
        return f"{value:.1%}"
    if unit == "percent_change":
        return f"{value:+.1%}"
    if unit == "currency":
        return f"-${-value:,.2f}" if value < 0 else f"${value:,.2f}"
    if unit == "integer" or float(value).is_integer():
        return f"{value:,.0f}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _cell(node: Any, path: str, context: str | None = None) -> tuple[Any, str]:
    """A cell ({"value": ...}) or a named part ({"name": "spend", "value": ...}) gives its
    value; hidden and missing values say why instead of showing a number."""
    if isinstance(node, dict) and "value" in node:
        if node.get("suppressed"):
            return None, "hidden (fewer than 5)"
        if node["value"] is None:
            return None, f"not available ({node.get('null_reason', 'no value')})"
        unit = _unit(f"{path}.{node['name']}", None) if "name" in node else _unit(path, context)
        return node["value"], _format(node["value"], unit)
    if isinstance(node, (dict, list)):
        raise ValueError("points at a group of values, not one value")
    return node, _format(node, _unit(path, context)) if node is not None else "not available"


def render(draft: SubmitAnswer, results: dict[str, dict]) -> Rendered:
    """Resolve every reference against the run's results (keyed "c1", "c2"...)."""
    rendered = Rendered(status=draft.status, text="", template=draft.answer)
    for numeral in bare_numerals(draft.answer):
        rendered.errors.append(
            f"the number {numeral!r} was typed, not referenced: use a {{{{cN:path}}}} reference"
        )

    def substitute(match: re.Match) -> str:
        call, path = f"c{match[1]}", match[2]
        if call not in results:
            rendered.errors.append(f"{match[0]}: there is no call {call}")
            return match[0]
        context = (results[call].get("metric") or {}).get("unit")
        try:
            value, display = _cell(walk(results[call], path), path, context)
        except (Missing, ValueError) as exc:
            rendered.errors.append(f"{match[0]}: {exc}")
            return match[0]
        rendered.citations.append(Citation(match[0], call, path, value, display))
        return display

    # A reference brings its own unit; "{{…change_pct}}%" would otherwise show "12.0%%".
    rendered.text = REFERENCE.sub(substitute, draft.answer).replace("%%", "%")
    codes = []
    for result in results.values():
        for warning in result.get("warnings", []):
            if warning["code"] not in codes:
                codes.append(warning["code"])
    rendered.caveats = [{"code": c, "message": WARNING_MESSAGES.get(c, c)} for c in codes]
    return rendered
