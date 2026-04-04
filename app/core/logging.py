"""Structured logging and trace helpers for agents, tools, and workflows."""

import json
import logging
import sys
from typing import Any

from app.core.config import get_settings, log_level


def setup_logging() -> None:
    settings = get_settings()
    level = getattr(logging, log_level())
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            )
        )
        root.addHandler(h)

    # Quiet noisy third-party loggers unless debug
    if not settings.debug:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def trace_event(logger: logging.Logger, kind: str, payload: dict[str, Any]) -> None:
    """JSON-serializable trace line for observability (agent decision / tool / failure)."""
    try:
        line = json.dumps({"kind": kind, **payload}, default=str)
    except Exception:
        line = json.dumps({"kind": kind, "error": "non-serializable payload"})
    logger.info("TRACE %s", line)
