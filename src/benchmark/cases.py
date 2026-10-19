"""Benchmark cases: loading, validation, and the small path language they use."""

import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from marketingiq.analytics.performance import WARNING_MESSAGES
from marketingiq.assistant.paths import walk
from marketingiq.tools import TOOLS

CASES = Path(__file__).with_name("cases.toml")
# Held-out questions, never used for tuning (docs/benchmark.md).
HELDOUT = Path(__file__).with_name("heldout.toml")
CASE_SETS = {"main": CASES, "heldout": HELDOUT}


class Call(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _valid(self) -> "Call":
        if self.tool not in TOOLS:
            raise ValueError(f"unknown tool {self.tool!r}")
        TOOLS[self.tool].input_model.model_validate(self.args)
        return self


class Expect(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    op: Literal["equals", "contains", "startswith", "not_null", "gt", "lt"]
    value: Any = None  # a string starting with "@" is another path


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    covers: str
    question: str
    kind: Literal["answer", "clarify", "abstain", "refuse"]
    scenario: str | None = None
    calls: list[Call] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    expect: list[Expect] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)
    notes: str = ""

    @model_validator(mode="after")
    def _consistent(self) -> "Case":
        if self.kind == "refuse" and self.calls:
            raise ValueError(f"{self.id}: a refusal makes no tool calls")
        if self.kind != "refuse" and not self.calls:
            raise ValueError(f"{self.id}: needs reference calls")
        unknown = set(self.warnings) - set(WARNING_MESSAGES)
        if unknown:
            raise ValueError(f"{self.id}: unknown warning codes {sorted(unknown)}")
        for path in [*self.facts, *(e.path for e in self.expect)]:
            index, _ = split_path(path)
            if index >= len(self.calls):
                raise ValueError(f"{self.id}: {path!r} refers to a call that doesn't exist")
        return self


def load_cases(path: Path = CASES) -> list[Case]:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    cases = [Case.model_validate(case) for case in raw["case"]]
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case ids")
    return cases


# --- paths ------------------------------------------------------------------------------------
#
# "<call index>:<path>", the path in the language of marketingiq.assistant.paths. Example:
#   1:rows{key=meta_prospecting_furnace}.values.cost_per_lead.value


def split_path(path: str) -> tuple[int, str]:
    index, _, rest = path.partition(":")
    return int(index), rest


def resolve(path: str, results: list[dict]) -> Any:
    index, rest = split_path(path)
    return walk(results[index], rest)
