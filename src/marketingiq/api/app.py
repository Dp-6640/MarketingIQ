"""FastAPI application."""

import logging
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from marketingiq import __version__
from marketingiq.api.routes_analytics import router as analytics_router
from marketingiq.api.routes_assistant import router as assistant_router
from marketingiq.db import get_app_engine

logger = logging.getLogger(__name__)
DEMO_PAGE = Path(__file__).with_name("static") / "index.html"

app = FastAPI(title="MarketingIQ", version=__version__)
app.include_router(analytics_router)
app.include_router(assistant_router)


@app.exception_handler(LookupError)
def not_found(request: Request, exc: LookupError) -> JSONResponse:
    """An unknown organization, or one with no data or no build yet."""
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.get("/", include_in_schema=False)
def demo_page() -> FileResponse:
    """A minimal page for demonstrating the assistant (docs/assistant.md)."""
    return FileResponse(DEMO_PAGE, media_type="text/html")


class HealthResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    database: Literal["ok", "error"]
    version: str


@app.get("/health", response_model=HealthResponse)
def health(
    response: Response, engine: Annotated[Engine, Depends(get_app_engine)]
) -> HealthResponse:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError:
        # Details go to the log only; the response never exposes connection info.
        logger.exception("Health check: database unreachable")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="unavailable", database="error", version=__version__)
    return HealthResponse(status="ok", database="ok", version=__version__)
