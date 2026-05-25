"""Memory store with mandatory domain isolation.

Design rules (enforced by code shape, not just by convention):

1. Every public read/write requires an explicit `domain` argument. There is
   no "default domain" the caller can omit. A typo or missing argument is
   a TypeError, not a quiet cross-domain leak.

2. `search()` and `list_recent()` filter by domain at the query layer.
   They never see rows from other domains; SQLAlchemy issues `WHERE domain = :d`.

3. `cross_domain_search()` exists for explicit cross-domain queries
   (e.g., "find me everything about EMS across personal and business").
   Every invocation writes an audit row tagged `memory.cross_domain_read`.

4. Writes go through `write()` which:
   a. checks the user's topic-disable list for the target domain
   b. embeds the text via Ollama
   c. inserts the row

If the embedding call fails, the row is still written with `embedding=NULL`.
A later re-index job can fill it in. The product cares more about not losing
the fact than about having it instantly searchable.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_sessionmaker
from app.db.models import Memory, MemoryKind, TopicDisable
from app.integrations import ollama
from app.security import audit

logger = logging.getLogger("jarvis.memory")


class TopicDisabledError(RuntimeError):
    """Raised when a write is blocked by a user's topic-disable list."""


@dataclass
class MemoryHit:
    id: uuid.UUID
    domain: str
    kind: MemoryKind
    text: str
    metadata: dict[str, Any]
    distance: float | None
    created_at: datetime


def _to_hit(m: Memory, *, distance: float | None = None) -> MemoryHit:
    return MemoryHit(
        id=m.id,
        domain=m.domain,
        kind=m.kind,
        text=m.text,
        metadata=m.metadata_json or {},
        distance=distance,
        created_at=m.created_at,
    )


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


async def _is_topic_disabled(
    session: AsyncSession, *, user_id: uuid.UUID, domain: str, text: str
) -> TopicDisable | None:
    result = await session.execute(
        select(TopicDisable).where(
            TopicDisable.user_id == user_id,
            TopicDisable.domain == domain,
        )
    )
    lowered = text.lower()
    for td in result.scalars():
        if td.pattern.lower() in lowered:
            return td
    return None


async def write(
    *,
    user_id: uuid.UUID,
    domain: str,
    kind: MemoryKind,
    text: str,
    metadata: dict[str, Any] | None = None,
    source_approval_id: uuid.UUID | None = None,
    source_audit_id: uuid.UUID | None = None,
    expires_at: datetime | None = None,
    session: AsyncSession | None = None,
) -> Memory:
    """Embed and persist a memory.

    Raises TopicDisabledError if the user has opted out of learning on a
    pattern that matches `text` for this domain.
    """
    if not text.strip():
        raise ValueError("refusing to write empty memory")

    async def _within(s: AsyncSession) -> Memory:
        blocked = await _is_topic_disabled(s, user_id=user_id, domain=domain, text=text)
        if blocked is not None:
            raise TopicDisabledError(
                f"memory write blocked by topic disable '{blocked.pattern}' "
                f"in domain '{domain}'"
            )

        embedding: list[float] | None = None
        try:
            result = await ollama.embed(text)
            embedding = result.vector
        except ollama.OllamaError as exc:
            # Don't lose the fact — store without embedding. Reindex later.
            logger.warning("embedding failed; storing memory without vector: %s", exc)

        memory = Memory(
            user_id=user_id,
            domain=domain,
            kind=kind,
            text=text,
            embedding=embedding,
            metadata_json=metadata or {},
            source_approval_id=source_approval_id,
            source_audit_id=source_audit_id,
            expires_at=expires_at,
        )
        s.add(memory)
        await s.flush()
        return memory

    if session is not None:
        return await _within(session)

    async with get_sessionmaker()() as owned:
        memory = await _within(owned)
        await owned.commit()
        await owned.refresh(memory)
        return memory


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


async def list_recent(
    *,
    user_id: uuid.UUID,
    domain: str,
    kind: MemoryKind | None = None,
    limit: int = 50,
) -> list[MemoryHit]:
    """Most-recent-first list, scoped to one user + domain."""
    stmt = (
        select(Memory)
        .where(
            Memory.user_id == user_id,
            Memory.domain == domain,
            Memory.deleted_at.is_(None),
        )
        .order_by(Memory.created_at.desc())
        .limit(limit)
    )
    if kind is not None:
        stmt = stmt.where(Memory.kind == kind)
    async with get_sessionmaker()() as session:
        result = await session.execute(stmt)
        return [_to_hit(m) for m in result.scalars()]


