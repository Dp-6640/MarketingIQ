"""The assistant endpoint: one question in, one answer out (single-turn in the MVP)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Engine

from marketingiq.api.routes_analytics import Org
from marketingiq.assistant.llm import ChatModel, ModelNotConfigured, get_chat_model
from marketingiq.assistant.run import Run, ask
from marketingiq.db import get_app_engine

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


def chat_model() -> ChatModel:
    try:
        return get_chat_model()
    except ModelNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


def present(run: Run) -> dict[str, Any]:
    rendered = run.rendered
    return {
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
    }


@router.post("/ask")
def ask_question(
    body: Question,
    engine: Annotated[Engine, Depends(get_app_engine)],
    model: Annotated[ChatModel, Depends(chat_model)],
    org: Org,
) -> dict[str, Any]:
    return present(ask(body.question, engine=engine, org=org, model=model))
