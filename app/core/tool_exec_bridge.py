"""Bind ExecContext during ADK tool calls (e.g. `adk deploy cloud_run`) when FastAPI middleware is absent."""

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


async def adk_before_tool(_tool: Any, _args: dict[str, Any], tool_context: ToolContext) -> None:
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
    _tool: Any,
    _args: dict[str, Any],
    _tool_context: ToolContext,
    _result: dict,
) -> None:
    stack = _get_stack()
    if not stack:
        return None
    tok = stack.pop()
    if tok is not None:
        reset_exec_context(tok)
    return None


async def adk_on_tool_error(
    _tool: Any,
    _args: dict[str, Any],
    _tool_context: ToolContext,
    _err: Exception,
) -> None:
    stack = _get_stack()
    if not stack:
        return None
    tok = stack.pop()
    if tok is not None:
        reset_exec_context(tok)
    return None
