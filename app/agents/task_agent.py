"""Task sub-agent: CRUD, prioritization, and behavior hints for personalization."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from google.adk.agents import LlmAgent
from google.adk.tools.function_tool import FunctionTool
from sqlalchemy import nulls_last, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.context import get_exec_context
from app.core.logging import get_logger, trace_event
from app.db.models import Task, UserPreference
from app.db.session import get_session_factory

logger = get_logger(__name__)


async def list_tasks_impl(status: Optional[str] = None) -> dict[str, Any]:
    ctx = get_exec_context()
    trace_event(logger, "tool", {"agent": "task", "tool": "list_tasks", "user": ctx.user_id})
    factory = get_session_factory()
    async with factory() as session:
        q = select(Task).where(Task.user_id == ctx.user_id)
        if status:
            q = q.where(Task.status == status)
        q = q.order_by(Task.priority.asc(), nulls_last(Task.due_at.asc()))
        r = await session.execute(q)
        tasks = r.scalars().all()
        return {
            "tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "status": t.status,
                    "priority": t.priority,
                    "due_at": t.due_at.isoformat() if t.due_at else None,
                }
                for t in tasks
            ]
        }


async def upsert_task_impl(
    title: str,
    status: str = "open",
    priority: int = 3,
    due_iso: Optional[str] = None,
    description: Optional[str] = None,
    task_id: Optional[str] = None,
) -> dict[str, Any]:
    ctx = get_exec_context()
    trace_event(logger, "tool", {"agent": "task", "tool": "upsert_task", "user": ctx.user_id})
    factory = get_session_factory()
    async with factory() as session:
        due = datetime.fromisoformat(due_iso.replace("Z", "+00:00")) if due_iso else None
        if task_id:
            r = await session.execute(select(Task).where(Task.id == task_id, Task.user_id == ctx.user_id))
            t = r.scalar_one_or_none()
            if not t:
                return {"error": "task not found"}
            t.title = title
            t.status = status
            t.priority = priority
            t.due_at = due
            if description is not None:
                t.description = description
        else:
            t = Task(
                user_id=ctx.user_id,
                title=title,
                status=status,
                priority=priority,
                due_at=due,
                description=description,
            )
            session.add(t)
        await _touch_behavior(session, ctx.user_id)
        await session.commit()
        return {"status": "ok", "id": t.id}


async def _touch_behavior(session: AsyncSession, user_id: str) -> None:
    r = await session.execute(select(UserPreference).where(UserPreference.user_id == user_id))
    p = r.scalar_one_or_none()
    if not p:
        p = UserPreference(user_id=user_id, behavior_stats={})
        session.add(p)
        await session.flush()
    stats = dict(p.behavior_stats or {})
    stats["task_write"] = int(stats.get("task_write", 0)) + 1
    p.behavior_stats = stats


async def prioritize_tasks_impl() -> dict[str, Any]:
    """Rank open tasks by priority then due date (deterministic)."""
    ctx = get_exec_context()
    factory = get_session_factory()
    async with factory() as session:
        r = await session.execute(
            select(Task)
            .where(Task.user_id == ctx.user_id, Task.status == "open")
            .order_by(Task.priority.asc(), nulls_last(Task.due_at.asc()))
        )
        tasks = list(r.scalars().all())
    ordered = [{"id": t.id, "title": t.title, "priority": t.priority} for t in tasks]
    return {"ordered": ordered}


def create_task_agent() -> LlmAgent:
    settings = get_settings()
    return LlmAgent(
        model=settings.gemini_model,
        name="task_agent",
        description="Manages user tasks: list, create/update, and prioritize work.",
        instruction="You are the task manager. Use tools to persist changes. Prefer clear titles and realistic priorities (1=urgent).",
        tools=[
            FunctionTool(list_tasks_impl),
            FunctionTool(upsert_task_impl),
            FunctionTool(prioritize_tasks_impl),
        ],
    )
