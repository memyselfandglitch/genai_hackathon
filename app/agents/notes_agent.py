"""Notes / RAG sub-agent: keyword search and summarization over stored notes."""

from __future__ import annotations

import re
from typing import Any, Optional

from google.adk.agents import LlmAgent
from google.adk.tools.function_tool import FunctionTool
from sqlalchemy import select

from app.core.config import get_settings
from app.core.context import get_exec_context
from app.core.logging import get_logger, trace_event
from app.db.models import Note
from app.db.session import get_session_factory

logger = get_logger(__name__)


def _tokenize(q: str) -> list[str]:
    return [t.lower() for t in re.split(r"\W+", q) if len(t) > 2]


async def search_notes_impl(query: str, limit: int = 8) -> dict[str, Any]:
    ctx = get_exec_context()
    trace_event(logger, "tool", {"agent": "notes", "tool": "search_notes", "user": ctx.user_id})
    tokens = _tokenize(query)
    factory = get_session_factory()
    async with factory() as session:
        r = await session.execute(
            select(Note).where(Note.user_id == ctx.user_id).order_by(Note.created_at.desc()).limit(50)
        )
        notes = list(r.scalars().all())
    scored: list[tuple[float, Note]] = []
    for n in notes:
        text = f"{n.title or ''} {n.body}".lower()
        score = sum(1 for t in tokens if t in text)
        if score or not tokens:
            scored.append((float(score), n))
    scored.sort(key=lambda x: -x[0])
    top = [n for _, n in scored[:limit]]
    return {
        "matches": [
            {"id": n.id, "title": n.title, "snippet": (n.body or "")[:400], "score_hint": "keyword"}
            for n in top
        ]
    }


async def add_note_impl(title: Optional[str], body: str) -> dict[str, Any]:
    ctx = get_exec_context()
    trace_event(logger, "tool", {"agent": "notes", "tool": "add_note", "user": ctx.user_id})
    factory = get_session_factory()
    async with factory() as session:
        n = Note(user_id=ctx.user_id, title=title, body=body)
        session.add(n)
        await session.commit()
        return {"status": "saved", "id": n.id}


async def summarize_notes_impl(topic: str) -> dict[str, Any]:
    """Returns concatenated snippets for the orchestrator model to summarize."""
    s = await search_notes_impl(topic, limit=5)
    lines = [m["snippet"] for m in s.get("matches", [])]
    return {"bullets": lines, "hint": "Synthesize these snippets for the user."}


def create_notes_agent() -> LlmAgent:
    settings = get_settings()
    return LlmAgent(
        model=settings.gemini_model,
        name="notes_agent",
        description="Searches and stores notes; lightweight RAG for executive context.",
        instruction=(
            "You help retrieve and store institutional memory. "
            "Use search_notes before answering factual questions about past notes."
        ),
        tools=[
            FunctionTool(search_notes_impl),
            FunctionTool(add_note_impl),
            FunctionTool(summarize_notes_impl),
        ],
    )