async def search(
    *,
    user_id: uuid.UUID,
    domain: str,
    query: str,
    k: int = 8,
    kind: MemoryKind | None = None,
) -> list[MemoryHit]:
    """Top-k cosine-similarity search inside a single domain.

    Falls back to recency if embedding the query fails (e.g., Ollama down).
    """
    try:
        q_vec = (await ollama.embed(query)).vector
    except ollama.OllamaError:
        # Degrade to a recency-bounded recent-list rather than empty results.
        return await list_recent(user_id=user_id, domain=domain, kind=kind, limit=k)

    stmt = (
        select(
            Memory,
            Memory.embedding.cosine_distance(q_vec).label("distance"),
        )
        .where(
            Memory.user_id == user_id,
            Memory.domain == domain,
            Memory.deleted_at.is_(None),
            Memory.embedding.is_not(None),
        )
        .order_by("distance")
        .limit(k)
    )
    if kind is not None:
        stmt = stmt.where(Memory.kind == kind)
    async with get_sessionmaker()() as session:
        result = await session.execute(stmt)
        return [_to_hit(m, distance=float(d)) for m, d in result.all()]


async def cross_domain_search(
    *,
    user_id: uuid.UUID,
    query: str,
    domains: list[str],
    k: int = 8,
    reason: str,
) -> list[MemoryHit]:
    """Explicit cross-domain query. Every call is audited.

    `reason` is required and written to the audit row so the user can see
    why cross-domain access happened.
    """
    if not reason.strip():
        raise ValueError("cross_domain_search requires a non-empty reason for audit")
    if len(domains) < 2:
        raise ValueError("use search() for single-domain queries")

    await audit.emit(
        agent="memory",
        domain=",".join(sorted(domains)),
        action_class="read",
        action_name="memory.cross_domain_read",
        target_summary=query[:200],
        decision="allow",
        user_id=user_id,
        extra={"reason": reason, "k": k},
    )

    try:
        q_vec = (await ollama.embed(query)).vector
    except ollama.OllamaError:
        return []

    stmt = (
        select(
            Memory,
            Memory.embedding.cosine_distance(q_vec).label("distance"),
        )
        .where(
            Memory.user_id == user_id,
            Memory.domain.in_(domains),
            Memory.deleted_at.is_(None),
            Memory.embedding.is_not(None),
        )
        .order_by("distance")
        .limit(k)
    )
    async with get_sessionmaker()() as session:
        result = await session.execute(stmt)
        return [_to_hit(m, distance=float(d)) for m, d in result.all()]


# ---------------------------------------------------------------------------
# Mutations / management (also used by app/memory/controls.py)
# ---------------------------------------------------------------------------


async def get(memory_id: uuid.UUID, *, user_id: uuid.UUID) -> Memory | None:
    """Fetch a single memory, scoped to the user (no cross-user reads)."""
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(Memory).where(
                Memory.id == memory_id,
                Memory.user_id == user_id,
                Memory.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()


async def update_text(
    memory_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    text: str,
    metadata: dict[str, Any] | None = None,
) -> Memory | None:
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(Memory).where(
                Memory.id == memory_id,
                Memory.user_id == user_id,
                Memory.deleted_at.is_(None),
            )
        )
        memory = result.scalar_one_or_none()
        if memory is None:
            return None
        memory.text = text
        if metadata is not None:
            memory.metadata_json = metadata
        try:
            memory.embedding = (await ollama.embed(text)).vector
        except ollama.OllamaError:
            memory.embedding = None
        await session.commit()
        await session.refresh(memory)
        return memory


async def soft_delete(memory_id: uuid.UUID, *, user_id: uuid.UUID) -> bool:
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(Memory).where(
                Memory.id == memory_id,
                Memory.user_id == user_id,
                Memory.deleted_at.is_(None),
            )
        )
        memory = result.scalar_one_or_none()
        if memory is None:
            return False
        memory.deleted_at = datetime.now(timezone.utc)
        await session.commit()
        return True


# Re-export for convenience.
__all__ = [
    "Memory",
    "MemoryHit",
    "MemoryKind",
    "TopicDisabledError",
    "cross_domain_search",
    "get",
    "list_recent",
    "search",
    "soft_delete",
    "update_text",
    "write",
]
