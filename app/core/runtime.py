"""Runtime capability flags (Python version, optional MCP SDK)."""

from __future__ import annotations

import sys


def python_supports_mcp_sdk() -> bool:
    return sys.version_info >= (3, 10)


def mcp_package_available() -> bool:
    if not python_supports_mcp_sdk():
        return False
    try:
        import mcp  # noqa: F401
    except ImportError:
        return False
    return True
