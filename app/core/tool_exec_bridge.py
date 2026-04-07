"""Optional ADK tool callbacks (currently unused with FastAPI).

``POST /query`` uses :func:`app.workflows.executor.run_turn`, which calls
``set_exec_context()`` for the whole turn. That context propagates to nested
``AgentTool`` runs, so ``before_tool_callback`` / ``after_tool_callback`` are
not required and some ADK versions mishandle callback signatures.

If you run ``adk deploy cloud_run`` **without** this FastAPI executor, you may
need to wire ``ExecContext`` again (e.g. re-attach these callbacks on the root
``LlmAgent`` after verifying your ADK version's callback keyword names).
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


def _extract_tool_context(
    tool_context: Optional[ToolContext] = None,
    callback_context: Any = None,
    **kwargs: Any,
) -> Optional[ToolContext]:
    """Accept both canonical and plugin-style ADK callback argument shapes."""
    if tool_context is not None:
        return tool_context
    if isinstance(callback_context, ToolContext):
        return callback_context
    maybe_tool_context = kwargs.get("tool_context")
    if isinstance(maybe_tool_context, ToolContext):
        return maybe_tool_context
    maybe_callback_context = kwargs.get("callback_context")
    if isinstance(maybe_callback_context, ToolContext):
        return maybe_callback_context
    return None


async def adk_before_tool(
    *,
    tool: Any = None,
    args: Optional[dict[str, Any]] = None,
    tool_args: Optional[dict[str, Any]] = None,
    tool_context: Optional[ToolContext] = None,
    callback_context: Any = None,
    **kwargs: Any,
) -> Optional[dict[str, Any]]:
    """Compatible with both older and newer ADK callback keyword names."""
    del tool, args, tool_args
    tool_context = _extract_tool_context(
        tool_context=tool_context,
        callback_context=callback_context,
        **kwargs,
    )
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


async def adk_after_tool(
    *,
    tool: Any = None,
    args: Optional[dict[str, Any]] = None,
    tool_args: Optional[dict[str, Any]] = None,
    tool_context: Optional[ToolContext] = None,
    callback_context: Any = None,
    tool_response: Optional[dict[str, Any]] = None,
    result: Optional[dict[str, Any]] = None,
    **kwargs: Any,
) -> Optional[dict[str, Any]]:
    """Compatible with both canonical and plugin-style ADK callback signatures."""
    del tool, args, tool_args, tool_context, callback_context, tool_response, result, kwargs
    stack = _get_stack()
    if not stack:
        return None
    tok = stack.pop()
    if tok is not None:
        reset_exec_context(tok)
    return None


async def adk_on_tool_error(
    *,
    tool: Any = None,
    args: Optional[dict[str, Any]] = None,
    tool_args: Optional[dict[str, Any]] = None,
    tool_context: Optional[ToolContext] = None,
    callback_context: Any = None,
    error: Optional[Exception] = None,
    **kwargs: Any,
) -> Optional[dict[str, Any]]:
    """Compatible with both canonical and plugin-style ADK error callbacks."""
    del tool, args, tool_args, tool_context, callback_context, error, kwargs
    stack = _get_stack()
    if not stack:
        return None
    tok = stack.pop()
    if tok is not None:
        reset_exec_context(tok)
    return None
