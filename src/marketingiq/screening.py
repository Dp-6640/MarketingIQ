"""Screening text from source data before a model reads it.

Labels in the data (annotation notes, campaign names) are written by people and systems
outside MarketingIQ. Text in them that addresses the assistant ("ignore your previous
instructions") is a prompt injection: the model might follow it, or repeat it to the user as
if it were a fact. Such text is withheld and the result says so.

This is pattern-based and can't catch every phrasing. The deeper protections don't depend on
it: the assistant can't act on anything (read-only tools), and every number in an answer
comes from a tool result, not from text.
"""

import re
from typing import Any

WITHHELD = "[withheld: text addressed to the assistant]"

_PATTERNS = [
    re.compile(r"\b(ignore|disregard|forget|override)\b.{0,40}\b(instruction|rule|prompt)s?\b"),
    re.compile(
        r"\b(note|message|instruction)s?\s+(to|for)\s+(the\s+)?(ai|assistant|llm|model|chatbot)\b"
    ),
    re.compile(r"\b(ai|llm|chatbot)\s+assistant\b"),
    re.compile(r"\bsystem\s+prompt\b"),
    re.compile(r"\byou\s+(must|should|are\s+now|will\s+now)\b"),
    re.compile(r"\b(tell|inform)\s+the\s+user\b"),
]


def looks_like_instruction(text: str) -> bool:
    lowered = text.casefold()
    return any(pattern.search(lowered) for pattern in _PATTERNS)


def screen(result: dict[str, Any]) -> dict[str, Any]:
    """Withhold instruction-like labels anywhere in a tool result, in place; add the
    `instruction_in_data` warning when anything was withheld."""
    found = False

    def visit(node: Any) -> None:
        nonlocal found
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "label" and isinstance(value, str) and looks_like_instruction(value):
                    node[key], found = WITHHELD, True
                elif key == "labels" and isinstance(value, dict):
                    for name, text in value.items():
                        if isinstance(text, str) and looks_like_instruction(text):
                            value[name], found = WITHHELD, True
                else:
                    visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(result)
    if found:
        warning = {
            "code": "instruction_in_data",
            "message": "Some text in the data looked like instructions to the assistant and "
            "was withheld; check the source record.",
        }
        result.setdefault("warnings", []).append(warning)
    return result
