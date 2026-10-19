"""`python -m marketingiq.assistant "question"`: ask the assistant from the terminal."""

import argparse
import sys

from marketingiq.assistant.llm import ModelNotConfigured, ProviderUnavailable, get_chat_model
from marketingiq.assistant.run import ask
from marketingiq.config import get_settings
from marketingiq.db import get_app_engine


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m marketingiq.assistant")
    parser.add_argument("question")
    parser.add_argument("--org", default=get_settings().default_org_slug)
    parser.add_argument("--trace", action="store_true", help="show every tool call")
    args = parser.parse_args()
    try:
        model = get_chat_model()
    except ModelNotConfigured as exc:
        sys.exit(str(exc))

    try:
        run = ask(args.question, engine=get_app_engine(), org=args.org, model=model)
    except ProviderUnavailable as exc:
        sys.exit(str(exc))
    if args.trace:
        for call in run.calls:
            status = call.id if call.ok else f"failed: {call.error}"
            print(f"  {call.tool} ({status}, {call.ms} ms) {call.arguments}")
    print(f"\n[{run.status}] {run.answer or ''}")
    if run.rendered:
        for caveat in run.rendered.caveats:
            print(f"  - {caveat['message']}")
    for error in run.errors if run.status == "failed" else []:
        print(f"  ! {error}")
    t = run.timing()
    print(
        f"\n{run.model}, run {run.id}: {t['total_ms'] / 1000:.1f} s in all; model"
        f" {t['model_ms'] / 1000:.1f} s over {t['model_requests']} requests, tools"
        f" {t['tools_ms'] / 1000:.1f} s, waiting on rate limits {t['waiting_ms'] / 1000:.1f} s"
        f" ({t['rate_limited']} rejected)"
    )


if __name__ == "__main__":
    main()
