"""FastAPI routes."""

from __future__ import annotations

import sys
from typing import Any, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import get_settings
from app.core.runtime import mcp_package_available, python_supports_mcp_sdk
from app.db.models import ConversationTurn, User, WorkflowRun
from app.db.session import get_session_factory
from app.workflows.executor import run_turn

router = APIRouter()


class QueryRequest(BaseModel):
    user_id: str = Field(..., description="Stable user identifier")
    session_id: Optional[str] = Field(default=None, description="Stable conversation identifier")
    query: str = Field(..., min_length=1)


class QueryResponse(BaseModel):
    status: str
    session_id: str
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
        "google_workspace_connected": bool(s.google_workspace_access_token),
        "google_calendar_mode": "mcp" if s.mcp_calendar_sse_url else ("rest" if s.google_workspace_access_token else "mock"),
        "google_tasks_mode": "mcp" if s.mcp_tasks_sse_url else ("rest" if s.google_workspace_access_token else "mock"),
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

    out = await run_turn(
        user_id=body.user_id,
        query=body.query,
        session_id=body.session_id,
        debug=dbg,
    )
    return QueryResponse(
        status=out.status,
        session_id=body.session_id or f"{body.user_id}-primary",
        actions=out.actions,
        result=out.result,
        trace=out.trace if dbg else None,
        error=out.error,
    )


@router.get("/api/users/{user_id}/memory")
async def user_memory(user_id: str, limit: int = Query(5, ge=1, le=20)) -> dict[str, Any]:
    """Inspect persisted conversation and workflow memory for demos/debugging."""
    factory = get_session_factory()
    async with factory() as session:
        turns = (
            await session.execute(
                select(ConversationTurn)
                .where(ConversationTurn.user_id == user_id)
                .order_by(ConversationTurn.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        workflows = (
            await session.execute(
                select(WorkflowRun)
                .where(WorkflowRun.user_id == user_id)
                .order_by(WorkflowRun.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()

    return {
        "user_id": user_id,
        "conversation_turns": [
            {
                "session_id": turn.session_id,
                "user_message": turn.user_message,
                "assistant_message": turn.assistant_message,
                "status": turn.status,
                "error": turn.error,
                "created_at": turn.created_at.isoformat(),
            }
            for turn in turns
        ],
        "workflow_runs": [
            {
                "workflow_name": run.workflow_name,
                "status": run.status,
                "summary": run.summary,
                "created_at": run.created_at.isoformat(),
            }
            for run in workflows
        ],
    }
