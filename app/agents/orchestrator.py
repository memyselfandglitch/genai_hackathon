"""
Central orchestrator (ADK LlmAgent): planning, delegation, memory, reflection.

Uses AgentTool wrappers so the root model delegates to specialist sub-agents
(calendar, task, notes, location) in a multi-agent workflow. Additional tools
call BigQuery MCP and a lightweight reflection step before risky operations.
"""

from __future__ import annotations

import os
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext

from app.agents.calendar_agent import create_calendar_agent
from app.agents.location_agent import create_location_agent
from app.agents.notes_agent import create_notes_agent
from app.agents.task_agent import create_task_agent
from app.core.config import get_settings
from app.core.context import get_exec_context
from app.core.logging import get_logger, trace_event
from app.db.memory import LongTermMemory
from app.db.session import get_session_factory
from app.tools.mcp_clients import get_bigquery_mcp, schemas_bundle

logger = get_logger(__name__)


async def load_memory_context_impl(tool_context: ToolContext) -> dict[str, Any]:
    """Injects long-term preferences + recent notes into the reasoning loop."""
    ctx = get_exec_context()
    trace_event(logger, "agent", {"step": "load_memory_context", "user": ctx.user_id})
    factory = get_session_factory()
    async with factory() as session:
        mem = LongTermMemory(session, ctx.user_id)
        text = await mem.summarize_context()
    return {"context": text}


async def bigquery_analytics_impl(query: str, max_rows: int = 50) -> dict[str, Any]:
    """Structured data via BigQuery MCP (mock when not configured)."""
    ctx = get_exec_context()
    trace_event(logger, "tool", {"agent": "orchestrator", "tool": "bigquery", "user": ctx.user_id})
    client = get_bigquery_mcp()
    return await client.call_tool("run_query", {"query": query, "max_rows": max_rows})


async def reflect_on_plan_impl(
    proposed_steps: str,
    tool_context: ToolContext,
) -> dict[str, Any]:
    """
    Reflection loop: quick model self-critique before executing multi-step plans.
    Returns approval + risks; the main agent should adjust if not approved.
    """
    settings = get_settings()
    if not settings.reflection_enabled:
        return {"approved": True, "critique": "Reflection disabled", "risks": []}
    api_key = settings.google_api_key or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"approved": True, "critique": "No API key for standalone reflection call", "risks": []}

    trace_event(logger, "agent", {"step": "reflect_on_plan", "user": get_exec_context().user_id})
    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        prompt = (
            "You are a safety and quality reviewer for an executive assistant plan. "
            "Evaluate the plan briefly. Reply JSON with keys: approved (boolean), "
            "critique (string), risks (array of strings).\nPlan:\n"
            + proposed_steps
        )
        resp = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
        )
        text = (getattr(resp, "text", None) or "").strip()
        if not text and getattr(resp, "candidates", None):
            try:
                parts = resp.candidates[0].content.parts
                text = "".join(getattr(p, "text", "") or "" for p in parts).strip()
            except Exception:
                text = ""
        approved = "true" in text.lower() or "approved" in text.lower()
        return {"approved": approved, "critique": text, "risks": []}
    except Exception as e:
        logger.exception("reflect_on_plan failed")
        return {"approved": True, "critique": f"reflection error: {e}", "risks": ["reflection_failure"]}


def create_orchestrator_agent() -> LlmAgent:
    """
    Root agent: ReAct-style tool loop via ADK, delegating to sub-agents as tools.

    The instruction encodes proactive behavior: conflicts, slots, travel buffers.
    """
    settings = get_settings()
    cal = create_calendar_agent()
    tasks = create_task_agent()
    notes = create_notes_agent()
    loc = create_location_agent()

    schema_ref = schemas_bundle()

    instruction = f"""
You are a proactive executive assistant orchestrator.

Behavior:
- Break the user request into steps. For domain work, delegate using the specialist tools:
  calendar_agent, task_agent, notes_agent, location_agent.
- Before scheduling, use calendar conflict detection when times overlap.
- For off-site meetings, use location_agent to estimate travel time and avoid impossible transitions.
- Use load_memory_context early if you need preferences or recent notes.
- Use bigquery_analytics for quantitative / warehouse questions.
- Call reflect_on_plan when the plan is non-trivial or has scheduling risk.

Proactive suggestions:
- If the user proposes a meeting, check conflicts and suggest alternative slots.
- Mention travel buffer when locations imply consecutive off-site moves.

MCP tool JSON contracts (for reasoning about structured data):
{schema_ref}

Always produce a concise final answer for the user after tools succeed.
"""

    return LlmAgent(
        model=settings.gemini_model,
        name="executive_orchestrator",
        description="Plans and coordinates specialized agents and MCP analytics.",
        instruction=instruction,
        tools=[
            AgentTool(cal),
            AgentTool(tasks),
            AgentTool(notes),
            AgentTool(loc),
            FunctionTool(load_memory_context_impl),
            FunctionTool(bigquery_analytics_impl),
            FunctionTool(reflect_on_plan_impl),
        ],
    )
