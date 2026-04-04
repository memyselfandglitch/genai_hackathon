"""Short-term (session) and long-term (DB) memory helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Note, User, UserPreference


@dataclass
class ShortTermMemory:
    """In-process session scratchpad (mirrors ADK session state extensions)."""

    last_intent: Optional[str] = None
    pending_plan: Optional[list[str]] = None
    last_tool_errors: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def record_error(self, msg: str) -> None:
        self.last_tool_errors.append(f"{datetime.utcnow().isoformat()}Z {msg}")


class LongTermMemory:
    """Loads preferences and recent notes for grounding."""

    def __init__(self, db: AsyncSession, user_id: str):
        self._db = db
        self._user_id = user_id

    async def get_preferences(self) -> Optional[UserPreference]:
        r = await self._db.execute(
            select(UserPreference).where(UserPreference.user_id == self._user_id)
        )
        return r.scalar_one_or_none()

    async def ensure_user(self, email: str | None = None) -> User:
        r = await self._db.execute(select(User).where(User.id == self._user_id))
        u = r.scalar_one_or_none()
        if u:
            return u
        u = User(id=self._user_id, email=email)
        self._db.add(u)
        await self._db.flush()
        return u

    async def summarize_context(self, note_limit: int = 5) -> str:
        """Compact string for system prompt injection."""
        prefs = await self.get_preferences()
        r = await self._db.execute(
            select(Note)
            .where(Note.user_id == self._user_id)
            .order_by(Note.created_at.desc())
            .limit(note_limit)
        )
        notes = r.scalars().all()
        parts: list[str] = []
        if prefs:
            parts.append(
                f"Timezone={prefs.timezone}; preferred windows={prefs.preferred_meeting_windows}; "
                f"buffer={prefs.buffer_minutes_between_meetings}m"
            )
        if notes:
            parts.append("Recent notes:")
            for n in notes:
                snippet = (n.body or "")[:200]
                parts.append(f"- {n.title or 'untitled'}: {snippet}")
        return "\n".join(parts) if parts else "(no long-term context yet)"
