"""A small path language for pointing at one value inside tool results.

A path is steps separated by dots. A step is a key, optionally followed by [n] (a list
index, negative from the end) or a selector, [field=value] or {field=value}: the first list
item whose field equals value (true/false and numbers compare as text). Examples:

    rows[0].values.qualified_leads.value
    rows[key=meta_prospecting_furnace].values.cost_per_lead
    capture_by_week[dropped=true].week_of

The assistant's answer references and the benchmark's facts both use it.
"""

import re
from typing import Any

_STEP = re.compile(
    r"^(?P<name>[^\[{]+)?"
    r"(?:\[(?P<index>-?\d+)\]"
    r"|\[(?P<field>[^=\]]+)=(?P<want>[^\]]*)\]"
    r"|\{(?P<field2>[^=}]+)=(?P<want2>[^}]*)\})?$"
)


class Missing(LookupError):
    """The path points at something the result doesn't have."""


def _text(value: Any) -> str:
    return str(value).lower() if isinstance(value, bool) else str(value)


def _steps(path: str) -> list[str]:
    """Split on dots outside selectors (a selected value may contain dots)."""
    steps, depth, current = [], 0, ""
    for char in path:
        if char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        if char == "." and depth == 0:
            steps.append(current)
            current = ""
        else:
            current += char
    steps.append(current)
    return steps


def walk(node: Any, path: str) -> Any:
    for step in _steps(path.strip()):
        match = _STEP.match(step.strip())
        if not match or not step.strip():
            raise ValueError(f"bad path step {step!r}")
        if match["name"]:
            if not isinstance(node, dict) or match["name"] not in node:
                raise Missing(f"{path}: no {match['name']!r}")
            node = node[match["name"]]
        field = match["field"] or match["field2"]
        if match["index"] is not None:
            try:
                node = node[int(match["index"])]
            except (IndexError, TypeError, KeyError):
                raise Missing(f"{path}: no item {match['index']}") from None
        elif field is not None:
            want = match["want"] if match["field"] else match["want2"]
            found = [
                item
                for item in (node if isinstance(node, list) else [])
                if isinstance(item, dict) and _text(item.get(field)) == want
            ]
            if not found:
                raise Missing(f"{path}: no item with {field}={want}")
            node = found[0]
    return node
