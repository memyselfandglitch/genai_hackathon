"""FastAPI routes."""

from __future__ import annotations

import sys
from typing import Any, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import get_settings
from app.core.runtime import mcp_package_available, python_supports_mcp_sdk
from app.db.session import get_session_factory
from app.db.models import User
from app.workflows.executor import run_turn

router = APIRouter()


class QueryRequest(BaseModel):
    user_id: str = Field(..., description="Stable user identifier")
    query: str = Field(..., min_length=1)


class QueryResponse(BaseModel):
    status: str
    actions: list[dict[str, Any]]
    result: str
    trace: Optional[list[dict[str, Any]]] = None
    error: Optional[str] = None


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/meta")
async def api_meta() -> dict[str, Any]:
    """Runtime info for the debug UI and operators."""
    s = get_settings()
    return {
        "product": "executive-assistant",
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "python_ok_for_mcp_sdk": python_supports_mcp_sdk(),
        "mcp_package_installed": mcp_package_available(),
        "adk_app_name": s.app_name,
        "gemini_model": s.gemini_model,
        "note": "Default ADK app_name is 'agents' to align with stock LlmAgent origin in google.adk.agents.",
    }


@router.post("/query", response_model=QueryResponse)
async def query_endpoint(
    body: QueryRequest,
    debug: bool = Query(False, description="Include execution trace (same as DEBUG=true)"),
) -> QueryResponse:
    settings = get_settings()
    dbg = debug or settings.debug
    factory = get_session_factory()
    async with factory() as session:
        r = await session.execute(select(User).where(User.id == body.user_id))
        if r.scalar_one_or_none() is None:
            session.add(User(id=body.user_id))
            await session.commit()

    out = await run_turn(user_id=body.user_id, query=body.query, debug=dbg)
    return QueryResponse(
        status=out.status,
        actions=out.actions,
        result=out.result,
        trace=out.trace if dbg else None,
        error=out.error,
    )
