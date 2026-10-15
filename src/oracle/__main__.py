"""`python -m oracle summary <dataset folder>`: the oracle's headline numbers for a dataset."""

import argparse
from datetime import date

from oracle import count, load


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m oracle")
    parser.add_argument("command", choices=["summary"])
    parser.add_argument("folder")
    args = parser.parse_args()

    facts = load(args.folder)
    everything = (date.min, date.max)
    print(f"leads: {len(facts.leads):,}")
    print("classes:", dict(count.classes(facts, *everything).most_common()))
    print("tiers (all first leads, 30 days):", dict(count.tiers(facts, *everything, "all")))
    junk = [lead.junk_reason for lead in facts.leads if lead.junk_reason]
    print("junk reasons:", {r: junk.count(r) for r in ("duplicate", "invalid", "test")})


if __name__ == "__main__":
    main()
