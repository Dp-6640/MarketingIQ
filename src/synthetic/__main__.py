"""Command line: `uv run python -m synthetic generate [--config tiny] [--seed N] [--out DIR]`."""

import argparse
import json
import sys
import time
from pathlib import Path

from synthetic.export import DEFAULT_SEED, generate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m synthetic",
        description="Generate a synthetic MarketingIQ dataset. All data is fictional.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    gen = commands.add_parser("generate", help="simulate a world and write its files")
    gen.add_argument("--config", default="default", help="config name or path to a .toml file")
    gen.add_argument("--seed", type=int, default=DEFAULT_SEED)
    gen.add_argument("--out", type=Path, default=Path("data/synthetic"))
    args = parser.parse_args(argv)

    started = time.perf_counter()
    folder = generate(args.config, args.seed, args.out)
    elapsed = time.perf_counter() - started
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))

    print(f"Wrote {folder} in {elapsed:.1f}s (synthetic, seed {manifest['seed']})")
    for path, info in manifest["files"].items():
        rows = "" if info["rows"] is None else f"{info['rows']:>9,} rows"
        print(f"  {path:<34}{rows}")
    print("Realized:")
    for key, value in manifest["realized"].items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
