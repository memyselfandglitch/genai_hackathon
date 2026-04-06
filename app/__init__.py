"""Executive assistant multi-agent backend."""

from app.env_bootstrap import load_backend_env

# Ensure GOOGLE_API_KEY and related flags exist before any ADK / google.genai imports.
load_backend_env()
