"""The benchmark scorer fails wrong answers for the right reason (no database needed)."""

import uuid

from benchmark.cases import Case
from benchmark.score import score
from marketingiq.assistant.answer import SubmitAnswer, render
from marketingiq.assistant.run import CallRecord, Run

CASE = Case.model_validate(
    {
        "id": "T01",
        "covers": "test",
        "question": "Which campaign had the most leads?",
        "kind": "answer",
        "calls": [
            {
                "tool": "get_performance",
                "args": {"period": {"preset": "last_month"}, "metrics": ["leads"]},
            }
        ],
        "warnings": ["low_attribution_coverage"],
        "facts": ["0:rows[0].key", "0:rows[0].values.leads.value"],
        "forbidden": ["caused"],
    }
)
RESULT = {
    "rows": [{"key": "meta_a", "values": {"leads": {"value": 12}}}],
    "warnings": [{"code": "low_attribution_coverage", "message": "..."}],
}
KEY = {"0:rows[0].key": "meta_a", "0:rows[0].values.leads.value": 12}


def run_with(answer: str, status: str = "answered", result: dict | None = None) -> Run:
    results = {"c1": result or RESULT}
    run = Run(id=uuid.uuid4(), question=CASE.question, model="test", results=results)
    run.calls = [CallRecord("c1", "get_performance", {}, True, None, 1)]
    run.rendered = render(SubmitAnswer(status=status, answer=answer), results)
    run.status, run.answer = status, run.rendered.text
    return run


def test_a_good_answer_passes():
    result = score(
        CASE, run_with("{{c1:rows[0].key}} was credited with {{c1:rows[0].values.leads}}."), KEY
    )

    assert result.passed and (result.cited, result.citable) == (2, 2)


def test_the_wrong_kind_of_response_fails():
    assert not score(CASE, run_with("I can't answer that.", status="refuse"), KEY).passed


def test_missing_facts_fail():
    other = {
        "rows": [{"key": "meta_b", "values": {"leads": {"value": 3}}}],
        "warnings": RESULT["warnings"],
    }

    result = score(CASE, run_with("{{c1:rows[0].key}}.", result=other), KEY)

    assert not result.passed and result.obtained == 0


def test_forbidden_phrases_and_missing_caveats_fail():
    causal = score(CASE, run_with("{{c1:rows[0].key}} caused {{c1:rows[0].values.leads}}."), KEY)
    no_warning = {**RESULT, "warnings": []}
    uncaveated = score(CASE, run_with("{{c1:rows[0].key}}.", result=no_warning), KEY)

    assert causal.forbidden_found == ["caused"] and not causal.passed
    assert uncaveated.caveats_missing == ["low_attribution_coverage"] and not uncaveated.passed
