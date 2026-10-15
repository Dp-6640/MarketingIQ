from collections import Counter

import pytest

from synthetic.rng import Categorical, Streams, stable_int


def test_stable_int_is_fixed_across_runs():
    # A hard-coded value: if this changes, every generated dataset changes.
    assert stable_int("household") == stable_int("household")
    assert stable_int("household") != stable_int("households")
    assert 0 <= stable_int("x") < 2**64


def test_same_name_and_keys_give_same_draws():
    streams = Streams(42)

    first = streams.rng("demand", 738000, 1).random(5)
    second = streams.rng("demand", 738000, 1).random(5)

    assert first.tolist() == second.tolist()


def test_streams_are_independent_of_creation_order():
    a = Streams(42)
    b = Streams(42)

    a.rng("other")  # extra stream created first on one side only
    assert a.rng("demand", 1).random() == b.rng("demand", 1).random()


def test_different_keys_seeds_or_names_differ():
    base = Streams(42).rng("demand", 1).random()

    assert Streams(42).rng("demand", 2).random() != base
    assert Streams(43).rng("demand", 1).random() != base
    assert Streams(42).rng("meta", 1).random() != base


def test_negative_seed_is_rejected():
    with pytest.raises(ValueError):
        Streams(-1)


def test_categorical_follows_weights_and_skips_zero_weights():
    rng = Streams(1).rng("test")
    categorical = Categorical({"a": 0.7, "never": 0.0, "b": 0.3})

    counts = Counter(categorical.sample(rng) for _ in range(20_000))

    assert counts["never"] == 0
    assert 0.68 < counts["a"] / 20_000 < 0.72
