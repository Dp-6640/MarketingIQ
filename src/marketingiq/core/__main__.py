"""Command line: `uv run python -m marketingiq.core build --org <slug>`."""

import argparse
import json
import sys

from marketingiq.core.build import build_core
from marketingiq.db import get_owner_engine


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m marketingiq.core",
        description="Rebuild the core model from the latest staging loads.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="rebuild one organization's core tables")
    build.add_argument("--org", required=True, help="organization slug")
    args = parser.parse_args(argv)

    result = build_core(get_owner_engine(), args.org)
    print(f"Build {result.run_id} from load batches {result.batches}")
    print(json.dumps(result.summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
