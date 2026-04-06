"""
ADK Cloud Run / Agent Engine entry: `adk deploy cloud_run` expects `root_agent` in this module.

The full FastAPI app (`app.main:app`) is unchanged; use that for the built-in UI and POST /query.
"""

from __future__ import annotations

from app.agents.orchestrator import create_orchestrator_agent

root_agent = create_orchestrator_agent()
