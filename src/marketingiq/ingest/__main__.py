"""Command line: `uv run python -m marketingiq.ingest load <dataset folder> [--org SLUG]`."""

import argparse
import sys
from pathlib import Path

from marketingiq.db import get_owner_engine
from marketingiq.ingest.loader import load_dataset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m marketingiq.ingest", description="Load source files into staging."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    load = commands.add_parser("load", help="load every known file in a dataset folder")
    load.add_argument("folder", type=Path)
    load.add_argument("--org", help="organization slug (needed when there is no manifest.json)")
    args = parser.parse_args(argv)

    results = load_dataset(get_owner_engine(), args.folder, org_slug=args.org)
    print(f"{'table':<24}{'status':<9}{'read':>9}{'loaded':>9}{'rejected':>9}{'duplicate':>10}")
    for r in results:
        print(
            f"{r.entity:<24}{r.status:<9}{r.rows_read:>9,}{r.rows_loaded:>9,}"
            f"{r.rows_rejected:>9,}{r.rows_duplicate:>10,}"
        )
        if r.error:
            print(f"  error: {r.error}")
    return 1 if any(r.status == "failed" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
