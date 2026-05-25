"""Memory store API surface — the domain-isolation guarantees.

These are unit tests of the function signatures and pure-Python branches.
Full pgvector round-trips live in DB-integration tests (`requires_db`).

The whole point of this file: it should be IMPOSSIBLE to accidentally read
across domains via the normal API. If a future change adds a `domain=None`
default, these tests should break.
"""

from __future__ import annotations

import inspect
import uuid

import pytest

from app.memory import store


def test_search_requires_explicit_domain() -> None:
    """search() must not have a default for `domain` — that would be a leak vector."""
    sig = inspect.signature(store.search)
    domain_param = sig.parameters["domain"]
    assert domain_param.default is inspect.Parameter.empty


def test_list_recent_requires_explicit_domain() -> None:
    sig = inspect.signature(store.list_recent)
    assert sig.parameters["domain"].default is inspect.Parameter.empty


def test_write_requires_explicit_domain() -> None:
    sig = inspect.signature(store.write)
    assert sig.parameters["domain"].default is inspect.Parameter.empty


def test_cross_domain_search_requires_reason() -> None:
    sig = inspect.signature(store.cross_domain_search)
    assert sig.parameters["reason"].default is inspect.Parameter.empty


@pytest.mark.asyncio
async def test_cross_domain_search_rejects_empty_reason() -> None:
    with pytest.raises(ValueError, match="reason"):
        await store.cross_domain_search(
            user_id=uuid.uuid4(),
            query="x",
            domains=["personal", "business"],
            reason="   ",
        )


@pytest.mark.asyncio
async def test_cross_domain_search_rejects_single_domain() -> None:
    with pytest.raises(ValueError, match="single-domain"):
        await store.cross_domain_search(
            user_id=uuid.uuid4(),
            query="x",
            domains=["personal"],
            reason="needed for context",
        )


@pytest.mark.asyncio
async def test_write_refuses_empty_text() -> None:
    with pytest.raises(ValueError, match="empty"):
        await store.write(
            user_id=uuid.uuid4(),
            domain="personal",
            kind=store.MemoryKind.semantic,
            text="   ",
        )
