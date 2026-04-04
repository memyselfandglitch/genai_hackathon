"""
Calendar sub-agent: scheduling, conflict detection, proactive slot suggestions.

Coordination: exposed as an ADK LlmAgent with domain tools. The model delegates
here when the user intent involves calendars. Tools persist to AlloyDB/SQLite.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any, Optional

from google.adk.agents import LlmAgent
from google.adk.tools.function_tool import FunctionTool
from sqlalchemy import select

from app.core.config import get_settings
from app.core.context import get_exec_context
from app.core.logging import get_logger, trace_event
from app.db.models import Event, UserPreference
from app.db.session import get_session_factory

logger = get_logger(__name__)


async def list_events_impl(
    start_iso: str,
    end_iso: str,
) -> dict[str, Any]:
    ctx = get_exec_context()
    trace_event(logger, "tool", {"agent": "calendar", "tool": "list_events", "user": ctx.user_id})
    start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    end = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    factory = get_session_factory()
    async with factory() as session:
        r = await session.execute(
            select(Event)
            .where(Event.user_id == ctx.user_id, Event.start_at < end, Event.end_at > start)
            .order_by(Event.start_at)
        )
        rows = r.scalars().all()
        return {
            "events": [
                {
                    "id": e.id,
                    "title": e.title,
                    "start_at": e.start_at.isoformat(),
                    "end_at": e.end_at.isoformat(),
                    "location": e.location,
                }
                for e in rows
            ]
        }


async def create_event_impl(
    title: str,
    start_iso: str,
    end_iso: str,
    location: Optional[str] = None,
) -> dict[str, Any]:
    ctx = get_exec_context()
    trace_event(logger, "tool", {"agent": "calendar", "tool": "create_event", "user": ctx.user_id})
    start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    end = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    factory = get_session_factory()
    async with factory() as session:
        ev = Event(user_id=ctx.user_id, title=title, start_at=start, end_at=end, location=location)
        session.add(ev)
        await session.commit()
        return {"status": "created", "id": ev.id}


async def detect_conflicts_impl(
    start_iso: str,
    end_iso: str,
) -> dict[str, Any]:
    ctx = get_exec_context()
    start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    end = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    factory = get_session_factory()
    async with factory() as session:
        r = await session.execute(
            select(Event).where(
                Event.user_id == ctx.user_id,
                Event.start_at < end,
                Event.end_at > start,
            )
        )
        conflicts = r.scalars().all()
        return {
            "has_conflict": len(conflicts) > 0,
            "conflicts": [
                {"id": c.id, "title": c.title, "start_at": c.start_at.isoformat(), "end_at": c.end_at.isoformat()}
                for c in conflicts
            ],
        }


async def suggest_slots_impl(
    day_iso: str,
    duration_minutes: int = 60,
) -> dict[str, Any]:
    """
    Suggest slots using user preferences (preferred windows) and existing events.
    Location-aware scheduling is enhanced when `travel_from_previous` is used upstream.
    """
    ctx = get_exec_context()
    day = datetime.fromisoformat(day_iso.replace("Z", "+00:00")).date()
    factory = get_session_factory()
    async with factory() as session:
        pref = (
            await session.execute(select(UserPreference).where(UserPreference.user_id == ctx.user_id))
        ).scalar_one_or_none()
        buffer = pref.buffer_minutes_between_meetings if pref else 15
        windows = pref.preferred_meeting_windows if pref and pref.preferred_meeting_windows else [
            {"start": "09:00", "end": "12:00"},
            {"start": "13:00", "end": "17:00"},
        ]
        day_start = datetime.combine(day, time(0, 0))
        day_end = day_start + timedelta(days=1)
        r = await session.execute(
            select(Event)
            .where(Event.user_id == ctx.user_id, Event.start_at >= day_start, Event.start_at < day_end)
            .order_by(Event.start_at)
        )
        busy = list(r.scalars().all())

    suggestions: list[dict[str, Any]] = []
    for w in windows:
        hs, ms = map(int, w["start"].split(":"))
        he, me = map(int, w["end"].split(":"))
        cursor = datetime.combine(day, time(hs, ms))
        window_end = datetime.combine(day, time(he, me))
        while cursor + timedelta(minutes=duration_minutes) <= window_end and len(suggestions) < 5:
            slot_end = cursor + timedelta(minutes=duration_minutes)
            overlap = False
            for b in busy:
                if b.start_at < slot_end and b.end_at > cursor:
                    overlap = True
                    break
            if not overlap:
                suggestions.append(
                    {
                        "start": cursor.isoformat(),
                        "end": slot_end.isoformat(),
                        "buffer_applied_minutes": buffer,
                    }
                )
            cursor += timedelta(minutes=30)
    return {"suggested_slots": suggestions, "buffer_minutes": buffer}


def create_calendar_agent() -> LlmAgent:
    settings = get_settings()
    return LlmAgent(
        model=settings.gemini_model,
        name="calendar_agent",
        description=(
            "Handles calendar events: list, create, detect conflicts, and suggest optimal slots "
            "using user preferences."
        ),
        instruction=(
            "You are the calendar specialist. Use tools to read/write events. "
            "Always call detect_conflicts before creating overlapping meetings. "
            "Proactively suggest_slots when the user asks for availability."
        ),
        tools=[
            FunctionTool(list_events_impl),
            FunctionTool(create_event_impl),
            FunctionTool(detect_conflicts_impl),
            FunctionTool(suggest_slots_impl),
        ],
    )
