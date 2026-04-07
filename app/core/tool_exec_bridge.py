"""Bind ExecContext during ADK tool calls when the outer FastAPI ExecContext is missing (e.g. isolated runners).

ADK invokes before/after tool callbacks like ``callback(tool=..., args=..., tool_context=...)`` and types them as
positional ``(BaseTool, dict, ToolContext)``. Use the same parameter names (not ``_tool`` / ``_args``).
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any, Optional

from google.adk.tools.tool_context import ToolContext

from app.core.config import get_settings
from app.core.context import ExecContext, ExecContextVar, reset_exec_context, set_exec_context

_stack: ContextVar[Optional[list[Optional[Token]]]] = ContextVar("tool_exec_token_stack", default=None)


def _get_stack() -> list[Optional[Token]]:
    s = _stack.get()
    if s is None:
        s = []
        _stack.set(s)
    return s


async def adk_before_tool(
    tool: Any,
    args: dict[str, Any],
    tool_context: ToolContext,
) -> Optional[dict[str, Any]]:
    del tool, args
    if ExecContextVar.get() is not None:
        _get_stack().append(None)
        return None
    sess = tool_context.session
    tok = set_exec_context(
        ExecContext(
            user_id=sess.user_id,
            session_id=sess.id,
            debug=get_settings().debug,
        )
    )
    _get_stack().append(tok)
    return None


async def adk_after_tool(
    tool: Any,
    args: dict[str, Any],
    tool_context: ToolContext,
    tool_response: dict,
) -> Optional[dict[str, Any]]:
    del tool, args, tool_context, tool_response
    stack = _get_stack()
    if not stack:
        return None
    tok = stack.pop()
    if tok is not None:
        reset_exec_context(tok)
    return None


async def adk_on_tool_error(
    tool: Any,
    args: dict[str, Any],
    tool_context: ToolContext,
    error: Exception,
) -> Optional[dict[str, Any]]:
    del tool, args, tool_context, error
    stack = _get_stack()
    if not stack:
        return None
    tok = stack.pop()
    if tok is not None:
        reset_exec_context(tok)
    return None
