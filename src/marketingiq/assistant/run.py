"""One assistant run: a question in, tool calls, one answer out, every step in the trace.

The loop gives the model the tools plus `submit_answer`, executes each tool call through the
same validated services as the REST API, and numbers each successful result (c1, c2...). The
answer is rendered by the backend (answer.py); if it breaks the contract (a typed number, an
unknown reference) the model gets the errors and one more try, then the run fails.
"""

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Engine, text

from marketingiq.assistant.answer import SUBMIT_DESCRIPTION, Rendered, SubmitAnswer, render
from marketingiq.assistant.llm import ChatModel, ToolCall
from marketingiq.assistant.prompt import system_prompt
from marketingiq.assistant.schemas import tool_definitions
from marketingiq.assistant.store import save_run
from marketingiq.tools import TOOLS, call_tool

MAX_STEPS = 10
MAX_ANSWER_TRIES = 2


@dataclass
class CallRecord:
    id: str | None  # "c1"... for a successful call, None for a failed one
    tool: str
    arguments: Any
    ok: bool
    error: str | None
    ms: int


@dataclass
class Run:
    id: uuid.UUID
    question: str
    model: str
    status: str = "failed"
    answer: str | None = None
    rendered: Rendered | None = None
    calls: list[CallRecord] = field(default_factory=list)
    results: dict[str, dict] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    steps: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0


def _json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    raise TypeError(f"can't serialize {type(value).__name__}")


def _dumps(value: Any) -> str:
    return json.dumps(value, default=_json, separators=(",", ":"))


def _validation_message(exc: ValidationError) -> list[dict]:
    return [
        {"where": ".".join(str(p) for p in e["loc"]), "problem": e["msg"]} for e in exc.errors()
    ]


def _execute(run: Run, call: ToolCall, engine: Engine, org: str) -> str:
    """Run one tool call; the reply is what the model sees."""
    started = time.perf_counter()
    try:
        arguments = json.loads(call.arguments or "{}")
    except json.JSONDecodeError as exc:
        arguments, error = call.arguments, f"arguments are not valid JSON: {exc}"
    else:
        error = None
    record = CallRecord(None, call.name, arguments, False, error, 0)
    run.calls.append(record)
    if error is None and call.name not in TOOLS:
        record.error = f"unknown tool {call.name!r}"
    if record.error is None:
        try:
            result = call_tool(engine, org, call.name, arguments)
        except ValidationError as exc:
            record.error = "invalid arguments"
            record.ms = int((time.perf_counter() - started) * 1000)
            return _dumps({"error": "invalid arguments", "details": _validation_message(exc)})
        except LookupError as exc:
            record.error = str(exc)
        else:
            record.id, record.ok = f"c{len(run.results) + 1}", True
            run.results[record.id] = json.loads(_dumps(result))
    record.ms = int((time.perf_counter() - started) * 1000)
    if not record.ok:
        return _dumps({"error": record.error})
    return _dumps({"call": record.id, "result": run.results[record.id]})


def ask(
    question: str,
    *,
    engine: Engine,
    org: str,
    model: ChatModel,
    store: bool = True,
) -> Run:
    run = Run(id=uuid.uuid4(), question=question, model=model.name)
    started = time.perf_counter()
    with engine.connect() as conn:
        org_row = conn.execute(
            text("SELECT id, data_as_of, currency FROM core.organizations WHERE slug = :slug"),
            {"slug": org},
        ).one_or_none()
    if org_row is None or org_row.data_as_of is None:
        raise LookupError(f"{org} has no data to answer from")

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt(org_row.data_as_of, org_row.currency)},
        {"role": "user", "content": question},
    ]
    tools = tool_definitions([("submit_answer", SUBMIT_DESCRIPTION, SubmitAnswer)])
    answer_tries = 0
    while run.steps < MAX_STEPS and run.status == "failed" and answer_tries < MAX_ANSWER_TRIES:
        run.steps += 1
        reply = model.complete(messages, tools)
        run.prompt_tokens += reply.prompt_tokens
        run.completion_tokens += reply.completion_tokens
        messages.append(reply.as_message())
        if not reply.tool_calls:
            messages.append(
                {"role": "user", "content": "Finish with exactly one submit_answer call."}
            )
            continue
        submits = [c for c in reply.tool_calls if c.name == "submit_answer"]
        for call in reply.tool_calls:
            if call.name != "submit_answer":
                content = _execute(run, call, engine, org)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
        if not submits and run.steps >= MAX_STEPS - 2:
            messages.append(
                {"role": "user", "content": "Finish now: call submit_answer with what you have."}
            )
        for call in submits:
            answer_tries += 1
            feedback = _submit(run, call)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": feedback})
            if run.status != "failed":
                break
    if run.status == "failed" and not run.errors:
        run.errors.append("no valid answer within the step limit")
    run.latency_ms = int((time.perf_counter() - started) * 1000)
    if store:
        save_run(engine, _row(run, org_row.id))
    return run


def _submit(run: Run, call: ToolCall) -> str:
    try:
        draft = SubmitAnswer.model_validate_json(call.arguments or "{}")
    except ValidationError as exc:
        run.errors.append("submit_answer: invalid arguments")
        return _dumps({"error": "invalid arguments", "details": _validation_message(exc)})
    rendered = render(draft, run.results)
    if rendered.errors:
        run.errors += rendered.errors
        return _dumps(
            {
                "error": "the answer breaks the rules; fix these and call submit_answer again",
                "problems": rendered.errors,
            }
        )
    run.rendered, run.status, run.answer = rendered, rendered.status, rendered.text
    return _dumps({"ok": True})


def _row(run: Run, org_id: int) -> dict:
    rendered = run.rendered
    trace = {
        "calls": [asdict(c) for c in run.calls],
        "template": rendered.template if rendered else None,
        "citations": [asdict(c) for c in rendered.citations] if rendered else [],
        "caveats": rendered.caveats if rendered else [],
        "errors": run.errors,
    }
    return {
        "id": run.id,
        "org_id": org_id,
        "question": run.question,
        "status": run.status,
        "model": run.model,
        "answer": run.answer,
        "trace": json.loads(_dumps(trace)),
        "steps": run.steps,
        "prompt_tokens": run.prompt_tokens,
        "completion_tokens": run.completion_tokens,
        "latency_ms": run.latency_ms,
    }
