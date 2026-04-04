"""FastAPI application entry."""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager

from app.env_bootstrap import load_backend_env

# Must run before imports that transitively load google.adk / google.genai.
load_backend_env()

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import init_db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    if sys.version_info < (3, 10):
        logger.warning(
            "Python %s.%s — use 3.10+ for the official MCP SDK (PyPI `mcp`). "
            "On older Python, BigQuery/Maps use built-in mocks or HTTP adapters.",
            sys.version_info.major,
            sys.version_info.minor,
        )
    settings = get_settings()
    if settings.google_api_key:
        # Always set so .env wins over empty shell vars; genai reads this at client use.
        os.environ["GOOGLE_API_KEY"] = settings.google_api_key
        logger.info(
            "Gemini API key loaded from config (%s characters).",
            len(settings.google_api_key),
        )
    else:
        logger.warning(
            "No GOOGLE_API_KEY in settings — POST /query will fail until backend/.env is set."
        )
    await init_db()
    yield


app = FastAPI(
    title="Executive Assistant",
    description="Multi-agent orchestration with ADK, MCP, and AlloyDB-compatible storage.",
    lifespan=lifespan,
)
app.include_router(router)

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if _FRONTEND_DIR.is_dir():
    app.mount(
        "/ui",
        StaticFiles(directory=str(_FRONTEND_DIR), html=True),
        name="ui",
    )


@app.get("/")
async def root():
    if _FRONTEND_DIR.is_dir():
        return RedirectResponse(url="/ui/")
    return {"service": "executive-assistant", "docs": "/docs", "ui": "/ui/"}
