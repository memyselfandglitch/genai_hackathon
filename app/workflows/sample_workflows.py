"""
Sample scenarios for manual / automated testing (no LLM required for DB seed).

Run from `backend/` with PYTHONPATH=.:
  python -m app.workflows.sample_workflows

Then exercise POST /query with GOOGLE_API_KEY set for full agent runs.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from sqlalchemy import select

from app.db.models import Event, Note, Task, User, UserPreference
from app.db.session import get_session_factory, init_db


async def seed_demo_user(user_id: str = "demo-user") -> None:
    await init_db()
    factory = get_session_factory()
    async with factory() as session:
        r = await session.execute(select(User).where(User.id == user_id))
        if r.scalar_one_or_none() is None:
            session.add(User(id=user_id, display_name="Demo Executive", home_address="1 Market St, San Francisco, CA"))
        pref = (
            await session.execute(select(UserPreference).where(UserPreference.user_id == user_id))
        ).scalar_one_or_none()
        if not pref:
            session.add(
                UserPreference(
                    user_id=user_id,
                    timezone="America/Los_Angeles",
                    preferred_meeting_windows=[
                        {"start": "09:00", "end": "11:30"},
                        {"start": "13:30", "end": "17:00"},
                    ],
                    buffer_minutes_between_meetings=20,
                )
            )
        now = datetime.utcnow().replace(hour=10, minute=0, second=0, microsecond=0)
        standup = (
            await session.execute(
                select(Event).where(
                    Event.user_id == user_id,
                    Event.title == "Standup",
                    Event.start_at == now,
                )
            )
        ).scalar_one_or_none()
        if not standup:
            session.add(
                Event(
                    user_id=user_id,
                    title="Standup",
                    start_at=now,
                    end_at=now + timedelta(minutes=30),
                    location="Zoom",
                )
            )

        q1_task = (
            await session.execute(
                select(Task).where(Task.user_id == user_id, Task.title == "Review Q1 plan")
            )
        ).scalar_one_or_none()
        if not q1_task:
            session.add(
                Task(
                    user_id=user_id,
                    title="Review Q1 plan",
                    priority=1,
                    status="open",
                )
            )

        board_note = (
            await session.execute(
                select(Note).where(Note.user_id == user_id, Note.title == "Board expectations")
            )
        ).scalar_one_or_none()
        if not board_note:
            session.add(
                Note(
                    user_id=user_id,
                    title="Board expectations",
                    body="We should emphasize margin expansion and hiring freeze in Q2.",
                )
            )
        await session.commit()
    print(f"Seeded user {user_id} with overlapping event, task, and note.")


def print_example_queries() -> None:
    print(
        """
Example queries (POST /query) after seeding and setting GOOGLE_API_KEY:

1) Conflict + travel:
   {"user_id": "demo-user", "query": "I need a 1h meeting at 10:15 tomorrow at the office downtown — check conflicts and travel from home."}

2) Tasks + prioritization:
   {"user_id": "demo-user", "query": "List my open tasks and reorder by urgency."}

3) Notes RAG:
   {"user_id": "demo-user", "query": "What did I write about board expectations?"}

4) BigQuery (mock rows):
   {"user_id": "demo-user", "query": "Pull revenue analytics from BigQuery for last quarter."}
"""
    )


async def main() -> None:
    await seed_demo_user()
    print_example_queries()


if __name__ == "__main__":
    asyncio.run(main())
