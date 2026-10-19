"""A scripted "perfect assistant" for checking the scorer.

For each case it replays the reference calls and submits an answer that cites every fact
that is a single value. Scored through the real run loop, it must pass every case; if it
doesn't, the scorer or the answer key is wrong, not the model.
"""

import re

from benchmark.cases import Case, split_path
from marketingiq.assistant.llm import Reply, ScriptedModel, call

_STATUS = {"answer": "answered", "clarify": "clarify", "abstain": "abstain", "refuse": "refuse"}


def _reference(path: str) -> str:
    index, rest = split_path(path)
    # Answer references use [field=value] selectors: braces would end the {{ }}.
    rest = re.sub(r"\{([^=}]+)=([^}]*)\}", r"[\1=\2]", rest)
    return f"{{{{c{index + 1}:{rest}}}}}"


def reference_agent(case: Case, citable_paths: list[str]) -> ScriptedModel:
    replies = [Reply(None, [call(c.tool, c.args, f"ref_{i}")]) for i, c in enumerate(case.calls)]
    cited = "; ".join(_reference(p) for p in citable_paths) or "No numbers apply."
    answer = f"Reference answer for {case.id}: {cited}."
    replies.append(
        Reply(None, [call("submit_answer", {"status": _STATUS[case.kind], "answer": answer})])
    )
    return ScriptedModel(replies, name="reference-agent")


def clarifying_agent() -> ScriptedModel:
    """An earlier turn of a conversation case: the reference agent asks which one is meant."""
    reply = call("submit_answer", {"status": "clarify", "answer": "Which one do you mean?"})
    return ScriptedModel([Reply(None, [reply])], name="reference-agent")
