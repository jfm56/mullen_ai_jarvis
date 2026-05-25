"""Topic-disable management (CRUD for the user's learning opt-outs).

Memory CRUD itself lives in `app/memory/store.py`; this module only
handles the user's preference list for what NOT to learn.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db.base import get_sessionmaker
from app.db.models import TopicDisable


async def list_topic_disables(*, user_id: uuid.UUID) -> list[TopicDisable]:
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(TopicDisable)
            .where(TopicDisable.user_id == user_id)
            .order_by(TopicDisable.created_at.desc())
        )
        return list(result.scalars())


async def add_topic_disable(
    *, user_id: uuid.UUID, domain: str, pattern: str, note: str = ""
) -> TopicDisable:
    td = TopicDisable(user_id=user_id, domain=domain, pattern=pattern, note=note)
    async with get_sessionmaker()() as session:
        session.add(td)
        await session.commit()
        await session.refresh(td)
    return td


async def remove_topic_disable(*, user_id: uuid.UUID, topic_id: uuid.UUID) -> bool:
    async with get_sessionmaker()() as session:
        td = await session.get(TopicDisable, topic_id)
        if td is None or td.user_id != user_id:
            return False
        await session.delete(td)
        await session.commit()
    return True
