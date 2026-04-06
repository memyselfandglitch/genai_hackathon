"""
Populate process env from backend/.env BEFORE google.genai / ADK are imported.

ADK reads GOOGLE_API_KEY when its HTTP client is first used; if routes are imported
first, lifespan runs too late. This module must be imported as the first app
dependency from main.py.
"""

from __future__ import annotations

import os
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent


def _strip_val(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
        return v[1:-1].strip()
    return v


def load_backend_env() -> None:
    path = _BACKEND_DIR / ".env"
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    # Strip UTF-8 BOM so the first variable is not "\ufeffGOOGLE_API_KEY"
    if text.startswith("\ufeff"):
        text = text[1:]
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key not in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
            continue
        val = _strip_val(val)
        if not val:
            continue
        os.environ[key] = val
    # Canonical name for google-genai / ADK (reads GOOGLE_API_KEY first)
    if os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]

    # Google AI Studio keys use the Gemini Developer API (generativelanguage), not Vertex.
    # If Vertex mode is on, the client may ignore the API key or use a different endpoint.
    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "0"
