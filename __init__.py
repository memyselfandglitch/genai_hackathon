"""Marks the deploy folder as a package for ADK (`from . import agent` in layout checks)."""

from . import agent

__all__ = ["agent"]
