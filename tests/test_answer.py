"""The answer contract (ADR-006) and the tool schemas the model sees. No database needed."""

import json

import pytest

from marketingiq.assistant.answer import SubmitAnswer, bare_numerals, render
from marketingiq.assistant.llm import Reply, ToolCall
from marketingiq.assistant.paths import walk
from marketingiq.assistant.schemas import tool_definitions
from marketingiq.tools import TOOLS

RESULTS = {
    "c1": {
        "rows": [
            {
                "key": "meta_promo",
                "values": {
                    "cost_per_lead": {"value": 31.2, "previous": 25.0, "change_pct": 0.248},
                    "leads": {"value": None, "suppressed": True},
                    "cost_per_qualified_lead": {"value": None, "null_reason": "no_spend_source"},
                },
            }
        ],
        "totals": {"qualification_rate": {"value": 0.5191}, "spend": {"value": 12345.6}},
        "warnings": [{"code": "synthetic_data", "message": "..."}],
    },
    "c2": {"total": {"numerator": {"name": "spend", "value": 2878.32}}, "warnings": []},
}


def answer(text: str, status: str = "answered"):
    return render(SubmitAnswer(status=status, answer=text), RESULTS)


@pytest.mark.parametrize(
    ("reference", "shown"),
    [
        ("{{c1:rows[key=meta_promo].values.cost_per_lead}}", "$31.20"),
        ("{{c1:rows[0].values.cost_per_lead.previous}}", "$25.00"),
        ("{{c1:rows[0].values.cost_per_lead.change_pct}}", "+24.8%"),
        ("{{c1:totals.qualification_rate}}", "51.9%"),
        ("{{c1:totals.spend}}", "$12,345.60"),
        ("{{c1:rows[0].key}}", "meta_promo"),
        ("{{c2:total.numerator}}", "$2,878.32"),
        ("{{c1:rows[0].values.leads}}", "hidden (fewer than 5)"),
        ("{{c1:rows[0].values.cost_per_qualified_lead}}", "not available (no_spend_source)"),
    ],
)
def test_references_are_filled_in_and_formatted_by_metric(reference, shown):
    result = answer(f"It was {reference}.")

    assert result.errors == []
    assert result.text == f"It was {shown}."
    assert result.citations[0].call == reference[2:4]


def test_typed_numbers_are_rejected_but_dates_and_years_are_not():
    assert bare_numerals("Spend was $1,200, up 12%, across 3 campaigns.") == ["$1,200", "12%", "3"]
    assert bare_numerals("From 2026-09-01 to September 30, 2026, over a 30-day lookback.") == []
    assert bare_numerals("Campaign meta_prospecting_furnace in Q3 and S04.") == []

    result = answer("Cost was 31.20 per lead.")
    assert result.errors and "typed, not referenced" in result.errors[0]


@pytest.mark.parametrize(
    ("reference", "problem"),
    [
        ("{{c9:rows}}", "there is no call c9"),
        ("{{c1:rows}}", "a group of values"),
        ("{{c1:rows[key=nope].key}}", "no item with key=nope"),
    ],
)
def test_bad_references_are_reported(reference, problem):
    assert problem in answer(reference).errors[0]


def test_caveats_come_from_the_tools_not_the_model():
    result = answer("No numbers here.", status="refuse")

    assert [c["code"] for c in result.caveats] == ["synthetic_data"]
    assert result.status == "refuse"


def test_selectors_may_contain_dots():
    data = {"pages": [{"path": "/a.b/", "n": 1}]}

    assert walk(data, "pages[path=/a.b/].n") == 1


def test_tool_schemas_use_only_the_portable_subset():
    definitions = tool_definitions([("submit_answer", "finish", SubmitAnswer)])
    text = json.dumps(definitions)

    assert {d["function"]["name"] for d in definitions} == {*TOOLS, "submit_answer"}
    for forbidden in ("$ref", "$defs", "anyOf", "additionalProperties", "title", '"format"'):
        assert forbidden not in text


def test_provider_fields_on_a_tool_call_are_sent_back_unchanged():
    signature = {"extra_content": {"google": {"thought_signature": "abc"}}}
    reply = Reply(None, [ToolCall("call_1", "get_performance", "{}", signature)])

    sent = reply.as_message()["tool_calls"][0]

    assert sent["extra_content"] == signature["extra_content"]
    assert sent["function"] == {"name": "get_performance", "arguments": "{}"}


def test_a_hidden_previous_value_renders_as_hidden():
    results = {
        "c1": {
            "rows": [{"key": "a", "values": {"leads": {"value": 0, "previous_suppressed": True}}}]
        }
    }

    rendered = render(
        SubmitAnswer(status="answered", answer="From {{c1:rows[0].values.leads.previous}}."),
        results,
    )

    assert rendered.errors == [] and rendered.text == "From hidden (fewer than 5)."


def test_a_copied_wrapper_prefix_is_ignored():
    rendered = render(
        SubmitAnswer(status="answered", answer="{{c1:results[0].totals.spend}}"), RESULTS
    )

    assert rendered.errors == [] and rendered.text == "$12,345.60"
