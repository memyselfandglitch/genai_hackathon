"""High-value workflow for proactive day planning and execution support."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any, Optional

from sqlalchemy import nulls_last, select

from app.core.context import get_exec_context
from app.core.logging import get_logger, trace_event
from app.db.memory import LongTermMemory
from app.db.models import Event, Note, Task, UserPreference
from app.db.session import get_session_factory
from app.tools.mcp_clients import get_maps_mcp

logger = get_logger(__name__)


def _parse_day(day_iso: Optional[str]) -> datetime.date:
    if not day_iso:
        return datetime.utcnow().date()
    normalized = day_iso.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        return datetime.fromisoformat(f"{normalized}T00:00:00").date()


def _compute_focus_slots(
    day: datetime.date,
    windows: list[dict[str, str]],
    busy: list[Event],
    duration_minutes: int,
) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for window in windows:
        hs, ms = map(int, window["start"].split(":"))
        he, me = map(int, window["end"].split(":"))
        cursor = datetime.combine(day, time(hs, ms))
        window_end = datetime.combine(day, time(he, me))
        while cursor + timedelta(minutes=duration_minutes) <= window_end and len(slots) < 4:
            slot_end = cursor + timedelta(minutes=duration_minutes)
            overlap = any(event.start_at < slot_end and event.end_at > cursor for event in busy)
            if not overlap:
                slots.append({"start": cursor.isoformat(), "end": slot_end.isoformat()})
            cursor += timedelta(minutes=30)
    return slots


async def build_daily_brief_impl(
    day_iso: Optional[str] = None,
    focus_block_minutes: int = 90,
) -> dict[str, Any]:
    """
    Chief-of-staff workflow:
    combines calendar, tasks, notes, preferences, and travel checks into one brief.
    """
    ctx = get_exec_context()
    target_day = _parse_day(day_iso)
    trace_event(
        logger,
        "workflow",
        {"name": "daily_brief", "user": ctx.user_id, "day": target_day.isoformat()},
    )

    factory = get_session_factory()
    async with factory() as session:
        mem = LongTermMemory(session, ctx.user_id)
        pref = await mem.get_preferences()

        day_start = datetime.combine(target_day, time(0, 0))
        day_end = day_start + timedelta(days=1)

        events_result = await session.execute(
            select(Event)
            .where(Event.user_id == ctx.user_id, Event.start_at >= day_start, Event.start_at < day_end)
            .order_by(Event.start_at.asc())
        )
        events = list(events_result.scalars().all())

        tasks_result = await session.execute(
            select(Task)
            .where(Task.user_id == ctx.user_id, Task.status == "open")
            .order_by(Task.priority.asc(), nulls_last(Task.due_at.asc()))
            .limit(5)
        )
        tasks = list(tasks_result.scalars().all())

        notes_result = await session.execute(
            select(Note).where(Note.user_id == ctx.user_id).order_by(Note.created_at.desc()).limit(3)
        )
        notes = list(notes_result.scalars().all())

        windows = (
            pref.preferred_meeting_windows
            if pref and pref.preferred_meeting_windows
            else [{"start": "09:00", "end": "12:00"}, {"start": "13:00", "end": "17:00"}]
        )
        buffer_minutes = pref.buffer_minutes_between_meetings if pref else 15
        focus_slots = _compute_focus_slots(target_day, windows, events, focus_block_minutes)

        travel_alerts: list[dict[str, Any]] = []
        maps = get_maps_mcp()
        for previous, current in zip(events, events[1:]):
            if not previous.location or not current.location:
                continue
            if previous.location.lower() == current.location.lower():
                continue
            if "zoom" in previous.location.lower() or "zoom" in current.location.lower():
                continue
            route = await maps.call_tool(
                "compute_route",
                {
                    "origin": previous.location,
                    "destination": current.location,
                    "mode": "driving",
                    "departure_time": previous.end_at.isoformat(),
                },
            )
            gap_minutes = max(0, int((current.start_at - previous.end_at).total_seconds() // 60))
            travel_minutes = int((route.get("duration_seconds") or 0) // 60)
            if travel_minutes + buffer_minutes > gap_minutes:
                travel_alerts.append(
                    {
                        "from_event": previous.title,
                        "to_event": current.title,
                        "gap_minutes": gap_minutes,
                        "estimated_travel_minutes": travel_minutes,
                        "route_summary": route.get("summary"),
                    }
                )

        note_highlights = [
            {
                "title": n.title or "untitled",
                "snippet": (n.body or "")[:180],
            }
            for n in notes
        ]
        priority_tasks = [
            {
                "title": task.title,
                "priority": task.priority,
                "due_at": task.due_at.isoformat() if task.due_at else None,
            }
            for task in tasks
        ]
        meetings = [
            {
                "title": event.title,
                "start_at": event.start_at.isoformat(),
                "end_at": event.end_at.isoformat(),
                "location": event.location,
            }
            for event in events
        ]

        summary_parts = [
            f"{len(events)} meetings on {target_day.isoformat()}",
            f"{len(priority_tasks)} priority tasks",
        ]
        if focus_slots:
            summary_parts.append(f"{len(focus_slots)} focus slot options")
        if travel_alerts:
            summary_parts.append(f"{len(travel_alerts)} travel risk alerts")
        summary = "; ".join(summary_parts)

        payload = {
            "workflow": "daily_brief",
            "day": target_day.isoformat(),
            "meetings": meetings,
            "priority_tasks": priority_tasks,
            "focus_slots": focus_slots,
            "travel_alerts": travel_alerts,
            "note_highlights": note_highlights,
            "buffer_minutes": buffer_minutes,
            "summary": summary,
        }
        await mem.record_workflow(
            workflow_name="daily_brief",
            status="ok",
            summary=summary,
            input_json={"day_iso": target_day.isoformat(), "focus_block_minutes": focus_block_minutes},
            output_json=payload,
        )
        await session.commit()
        return payload
