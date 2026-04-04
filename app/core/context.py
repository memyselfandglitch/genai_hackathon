"""Request-scoped execution context for tools (DB session, user, flags)."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Optional

ExecContextVar: ContextVar[Optional["ExecContext"]] = ContextVar("exec_context", default=None)


@dataclass
class ExecContext:
    """Bound for the duration of a single /query invocation."""

    user_id: str
    session_id: str
    debug: bool


def get_exec_context() -> ExecContext:
    ctx = ExecContextVar.get()
    if ctx is None:
        raise RuntimeError("ExecContext not set — bug in middleware wiring")
    return ctx


def set_exec_context(ctx: ExecContext) -> Token:
    return ExecContextVar.set(ctx)


def reset_exec_context(token: Token) -> None:
    ExecContextVar.reset(token)
