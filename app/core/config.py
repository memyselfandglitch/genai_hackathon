"""Application configuration (env-based)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve backend/.env regardless of process cwd (uvicorn often started from ~ or repo root)
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_ENV_PATH = _BACKEND_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_PATH if _ENV_PATH.is_file() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ADK Runner / session namespace. Stock `LlmAgent` is defined under `google/adk/agents/`,
    # so ADK infers app name "agents"; matching avoids "App name mismatch" warnings.
    # Override via env `APP_NAME` if you use a custom agent package layout.
    app_name: str = Field(default="agents")
    debug: bool = False

    # Gemini / ADK — shell env or backend/.env (either name works)
    google_api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    )
    gemini_model: str = "gemini-flash-latest"

    # AlloyDB is PostgreSQL-compatible; for local dev use SQLite async URL
    database_url: str = "sqlite+aiosqlite:///./exec_assistant.db"

    # MCP endpoints (optional — mocks used if unset)
    mcp_bigquery_sse_url: Optional[str] = None
    mcp_maps_sse_url: Optional[str] = None
    mcp_calendar_sse_url: Optional[str] = None
    mcp_tasks_sse_url: Optional[str] = None

    # Optional direct Google Workspace REST connectivity
    google_workspace_access_token: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_WORKSPACE_ACCESS_TOKEN", "GOOGLE_OAUTH_ACCESS_TOKEN"),
    )
    google_calendar_id: str = "primary"
    google_tasks_list_id: str = "@default"

    # Workflow
    max_agent_steps: int = 32
    reflection_enabled: bool = True

    @field_validator("google_api_key", mode="before")
    @classmethod
    def _normalize_api_key(cls, v: object) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
                s = s[1:-1].strip()
            return s or None
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


def log_level() -> Literal["DEBUG", "INFO", "WARNING", "ERROR"]:
    return "DEBUG" if get_settings().debug else "INFO"
