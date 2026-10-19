"""The assistant endpoint: one question in, one answer out (single-turn in the MVP)."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Engine, text

from marketingiq.api.routes_analytics import Org
from marketingiq.assistant.answer import REFERENCE
from marketingiq.assistant.llm import (
    ChatModel,
    ModelNotConfigured,
    ProviderQuotaExhausted,
    get_chat_model,
)
from marketingiq.assistant.run import Run, ask
from marketingiq.db import get_app_engine

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    # Continue a conversation: the run this question replies to (a clarification, a follow-up).
    follows: uuid.UUID | None = None


MAX_TURNS = 4  # earlier turns given to the model; older ones are dropped


def conversation(engine: Engine, org: str, last: uuid.UUID) -> list[tuple[str, str]]:
    """Earlier (question, answer) turns ending at `last`, oldest first. Failed runs are
    skipped: they have no answer to continue from."""
    turns, current = [], last
    with engine.connect() as conn:
        while current is not None and len(turns) < MAX_TURNS:
            row = conn.execute(
                text(
                    "SELECT r.question, r.answer, r.trace->>'follows' AS follows"
                    " FROM app.assistant_runs r JOIN core.organizations o ON o.id = r.org_id"
                    " WHERE o.slug = :org AND r.id = :id"
                ),
                {"org": org, "id": current},
            ).one_or_none()
            if row is None:
                if current == last:
                    raise HTTPException(status_code=404, detail="no such run to follow")
                break
            if row.answer:
                turns.append((row.question, row.answer))
            current = uuid.UUID(row.follows) if row.follows else None
    return list(reversed(turns))


def chat_model() -> ChatModel:
    try:
        return get_chat_model()
    except ModelNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


def segments(template: str | None, displays: list[str]) -> list[dict[str, Any]]:
    """The answer as text pieces and filled-in values, so a page can mark each number and
    link it to the call it came from."""
    if not template:
        return []
    pieces, position = [], 0
    for index, match in enumerate(REFERENCE.finditer(template)):
        pieces.append({"text": template[position : match.start()]})
        pieces.append({"value": displays[index], "citation": index})
        position = match.end()
    pieces.append({"text": template[position:]})
    return [p for p in pieces if p.get("text") != ""]


def present(run: Run) -> dict[str, Any]:
    rendered = run.rendered
    return {
        "segments": segments(
            rendered.template if rendered else None,
            [c.display for c in rendered.citations] if rendered else [],
        ),
        "run_id": str(run.id),
        "status": run.status,
        "answer": run.answer,
        "citations": [
            {"reference": c.reference, "call": c.call, "path": c.path, "shown": c.display}
            for c in (rendered.citations if rendered else [])
        ],
        "caveats": rendered.caveats if rendered else [],
        "calls": [
            {"id": c.id, "tool": c.tool, "arguments": c.arguments, "ok": c.ok, "error": c.error}
            for c in run.calls
        ],
        "errors": run.errors if run.status == "failed" else [],
        "model": run.model,
        "latency_ms": run.latency_ms,
        "timing": run.timing(),
        "follows": str(run.follows) if run.follows else None,
    }


def present_stored(row: Any) -> dict[str, Any]:
    """A logged run in the same shape as a fresh answer."""
    trace = row.trace
    citations = trace.get("citations", [])
    return {
        "segments": segments(trace.get("template"), [c["display"] for c in citations]),
        "run_id": str(row.id),
        "question": row.question,
        "created_at": row.created_at.isoformat(),
        "status": row.status,
        "answer": row.answer,
        "citations": [
            {
                "reference": c["reference"],
                "call": c["call"],
                "path": c["path"],
                "shown": c["display"],
            }
            for c in citations
        ],
        "caveats": trace.get("caveats", []),
        "calls": [
            {k: c.get(k) for k in ("id", "tool", "arguments", "ok", "error")}
            for c in trace.get("calls", [])
        ],
        "errors": trace.get("errors", []) if row.status == "failed" else [],
        "model": row.model,
        "latency_ms": row.latency_ms,
        "timing": trace.get("timing"),
        "follows": trace.get("follows"),
    }


@router.get("/runs")
def recent_runs(
    engine: Annotated[Engine, Depends(get_app_engine)],
    org: Org,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    """The latest questions asked, newest first, for reopening an answer without waiting."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT r.id, r.question, r.status, r.created_at, r.latency_ms, r.model"
                " FROM app.assistant_runs r JOIN core.organizations o ON o.id = r.org_id"
                " WHERE o.slug = :org ORDER BY r.created_at DESC LIMIT :limit"
            ),
            {"org": org, "limit": limit},
        ).mappings()
        return {
            "runs": [
                {**dict(r), "id": str(r["id"]), "created_at": r["created_at"].isoformat()}
                for r in rows
            ]
        }


@router.get("/runs/{run_id}")
def stored_run(
    run_id: uuid.UUID, engine: Annotated[Engine, Depends(get_app_engine)], org: Org
) -> dict[str, Any]:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT r.* FROM app.assistant_runs r JOIN core.organizations o"
                " ON o.id = r.org_id WHERE o.slug = :org AND r.id = :id"
            ),
            {"org": org, "id": run_id},
        ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="no such run")
    return present_stored(row)


@router.post("/ask")
def ask_question(
    body: Question,
    engine: Annotated[Engine, Depends(get_app_engine)],
    model: Annotated[ChatModel, Depends(chat_model)],
    org: Org,
) -> dict[str, Any]:
    try:
        history = conversation(engine, org, body.follows) if body.follows else []
        run = ask(
            body.question,
            engine=engine,
            org=org,
            model=model,
            history=history,
            follows=body.follows,
        )
        return present(run)
    except ProviderQuotaExhausted as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
