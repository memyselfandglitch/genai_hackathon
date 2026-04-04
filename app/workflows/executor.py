"""
Workflow engine: wraps ADK Runner with explicit execution tracing, retries, and outcomes.

Pattern:
  while not complete:
    agent plans next step (inside ADK)
    tools execute
    state updates (session + DB via tools)

The outer API exposes a single `run_turn` that drains the async event stream and
aggregates tool calls for observability.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from google.adk.apps.app import App
from google.adk.errors.already_exists_error import AlreadyExistsError
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types

from app.agents.orchestrator import create_orchestrator_agent
from app.core.config import get_settings
from app.core.context import ExecContext, reset_exec_context, set_exec_context
from app.core.logging import get_logger, trace_event

logger = get_logger(__name__)


@dataclass
class WorkflowResult:
    status: str
    result: str
    actions: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


def _extract_text(content: types.Content | None) -> str:
    if not content or not content.parts:
        return ""
    chunks: list[str] = []
    for p in content.parts:
        if p.text:
            chunks.append(p.text)
    return "\n".join(chunks)


def _collect_parts(event: Any, actions: list[dict[str, Any]], trace: list[dict[str, Any]], debug: bool) -> None:
    c = getattr(event, "content", None)
    if not c or not c.parts:
        return
    for p in c.parts:
        fc = getattr(p, "function_call", None)
        if fc:
            raw = getattr(fc, "args", None) or {}
            try:
                args_dict = dict(raw) if not hasattr(raw, "items") else dict(raw.items())
            except Exception:
                args_dict = {"_raw": str(raw)}
            entry = {
                "type": "function_call",
                "name": fc.name,
                "args": args_dict,
            }
            actions.append(entry)
            if debug:
                trace.append(entry)
        fr = getattr(p, "function_response", None)
        if fr:
            rr = getattr(fr, "response", None) or {}
            try:
                resp_dict = dict(rr) if not hasattr(rr, "items") else dict(rr.items())
            except Exception:
                resp_dict = {"_raw": str(rr)}
            entry = {
                "type": "function_response",
                "name": fr.name,
                "response": resp_dict,
            }
            actions.append(entry)
            if debug:
                trace.append(entry)


async def run_turn(
    user_id: str,
    query: str,
    session_id: Optional[str] = None,
    debug: Optional[bool] = None,
) -> WorkflowResult:
    settings = get_settings()
    debug = settings.debug if debug is None else debug
    session_id = session_id or str(uuid.uuid4())
    app_name = settings.app_name

    root_agent = create_orchestrator_agent()
    session_service = InMemorySessionService()
    # Prefer App(...) so ADK has a proper root_agent container; app_name matches Settings (default "agents").
    adk_app = App(name=app_name, root_agent=root_agent)
    runner = Runner(
        app=adk_app,
        session_service=session_service,
    )

    ctx = ExecContext(
        user_id=user_id,
        session_id=session_id,
        debug=debug,
    )
    token = set_exec_context(ctx)

    actions: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    final_text = ""
    status = "ok"
    last_error: Optional[str] = None

    try:
        try:
            await session_service.create_session(
                app_name=app_name,
                user_id=user_id,
                session_id=session_id,
                state={"user_id": user_id},
            )
        except AlreadyExistsError:
            logger.debug("Session %s already exists for user %s", session_id, user_id)

        user_message = types.Content(role="user", parts=[types.Part(text=query)])
        max_retries = 2
        active_session_id = session_id

        for attempt in range(1, max_retries + 1):
            if attempt > 1:
                # Fresh session on retry so we do not duplicate user turns in history.
                active_session_id = f"{session_id}-retry-{attempt}"
                try:
                    await session_service.create_session(
                        app_name=app_name,
                        user_id=user_id,
                        session_id=active_session_id,
                        state={"user_id": user_id},
                    )
                except AlreadyExistsError:
                    pass
            try:
                async for event in runner.run_async(
                    user_id=user_id,
                    session_id=active_session_id,
                    new_message=user_message,
                ):
                    if debug:
                        trace_event(
                            logger,
                            "event",
                            {
                                "author": getattr(event, "author", ""),
                                "id": getattr(event, "id", ""),
                            },
                        )
                        t_prev = _extract_text(getattr(event, "content", None))
                        trace.append(
                            {
                                "type": "event",
                                "author": getattr(event, "author", ""),
                                "event_id": getattr(event, "id", ""),
                                "text_preview": (t_prev[:800] + "…") if len(t_prev) > 800 else t_prev,
                            }
                        )
                    _collect_parts(event, actions, trace, debug)
                    t = _extract_text(getattr(event, "content", None))
                    if t:
                        final_text = t
                break
            except Exception as e:
                last_error = str(e)
                logger.exception("run_async failure attempt %s", attempt)
                trace_event(logger, "failure", {"attempt": attempt, "error": last_error})
                if attempt == max_retries:
                    status = "error"
                    return WorkflowResult(
                        status=status,
                        result="",
                        actions=actions,
                        trace=trace,
                        error=last_error,
                    )
                await asyncio.sleep(0.2 * attempt)

        return WorkflowResult(
            status=status,
            result=final_text or "(no text response)",
            actions=actions,
            trace=trace,
        )
    finally:
        reset_exec_context(token)
