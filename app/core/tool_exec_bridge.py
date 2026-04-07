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


def _tool_context_from_kwargs(kwargs: dict[str, Any]) -> Optional[ToolContext]:
    raw = kwargs.get("tool_context")
    return raw if isinstance(raw, ToolContext) else None


async def adk_before_tool(**kwargs: Any) -> Any:
    """ADK may call with tool=, args=, tool_context= (agent) or tool_args= (plugins); accept all via kwargs."""
    tool_context = _tool_context_from_kwargs(kwargs)
    if tool_context is None:
        return None
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


async def adk_after_tool(**kwargs: Any) -> Any:
    del kwargs
    stack = _get_stack()
    if not stack:
        return None
    tok = stack.pop()
    if tok is not None:
        reset_exec_context(tok)
    return None


async def adk_on_tool_error(**kwargs: Any) -> Any:
    del kwargs
    stack = _get_stack()
    if not stack:
        return None
    tok = stack.pop()
    if tok is not None:
        reset_exec_context(tok)
    return None
