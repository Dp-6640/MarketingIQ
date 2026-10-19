"""The benchmark's cases and path language (no database needed)."""

import re

import pytest

from benchmark.cases import CASE_SETS, load_cases, resolve
from marketingiq.analytics.metrics import METRICS
from marketingiq.analytics.performance import _significant
from marketingiq.assistant.paths import Missing

RESULTS = [
    {
        "rows": [
            {"key": "a", "values": {"leads": {"value": 3}}, "flags": []},
            {"key": "b", "values": {"leads": {"value": None, "suppressed": True}}, "flags": ["x"]},
        ],
        "weeks": [{"week_of": "2026-07-06", "dropped": True}],
    }
]


def test_every_case_is_valid_and_ids_are_unique():
    cases = load_cases()

    assert len({case.id for case in cases}) == len(cases)


def test_every_mvp_question_in_the_map_has_a_case():
    covered = {
        int(match.group(1))
        for case in load_cases()
        if (match := re.search(r"question-tool-map #(\d+)", case.covers))
    }

    assert covered == set(range(1, 24))  # 24 and 25 are V1 (Clarity)


def test_refusal_clarification_and_abstention_are_all_represented():
    kinds = {case.kind for case in load_cases()}

    assert kinds == {"answer", "clarify", "abstain", "refuse"}


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("0:rows[0].values.leads.value", 3),
        ("0:rows[-1].key", "b"),
        ("0:rows{key=b}.flags", ["x"]),
        ("0:weeks{dropped=true}.week_of", "2026-07-06"),
    ],
)
def test_paths_resolve(path, value):
    assert resolve(path, RESULTS) == value


@pytest.mark.parametrize("path", ["0:rows{key=z}.key", "0:rows[5]", "0:nothing"])
def test_missing_paths_say_what_is_missing(path):
    with pytest.raises(Missing):
        resolve(path, RESULTS)


def test_a_rate_change_is_significant_only_beyond_chance():
    rate = METRICS["form_submit_rate"]
    small = _significant(
        rate,
        {rate.numerator: 18, rate.denominator: 421},
        {rate.numerator: 19, rate.denominator: 418},
    )
    large = _significant(
        rate,
        {rate.numerator: 1800, rate.denominator: 42100},
        {rate.numerator: 1500, rate.denominator: 41800},
    )

    assert small is False  # 4.3% vs 4.5% on ~420 sessions: noise
    assert large is True  # 4.3% vs 3.6% on ~42,000 sessions: real
    assert _significant(rate, {rate.numerator: 0, rate.denominator: 0}, {}) is None


def test_the_held_out_set_is_separate_from_the_main_set():
    main, held_out = load_cases(CASE_SETS["main"]), load_cases(CASE_SETS["heldout"])

    assert all(case.id.startswith("H") for case in held_out)

    # A held-out conversation may open like a main case (H13 and R06); the turns as a whole differ.
    def conversations(cases):
        return {(c.question, *c.followups) for c in cases}

    assert conversations(main).isdisjoint(conversations(held_out))
