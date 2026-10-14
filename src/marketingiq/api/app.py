"""FastAPI application."""

import logging
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Response, status
from pydantic import BaseModel
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from marketingiq import __version__
from marketingiq.db import get_app_engine

logger = logging.getLogger(__name__)

app = FastAPI(title="MarketingIQ", version=__version__)


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
