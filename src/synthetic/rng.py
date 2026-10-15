"""Named, independent random streams.

Every draw comes from a generator keyed by (seed, stream name, integer keys), for example
("household", day, region, ...). Generators don't share state, so the order in which parts
of the simulation run doesn't change any numbers, and a scenario that adds records on one
day doesn't reshuffle every other day.
"""

import hashlib
from bisect import bisect_right
from collections.abc import Mapping, Sequence

import numpy as np


def stable_int(text: str) -> int:
    """A 64-bit integer derived from text: identical across runs, machines and Python versions."""
    return int.from_bytes(hashlib.blake2b(text.encode(), digest_size=8).digest(), "big")


class Streams:
    def __init__(self, seed: int) -> None:
        if seed < 0:
            raise ValueError("seed must be non-negative")
        self.seed = seed

    def rng(self, name: str, *keys: int) -> np.random.Generator:
        sequence = np.random.SeedSequence(self.seed, spawn_key=(stable_int(name), *keys))
        return np.random.Generator(np.random.PCG64(sequence))


class Categorical[T]:
    """Sampling from a fixed discrete distribution; much faster per draw than rng.choice."""

    __slots__ = ("_cumulative", "_items")

    def __init__(self, weights: Mapping[T, float]) -> None:
        total = float(sum(weights.values()))
        if total <= 0:
            raise ValueError("weights must sum to a positive number")
        self._items = list(weights)
        running = 0.0
        self._cumulative = []
        for item in self._items:
            running += weights[item]
            self._cumulative.append(running / total)

    @classmethod
    def uniform(cls, items: Sequence[T]) -> "Categorical[T]":
        return cls(dict.fromkeys(items, 1.0))

    @property
    def items(self) -> list[T]:
        return list(self._items)

    def sample(self, rng: np.random.Generator) -> T:
        index = bisect_right(self._cumulative, rng.random())
        return self._items[min(index, len(self._items) - 1)]
