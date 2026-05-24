"""Memory store with mandatory domain isolation.

Every read/write takes an explicit domain. Cross-domain reads must be
performed via an explicit grant API (Phase 3) so they show up in audits.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class MemoryKind(str, Enum):
    short_term = "short_term"
    episodic = "episodic"
    semantic = "semantic"
    procedural = "procedural"


@dataclass(frozen=True)
class Memory:
    domain: str
    kind: MemoryKind
    text: str
    created_at: datetime
    metadata: dict[str, str]


async def write(domain: str, kind: MemoryKind, text: str, **metadata: str) -> None:
    """Embed and persist a memory. Phase 3 implementation."""
    raise NotImplementedError("memory.write — implement in Phase 3")


async def search(domain: str, query: str, *, k: int = 8) -> list[Memory]:
    """Top-k similarity search scoped to a single domain."""
    raise NotImplementedError("memory.search — implement in Phase 3")
