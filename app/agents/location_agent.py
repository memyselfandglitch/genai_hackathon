"""
Location sub-agent: travel time and routing via Maps MCP (mock or live).

Feeds calendar decisions: add travel buffer when scheduling back-to-back off-site.
"""

from __future__ import annotations

from typing import Any, Optional

from google.adk.agents import LlmAgent
from google.adk.tools.function_tool import FunctionTool
from sqlalchemy import select

from app.core.config import get_settings
from app.core.context import get_exec_context
from app.core.tool_exec_bridge import adk_after_tool, adk_before_tool, adk_on_tool_error
from app.core.logging import get_logger, trace_event
from app.db.models import User
from app.db.session import get_session_factory
from app.tools.mcp_clients import get_maps_mcp

logger = get_logger(__name__)


async def compute_route_impl(
    origin: str,
    destination: str,
    mode: str = "driving",
    departure_time_iso: Optional[str] = None,
) -> dict[str, Any]:
    ctx = get_exec_context()
    trace_event(logger, "tool", {"agent": "location", "tool": "compute_route", "user": ctx.user_id})
    mcp = get_maps_mcp()
    args = {"origin": origin, "destination": destination, "mode": mode}
    if departure_time_iso:
        args["departure_time"] = departure_time_iso
    result = await mcp.call_tool("compute_route", args)
    return result


async def travel_from_home_impl(destination: str, mode: str = "driving") -> dict[str, Any]:
    """Uses user's stored home address when available."""
    ctx = get_exec_context()
    factory = get_session_factory()
    async with factory() as session:
        r = await session.execute(select(User).where(User.id == ctx.user_id))
        u = r.scalar_one_or_none()
        origin = (u.home_address if u else None) or "current location"
    return await compute_route_impl(origin, destination, mode=mode)


def create_location_agent() -> LlmAgent:
    settings = get_settings()
    return LlmAgent(
        model=settings.gemini_model,
        name="location_agent",
        before_tool_callback=adk_before_tool,
        after_tool_callback=adk_after_tool,
        on_tool_error_callback=adk_on_tool_error,
        description="Computes routes and travel times using Google Maps MCP tools.",
        instruction=(
            "You translate addresses into travel durations. "
            "When the user schedules meetings, combine your output with calendar_agent "
            "to avoid impossible back-to-back off-site moves."
        ),
        tools=[
            FunctionTool(compute_route_impl),
            FunctionTool(travel_from_home_impl),
        ],
    )
