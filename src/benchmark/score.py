"""Scoring one assistant run against a case's answer key.

What counts:
- kind:      the run's status matches the case (answer ↔ answered, clarify, abstain, refuse)
- obtained:  every fact the answer needs is in the run's tool results, however it got there
             (the fact's value appears at the same path in a result of the same tool)
- cited:     of the facts that are single values, the share whose value the answer cites
- caveats:   every required caveat is attached to the answer
- forbidden: none of the case's forbidden phrases appear in the answer

A case passes on kind, obtained, caveats and forbidden. Citing is reported as a share: an
answer can be right without quoting every supporting number. Facts are required only for
answers and clarifications: an abstention or refusal is judged on the decision it makes.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from benchmark.cases import Case, resolve, split_path
from marketingiq.assistant.paths import Missing, walk
from marketingiq.assistant.run import Run

STATUS_FOR_KIND = {
    "answer": "answered",
    "clarify": "clarify",
    "abstain": "abstain",
    "refuse": "refuse",
}


@dataclass
class Score:
    case: str
    status: str
    kind_ok: bool
    obtained: int
    needed: int
    cited: int
    citable: int
    caveats_missing: list[str] = field(default_factory=list)
    forbidden_found: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            self.kind_ok
            and self.obtained == self.needed
            and not self.caveats_missing
            and not self.forbidden_found
        )


def _value(node: Any) -> Any:
    """A cell's value, or the node itself; normalized for comparison."""
    if (
        isinstance(node, dict)
        and "value" in node
        and set(node)
        <= {
            "value",
            "previous",
            "change",
            "change_pct",
            "change_significant",
            "rank",
            "rank_of",
            "suppressed",
            "null_reason",
            "name",
        }
    ):
        node = node["value"]
    return json.loads(json.dumps(node, default=str))


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 1e-6 * max(1.0, abs(b))
    return a == b


def citable(value: Any) -> bool:
    return isinstance(value, (int, float, str)) and not isinstance(value, bool)


def expected_facts(case: Case, reference_results: list[dict]) -> dict[str, Any]:
    """The answer key: each fact path resolved against the reference run's results."""
    return {path: _value(resolve(path, reference_results)) for path in case.facts}


def score(case: Case, run: Run, key: dict[str, Any]) -> Score:
    status = run.status
    tools_by_call = {c.id: c.tool for c in run.calls if c.ok}
    obtained = 0
    for path, wanted in key.items():
        index, rest = split_path(path)
        tool = case.calls[index].tool
        for call_id, result in run.results.items():
            if tools_by_call.get(call_id) != tool:
                continue
            try:
                if _same(_value(walk(result, rest)), wanted):
                    obtained += 1
                    break
            except (Missing, ValueError, TypeError):
                continue

    shown = [c.value for c in (run.rendered.citations if run.rendered else [])]
    citable_facts = [v for v in key.values() if citable(v)]
    cited = sum(any(_same(_value(s), v) for s in shown) for v in citable_facts)

    codes = {c["code"] for c in (run.rendered.caveats if run.rendered else [])}
    text = (run.answer or "").lower()
    # Answers and clarifications are built from facts. An abstention or refusal is judged on
    # the decision itself; facts it could have quoted are reported as cited, not required.
    needs_facts = case.kind in ("answer", "clarify")
    return Score(
        case=case.id,
        status=status,
        kind_ok=status == STATUS_FOR_KIND[case.kind],
        obtained=obtained if needs_facts else 0,
        needed=len(key) if needs_facts else 0,
        cited=cited,
        citable=len(citable_facts),
        caveats_missing=[c for c in case.warnings if c not in codes],
        forbidden_found=[p for p in case.forbidden if re.search(re.escape(p.lower()), text)],
        problems=run.errors if status == "failed" else [],
    )
